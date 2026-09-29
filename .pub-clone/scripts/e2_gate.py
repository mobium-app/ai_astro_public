#!/usr/bin/env python3
"""Bramka E2: pełne narzędzia + pamięć, wykonane na CPU (bez PC, bez głosu).

Sprawdza: dokumentację poleceń, walidację i uruchomienie skryptu w piaskownicy,
ochronę SSRF oraz obecność kuratorowanej wiedzy. Z --llm uruchamia też pętlę agenta.
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from astro import backends as B  # noqa: E402
from astro import config, core, memory  # noqa: E402
from astro.safety import Confirmer  # noqa: E402
from astro.tools import ToolContext, registry, system  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", action="store_true")
    args = parser.parse_args()

    config.ensure_dirs()
    mem = memory.default_memory()
    if mem.learned_count() == 0:
        memory.import_curated(mem)
    agent = core.create_agent(memory=mem)
    ctx = ToolContext(settings=config, memory=mem, confirmer=Confirmer(auto=True),
                      registry=registry, backends=agent.backends)
    checks = []

    out = system.man_page_text("grep")
    checks.append(("man_page", "GREP" in out.upper()))

    write = registry.execute("write_file",
                             {"path": "e2_gate.sh",
                              "content": "#!/bin/bash\necho astro-e2-ok\n"}, ctx)
    check = registry.execute("check_script", {"path": "e2_gate.sh"}, ctx)
    run = registry.execute("run_script", {"path": "e2_gate.sh"}, ctx)
    checks.append(("script_pipeline",
                   write.ok and check.ok and run.ok and "astro-e2-ok" in run.text))

    ssrf = registry.execute("web_fetch", {"url": "http://127.0.0.1:11434"}, ctx)
    checks.append(("ssrf_block", not ssrf.ok))

    checks.append(("curated_knowledge", mem.learned_verified_count() > 400))

    e1 = core.dispatch("sprawdź temperaturę procesora i wolne miejsce na dysku", agent)
    checks.append(("e1_regression", e1.route == "fast" and "°C" in e1.reply))

    for name, ok in checks:
        print(f"[gate] {name}: {'OK' if ok else 'FAIL'}")

    if args.llm:
        from astro.core.agent import normalize_call
        print("[gate] llm_tool_call: sprawdzam na lokalnym CPU (może potrwać)...")
        schemas = registry.select("sprawdź stronę man polecenia grep")
        prompt = [{"role": "user", "content": "Użyj narzędzia man_page dla polecenia grep."}]
        result = agent.backends.run("tools", prompt, tools=schemas, max_tokens=200)
        name, cargs = normalize_call(result.tool_calls[0]) if result.tool_calls else ("", {})
        used = name == "man_page" and "GREP" in system.man_page_text(cargs.get("name", "grep")).upper()
        checks.append(("llm_tool_call", used))
        print(f"[gate] llm_tool_call: {'OK' if used else 'FAIL'}")

    ok = all(o for _n, o in checks)
    print("[gate] " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
