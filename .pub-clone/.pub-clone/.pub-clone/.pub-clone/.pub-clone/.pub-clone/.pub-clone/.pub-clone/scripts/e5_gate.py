#!/usr/bin/env python3
"""Bramka E5: Hailo-first — telemetria NPU, status urządzenia, polityka czatu (jakość vs NPU).

Domyślnie sprawdzenia deterministyczne (bez otwierania urządzenia). `--live` wykonuje
realne wywołanie na NPU, ale TYLKO gdy `/dev/hailo0` jest wolne (HailoRT 5.1.1 = wyłączność).
"""

import argparse
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from astro import backends as B  # noqa: E402
from astro import config  # noqa: E402
from astro.backends.telemetry import NpuTelemetry  # noqa: E402
from astro.core.fast_tools import try_fast  # noqa: E402
from astro.safety import Confirmer  # noqa: E402
from astro.tools import ToolContext, registry  # noqa: E402


class Dummy(B.Backend):
    def __init__(self, name, caps):
        self.name = name
        self.capabilities = set(caps)

    def ready(self):
        return True

    def run(self, messages, **kw):
        return B.BackendResult(text=self.name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    checks = []

    tel = NpuTelemetry(os.path.join(tempfile.mkdtemp(), "npu.jsonl"))
    tel.record("stt", 0.44, ok=True, model="Whisper-Base")
    tel.record("chat", 8.0, ok=True, model="qwen2.5-1.5b")
    s = tel.summary()
    checks.append(("telemetry_counts", s["stt"]["count"] == 1 and s["chat"]["count"] == 1))
    checks.append(("telemetry_cpu_saved", tel.totals()["cpu_saved_secs"] > 0))
    print(f"[gate] telemetria: {tel.text()}")

    status = B.npu_status()
    checks.append(("device_detected", status["device_present"]))
    checks.append(("hefs_detected",
                   status["hefs"]["whisper"]["exists"] and status["hefs"]["llm"]["exists"]))
    checks.append(("firmware_known", status["firmware"] not in ("", "?")))
    print(f"[gate] status: {B.npu_status_text()}")

    reg = B.BackendRegistry()
    reg.register(Dummy("cpu", {"chat", "tools", "json", "plan"}))
    reg.register(Dummy("npu", {"chat"}))
    config.NPU_CHAT = False
    chosen, _reason = reg.choose_detail("chat")
    checks.append(("chat_quality_first", chosen.name == "cpu"))
    config.NPU_CHAT = True
    chosen_npu, _reason2 = reg.choose_detail("chat")
    checks.append(("chat_npu_opt_in", chosen_npu.name == "npu"))
    config.NPU_CHAT = False
    checks.append(("cpu_for_tools", reg.choose("tools").name == "cpu"))
    checks.append(("cpu_for_json", reg.choose("json").name == "cpu"))
    checks.append(("embed_not_npu", "npu" not in B.POLICY["embed"]))

    ctx = ToolContext(settings=config, memory=None, confirmer=Confirmer(auto=True),
                      registry=registry)
    fast = try_fast("sprawdź stan npu i telemetrię", ctx)
    checks.append(("fast_npu_route", bool(fast) and "NPU" in fast))

    if args.live:
        if B.device_busy():
            holders = ", ".join(f"{h['comm']}({h['pid']})" for h in B.device_holders())
            print(f"[gate] live: SKIP — /dev/hailo0 zajęte przez {holders} "
                  "(HailoRT 5.1.1 = wyłączność; zatrzymaj właściciela, by przetestować)")
        else:
            try:
                text = B.NPU_ENGINE.chat([{"role": "user", "content": "Odpowiedz jednym "
                                                                     "słowem: ASTRO"}], max_tokens=10)
                ok = bool(text.strip())
                B.NPU_ENGINE.release()
            except Exception as e:
                text, ok = str(e), False
            checks.append(("live_npu_chat", ok))
            print(f"[gate] live NPU: {text!r}")

    for name, ok in checks:
        print(f"[gate] {name}: {'OK' if ok else 'FAIL'}")
    ok = all(o for _n, o in checks)
    print("[gate] " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
