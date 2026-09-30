#!/usr/bin/env python3
"""E6 — bramka jakości tool-callingu ASTRO (per kategoria, kandydat vs baseline).

Kategorie (mierzone dla KANDYDATA i BASELINE w tej samej sesji):
  - tools : czy model woła WŁAŚCIWE narzędzie z sensownymi argumentami (19 przypadków)
  - chain : czy łączy >=2 różne narzędzia w jednym zadaniu + domyka odpowiedzią
  - chat  : ogólny czat bez narzędzi (brak regresji rozmowy)

Zasada promocji: kandydat musi osiągnąć progi ORAZ być >= baseline w KAŻDEJ kategorii.
Wyniki narzędzi są syntetyczne - testujemy DECYZJĘ modelu, nie wykonanie.

Użycie:
    python3 astro/scripts/e6_gate.py --model astro-lora
    python3 astro/scripts/e6_gate.py --model qwen2.5:3b --no-baseline      # tylko baseline
    python3 astro/scripts/e6_gate.py --model astro-lora --baseline qwen2.5:3b --quick
    python3 astro/scripts/e6_gate.py --model astro-lora --url http://127.0.0.1:11435  # PC GPU

Kod wyjścia: 0 = PASS (progi + brak regresji), 1 = FAIL.
"""

import argparse
import json
import sys
import time
import urllib.request

import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from astro import config  # noqa: E402
from astro.core.agent import (_needs_chain, chain_nudge_message,  # noqa: E402
                              normalize_call, parse_text_calls)
from astro.core.context import SYSTEM_PROMPT, tool_example_text  # noqa: E402
from astro.tools import registry  # noqa: E402

TOOL_TESTS = [
    ("Jaka jest teraz temperatura procesora i ile jest wolnej pamięci?", ["system_info"], None),
    ("Przeczytaj plik /etc/hostname", ["read_file"],
     lambda a: "hostname" in str(a.get("path", "")).lower()),
    ("Wylistuj zawartość katalogu /etc", ["list_dir"],
     lambda a: "etc" in str(a.get("path", "")).lower()),
    ("Znajdź w projekcie ASTRO pliki zawierające wzorzec ToolContext", ["search_files"],
     lambda a: "toolcontext" in (str(a.get("pattern", "")) + str(a.get("text", ""))).lower()),
    ("Wykonaj polecenie df -h", ["run_command"],
     lambda a: "df" in str(a.get("command", "")).lower()),
    ("Zapisz w katalogu roboczym plik notatka.txt z treścią test", ["write_file"],
     lambda a: "notatka" in str(a.get("path", "")).lower()),
    ("Zapamiętaj, że lubię zieloną herbatę", ["remember"],
     lambda a: "herbat" in str(a.get("text", "")).lower()),
    ("Pokaż stronę man polecenia rsync", ["man_page"],
     lambda a: "rsync" in (str(a.get("name", "")) + str(a.get("command", ""))).lower()),
    ("Pokaż pomoc polecenia rsync (--help)", ["cmd_help"],
     lambda a: "rsync" in (str(a.get("command", "")) + str(a.get("name", ""))).lower()),
    ("Sprawdź poprawność skryptu hello.sh", ["check_script"],
     lambda a: "hello" in str(a.get("path", "")).lower()),
    ("Uruchom skrypt hello.sh z katalogu roboczego", ["run_script"],
     lambda a: "hello" in str(a.get("path", "")).lower()),
    ("Wyszukaj w internecie, kto napisał Pana Tadeusza", ["web_search"],
     lambda a: "tadeusz" in str(a.get("query", "")).lower()),
    ("Pobierz treść strony https://pl.wikipedia.org/wiki/Debian", ["web_fetch"],
     lambda a: "wikipedia" in str(a.get("url", "")).lower()),
    ("Jaki jest najbliższy paczkomat w pobliżu Poznań, ul. Byka 1?", ["nearby_places"],
     lambda a: "paczkomat" in str(a.get("kind", "")).lower()),
    ("Co w bazie wiedzy wiadomo o systemd?", ["search_knowledge"],
     lambda a: "systemd" in str(a.get("query", "")).lower()),
    ("Ile dokumentów jest w bazie wiedzy?", ["knowledge_stats"], None),
    ("Sprawdź stan NPU / Hailo", ["npu_status"], None),
    ("Zainstaluj i skonfiguruj serwer nginx", ["system_task"], None),
    ("Zapisz to w pliku", ["ask_user"], None),
    ("Jakie masz przepisy i skille?", ["list_skills"], None),
    ("Pokaż stan repozytorium git", ["run_skill"],
     lambda a: "git" in (str(a.get("name", "")) + json.dumps(a.get("params", {}))).lower()),
]

# Zestaw ODŁOŻONY (held-out): parafrazy tych samych intencji, których NIE ma dosłownie w
# pamięci. Mierzy UOGÓLNIENIE nauki w runtime (retrieval + few-shot), a nie zapamiętanie
# dokładnego celu. Wymaga `default_memory()` (embeddingi), inaczej parafrazy nie trafiają.
HOLDOUT_TESTS = [
    ("Podaj aktualną temperaturę CPU i ile zostało wolnego RAM-u", ["system_info"], None),
    ("Odczytaj zawartość pliku /etc/hostname", ["read_file"],
     lambda a: "hostname" in str(a.get("path", "")).lower()),
    ("Co znajduje się w katalogu /etc?", ["list_dir"],
     lambda a: "etc" in str(a.get("path", "")).lower()),
    ("Przeszukaj kod ASTRO w poszukiwaniu odwołań do ToolContext", ["search_files"],
     lambda a: "toolcontext" in (str(a.get("pattern", "")) + str(a.get("text", ""))).lower()),
    ("Uruchom komendę pokazującą zajętość dysków (df -h)", ["run_command"],
     lambda a: "df" in str(a.get("command", "")).lower()),
    ("Utwórz plik notatka.txt z wpisem test w katalogu roboczym", ["write_file"],
     lambda a: "notatka" in str(a.get("path", "")).lower()),
    ("Zapisz w pamięci, że przepadam za zieloną herbatą", ["remember"],
     lambda a: "herbat" in str(a.get("text", "")).lower()),
    ("Wyświetl podręcznik polecenia rsync", ["man_page"],
     lambda a: "rsync" in (str(a.get("name", "")) + str(a.get("command", ""))).lower()),
    ("Sprawdź szybką pomoc dla rsync", ["cmd_help"],
     lambda a: "rsync" in (str(a.get("command", "")) + str(a.get("name", ""))).lower()),
    ("Zweryfikuj składnię pliku hello.sh", ["check_script"],
     lambda a: "hello" in str(a.get("path", "")).lower()),
    ("Wykonaj hello.sh z katalogu roboczego", ["run_script"],
     lambda a: "hello" in str(a.get("path", "")).lower()),
    ("Poszukaj w sieci informacji o autorze Pana Tadeusza", ["web_search"],
     lambda a: "tadeusz" in str(a.get("query", "")).lower()),
    ("Pobierz zawartość adresu https://pl.wikipedia.org/wiki/Debian", ["web_fetch"],
     lambda a: "wikipedia" in str(a.get("url", "")).lower()),
    ("Gdzie jest najbliższy paczkomat, jeśli jestem na Poznań, ul. Byka 1?", ["nearby_places"],
     lambda a: "paczkomat" in str(a.get("kind", "")).lower()),
    ("Czego baza wiedzy mówi o systemd?", ["search_knowledge"],
     lambda a: "systemd" in str(a.get("query", "")).lower()),
    ("Podaj liczbę dokumentów zgromadzonych w bazie wiedzy", ["knowledge_stats"], None),
    ("Jaki jest stan Hailo / NPU?", ["npu_status"], None),
    ("Skonfiguruj działający serwer nginx", ["system_task"], None),
    ("Zapisz to na później", ["ask_user"], None),
    ("Wymień swoje dostępne umiejętności i procedury", ["list_skills"], None),
    ("Jaki jest status repozytorium git?", ["run_skill"],
     lambda a: "git" in (str(a.get("name", "")) + json.dumps(a.get("params", {}))).lower()),
]

CHAIN_TESTS = [
    ("Sprawdź temperaturę procesora i wyszukaj w internecie, jaka temperatura jest bezpieczna "
     "dla Raspberry Pi 5", {"system_info", "web_search"}),
    ("Przeczytaj /etc/os-release i wyszukaj w internecie informacje o tej wersji Debiana",
     {"read_file", "web_search"}),
    ("Sprawdź stan NPU oraz temperaturę procesora", {"npu_status", "system_info"}),
]

CHAT_TESTS = [
    "Kim jesteś?",
    "Co to jest Linux? Odpowiedz krótko.",
    "Opowiedz w dwóch zdaniach, co potrafisz.",
]

FAKE_RESULTS = {
    "system_info": "Temperatura CPU: 46C; RAM: 9000 MB; Dysk: 406 GB wolne",
    "read_file": "astro",
    "list_dir": "/etc: 3 pozycje\n[plik] hostname\n[plik] hosts",
    "search_files": "dopasowania (1): astro/tools/registry.py:1: ToolContext",
    "run_command": "Filesystem Size Used Avail\n/dev/root 470G 41G 406G",
    "write_file": "zapisano 4 znaków do /home/user/astro-agent/notatka.txt",
    "append_file": "dopisano do /home/user/astro-agent/notatka.txt",
    "remember": "Zapisałam to w pamięci.",
    "man_page": "RSYNC(1) User Commands RSYNC(1) ...",
    "cmd_help": "Usage: rsync [OPTION]... SRC DEST ...",
    "check_script": "OK: brak błędów składni",
    "run_script": "(kod 0) Witaj z ASTRO",
    "web_search": "Pan Tadeusz - autor Adam Mickiewicz (1798-1855)",
    "web_fetch": "Debian - Wikipedia: system operacyjny oparty na Linuksie",
    "nearby_places": "Najbliższy paczkomat: InPost POZ03B (140 m), Poznań",
    "search_knowledge": "systemd: inicjalizacja i zarządzanie usługami w Linuksie",
    "knowledge_stats": "learned=2190, dokumenty=130573",
    "npu_status": "NPU Hailo: urządzenie obecne (FW 5.1.1); STT Whisper gotowe",
    "system_task": "Plan: 1. instalacja nginx. Powiedz potwierdzam, aby wykonać.",
    "ask_user": "Pytanie zadane użytkownikowi",
    "list_skills": "Dostępne przepisy: journal, dir_size, git_status, venv_packages, ...",
    "run_skill": "## main...origin/main\n M README.md\n?? scripts/new.py",
}

CATS = ["tools", "chain", "chat"]
DEFAULT_URL = "http://127.0.0.1:11434"
# Determinizm pomiaru: temperatura i ziarno (0.0/ustawione = powtarzalna bramka).
TEMP = 0.2
SEED = None
# Kontekst i budżet generacji: 32 schematy narzędzi + prompt to kilka tys. tokenów - domyślny
# kontekst Ollamy (4096) je OBCINA i model nie widzi narzędzi (objaw: "brak" wywołań).
# 8192 = minimum dla pełnego zestawu schematów; num_predict musi pomieścić "thinking" (Qwen3),
# inaczej odpowiedź czatu jest pusta (reasoning zjada budżet).
NUM_CTX = 8192
N_TOK = 1024
# None = domyślne modelu; False = /no_think (zalecane dla Qwen3 tool-calling); True = wymuś thinking.
THINK = None
SYS_PROMPT = SYSTEM_PROMPT
# Zwięzły prompt "tool-first" - Qwen3-1.7B gubi tool-calling przy długim, instrukcjami przeładowanym
# system prompcie; krótka, kategoryczna instrukcja działa (zmierzone).
TOOL_FIRST_PROMPT = (
    "Jesteś ASTRO, agentem na Raspberry Pi. ZASADA NADRZĘDNA: ZANIM odpowiesz, WYWOŁAJ narzędzie. "
    "Nigdy nie mów 'sprawdzam/sprawdziłam' bez wywołania narzędzia. Nie odmawiaj - dane są lokalne. "
    "Po wyniku odpowiedz krótko po polsku (rodzaj żeński).")
# Faza C: wariant "lean" - krótki prompt + /no_think W PROMPCIE (nie flagą `think`, która psuje
# argumenty), dobór <= MAX_TOOLS narzędzi i 1 wzorzec few-shot. Cel: mniejszy budżet tokenowy
# przy niegorszym tool-callingu (patrz docs/RESEARCH_HAILO_QWEN3.md, sekcja 7 "Faza C").
LEAN_PROMPT = (
    "Jesteś ASTRO, agentem na Raspberry Pi. Zawsze najpierw WYWOŁAJ narzędzie, zamiast mówić, że "
    "coś sprawdzasz. Dane są lokalne - nie odmawiaj. Odpowiedz krótko po polsku. /no_think")


def _chat(url, model, msgs, threads=3, tools=None, n=None, timeout=1800):
    body = {"model": model, "messages": msgs, "stream": False, "keep_alive": "24h",
            "options": {"num_thread": threads, "num_ctx": NUM_CTX,
                        "num_predict": n or N_TOK, "temperature": TEMP}}
    if SEED is not None:
        body["options"]["seed"] = SEED
    if tools:
        body["tools"] = tools
    if THINK is not None:
        body["think"] = THINK
    req = urllib.request.Request(url.rstrip("/") + "/api/chat",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _calls(msg):
    out = []
    for tc in (msg.get("tool_calls") or []):
        name, args = normalize_call(tc)
        if name:
            out.append({"id": tc.get("id") or name, "name": name, "args": args, "raw": tc})
    if not out:
        for tc in parse_text_calls(msg.get("content") or ""):
            name, args = normalize_call(tc)
            if name:
                out.append({"id": name, "name": name, "args": args, "raw": tc})
    return out


MEM = None
FEW = 0
FEW_MIN_SCORE = None
TOOL_SUITE = TOOL_TESTS


def _examples_for(query):
    if FEW <= 0 or MEM is None:
        return ""
    try:
        hits = MEM.similar_trajectories(query, k=FEW, min_score=FEW_MIN_SCORE)
    except Exception:
        hits = []
    return tool_example_text(hits)


def agent_steps(url, model, question, threads=3, max_steps=1, n=None, tools=None,
                examples=""):
    if callable(tools):
        tools = tools(question)
    msgs = [{"role": "system", "content": SYS_PROMPT}]
    if examples:
        msgs.append({"role": "system", "content": examples})
    msgs.append({"role": "user", "content": question})
    calls, final = [], ""
    chain_nudges = 0
    for step in range(max_steps):
        d = _chat(url, model, msgs, threads=threads, tools=tools, n=n)
        msg = d.get("message") or {}
        cs = _calls(msg)
        if cs:
            calls += cs
            msgs.append({"role": "assistant", "content": msg.get("content") or "",
                         "tool_calls": [c["raw"] for c in cs]})
            for c in cs:
                msgs.append({"role": "tool", "tool_call_id": c["id"], "name": c["name"],
                             "content": FAKE_RESULTS.get(c["name"], "wynik narzędzia")})
            continue
        # Przedwczesne zakończenie przy złożonym zadaniu -> ponaglij o drugą część.
        if (chain_nudges < 2 and step < max_steps - 1
                and _needs_chain(question, [c["name"] for c in calls])):
            msgs.append({"role": "system",
                         "content": chain_nudge_message(question, [c["name"] for c in calls])})
            chain_nudges += 1
            continue
        final = (msg.get("content") or "").strip()
        break
    return calls, final


def test_tools(url, model, tests, threads, tools):
    ok, details = 0, []
    for q, expect, argchk in tests:
        try:
            calls, _ = agent_steps(url, model, q, threads=threads, max_steps=1, tools=tools,
                                   examples=_examples_for(q))
        except Exception as e:
            details.append((q, f"BŁĄD {e}"))
            print(f"  [FAIL] tool: {q[:55]} -> BŁĄD {e}", flush=True)
            continue
        first = calls[0] if calls else None
        good = bool(first) and first["name"] in expect and (argchk is None or argchk(first["args"]))
        ok += 1 if good else 0
        got = "brak" if not first else f"{first['name']} {json.dumps(first['args'], ensure_ascii=False)[:60]}"
        details.append((q, got))
        print(f"  [{'OK  ' if good else 'FAIL'}] tool: {q[:55]} -> {got}", flush=True)
    return ok, len(tests), details


def test_chains(url, model, tests, threads, tools):
    ok, details = 0, []
    for q, expect in tests:
        try:
            calls, final = agent_steps(url, model, q, threads=threads, max_steps=6, tools=tools,
                                       examples=_examples_for(q))
        except Exception as e:
            details.append((q, f"BŁĄD {e}"))
            print(f"  [FAIL] chain: {q[:55]} -> BŁĄD {e}", flush=True)
            continue
        names = {c["name"] for c in calls}
        good = expect.issubset(names) and bool(final)
        ok += 1 if good else 0
        details.append((q, f"{sorted(names)} final={bool(final)}"))
        print(f"  [{'OK  ' if good else 'FAIL'}] chain: {q[:55]} -> {sorted(names)} "
              f"final={bool(final)}", flush=True)
    return ok, len(tests), details


def test_chat(url, model, tests, threads):
    ok, details = 0, []
    for q in tests:
        try:
            d = _chat(url, model, [{"role": "system", "content": SYS_PROMPT},
                                   {"role": "user", "content": q}], threads=threads)
        except Exception as e:
            details.append((q, f"BŁĄD {e}"))
            print(f"  [FAIL] chat: {q[:45]} -> BŁĄD {e}", flush=True)
            continue
        ans = ((d.get("message") or {}).get("content") or "").strip()
        bad = (not ans or len(ans) < 15 or ans.lstrip().startswith(("{", "["))
               or '"tool"' in ans or "tool_call" in ans)
        ok += 0 if bad else 1
        details.append((q, ans[:80]))
        print(f"  [{'OK  ' if not bad else 'FAIL'}] chat: {q[:45]} -> {ans[:70]!r}", flush=True)
    return ok, len(tests), details


def run_model(url, model, threads, tools, quick=False):
    res = {}
    t0 = time.time()
    print(f"== eval {model} (url={url}, threads={threads}) ==", flush=True)
    if "tools" in CATS:
        print("Narzędzia:", flush=True)
        tt = TOOL_SUITE[:8] if quick else TOOL_SUITE
        res["tools"] = test_tools(url, model, tt, threads, tools)[:2]
    if "chain" in CATS:
        print("Łańcuchy:", flush=True)
        ct = CHAIN_TESTS[:2] if quick else CHAIN_TESTS
        res["chain"] = test_chains(url, model, ct, threads, tools)[:2]
    if "chat" in CATS:
        print("Czat:", flush=True)
        ht = CHAT_TESTS[:2] if quick else CHAT_TESTS
        res["chat"] = test_chat(url, model, ht, threads)[:2]
    res["_t"] = time.time() - t0
    print(f"-- {model}: " + " | ".join(f"{c} {res[c][0]}/{res[c][1]}" for c in CATS)
          + f"  ({res['_t']:.0f}s)", flush=True)
    return res


def main():
    global MEM, FEW, FEW_MIN_SCORE, TOOL_SUITE, THINK, SYS_PROMPT, TEMP, SEED, NUM_CTX, N_TOK
    ap = argparse.ArgumentParser(description="Bramka E6 tool-calling (ASTRO)")
    ap.add_argument("--model", required=True, help="model kandydata (tag Ollama)")
    ap.add_argument("--baseline", default="qwen2.5:3b")
    ap.add_argument("--no-baseline", action="store_true")
    ap.add_argument("--url", default=DEFAULT_URL, help="Ollama (Pi CPU :11434; PC GPU :11435)")
    ap.add_argument("--threads", type=int, default=3)
    ap.add_argument("--quick", action="store_true", help="mniejszy zestaw (szybki sanity)")
    ap.add_argument("--few-shot", type=int, default=0,
                    help="wstrzyknij N wzorców trajektorii (nauka w runtime) do kontekstu")
    ap.add_argument("--few-shot-threshold", type=float, default=None,
                    help="min. podobieństwo retrieval (domyślnie wg Memory: 0.55 z embedderem)")
    ap.add_argument("--holdout", action="store_true",
                    help="użyj parafraz HELD-OUT (nieobecnych w pamięci) — pomiar uogólnienia")
    ap.add_argument("--tools-only", action="store_true",
                    help="tylko kategoria tools (szybszy pomiar few-shot)")
    ap.add_argument("--chains-only", action="store_true",
                    help="tylko kategoria chain (szybka diagnostyka łańcuchów)")
    ap.add_argument("--think", action="store_true",
                    help="wymuś tryb thinking (Qwen3) - wolny, niezalecany do tool-callingu")
    ap.add_argument("--no-think", action="store_true",
                    help="WYMUŚ think=false. UWAGA: fałszywie oblewało adaptery ASTRO "
                         "(v5/kali-full3: 8/8 -> 0/8) — do kanonicznej bramki NIE używać")
    ap.add_argument("--tool-first", action="store_true",
                    help="zwięzły system prompt 'tool-first' (zalecane dla Qwen3-1.7B)")
    ap.add_argument("--runtime-prompt", action="store_true",
                    help="DOKŁADNIE prompt runtime (core/context.SYSTEM_PROMPT) — kanoniczna bramka")
    ap.add_argument("--max-tools", type=int, default=None,
                    help="ogranicz schematy do <= N narzędzi dobranych per pytanie (budżet promptu)")
    ap.add_argument("--lean", action="store_true",
                    help="wariant Faza C: krótki prompt + /no_think + --max-tools 6 + --few-shot 1")
    ap.add_argument("--min-tools", type=float, default=0.80)
    ap.add_argument("--min-chain", type=float, default=0.60)
    ap.add_argument("--min-chat", type=float, default=0.80)
    ap.add_argument("--temp", type=float, default=None,
                    help="temperatura próbkowania (0.0 = deterministyczna bramka)")
    ap.add_argument("--seed", type=int, default=None, help="ziarno próbkowania (determinizm)")
    ap.add_argument("--num-ctx", type=int, default=8192,
                    help="kontekst Ollamy (>=8192 dla 32 schematów; domyślny 4096 obcina prompt)")
    ap.add_argument("--num-predict", type=int, default=1024,
                    help="budżet generacji; modele 'thinking' (Qwen3) wymagają >=1024")
    args = ap.parse_args()

    NUM_CTX = args.num_ctx
    N_TOK = args.num_predict
    print(f"[gate] num_ctx={NUM_CTX} num_predict={N_TOK}", flush=True)

    if args.temp is not None:
        TEMP = args.temp
    if args.seed is not None:
        SEED = args.seed
    if args.temp is not None or args.seed is not None:
        print(f"[gate] determinizm: temp={TEMP} seed={SEED}", flush=True)

    tools = registry.schemas()
    mins = {"tools": args.min_tools, "chain": args.min_chain, "chat": args.min_chat}
    if args.no_think:
        THINK = False
    elif args.think:
        THINK = True
    if args.tool_first:
        SYS_PROMPT = TOOL_FIRST_PROMPT
        print("[gate] system prompt: tool-first (zwiezly)", flush=True)
    if args.lean:
        SYS_PROMPT = LEAN_PROMPT
        if args.max_tools is None:
            args.max_tools = config.MAX_TOOLS
        if not args.few_shot:
            args.few_shot = 1
        print(f"[gate] LEAN: krotki prompt + /no_think + max-tools={args.max_tools} "
              f"+ few-shot={args.few_shot}", flush=True)
    if args.runtime_prompt:
        # Kanoniczna bramka: mierzymy model DOKŁADNIE tak, jak widzi go runtime.
        SYS_PROMPT = SYSTEM_PROMPT
        print("[gate] system prompt: runtime (core/context.SYSTEM_PROMPT)", flush=True)
    if args.max_tools:
        tools = (lambda q: registry.select(q, args.max_tools))
        print(f"[gate] schematy per pytanie: <= {args.max_tools} narzedzi", flush=True)
    if args.holdout:
        TOOL_SUITE = HOLDOUT_TESTS
        print(f"[gate] zestaw HELD-OUT: {len(TOOL_SUITE)} parafraz (nieobecnych w pamięci)",
              flush=True)
    if args.few_shot:
        from astro.memory import default_memory
        MEM = default_memory()  # jak w runtime: z embedderem (retrieval kosinusowy)
        FEW = args.few_shot
        FEW_MIN_SCORE = args.few_shot_threshold
        print(f"[gate] few-shot: {FEW} wzorców z {config.DB_PATH} "
              f"(embedder={'tak' if MEM.embedder else 'nie'}, próg={FEW_MIN_SCORE or 'auto'})",
              flush=True)
    if args.tools_only:
        global CATS
        CATS = ["tools"]
    if args.chains_only:
        CATS = ["chain"]

    cand = run_model(args.url, args.model, args.threads, tools, quick=args.quick)
    base = None
    if not args.no_baseline and args.baseline != args.model:
        base = run_model(args.url, args.baseline, args.threads, tools, quick=args.quick)

    print("\n== PODSUMOWANIE ==")
    ok_all = True
    for c in CATS:
        cok, cn = cand[c]
        rate = cok / cn if cn else 0
        line = f"{c:6s}: {cok}/{cn} ({rate:.0%}, próg {mins[c]:.0%})"
        passed = rate >= mins[c]
        if base:
            bok, bn = base[c]
            brate = bok / bn if bn else 0
            line += f" | baseline {bok}/{bn} ({brate:.0%})"
            passed = passed and rate >= brate
        if not passed:
            ok_all = False
        print(("PASS " if passed else "FAIL ") + line)
    print("\nWYNIK:", "PASS" if ok_all else "FAIL")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
