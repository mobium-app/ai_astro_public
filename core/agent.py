"""Pętla agenta: observe -> act -> verify."""

import json
import re
from dataclasses import dataclass, field

from .. import backends as backends_mod
from .. import config
from .. import log as astro_log
from ..affect import appraisal
from ..persona import expression
from ..persona import polish as persona_polish
from ..safety import is_executable_command, normalize_facts
from ..tools import ToolContext, ToolResult, registry as default_registry
from . import verifier
from .context import build_context
from .session import Session

TEXT_TOOL_RE = re.compile(r"\[TOOL\s+(\w+)\s+(\{.*?\})\s*\]", re.S)
# Złożone polecenia („X i Y", „X oraz Y"): po 1. narzędziu ponaglamy model o drugą część,
# zamiast pozwolić mu odpowiedzieć przedwcześnie. Naprawia łańcuchy (0/3 -> 2/3).
_CONJ_RE = re.compile(r"\b(i|oraz|a\s+takze|nastepnie|potem)\b")
CHAIN_NUDGE = ("To złożone zadanie (zawiera „i/oraz”) - brakuje jeszcze jednej części. Wywołaj "
               "narzędzie dla brakującej części (np. web_search/system_info) i dopiero potem "
               "odpowiedz. Nie odpowiadaj teraz tekstem.")


def _needs_chain(text, used_names):
    """Spójnik „i/oraz" + brakuje co najmniej jednego rozpoznanego narzędzia.

    Działa też gdy model nie wywołał jeszcze ŻADNEGO narzędzia (wtedy tylko dla zdań
    rozpoznanych jako komenda wykonywalna) — inaczej Qwen3-1.7B odpowiada „z głowy"
    i łańcuch nigdy nie startuje.
    """
    if not _CONJ_RE.search(normalize_facts(text or "")):
        return False
    used = set(used_names)
    if len(used) > 1:
        return False
    tools = chain_tools(text)
    remaining = [t for t in tools if t not in used]
    if not remaining or len(set(tools) | used) < 2:
        return False
    if not used and not is_executable_command(text):
        return False
    return True


def chain_tools(text):
    """Wszystkie narzędzia wskazane przez treść zadania (kolejność wg `_CHAIN_HINTS`)."""
    low = normalize_facts(text or "")
    out = []
    for rx, tool in _CHAIN_HINTS:
        if rx.search(low) and tool not in out:
            out.append(tool)
    return out


# Wskazówka, jakiego narzędzia brakuje (deterministycznie z treści zadania).
_CHAIN_HINTS = (
    (re.compile(r"w internecie|wyszukaj|szukaj w sieci|google|www|pogod|aktualn"), "web_search"),
    (re.compile(r"npu|hailo"), "npu_status"),
    (re.compile(r"podrecznik|\bman\b"), "man_page"),
    (re.compile(r"przeczytaj|zawartosc pliku|plik\s+/|/etc/"), "read_file"),
    (re.compile(r"temperatur|dysk|ram|pami[eę]c|procesor|\bcpu\b|uptime|zasob|\bsystem\w*"), "system_info"),
    (re.compile(r"uslug|service"), "run_command"),
)


def chain_hint(text, used_names):
    low = normalize_facts(text or "")
    used = set(used_names)
    for rx, tool in _CHAIN_HINTS:
        if rx.search(low) and tool not in used:
            return tool
    return ""


def chain_nudge_message(text, used_names):
    used = set(used_names)
    remaining = [t for t in chain_tools(text) if t not in used]
    if not used and remaining:
        return ("To zadanie wymaga narzędzi. Wywołaj po kolei: " + ", ".join(remaining) +
                ", a dopiero potem odpowiedz krótko po polsku. Nie odpowiadaj bez wyników narzędzi.")
    hint = remaining[0] if remaining else chain_hint(text, used_names)
    if hint:
        return (f"Brakuje drugiej części zadania. Wywołaj teraz narzędzie {hint}, "
                f"a dopiero potem odpowiedz krótko po polsku.")
    return CHAIN_NUDGE


@dataclass
class AgentResult:
    reply: str
    tool_calls: list = field(default_factory=list)
    steps: int = 0
    route: str = "agent"
    used_tools: bool = False


def normalize_call(call):
    if not isinstance(call, dict):
        return "", {}
    if "function" in call:
        fn = call.get("function") or {}
        name = fn.get("name") or ""
        args = fn.get("arguments")
    else:
        name = call.get("name") or call.get("tool") or ""
        args = call.get("arguments") or call.get("args")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            args = {}
    if not isinstance(args, dict):
        args = {}
    return name, args


def _affect_after(memory, text, calls_log):
    """Appraisal tury + reminiscencja (pamięć afektywna) -> delty PAD (E7.3/E8)."""
    store = getattr(memory, "affect", None) if memory is not None else None
    if store is None:
        return
    try:
        state = store.load()
        mem = getattr(memory, "affect_memory", None)
        if mem is not None:
            pad, _hits = mem.recall(text)
            if pad:
                w = config.AFFECT_RECALL_WEIGHT
                state.apply(pad[0] * w, pad[1] * w, pad[2] * w, mood_share=0.5)
        signals = appraisal.detect(text)
        for event in signals:
            state.apply(*appraisal.appraise(event))
        for event, strength in appraisal.outcome_events(calls_log):
            state.apply(*appraisal.appraise(event, strength))
        if not signals and not calls_log:
            state.apply(*appraisal.appraise("greeting", 0.4))
        store.save(state)
        if mem is not None:
            mem.record(text, state.effective())
    except Exception:
        pass


def parse_text_calls(text):
    calls = []
    for name, raw in TEXT_TOOL_RE.findall(text or ""):
        try:
            args = json.loads(raw)
        except Exception:
            args = {}
        calls.append({"function": {"name": name, "arguments": args}})
    return calls


class Agent:
    def __init__(self, backends=None, registry=None, memory=None, ctx=None, max_steps=None,
                 session=None):
        self.backends = backends or backends_mod.DEFAULT
        self.registry = registry or default_registry
        self.memory = memory
        self.ctx = ctx or ToolContext(settings=config, memory=memory,
                                      registry=self.registry)
        self.ctx.registry = self.registry
        self.ctx.backends = self.backends
        self.max_steps = max_steps or config.AGENT_MAX_STEPS
        self.session = session if session is not None else Session(
            store=memory, summarizer=self._summarize_thread)
        self._pinned = None  # P4: cache stałego bloku kontekstu trwałego

    def _pinned_context(self):
        """Stały blok kontekstu z poprzednich dni (P4). Liczony raz i cache'owany."""
        if self._pinned is None:
            self._pinned = ""
            if getattr(config, "CONTEXT_ENABLED", False) and self.memory is not None:
                try:
                    from . import persistent_context
                    self._pinned = persistent_context.build_block(self.memory)
                except Exception:
                    self._pinned = ""
        return self._pinned

    def _summarize_thread(self, prev_summary, latest, limit):
        """P3: streszczenie wątku modelem LOKALNYM (nigdy chmura). Pusty wynik = heurystyka."""
        system = ("Streść wątek rozmowy dla pamięci roboczej asystenta. Zwróć 1-2 krótkie zdania "
                  "po polsku: fakty i ustalenia istotne dla dalszej rozmowy (pomiń uprzejmości).")
        user = (f"Wcześniejszy wątek: {prev_summary}\nNowa tura: {latest}" if prev_summary
                else f"Nowa tura: {latest}")
        try:
            result = self.backends.run("chat", [{"role": "system", "content": system},
                                                {"role": "user", "content": user}],
                                       max_tokens=120, temperature=0.2, local_only=True)
            return (getattr(result, "text", "") or "").strip()
        except Exception:
            return ""

    def _execute(self, call):
        name, args = normalize_call(call)
        if not name:
            return name, ToolResult("puste wywołanie narzędzia", ok=False)
        result = self.registry.execute(name, args, self.ctx)
        return name, result

    def _learn_premium(self, text, reply, local_only):
        """Nauka z premium (2026-10-03): odpowiedzi na pytania wiedzowe → `learned` (offline).

        Warunki: ostatni backend = `premium`, to nie komenda (local_only), odpowiedź ma ≥ 80
        znaków, wypowiedź klasyfikuje się jako pytanie (po zdjęciu prefiksu kanału).
        Wyłączalne: `ASTRO_PREMIUM_LEARN=0`. Bramki jakości/dedup robi `memory.add_learned`.
        """
        import os as _os
        if _os.environ.get("ASTRO_PREMIUM_LEARN", "1") == "0":
            return
        if local_only or not self.memory or not (reply or "").strip() or len(reply) < 80:
            return
        try:
            last = getattr(self.backends, "last_choice", None)
            if "premium" not in (getattr(last, "name", "") or ""):
                return
            from . import prefix as prefix_mod
            _channel, body = prefix_mod.parse(text)
            q = (body or text or "").strip()
            from ..safety import quality
            if not quality.pair_ok(q, reply):
                return
            self.memory.add_learned(topic="premium", title=(q or "")[:200], text=reply,
                                    source="premium", confidence=0.55)
        except Exception:
            pass

    def run(self, text, force_chat=False):
        # `force_chat` (prefix „czat"): WYŁĄCZA narzędzia i traktuje wypowiedź jak rozmowę —
        # czat nigdy nie może wykonać komendy, nawet gdy brzmi jak zlecenie.
        tool_schemas = [] if force_chat else self.registry.select(text)
        # Pamięć robocza tylko dla CZATU/PYTAŃ — nie dla komend wykonawczych. Chroni
        # tool-calling LoRA v7 (historia mogłaby gasić wywołania) i nie miesza RAG.
        history = None
        summary = ""
        if config.SESSION_ENABLED and (force_chat or not is_executable_command(text)):
            sess = getattr(self, "session", None)
            if sess is not None:
                history = sess.history()
                summary = getattr(sess, "summary", "") or ""
        # Kontekst trwały (P4) tylko dla czatu/pytań — nie dla komend wykonawczych (ochrona
        # tool-callingu i brak zbędnego prefillu).
        pinned = self._pinned_context() if history is not None else ""
        messages = build_context(text, self.memory, max_examples=config.FEWSHOT,
                                 history=history, summary=summary, pinned=pinned)
        params = expression.for_run(text, self.memory)
        # Komenda wykonawcza: tylko backendy lokalne (npu/cpu) - nigdy pc/remote.
        local_only = (not force_chat) and is_executable_command(text)
        used_tools = []
        calls_log = []
        seen = set()
        answer = ""
        nudged = False
        chain_nudged = False
        no_tools_next = False

        for step in range(self.max_steps):
            last = step == self.max_steps - 1
            tools_arg = None if (last or no_tools_next) else tool_schemas
            no_tools_next = False
            kind = "tools" if tools_arg else "chat"
            # Streaming (C4, opt-in): deltki treści lecą do sinka; `tool_calls` składamy z chunków
            # w backendzie. Gdy sinka nie ma / STREAM=0 — działa jak dotąd (bez zmian).
            sink = None
            if getattr(config, "STREAM", False):
                sink = getattr(self.ctx, "stream_sink", None)
            # C4: oznacz krok (narzędzia czy czat) i zresetuj mówienie — pętla głosowa mówi
            # tylko deltki kroku bez narzędzi.
            if sink is not None:
                try:
                    self.ctx.stream_tools = bool(tools_arg)
                    reset = getattr(sink, "reset", None)
                    if callable(reset):
                        reset()
                except Exception:
                    pass
            result = self.backends.run(kind, messages, tools=tools_arg,
                                       max_tokens=params["max_tokens"],
                                       temperature=params["temperature"],
                                       local_only=local_only, on_token=sink)
            calls = list(result.tool_calls or [])
            if tools_arg and not calls:
                calls = parse_text_calls(result.text)
            if calls and tools_arg:
                keys = []
                for i, call in enumerate(calls):
                    nm, ar = normalize_call(call)
                    # OpenAI-compatible wymaga zgodnych id wywołania i odpowiedzi `tool`.
                    if isinstance(call, dict) and not call.get("id"):
                        call["id"] = f"call_{len(seen)}_{i}"
                    keys.append((nm, json.dumps(ar, sort_keys=True, ensure_ascii=False)))
                if keys and all(k in seen for k in keys):
                    no_tools_next = True
                    messages.append({"role": "system",
                                     "content": "Masz już wyniki tych narzędzi - odpowiedz teraz "
                                                "bez wywoływania narzędzi."})
                    continue
                seen.update(keys)
                messages.append({"role": "assistant", "content": result.text or "",
                                 "tool_calls": calls})
                for call in calls:
                    name, res = self._execute(call)
                    args = normalize_call(call)[1]
                    calls_log.append({"name": name, "args": args,
                                      "ok": bool(getattr(res, "ok", True)),
                                      "result": str(getattr(res, "text", res))[:800]})
                    if name == "ask_user":
                        question = (getattr(res, "data", None) or {}).get("ask") \
                            or getattr(res, "text", "") or "Doprecyzuj proszę."
                        _affect_after(self.memory, text, calls_log)
                        return AgentResult(str(question), calls_log, step + 1, "ask_user",
                                           bool(used_tools))
                    used_tools.append(name)
                    tool_msg = {"role": "tool", "name": name,
                                "content": getattr(res, "text", str(res))}
                    if isinstance(call, dict) and call.get("id"):
                        tool_msg["tool_call_id"] = call["id"]
                    messages.append(tool_msg)
                continue

            answer = (result.text or "").strip()
            # Złożone zadanie, a model chce zakończyć po 1. narzędziu -> ponaglij o drugą część.
            if (not chain_nudged and step < self.max_steps - 1
                    and _needs_chain(text, used_tools)):
                messages.append({"role": "system",
                                 "content": chain_nudge_message(text, used_tools)})
                chain_nudged = True
                continue
            ok, nudge = verifier.check(answer, bool(used_tools), text, nudged)
            if not ok and not nudged:
                nudged = True
                messages.append({"role": "system", "content": nudge})
                continue
            reply = answer or "Nie udało mi się tego teraz wykonać."
            # Strażnik języka: model (zwłaszcza zdalny) czasem przechodzi na angielski. Jedna
            # regeneracja z twardą instrukcją; przy niepowodzeniu zostaje oryginał.
            if persona_polish.looks_english(reply):
                try:
                    fix_msgs = messages + [
                        {"role": "assistant", "content": answer or ""},
                        {"role": "system",
                         "content": "Odpowiedz TERAZ wyłącznie po polsku, krótko i naturalnie."}]
                    fix = self.backends.run("chat", fix_msgs, tools=None,
                                            max_tokens=params["max_tokens"],
                                            temperature=params["temperature"],
                                            local_only=local_only)
                    fixed = (getattr(fix, "text", "") or "").strip()
                    if fixed and not persona_polish.looks_english(fixed):
                        reply = fixed
                except Exception:
                    pass
            # Nauka z premium (2026-10-03): odpowiedź zdalna na pytanie wiedzowe -> `learned`.
            self._learn_premium(text, reply, local_only)
            if self.memory:
                try:
                    self.memory.add_episode(text, reply, used_tools, ok=True)
                    if calls_log:
                        self.memory.add_trajectory(
                            kind="agent", goal=text, steps=calls_log,
                            result=", ".join(used_tools), answer=reply,
                            source="agent", ok=bool(used_tools))
                except Exception as e:
                    astro_log.get_logger("agent").debug("zapis epizodu/trajektorii nieudany: %s", e)
            _affect_after(self.memory, text, calls_log)
            return AgentResult(reply, calls_log, step + 1, "agent", bool(used_tools))

        reply = answer or "Przekroczyłam limit kroków - spróbuj proszę prościej sformułować zadanie."
        _affect_after(self.memory, text, calls_log)
        return AgentResult(reply, calls_log, self.max_steps, "agent", bool(used_tools))
