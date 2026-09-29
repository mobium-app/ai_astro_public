"""Rejestr backendów + polityka wyboru (NPU-first czat, CPU tools/json/plan, PC/remote opt-in)."""

import json
import time

from .. import config
from . import modes
from .base import Backend
from .cpu import CpuBackend
from .npu import NpuBackend
from .remote import RemoteBackend

def _chat_order():
    """Kolejność backendów czatu. Domyślnie jakość: CPU 7B, potem NPU jako zapas.
    `ASTRO_NPU_CHAT=1` przywraca NPU-first (E5)."""
    if config.NPU_CHAT:
        return ["npu", "cpu", "pc", "remote"]
    return ["cpu", "npu", "pc", "remote"]


POLICY = {
    "chat": _chat_order(),
    "tools": ["cpu_fast", "cpu", "pc", "remote"],
    "json": ["cpu_fast", "cpu", "pc", "remote"],
    "plan": ["cpu_fast", "cpu", "pc", "remote"],
    "embed": ["cpu", "pc", "remote"],
    "heavy": ["pc", "cpu", "remote"],
    "fresh": ["remote", "cpu", "pc"],
}
REASONS = {    "chat": "CPU 7B dla czatu (jakość polszczyzny); NPU jako zapas; fallback PC/remote",
    "tools": "CPU 3B dla narzędzi (szybki, pewny tool-calling); fallback 7B",
    "json": "CPU 3B dla JSON/structured output; fallback 7B",
    "plan": "CPU 3B dla planowania; fallback 7B",
    "embed": "embeddingi poza NPU (brak HEF) - CPU/Ollama nomic-embed-text",
    "heavy": "PC opt-in dla zadań ciężkich (offline/trening)",
    "fresh": "remote opt-in dla świeżej wiedzy z sieci",
}

# Switch „po przeznaczeniu" (Faza E): model i tryb dla typu zadania. Tryb (`quality`/`no_think`)
# dotyczy modeli hybrydowych (Qwen3). Nadpisywalne przez ASTRO_MODEL_*/ASTRO_MODE_*.
MODE_BY_KIND = {
    "chat": lambda: config.MODE_CHAT,
    "tools": lambda: config.MODE_TOOLS,
    "json": lambda: config.MODE_TOOLS,
    "plan": lambda: config.MODE_TOOLS,
    "heavy": lambda: config.MODE_CHAT,
    "fresh": lambda: config.MODE_CHAT,
}
MODEL_BY_KIND = {
    "chat": lambda: config.MODEL_CHAT,
    "tools": lambda: config.MODEL_TOOLS,
    "json": lambda: config.MODEL_TOOLS,
    "plan": lambda: config.MODEL_TOOLS,
    "heavy": lambda: config.PC_MODEL,
    "fresh": lambda: config.REMOTE_MODEL or config.MODEL_CHAT,
}


def model_for(kind):
    return MODEL_BY_KIND.get(kind, lambda: config.MODEL_CHAT)()


def mode_for(kind):
    return MODE_BY_KIND.get(kind, lambda: config.MODE_CHAT)()


# Krótki opis backendu do diagnostyki (żeby reason nie mówił „CPU 7B", gdy użyto PC/premium).
_BACKEND_DESC = {
    "cpu": "CPU 7B lokalnie",
    "cpu_fast": "CPU 3B/LoRA lokalnie",
    "npu": "NPU 1.5B lokalnie",
    "pc": "PC-Kali bielik-11b (tunel)",
    "premium": "OpenCode Go/DeepSeek",
    "remote": "łańcuch zdalny (awaryjnie)",
}


def _reason(backend, kind):
    base = REASONS.get(kind, "")
    desc = _BACKEND_DESC.get(backend.name, backend.name)
    return f"{desc} — {base}" if base else desc


class BackendRegistry:
    def __init__(self):
        self.backends = {}
        self.last_choice = None
        self.last_reason = None
        self._ready_cache = {}  # nazwa -> (ts, bool); TTL ogranicza HTTP /api/tags per tura

    def register(self, backend):
        self.backends[backend.name] = backend
        return backend

    def _ready(self, backend):
        """`backend.ready()` z krótkim cache (P1.4) — mniej roundtripów HTTP na turę."""
        ttl = float(getattr(config, "BACKEND_READY_TTL", 3.0))
        now = time.time()
        cached = self._ready_cache.get(backend.name)
        if cached and ttl > 0 and (now - cached[0]) < ttl:
            return cached[1]
        try:
            ok = bool(backend.ready())
        except Exception:
            ok = False
        self._ready_cache[backend.name] = (now, ok)
        return ok

    def get(self, name):
        return self.backends.get(name)

    def _capable(self, backend, tools=None, fmt=None):
        if tools and "tools" not in backend.capabilities:
            return False
        if fmt and "json" not in backend.capabilities:
            return False
        return True

    def order(self, kind, local_only=False):
        # Tryby pracy (offline/komputer/premium) zmieniają kolejność backendów per zadanie.
        names = modes.order_for(kind)
        # Dzienny budżet premium: po przekroczeniu limitu cicho schodzimy na pc/cpu.
        if "premium" in names and not modes.premium_budget_ok():
            names = [n for n in names if n != "premium"]
        if local_only:
            # Twarda zasada bezpieczeństwa: komendy wykonawcze NIGDY do chmury (pc/remote).
            # Gdy brak lokalnego backendu zwracamy PUSTĄ listę (caller zgłosi błąd) — NIE
            # fallback do pc/remote, bo to złamałoby zasadę „komendy nigdy do chmury".
            return [self.backends[n] for n in names
                    if n in ("npu", "cpu") and n in self.backends]
        ordered = [self.backends[n] for n in names if n in self.backends]
        return ordered or list(self.backends.values())

    def choose(self, kind="chat", text=""):
        backend, _reason = self.choose_detail(kind, text)
        return backend

    def choose_detail(self, kind="chat", text=""):
        order = self.order(kind)
        for i, backend in enumerate(order):
            if self._ready(backend):
                reason = _reason(backend, kind)
                if kind == "chat" and config.NPU_CHAT:
                    reason = "NPU-first dla czatu (odciąża CPU); fallback CPU"
                if i > 0:
                    reason = f"{reason} [fallback: {backend.name}]"
                reason = f"{backend.name}: {reason}"
                self.last_choice = backend
                self.last_reason = reason
                return backend, reason
        backend = order[0] if order else None
        self.last_reason = "brak gotowego backendu"
        return backend, self.last_reason

    def run(self, kind, messages, *, tools=None, fmt=None, max_tokens=400, temperature=0.2,
            on_token=None, local_only=False):
        errors = []
        for i, backend in enumerate(self.order(kind, local_only=local_only)):
            if not self._capable(backend, tools=tools, fmt=fmt):
                errors.append(f"{backend.name}: brak zdolności")
                continue
            if not self._ready(backend):
                errors.append(f"{backend.name}: not ready")
                continue
            start = time.time()
            try:
                result = backend.run(messages, tools=tools, fmt=fmt, max_tokens=max_tokens,
                                     temperature=temperature, on_token=on_token)
                reason = _reason(backend, kind)
                if i > 0:
                    reason = f"{reason} [fallback: {backend.name}]"
                reason = f"{backend.name}: {reason}"
                self._metric(backend, kind, time.time() - start, ok=True, tools=tools, fmt=fmt,
                             reason=reason)
                self.last_choice = backend
                self.last_reason = reason
                return result
            except Exception as e:
                errors.append(f"{backend.name}: {e}")
                self._metric(backend, kind, time.time() - start, ok=False, tools=tools, fmt=fmt,
                             reason=REASONS.get(kind, ""), error=str(e)[:200])
        raise RuntimeError("wszystkie backendy zawiodły: " + "; ".join(errors or ["brak"]))

    def _metric(self, backend, kind, seconds, ok, tools=None, fmt=None, reason="", error=""):
        entry = {
            "ts": time.time(),
            "backend": backend.name,
            "model": getattr(backend, "model", ""),
            "kind": kind,
            "tools": len(tools or []),
            "fmt": fmt or "",
            "secs": round(seconds, 3),
            "ok": bool(ok),
            "reason": reason,
        }
        if error:
            entry["error"] = error
        try:
            config.ensure_dirs()
            with open(config.METRICS_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def read_metrics(self, limit=100):
        try:
            with open(config.METRICS_FILE, encoding="utf-8") as f:
                lines = f.readlines()[-limit:]
            return [json.loads(x) for x in lines if x.strip()]
        except Exception:
            return []

    def metrics_summary(self):
        summary = {}
        for m in self.read_metrics(limit=10000):
            key = f"{m['backend']}:{m['kind']}"
            row = summary.setdefault(key, {"count": 0, "ok": 0, "secs": 0.0})
            row["count"] += 1
            row["ok"] += 1 if m.get("ok") else 0
            row["secs"] += float(m.get("secs") or 0)
        for row in summary.values():
            row["avg_secs"] = round(row["secs"] / row["count"], 3) if row["count"] else 0.0
        return summary


def build_default():
    reg = BackendRegistry()
    reg.register(CpuBackend(config.LLM_URL, config.LLM_MODEL, threads=config.LLM_THREADS,
                            keep_alive=config.LLM_KEEP_ALIVE))
    if config.LLM_TOOLS_MODEL and config.LLM_TOOLS_MODEL != config.LLM_MODEL:
        reg.register(CpuBackend(config.LLM_URL, config.LLM_TOOLS_MODEL,
                                threads=config.LLM_THREADS, keep_alive=config.LLM_KEEP_ALIVE,
                                name="cpu_fast"))
    if config.NPU_ENABLED:
        reg.register(NpuBackend(model=config.NPU_MODEL))
    if config.PC_ENABLED or getattr(config, "PC_RUNTIME", False):
        # PC-Kali (Ollama przez tunel) jako backend runtime: tryb „komputer" + awaryjny offline.
        reg.register(CpuBackend(config.PC_URL, config.PC_MODEL, threads=config.LLM_THREADS,
                                keep_alive=getattr(config, "PC_KEEP_ALIVE", "30m"), name="pc"))
    if config.REMOTE_ENABLED and config.REMOTE_URL:
        reg.register(RemoteBackend(config.REMOTE_URL, config.REMOTE_MODEL,
                                   key=config.REMOTE_KEY, timeout=config.REMOTE_TIMEOUT))
    elif config.REMOTE_ENABLED:
        from .remote_chain import RemoteChainBackend
        reg.register(RemoteChainBackend())
        # Tryb „premium": OpenCode Go (DeepSeek) PIERWSZY, reszta zdalna dopiero za nim.
        try:
            from .. import remote_support
            premium = remote_support.opencode_chain()
            if premium:
                reg.register(RemoteChainBackend(chain=premium, name="premium"))
        except Exception:
            pass
    return reg


DEFAULT = build_default()


def choose(kind="chat", text=""):
    return DEFAULT.choose(kind, text)


def choose_detail(kind="chat", text=""):
    return DEFAULT.choose_detail(kind, text)


def run(kind, messages, **kw):
    return DEFAULT.run(kind, messages, **kw)


def set_default(registry):
    global DEFAULT
    DEFAULT = registry
    return DEFAULT


def policy_table():
    """Polityka „backend + model + tryb" per przeznaczenie (do wglądu/diagnostyki)."""
    table = {}
    active = modes.get_mode()
    for kind in POLICY:
        table[kind] = {
            "order": [backend.name for backend in DEFAULT.order(kind)],
            "model": model_for(kind),
            "mode": mode_for(kind),
            "reason": REASONS.get(kind, ""),
            "active_mode": active,
        }
    return table
