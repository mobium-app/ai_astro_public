#!/usr/bin/env python3
"""Preflight maszyn-nauczycieli: sprawdza, czy Ollama żyje i czy model REALNIE odpowiada
w limicie czasu (czyli czy zmieścił się w VRAM). Niezdatne maszyny są pomijane, żeby nie
blokowały pętli (np. PC-2 gdy VRAM zajęty przez pulpit).

Wejście: --endpoint "label=url|model|role" (mnożne).
Wyjście (stdout): TYLKO zdrowe endpointy w tym samym formacie (po jednym w linii) + logi na stderr.
Kod wyjścia: 0 jeśli jest >=1 zdrowy, 1 jeśli brak.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request

DEFAULT_TOOLS = [{"type": "function", "function": {
    "name": "system_info", "description": "Stan systemu",
    "parameters": {"type": "object", "properties": {}, "required": []}}}]


def base_of(url):
    b = url.rstrip("/")
    return b[:-3] if b.endswith("/v1") else b


def probe(ep, timeout):
    label, rest = ep.split("=", 1)
    parts = rest.split("|")
    url, model = parts[0], parts[1]
    role = parts[2] if len(parts) > 2 else "tools"
    base = base_of(url)
    # 1) serwer żyje?
    try:
        with urllib.request.urlopen(base + "/api/version", timeout=8) as r:
            if r.status != 200:
                return False, "serwer nie odpowiada"
    except Exception as e:
        return False, f"serwer: {str(e)[:50]}"
    # 2) model realnie odpowiada (ładuje się do VRAM) w limicie?
    payload = {"model": model, "stream": False, "keep_alive": "24h",
               "messages": [{"role": "user", "content": "Odpowiedz jednym słowem: OK"}],
               "options": {"num_predict": 128, "temperature": 0}}
    t0 = time.time()
    try:
        req = urllib.request.Request(base + "/api/chat",
                                     data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
        # Sukces = serwer zwrócił odpowiedź (model wczytany do VRAM); treść może być pusta
        # przy modelach "thinking" (Qwen3) - to NIE jest błąd.
        ok = bool(d.get("message") is not None or d.get("done"))
        dt = time.time() - t0
        if not ok:
            return False, f"brak odpowiedzi ({dt:.0f}s)"
        return True, f"OK ({dt:.0f}s)"
    except Exception as e:
        return False, f"model: {str(e)[:50]} ({time.time() - t0:.0f}s)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", action="append", default=[])
    ap.add_argument("--timeout", type=int, default=90)
    args = ap.parse_args()
    healthy = 0
    for ep in args.endpoint:
        ok, why = probe(ep, args.timeout)
        label = ep.split("=", 1)[0]
        if ok:
            healthy += 1
            print(ep)
            print(f"[preflight] {label}: {why}", file=sys.stderr, flush=True)
        else:
            print(f"[preflight] {label}: POMINIĘTY — {why}", file=sys.stderr, flush=True)
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())
