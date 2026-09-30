#!/usr/bin/env python3
"""Bramka E3: polityka backendów, metryki (JSONL) i selekcja podzbioru narzędzi.

Bez PC i bez chmury: politykę i metryki sprawdzamy na lekkich backendach zastępczych;
selekcję narzędzi na prawdziwym rejestrze. Z --llm wykonuje realne wywołanie CPU.
"""

import argparse
import os
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from astro import backends as B  # noqa: E402
from astro import config  # noqa: E402
from astro.tools import registry  # noqa: E402


class Dummy(B.Backend):
    def __init__(self, name, caps, text=None, fail=False):
        self.name = name
        self.capabilities = set(caps)
        self._text = text or name
        self._fail = fail

    def ready(self):
        return True

    def run(self, messages, **kw):
        if self._fail:
            raise RuntimeError("celowy błąd")
        return B.BackendResult(text=self._text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", action="store_true")
    args = parser.parse_args()
    checks = []

    checks.append(("default_local_cpu",
                   set(B.DEFAULT.backends) <= {"cpu", "cpu_fast"}))
    chosen, reason = B.choose_detail("chat")
    print(f"[gate] chat -> {chosen.name} ({reason})")
    checks.append(("chat_ready", chosen is not None))
    chosen_tools, reason_tools = B.choose_detail("tools")
    print(f"[gate] tools -> {chosen_tools.name} ({reason_tools})")
    checks.append(("tools_cpu", chosen_tools.name in ("cpu", "cpu_fast", "pc", "remote")))

    chat_policy = B.BackendRegistry()
    chat_policy.register(Dummy("cpu", {"chat", "tools", "json", "plan"}))
    chat_policy.register(Dummy("npu", {"chat"}))
    config.NPU_CHAT = False
    checks.append(("chat_quality_first", chat_policy.choose("chat").name == "cpu"))
    config.NPU_CHAT = True
    checks.append(("chat_npu_opt_in", chat_policy.choose("chat").name == "npu"))
    config.NPU_CHAT = False
    checks.append(("cpu_for_tools", chat_policy.choose("tools").name == "cpu"))

    fallback = B.BackendRegistry()
    fallback.register(Dummy("npu", {"chat"}, fail=True))
    fallback.register(Dummy("cpu", {"chat", "tools", "json", "plan"}, text="cpu-fallback"))
    metrics_path = Path(tempfile.mkdtemp()) / "metrics.jsonl"
    old_metrics = config.METRICS_FILE
    config.METRICS_FILE = metrics_path
    config.NPU_CHAT = True  # wymuś NPU-first, by przetestować kaskadę awaryjną
    try:
        result = fallback.run("chat", [{"role": "user", "content": "x"}])
        entries = fallback.read_metrics()
        summary = fallback.metrics_summary()
    finally:
        config.METRICS_FILE = old_metrics
        config.NPU_CHAT = False
    checks.append(("fallback_cascade", result.text == "cpu-fallback"))
    checks.append(("metrics_written",
                   len(entries) == 2 and any(e["ok"] for e in entries)
                   and any(not e["ok"] for e in entries)))
    checks.append(("metrics_summary", summary.get("cpu:chat", {}).get("ok") == 1
                   and summary.get("npu:chat", {}).get("ok") == 0))

    full = len(registry.names())
    subset = registry.select_names("sprawdź stronę man polecenia grep")
    print(f"[gate] narzędzia: pełny={full}, podzbiór={len(subset)} {subset}")
    checks.append(("tool_subset_bounded", len(subset) <= config.MAX_TOOLS < full))
    checks.append(("tool_subset_relevant", "man_page" in subset))

    if args.llm:
        schemas = registry.select("Użyj narzędzia system_info, aby sprawdzić temperaturę CPU.")
        prompt = [{"role": "user", "content": "Sprawdź temperaturę CPU narzędziem system_info."}]
        res = B.DEFAULT.run("tools", prompt, tools=schemas, max_tokens=120)
        used = bool(res.tool_calls) and res.tool_calls[0]["function"]["name"] == "system_info"
        checks.append(("llm_cpu_tool_call", used))

    for name, ok in checks:
        print(f"[gate] {name}: {'OK' if ok else 'FAIL'}")
    ok = all(o for _n, o in checks)
    print("[gate] " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
