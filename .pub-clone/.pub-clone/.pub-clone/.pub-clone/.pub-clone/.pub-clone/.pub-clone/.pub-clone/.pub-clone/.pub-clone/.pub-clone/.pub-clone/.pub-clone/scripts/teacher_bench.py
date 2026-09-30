#!/usr/bin/env python3
"""E6 — benchmark kandydatów na NAUCZYCIELA trajektorii tool-calling (Ollama, np. PC-MAX).

Realistycznie: bierze PRAWDZIWY system prompt i schematy narzędzi ASTRO, zadaje cele
ze `toolcall_gen` (pojedyncze narzędzia + łańcuchy) i sprawdza, czy model zwraca
poprawne wywołania (natywne `tool_calls`), mierzy czas i tok/s oraz VRAM.

Użycie:
    python3 astro/scripts/teacher_bench.py --host http://127.0.0.1:11436 \
        --models bielik,qwen2.5:14b,gpt-oss:20b --scenarios 12 --chains 4
    python3 astro/scripts/teacher_bench.py --host http://127.0.0.1:11436 --list
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from astro.core.context import SYSTEM_PROMPT  # noqa: E402
from astro.tools import registry  # noqa: E402
from astro.scripts import toolcall_gen  # noqa: E402
from astro.scripts.cloud_teacher import validate_calls  # noqa: E402


def _post(host, path, payload, timeout=600):
    req = urllib.request.Request(
        host.rstrip("/") + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _get(host, path, timeout=30):
    req = urllib.request.Request(host.rstrip("/") + path)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def show(host, model):
    try:
        return _post(host, "/api/show", {"model": model})
    except Exception as e:
        return {"error": str(e)}


def unload(host, model):
    try:
        _post(host, "/api/generate", {"model": model, "keep_alive": 0}, timeout=60)
    except Exception:
        pass


def ps(host):
    try:
        return {m["name"]: m for m in _get(host, "/api/ps").get("models", [])}
    except Exception:
        return {}


def parse_tool_calls(msg):
    out = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        name = fn.get("name") or ""
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}
        if name:
            out.append({"name": name, "args": args or {}})
    return out


def chat(host, model, messages, tools=None, num_ctx=8192, timeout=600, temperature=0.0):
    payload = {"model": model, "messages": messages, "stream": False,
               "options": {"temperature": temperature, "num_ctx": num_ctx}}
    if tools:
        payload["tools"] = tools
    t0 = time.time()
    data = _post(host, "/api/chat", payload, timeout=timeout)
    dt = time.time() - t0
    msg = data.get("message") or {}
    ev = data.get("eval_count") or 0
    evd = data.get("eval_duration") or 0
    return {
        "msg": msg,
        "calls": parse_tool_calls(msg),
        "content": (msg.get("content") or "").strip(),
        "wall": dt,
        "load_s": (data.get("load_duration") or 0) / 1e9,
        "prompt_tokens": data.get("prompt_eval_count") or 0,
        "completion_tokens": ev,
        "tps": (ev / (evd / 1e9)) if evd else 0.0,
    }


def run_scenarios(host, model, schemas, pairs, num_ctx, timeout):
    valid = exact = 0
    tps, wall = [], []
    fails = []
    for q, want in pairs:
        try:
            res = chat(host, model, [{"role": "system", "content": SYSTEM_PROMPT},
                                     {"role": "user", "content": q}], tools=schemas,
                       num_ctx=num_ctx, timeout=timeout)
        except Exception as e:
            fails.append((q, f"błąd: {str(e)[:60]}"))
            continue
        names = [c["name"] for c in res["calls"]]
        ok, why = validate_calls(res["calls"]) if res["calls"] else (False, "brak wywołań")
        if ok:
            valid += 1
        else:
            fails.append((q, why))
        if want in names:
            exact += 1
        elif names:
            fails.append((q, f"oczekiwano {want}, jest {names}"))
        tps.append(res["tps"])
        wall.append(res["wall"])
    n = len(pairs)
    return {"n": n, "valid": valid, "exact": exact,
            "valid_rate": valid / n if n else 0, "exact_rate": exact / n if n else 0,
            "tps": sum(tps) / len(tps) if tps else 0,
            "wall": sum(wall) / len(wall) if wall else 0, "fails": fails}


def run_chains(host, model, schemas, chains, num_ctx, timeout):
    success = 0
    fails = []
    for ch in chains:
        want = [s["tool"] for s in ch["steps"]]
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": ch["q"]}]
        got = []
        ok = True
        for step in ch["steps"]:
            try:
                res = chat(host, model, messages, tools=schemas, num_ctx=num_ctx,
                           timeout=timeout)
            except Exception as e:
                fails.append((ch["q"], f"błąd: {str(e)[:60]}"))
                ok = False
                break
            if not res["calls"]:
                fails.append((ch["q"], f"brak wywołania; oczekiwano {step['tool']}"))
                ok = False
                break
            call = res["calls"][0]
            got.append(call["name"])
            if call["name"] != step["tool"]:
                fails.append((ch["q"], f"krok: jest {got}, oczekiwano {want}"))
                ok = False
                break
            messages.append({"role": "assistant", "content": "",
                             "tool_calls": [{"function": {"name": call["name"],
                                                           "arguments": call["args"]}}]})
            messages.append({"role": "tool", "content":
                             step.get("canned") or toolcall_gen.CANNED.get(step["tool"],
                                                                            "wynik")})
        else:
            try:
                final = chat(host, model, messages, num_ctx=num_ctx, timeout=timeout)
                if not final["content"]:
                    fails.append((ch["q"], "brak finalnej odpowiedzi"))
                    ok = False
            except Exception as e:
                fails.append((ch["q"], f"finał błąd: {str(e)[:60]}"))
                ok = False
        if ok and got == want:
            success += 1
    n = len(chains)
    return {"n": n, "success": success, "rate": success / n if n else 0, "fails": fails}


def bench(host, model, schemas, pairs, chains, num_ctx, timeout):
    unload(host, model)
    info = show(host, model)
    details = info.get("details") or {}
    t0 = time.time()
    warm = None
    try:
        warm = chat(host, model, [{"role": "user", "content": "Odpowiedz: OK"}],
                    num_ctx=num_ctx, timeout=timeout)
    except Exception as e:
        return {"model": model, "error": f"nie ładuje się: {str(e)[:80]}"}
    load_s = time.time() - t0
    mps = ps(host).get(model) or {}
    vram = mps.get("size_vram") or 0
    size = mps.get("size") or 0
    sc = run_scenarios(host, model, schemas, pairs, num_ctx, timeout)
    ch = run_chains(host, model, schemas, chains, num_ctx, timeout)
    return {
        "model": model,
        "params": details.get("parameter_size", "?"),
        "quant": details.get("quantization_level", "?"),
        "ctx_max": (info.get("model_info") or {}).get(
            next((k for k in (info.get("model_info") or {}) if k.endswith(".context_length")),
                 ""), "?"),
        "load_s": load_s,
        "size_gb": size / 1e9,
        "vram_gb": vram / 1e9,
        "fits_vram": vram > 0 and vram >= size * 0.98,
        "scenarios": sc,
        "chains": ch,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="http://127.0.0.1:11436")
    ap.add_argument("--models", default="")
    ap.add_argument("--scenarios", type=int, default=12)
    ap.add_argument("--chains", type=int, default=4)
    ap.add_argument("--num-ctx", type=int, default=8192)
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--out", default=os.path.join(ROOT, "runtime", "logs", "teacher_bench.json"))
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if args.list:
        for m in models or [x["name"] for x in _get(args.host, "/api/tags").get("models", [])]:
            print(m)
        return 0
    if not models:
        print("podaj --models", file=sys.stderr)
        return 2

    schemas = registry.schemas()
    pairs = [(s["q"], s["tool"]) for s in toolcall_gen.SCENARIOS[:args.scenarios]]
    chains = toolcall_gen.CHAINS[:args.chains]
    print(f"[bench] host={args.host} narzędzia={len(schemas)} scenariusze={len(pairs)} "
          f"łańcuchy={len(chains)} num_ctx={args.num_ctx}", flush=True)

    results = []
    for m in models:
        print(f"\n[bench] === {m} ===", flush=True)
        r = bench(args.host, m, schemas, pairs, chains, args.num_ctx, args.timeout)
        results.append(r)
        if r.get("error"):
            print(f"[bench] {m}: {r['error']}", flush=True)
            continue
        print(f"[bench] {m} {r['params']} {r['quant']}: load={r['load_s']:.1f}s "
              f"vram={r['vram_gb']:.1f}GB/{r['size_gb']:.1f}GB fits={r['fits_vram']} "
              f"| tools {r['scenarios']['valid']}/{r['scenarios']['n']} valid, "
              f"{r['scenarios']['exact']}/{r['scenarios']['n']} exact, "
              f"{r['scenarios']['tps']:.1f} tok/s | chain {r['chains']['success']}/"
              f"{r['chains']['n']}", flush=True)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)
    print(f"\n[bench] raport -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
