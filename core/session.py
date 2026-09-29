"""Pamięć robocza rozmowy (P1/P2) — krótka historia tur bieżącej sesji.

Cel: czat widzi ostatnie tury, więc ASTRO nie gubi wątku (np. „lubisz ze mną
pracować?” → „a jak bardzo?”). Historia jest wstrzykiwana WYŁĄCZNIE dla tur bez
komend wykonawczych (ochrona tool-callingu LoRA v7 przed regresem). Fakty i dane
systemowe nadal pochodzą z RAG/narzędzi — historia tego nie zastępuje.

P2 (trwałość + zwijanie wątku): przy `store` (Memory) tury są zapisywane do SQLite
i wczytywane po restarcie usługi (o ile przerwa < `gap`). Najstarsze tury są zwijane
do zwięzłego `summary` (bez modelu), które wraca do kontekstu jako „wcześniejszy wątek”.
"""

import time

from .. import config


class Session:
    def __init__(self, max_turns=None, gap_s=None, max_chars=None, store=None,
                 summary_max_chars=None, summarizer=None):
        self.max_turns = int(max_turns if max_turns is not None else config.SESSION_TURNS)
        self.gap_s = float(gap_s if gap_s is not None else config.SESSION_GAP_S)
        self.max_chars = int(max_chars if max_chars is not None else config.SESSION_MAX_CHARS)
        self.summary_max_chars = int(summary_max_chars if summary_max_chars is not None
                                     else config.SESSION_SUMMARY_MAX_CHARS)
        self.store = store
        # Streszczanie modelem lokalnym (P3, opt-in `ASTRO_SESSION_SUMMARY_MODEL=1`): callable
        # (prev_summary, latest_text, limit) -> str. Bez niego / przy błędzie = zwijanie heurystyczne.
        self.summarizer = summarizer
        self.turns = []
        self.summary = ""
        self.last_ts = 0.0
        if store is not None:
            self._load()

    # --- trwałość (P2) -------------------------------------------------------------------
    def _load(self):
        try:
            turns = self.store.recent_session_turns(self.max_turns)
            summary, meta_ts = self.store.session_summary()
        except Exception:
            return
        last = max([t["ts"] for t in turns] + [meta_ts, 0.0])
        self.last_ts = last
        if last and (time.time() - last) > self.gap_s:
            self.turns = []
            self.summary = ""
            return
        self.turns = [{"user": t["user"], "assistant": t["assistant"]} for t in turns]
        self.summary = summary or ""

    def _expired(self, now):
        return bool(self.last_ts) and (now - self.last_ts) > self.gap_s

    def _fold(self, turn):
        """Zwija najstarszą turę do `summary`: modelem lokalnym (opt-in) albo heurystycznie."""
        text = (turn.get("user") or "").strip()
        if not text:
            return
        if self.summarizer is not None and getattr(config, "SESSION_SUMMARY_MODEL", False):
            try:
                summary = (self.summarizer(self.summary, text, self.summary_max_chars) or "").strip()
            except Exception:
                summary = ""
            if summary:
                self.summary = summary[:self.summary_max_chars]
                return
        piece = text if len(text) <= 120 else text[:117] + "..."
        items = [s for s in self.summary.split("; ") if s]
        items.append(piece)
        summary = "; ".join(items)
        if len(summary) > self.summary_max_chars:
            summary = summary[-self.summary_max_chars:]
        self.summary = summary

    def record(self, user, assistant, now=None):
        """Dokłada turę (user, assistant) do sesji; przerwa > gap czyści historię."""
        now = time.time() if now is None else now
        # Zmiana dnia: domknij wczoraj (digest + archiwum .md), zanim tury wypadną z retention.
        if self.last_ts and self.store is not None and getattr(config, "CONTEXT_ENABLED", False):
            from . import persistent_context
            if persistent_context.day_key(self.last_ts) != persistent_context.day_key(now):
                try:
                    persistent_context.warm_start(self.store, days=1)
                except Exception:
                    pass
        if self._expired(now):
            self.turns = []
            self.summary = ""
        u = (user or "").strip()
        a = (assistant or "").strip()
        if not u and not a:
            return
        self.turns.append({"user": u, "assistant": a})
        while self.max_turns > 0 and len(self.turns) > self.max_turns:
            self._fold(self.turns.pop(0))
        self.last_ts = now
        if self.store is not None:
            try:
                self.store.add_session_turn(u, a, ts=now)
                self.store.set_session_summary(self.summary, last_ts=now)
                keep = int(getattr(config, "SESSION_RAW_KEEP", 0) or 0)
                self.store.prune_session_turns(keep=max(50, keep, self.max_turns * 4))
            except Exception:
                pass

    def history(self, now=None, max_turns=None, max_chars=None):
        """Historia jako wiadomości chat (`user`/`assistant`) w kolejności od najstarszej.

        Budżet znaków liczony od najnowszej tury; najnowsza para zostaje zawsze.
        """
        now = time.time() if now is None else now
        if self._expired(now):
            return []
        limit = int(max_turns if max_turns is not None else self.max_turns)
        budget = int(max_chars if max_chars is not None else self.max_chars)
        turns = self.turns[-limit:] if limit > 0 else []
        selected = []
        used = 0
        for turn in reversed(turns):
            cost = len(turn["user"]) + len(turn["assistant"])
            if selected and used + cost > budget:
                break
            selected.append(turn)
            used += cost
        selected.reverse()
        out = []
        for turn in selected:
            if turn["user"]:
                out.append({"role": "user", "content": turn["user"]})
            if turn["assistant"]:
                out.append({"role": "assistant", "content": turn["assistant"]})
        return out

    def clear(self, forget=False):
        self.turns = []
        self.summary = ""
        self.last_ts = 0.0
        if forget and self.store is not None:
            try:
                self.store.clear_session()
            except Exception:
                pass
