"""HP1: telemetria aplikacyjna NPU (liczniki, czasy, szacunek odciążenia CPU).

HailoRT 5.1.1 nie udostępnia telemetrii sprzętowej (brak hwmon; `measure-power` wymaga
zwolnienia urządzenia), dlatego mierzymy na poziomie aplikacji: ile operacji STT/LLM
poszło na NPU, ile trwały i ile czasu CPU zaoszczędzono względem baseline'u CPU.
"""

import json
import threading
import time
from collections import defaultdict

from .. import config

CPU_BASELINE_SECS = {
    "stt": 7.5,
    "chat": 60.0,
    "embed": 2.0,
}


class NpuTelemetry:
    def __init__(self, path=None):
        self.path = str(path or config.NPU_TELEMETRY_FILE)
        self._lock = threading.Lock()
        self._ops = defaultdict(lambda: {"count": 0, "ok": 0, "fail": 0, "secs": 0.0,
                                         "last": 0.0, "model": ""})

    def record(self, op, secs, ok=True, model="", note=""):
        entry = {"ts": time.time(), "op": op, "secs": round(float(secs), 4),
                 "ok": bool(ok), "model": model}
        if note:
            entry["note"] = note
        with self._lock:
            row = self._ops[op]
            row["count"] += 1
            row["ok" if ok else "fail"] += 1
            row["secs"] += float(secs)
            row["last"] = time.time()
            if model:
                row["model"] = model
        self._append(entry)
        return entry

    def _append(self, entry):
        try:
            config.ensure_dirs()
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def summary(self):
        with self._lock:
            out = {}
            for op, row in self._ops.items():
                count = row["count"]
                baseline = CPU_BASELINE_SECS.get(op)
                cpu_saved = None
                if baseline is not None:
                    cpu_saved = max(0.0, count * baseline - row["secs"])
                out[op] = {
                    "count": count, "ok": row["ok"], "fail": row["fail"],
                    "avg_secs": round(row["secs"] / count, 4) if count else 0.0,
                    "total_secs": round(row["secs"], 3),
                    "cpu_baseline_secs": baseline,
                    "cpu_saved_secs": round(cpu_saved, 2) if cpu_saved is not None else None,
                    "model": row["model"],
                }
            return out

    def totals(self):
        with self._lock:
            count = sum(r["count"] for r in self._ops.values())
            secs = sum(r["secs"] for r in self._ops.values())
            saved = 0.0
            for op, r in self._ops.items():
                baseline = CPU_BASELINE_SECS.get(op)
                if baseline is not None:
                    saved += max(0.0, r["count"] * baseline - r["secs"])
            return {"count": count, "total_secs": round(secs, 3),
                    "cpu_saved_secs": round(saved, 2)}

    def text(self):
        rows = self.summary()
        t = self.totals()
        if not rows:
            return ("Telemetria NPU: brak operacji. "
                    f"Łącznie 0 (CPU zaoszczędzony: 0 s, szacunek).")
        parts = []
        for op, r in sorted(rows.items()):
            sv = f", CPU ~{r['cpu_saved_secs']} s" if r["cpu_saved_secs"] is not None else ""
            parts.append(f"{op}: {r['count']}× (śr. {r['avg_secs']} s{sv})")
        return ("Telemetria NPU: " + "; ".join(parts) +
                f". Łącznie {t['count']} operacji, CPU zaoszczędzony ~{t['cpu_saved_secs']} s "
                "(szacunek względem baseline'u CPU).")

    def reset(self):
        with self._lock:
            self._ops.clear()


NPU_TELEMETRY = NpuTelemetry()


def record(op, secs, ok=True, model=""):
    return NPU_TELEMETRY.record(op, secs, ok=ok, model=model)


def summary():
    return NPU_TELEMETRY.summary()


def text():
    return NPU_TELEMETRY.text()
