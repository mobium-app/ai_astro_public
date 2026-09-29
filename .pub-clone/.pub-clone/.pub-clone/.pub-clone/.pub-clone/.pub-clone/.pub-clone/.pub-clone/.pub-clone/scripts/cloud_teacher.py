#!/usr/bin/env python3
"""E6 — chmurowy NAUCZYCIEL: generuje i ocenia trajektorie tool-calling (dane, nie trening).

Chmura nie trenuje modelu. Silny model (OpenAI-compatible) służy jako:
  1) TEACHER - dla pytania użytkownika zwraca wywołania narzędzi ASTRO (wg `registry.schemas()`),
     my dokładamy wynik (realny dla read-only, inaczej kontrolowany) i prosimy o finalną odpowiedź;
  2) JUDGE   - ocenia trajektorię (JSON: score 1-5, ok, problems); zapisujemy tylko dobre.

Dostawcy (failover, DARMOWE najpierw): `/etc/atena-remote-ai.env` (Atena: Gemini -> Groq ->
OpenRouter :free), potem `ASTRO_TEACHER_URL/MODEL/KEY`, a na końcu klucz opencode-go
(`~/.local/share/opencode/auth.json`). Można też podać własną listę przez `ASTRO_TEACHER_PROVIDERS`
(JSON) lub OpenAI-compatible URL. Klucze NIE są logowane.

Wynik → `trajectories` (`kind=agent`, source=`cloud_teacher`) + `datasets/cloud_teacher.jsonl`.
Te dane działają od razu w runtime (few-shot/retrieval) i mogą później posłużyć do treningu.

Użycie:
    python3 astro/scripts/cloud_teacher.py --probe            # który dostawca odpowiada
    python3 astro/scripts/cloud_teacher.py --limit 5 --dry-run
    python3 astro/scripts/cloud_teacher.py --limit 20 --expand 3
    python3 astro/scripts/cloud_teacher.py --judge-only --min-score 4
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from astro import config  # noqa: E402
from astro.core.agent import normalize_call  # noqa: E402
from astro.core.context import SYSTEM_PROMPT  # noqa: E402
from astro.memory import Memory  # noqa: E402
from astro.safety import Confirmer  # noqa: E402
from astro.tools import ToolContext, registry  # noqa: E402

OPENCODE_AUTH = os.path.expanduser("~/.local/share/opencode/auth.json")
OPENCODE_URL = "https://opencode.ai/zen/go/v1"
JUDGE_PROMPT = (
    "Jesteś sędzią trajektorii agenta narzędziowego ASTRO. Otrzymasz dozwoloną listę narzędzi ASTRO "
    "(każde z nich jest POPRAWNE), kroki i finalną odpowiedź. Oceniaj WYŁĄCZNIE twarde błędy - "
    "trajektoria jest OK, gdy: (1) użyte narzędzia należą do listy i pasują do zadania; (2) argumenty "
    "są sensowne; (3) finalna odpowiedź to tekst dla użytkownika oparty na wynikach (NIE kolejne "
    "wywołanie narzędzia ani znaczniki typu tool_call/DSML). NIE karz za: brak minimalizacji liczby "
    "narzędzi, brak dodatkowych kroków weryfikacji, brak wcześniejszego sprawdzenia istnienia pliku, "
    "ostrożne lub niepewne sformułowania, gdy wynik narzędzia był pusty/błędny, ani za kilka narzędzi, "
    "jeśli pasują do zadania. ask_user jest OK tylko gdy brakuje kluczowej informacji; jeśli zadanie "
    "da się wykonać znanym narzędziem bez pytania, wtedy ask_user = problem. Zwróć WYŁĄCZNIE JSON: "
    "{\"score\": 1-5, \"ok\": true/false, \"problems\": [\"...\"]}. `ok` = brak twardych błędów. "
    "score: 5 bez uwag, 4 drobiazgi, 3 wątpliwe ale wykonalne, 2 lub 1 poważne błędy."
)


@dataclass
class Provider:
    url: str
    model: str
    key: str = ""
    label: str = ""
    headers: dict = field(default_factory=dict)


def _read_maybe_root(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except PermissionError:
        pass
    except OSError:
        return ""
    try:
        p = subprocess.run(["sudo", "-n", "cat", path], capture_output=True, text=True,
                           timeout=10)
        return p.stdout or ""
    except Exception:
        return ""


def _atena_providers(path=None):
    """Dostawcy z kluczy ASTRO (`ASTRO_API_FILE`), w kolejności ASTRO/DeepSeek/Grok/Gemini/OpenRouter.
    Nazwa historyczna; NIE czyta już konfiguracji Ateny."""
    from astro import remote_support
    out = []
    for p in remote_support.provider_chain(path=path, include_pc=False):
        # etykieta per KONTO (np. gemini#1) - pozwala wykorzystać dzienne limity wszystkich kont
        # (wspólna etykieta „gemini” po 429 ucinałaby wszystkie konta naraz).
        out.append(Provider(p.url, p.model, p.key, p.account or p.label,
                            headers=getattr(p, "headers", None)))
    return out


def _opencode_provider():
    try:
        with open(OPENCODE_AUTH, encoding="utf-8") as fh:
            key = (json.load(fh).get("opencode-go") or {}).get("key")
    except Exception:
        key = None
    if not key:
        return None
    model = os.environ.get("ASTRO_OPENCODE_MODEL", "deepseek-v4.1-flash")
    return Provider(OPENCODE_URL, model, key, "opencode-go",
                    headers={"x-opencode-session": str(uuid.uuid4())})


def _json_providers(raw):
    try:
        data = json.loads(raw)
    except Exception:
        return []
    out = []
    for p in data if isinstance(data, list) else []:
        if isinstance(p, dict) and p.get("url") and p.get("model"):
            out.append(Provider(p["url"], p["model"], p.get("key", ""), p.get("label", "custom")))
    return out


def build_providers(args):
    if os.environ.get("ASTRO_TEACHER_PROVIDERS"):
        provs = _json_providers(os.environ["ASTRO_TEACHER_PROVIDERS"])
        if provs:
            return provs
    provs = _atena_providers(getattr(args, "api_file", None))
    if args.url and args.model:
        provs = [Provider(args.url, args.model, args.key, "cli")] + provs
    if not getattr(args, "no_opencode", False):
        oc = _opencode_provider()
        if oc:
            provs.append(oc)
    # Filtr dostawców-nauczycieli: pomiń niestabilne do tool-callingu (np. gemini thought_signature,
    # groq/opencode 403). Przykład: ASTRO_TEACHER_SKIP=gemini,groq,deepseek,grok,opencode.
    skip = {s.strip().lower() for s in os.environ.get("ASTRO_TEACHER_SKIP", "").split(",") if s.strip()}
    if skip:
        # etykiety kont mają sufiks „#n" (gemini#1) — porównujemy po nazwie dostawcy.
        provs = [p for p in provs if p.label.split("#")[0].lower() not in skip]
    return provs


DEFAULT_CHAT_SEEDS = [
    "Wyjaśnij krok po kroku, jak działa fotosynteza.",
    "Czym różni się pamięć RAM od dysku SSD? Wyjaśnij prosto.",
    "Dlaczego niebo jest niebieskie? Uzasadnij.",
    "Wyjaśnij, jak działa algorytm sortowania bąbelkowego.",
    "Co to jest inflacja i jak wpływa na oszczędności?",
    "Wyjaśnij różnicę między AI a uczeniem maszynowym.",
    "Jak działa protokół HTTPS i dlaczego jest bezpieczny?",
    "Wyjaśnij zasadę działania silnika spalinowego.",
    "Dlaczego woda wrze w niższej temperaturze w górach?",
    "Porównaj demokrację i autokrację, podaj wady i zalety.",
    "Jak zaplanować zdrowy tydzień pracy, uwzględniając odpoczynek?",
    "Wyjaśnij, czym jest fotowoltaika i jak działa instalacja PV.",
    "Jak działa GPS? Wyjaśnij, skąd bierze się dokładna pozycja.",
    "Czym jest odporność zbiorowa i dlaczego jest ważna?",
    "Wyjaśnij różnicę między procesem a wątkiem w systemie.",
    "Jak działa kryptografia klucza publicznego? Podaj intuicję.",
    "Dlaczego warto oszczędzać energię elektryczną? Podaj argumenty.",
    "Wyjaśnij, jak implanty słuchowe pomagają w niedosłuchu.",
    "Jak przebiega proces uchwalania ustawy w Polsce?",
    "Czym różni się teoria od hipotezy? Wyjaśnij na przykładzie.",
    "Jak działa sieć neuronowa? Wyjaśnij laikowi.",
    "Dlaczego ćwiczę i nie widzę efektów? Wyjaśnij możliwe przyczyny.",
    "Wyjaśnij, jak działa chłodzenie w komputerze i czemu służy.",
    "Jakie są skutki nadmiaru cukru w diecie? Wyjaśnij rzeczowo.",
    "Czym jest ślad węglowy i jak można go zmniejszyć?",
]


@dataclass
class Endpoint:
    label: str
    url: str
    model: str
    key: str = ""
    role: str = "tools"   # tools | chat


def _endpoints(args):
    """Lista maszyn-nauczycieli do pracy RÓWNOLEGŁEJ (env/JSON albo --endpoint)."""
    raw = os.environ.get("ASTRO_TEACHER_ENDPOINTS")
    if raw:
        try:
            data = json.loads(raw)
        except Exception:
            data = []
        out = []
        for e in data if isinstance(data, list) else []:
            if isinstance(e, dict) and e.get("url") and e.get("model"):
                out.append(Endpoint(e.get("label", "ep"), e["url"], e["model"],
                                    e.get("key", ""), e.get("role", "tools")))
        if out:
            return out
    out = []
    for spec in getattr(args, "endpoint", None) or []:
        # "label=url|model|role" (role opcjonalnie)
        try:
            label, rest = spec.split("=", 1)
            parts = rest.split("|")
            url, model = parts[0], parts[1]
            role = parts[2] if len(parts) > 2 else "tools"
            out.append(Endpoint(label, url, model, "", role))
        except Exception:
            print(f"[teacher] zły --endpoint: {spec}", file=sys.stderr)
    if out:
        return out
    # Domyślnie: PC (Kali) i PC-MAX z konfiguracji ASTRO.
    pc2_url = os.environ.get("ASTRO_PC2_URL")
    pc2_model = os.environ.get("ASTRO_PC2_MODEL")
    if config.PC_URL:
        out.append(Endpoint("pc", config.PC_URL.rstrip("/") + "/v1", config.PC_MODEL, "",
                            os.environ.get("ASTRO_PC_ROLE", "tools")))
    if pc2_url and pc2_model:
        out.append(Endpoint("pc-max", pc2_url.rstrip("/") + "/v1", pc2_model, "",
                            os.environ.get("ASTRO_PC2_ROLE", "tools")))
    return out


def generate_chat(goal, teacher, timeout=120, temperature=0.3):
    """Trajektoria tekstowa (polszczyzna/teoria/rozumowanie): pytanie -> odpowiedź bez narzędzi.

    Używamy promptu CZATU (nie agenta narzędziowego): z SYSTEM_PROMPT nauczyciel odmawiał przy
    pytaniach o obyczaje/język („nie mam dostępu do narzędzi językowych").
    """
    messages = [{"role": "system", "content": CHAT_TEACHER_PROMPT},
                {"role": "user", "content": goal}]
    try:
        msg = teacher.chat(messages, timeout=timeout, temperature=temperature)
    except Exception:
        return None
    answer = (msg.get("content") or "").strip()
    if len(answer) < 40:
        return None
    return {"goal": goal, "steps": [], "answer": answer, "result": ""}


import re as _re

# Prompt NAUCZYCIELA CZATU (nie agenta narzędzi): obyczajowe/społeczne/polszczyzna bez odmów.
CHAT_TEACHER_PROMPT = (
    "Jesteś ASTRO — życzliwą asystentką mówiącą poprawną polszczyzną. Odpowiadaj rzeczowo, ciepło "
    "i konkretnie. Swobodnie odpowiadaj na pytania o obyczaje, tradycje, relacje społeczne, kulturę "
    "i język polski (gramatyka, ortografia, odmiana, frazeologia). Nie wspominaj o narzędziach, "
    "systemie ani własnych ograniczeniach — po prostu udziel dobrej, użytecznej odpowiedzi.")

# Meta-instrukcje, które model-nauczyciel zwracał zamiast pytań (np. „Pytania powinny być
# otwarte…", „Wygeneruj 10 pytań…", „Unikaj powtarzania…"). Wcześniej trafiały jako cele do
# zbioru treningowego (pętla zwrotna przez chat_bank.txt) — teraz twardo odrzucane.
_META_GOAL_RE = _re.compile(
    r"\b(?:wygeneruj|stworz|stwórz|unikaj|nie powtarzaj|zwroc|zwróć|"
    r"sformuluj|sformułuj|wymysl|wymyśl|pytania powinny|odpowiedzi powinny)\b", _re.I)
_META_PHRASES = ("pytania powinny", "odpowiedzi powinny", "unikaj powtarzania", "nie powtarzaj",
                 "zadbaj o to", "pytania musza", "pytania muszą",
                 "odpowiedzi musza", "odpowiedzi muszą")


def _valid_goal(g, question_only=False):
    """Czy wygenerowany cel nadaje się na pytanie/polecenie użytkownika (nie meta-instrukcja).

    Odrzucamy wyłącznie ewidentne meta-instrukcje generatora („Pytania powinny…", „Wygeneruj
    listę pytań…", „Unikaj powtarzania…") — NIE wymuszamy formy pytania, bo poprawne cele to też
    rozkaźniki („Wyjaśnij…", „Porównaj…"). `question_only` zachowane dla kompatybilności."""
    g = (g or "").strip()
    if len(g) < 6 or len(g) > 200 or "\n" in g or g.startswith(("{", "[")):
        return False
    low = g.lower()
    if _META_GOAL_RE.search(g) or any(p in low for p in _META_PHRASES):
        return False
    return True


def invent_goals(teacher, schemas, n, timeout=180, temperature=0.9, avoid=None):
    """Wymyśla N NOWYCH, realistycznych poleceń użytkownika (na podstawie schematów narzędzi)."""
    names = [s["function"]["name"] for s in schemas]
    user = f"Narzędzia: {', '.join(names)}. Wygeneruj {n} poleceń."
    if avoid:
        user += "\nNIE powtarzaj poleceń podobnych do tych: " + "; ".join(list(avoid)[-25:])
    msgs = [{"role": "system", "content":
             "Jesteś projektantem zbioru danych dla agenta narzędziowego ASTRO. Wygeneruj RÓŻNE, "
             "realistyczne polecenia użytkownika po polsku, których wykonanie wymaga narzędzia z "
             "listy. Każde inne, konkretne i wykonalne. Zwróć WYŁĄCZNIE JSON: "
             "{\"goals\": [\"...\"]}."},
            {"role": "user", "content": user}]
    out = []
    try:
        msg = teacher.chat(msgs, fmt={"type": "json_object"}, timeout=timeout,
                           temperature=temperature)
        data = json.loads(msg.get("content") or "{}")
        out = [g.strip() for g in (data.get("goals") or [])
               if isinstance(g, str) and _valid_goal(g)]
    except Exception:
        pass
    return out


def invent_chat_goals(teacher, n, timeout=180, temperature=0.9, avoid=None):
    """Wymyśla N nowych pytań do rozmowy (polszczyzna/teoria/rozumowanie)."""
    user = f"Wygeneruj {n} pytań."
    if avoid:
        user += "\nNIE powtarzaj pytań podobnych do tych: " + "; ".join(list(avoid)[-25:])
    msgs = [{"role": "system", "content":
             "Wygeneruj RÓŻNE, naturalne pytania po polsku do rozmowy z asystentem: teoria, "
             "wyjaśnienia krok po kroku, rozumowanie, praktyczne porady. Każde inne. "
             "Zwróć WYŁĄCZNIE JSON: {\"goals\": [\"...\"]}."},
            {"role": "user", "content": user}]
    out = []
    try:
        msg = teacher.chat(msgs, fmt={"type": "json_object"}, timeout=timeout,
                           temperature=temperature)
        data = json.loads(msg.get("content") or "{}")
        out = [g.strip() for g in (data.get("goals") or [])
               if isinstance(g, str) and _valid_goal(g, question_only=True)]
    except Exception:
        pass
    return out


def _chat_ok(answer):
    low = answer.lower()
    if len(answer) < 40:
        return False
    if any(b in low for b in ("<tool", "dsml", "as an ai", "i cannot", "i'm sorry")):
        return False
    # odrzuć odpowiedzi niemal w całości angielskie
    pl = sum(low.count(ch) for ch in "ąćęłńóśźż ")
    en = sum(low.count(f" {w} ") for w in (" the ", " and ", " is ", " are ", " of ", " to "))
    return pl > 0 and en <= 2


def run_parallel(endpoints, tasks, args, mem, schemas, seed_tools):
    """Uruchamia maszyny równolegle. `tasks` = {label: [goals]}. Zwraca {label: stats}.

    ZAPIS PRZYROSTOWY: każdy zdobyty rekord jest natychmiast zapisywany do SQLite (własne
    połączenie per wątek) i dopisywany do JSONL pod zamkiem — restart/awaria nie traci danych.
    """
    lock = threading.Lock()
    out_fh = None if args.dry_run else open(args.out, "a", encoding="utf-8")

    def _save(tmem, rec, score):
        with lock:
            if args.dry_run:
                print(f"[dry] {rec['goal'][:50]} -> "
                      f"{rec.get('result') or rec['answer'][:40]} (score={score})")
                return
            store(tmem, rec, score)
            out_fh.write(json.dumps({"messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": rec["goal"]}],
                "steps": rec["steps"], "answer": rec["answer"], "score": score},
                ensure_ascii=False) + "\n")
            out_fh.flush()

    def work(ep):
        teacher = Teacher([Provider(ep.url, ep.model, ep.key, ep.label)], verbose=True)
        tmem = Memory(args.db)
        goals = tasks.get(ep.label, [])
        stats = {"added": 0, "rejected": 0, "goals": len(goals)}
        t_start = time.time()
        for idx, goal in enumerate(goals, 1):
            if ep.role == "chat":
                rec = generate_chat(goal, teacher, timeout=args.timeout)
                if not rec or not _chat_ok(rec["answer"]):
                    stats["rejected"] += 1
                    print(f"[prog] {ep.label} {idx}/{len(goals)} ODRZUCONE", flush=True)
                    continue
                _save(tmem, rec, 5)
                stats["added"] += 1
                print(f"[prog] {ep.label} {idx}/{len(goals)} OK", flush=True)
                continue
            try:
                hint = seed_tools.get(goal) if seed_tools else None
                rec = generate_trajectory(goal, teacher, schemas, make_ctx(),
                                          execute=not args.no_execute, timeout=args.timeout,
                                          hint=hint)
            except Exception as e:
                print(f"[{ep.label}] błąd ({goal[:40]}): {e}", file=sys.stderr)
                rec = None
            if not rec:
                stats["rejected"] += 1
                print(f"[prog] {ep.label} {idx}/{len(goals)} ODRZUCONE", flush=True)
                continue
            score = 5
            if not args.no_judge:
                ok, score, note = judge(rec["goal"], rec["steps"], rec["answer"], teacher)
                if not ok or score < args.min_score:
                    stats["rejected"] += 1
                    print(f"[{ep.label}] odrzucone (score={score}): {goal[:50]} {note}")
                    print(f"[prog] {ep.label} {idx}/{len(goals)} ODRZUCONE", flush=True)
                    continue
            _save(tmem, rec, score)
            stats["added"] += 1
            n_steps = len(rec.get("steps") or [])
            print(f"[prog] {ep.label} {idx}/{len(goals)} OK ({n_steps} kroków, "
                  f"{time.time() - t_start:.0f}s)", flush=True)
        print(f"[{ep.label}] ({ep.model}, rola={ep.role}): dodane={stats['added']} "
              f"odrzucone={stats['rejected']}", flush=True)
        return ep.label, stats

    results = {}
    try:
        with ThreadPoolExecutor(max_workers=max(1, len(endpoints))) as ex:
            futs = {ex.submit(work, ep): ep for ep in endpoints}
            for f in as_completed(futs):
                label, stats = f.result()
                results[label] = stats
    finally:
        if out_fh:
            out_fh.close()
    return results


def _post_json(base, key, payload, timeout=120, extra_headers=None):
    url = base.rstrip("/") + "/chat/completions"
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json",
               "Accept": "application/json",
               "User-Agent": ("Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")}
    if key:
        headers["Authorization"] = "Bearer " + key
    if "openrouter" in base:
        headers["HTTP-Referer"] = "https://opencode.ai"
        headers["X-Title"] = "ASTRO-teacher"
    if extra_headers:
        headers.update(extra_headers)
    # OpenCode Go wymaga `x-opencode-session` (inaczej 400 MissingSessionID) — obronnie.
    if "opencode" in base.lower() and "x-opencode-session" not in {k.lower() for k in headers}:
        headers["x-opencode-session"] = str(uuid.uuid4())
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _chat_one(provider, messages, tools=None, fmt=None, timeout=120, temperature=0.2,
              max_tokens=None):
    # Limit generacji nauczyciela: darmowe konta (OpenRouter/HF) mają mały budżet na request
    # (np. „afford 625" przy 2048 → HTTP 402). Domyślnie 512 z configu; nadpisywalne.
    if max_tokens is None:
        max_tokens = int(getattr(config, "TEACHER_MAX_TOKENS", 512) or 512)
    payload = {"model": provider.model, "messages": messages,
               "temperature": temperature, "stream": False, "max_tokens": max_tokens}
    if tools:
        payload["tools"] = tools
    if fmt:
        payload["response_format"] = fmt
    try:
        data = _post_json(provider.url, provider.key, payload, timeout=timeout,
                          extra_headers=provider.headers)
    except urllib.error.HTTPError:
        if fmt:
            payload.pop("response_format", None)
            data = _post_json(provider.url, provider.key, payload, timeout=timeout,
                              extra_headers=provider.headers)
        else:
            raise
    msg = (data.get("choices") or [{}])[0].get("message") or {}
    msg["_usage"] = data.get("usage") or {}
    return msg


class Teacher:
    """Łańcuch dostawców z failoverem (darmowe najpierw; błąd/429 -> następny)."""

    def __init__(self, providers, verbose=True):
        self.providers = providers
        self.verbose = verbose
        self._strikes = {}
        self._dead = set()
        self.usage = {}

    def _add_usage(self, label, usage):
        row = self.usage.setdefault(label, {"prompt": 0, "completion": 0, "total": 0, "calls": 0})
        row["calls"] += 1
        row["prompt"] += int(usage.get("prompt_tokens") or 0)
        row["completion"] += int(usage.get("completion_tokens") or 0)
        row["total"] += int(usage.get("total_tokens") or 0)

    def chat(self, messages, tools=None, fmt=None, timeout=120, temperature=0.2,
             max_tokens=None):
        last = None
        for p in self.providers:
            if p.label in self._dead:
                continue
            for attempt in range(3):
                try:
                    result = _chat_one(p, messages, tools=tools, fmt=fmt, timeout=timeout,
                                       temperature=temperature, max_tokens=max_tokens)
                    self._add_usage(p.label, result.pop("_usage", {}) or {})
                    self._strikes[p.label] = 0
                    return result
                except urllib.error.HTTPError as e:
                    body = e.read().decode("utf-8", "replace")[:200].replace("\n", " ")
                    last = RuntimeError(f"HTTP {e.code}: {body}")
                    if e.code in (400, 401, 402, 403, 404):
                        # trwały błąd konta (brak środków/uprawnień/klucza) - nie ponawiaj w kółko
                        self._dead.add(p.label)
                    if e.code == 429:
                        self._strikes[p.label] = self._strikes.get(p.label, 0) + 1
                        if self._strikes[p.label] >= 2:
                            self._dead.add(p.label)
                    if e.code in (429, 500, 502, 503, 504, 422) and attempt < 2:
                        time.sleep(2 * (attempt + 1))
                        continue
                    break
                except Exception as e:
                    last = e
                    break
            if self.verbose:
                print(f"[teacher] {p.label} ({p.model}) nie odpowiada: {last}", file=sys.stderr)
        raise last or RuntimeError("brak dostawców")


def _tool_seeds():
    try:
        from astro.scripts import toolcall_gen
        seeds = [s["q"] for s in toolcall_gen.SCENARIOS] + [c["q"] for c in toolcall_gen.CHAINS]
        return list(dict.fromkeys(seeds))
    except Exception:
        return []


def _seed_tools():
    """Mapowanie pytanie-seed -> oczekiwane narzędzia (dla trybu --guided)."""
    out = {}
    try:
        from astro.scripts import toolcall_gen
        for s in toolcall_gen.SCENARIOS:
            out[s["q"]] = [s["tool"]]
        for c in toolcall_gen.CHAINS:
            out[c["q"]] = [st["tool"] for st in c["steps"]]
    except Exception:
        pass
    return out


PASSWORD_CHAT_SEEDS = [
    "Jak bezpiecznie podyktować hasło do Wi-Fi asystentowi głosowemu?",
    "Jak literować hasło zawierające znaki specjalne przez głos?",
    "Co zrobić, gdy asystent nie rozumie literowanego hasła?",
    "Jak potwierdzić podane hasło przed połączeniem z siecią?",
    "Dlaczego hasło podaje się litera po literze, a nie całym słowem?",
    "Jak zmienić hasło do sieci Wi-Fi w domu?",
    "Czy asystent zapisuje podane hasło i czy to bezpieczne?",
]

# Nazwa pliku z realnymi komendami must-have (## / ### = „hasła" użytkownika).
COMMANDS_FILE = config.REPO / "data" / "commands" / "komendy_must-have.txt"

# Reguła -> oczekiwane narzędzie (pierwsze trafienie wygrywa). Celem jest zakotwiczenie
# generacji w REALNYCH komendach użytkownika, nie w losowych celach z samych schematów.
_CMD_HINT_RULES = [
    (r"aktualizuj repozytoria|aktualizuj zrodla|aktualizuj źródła", ["update_system"]),
    (r"aktualizuj aplikacje|aktualizuj programy|instaluj program|instaluj aplikacj", ["update_system"]),
    (r"znajdz dostepne sieci|znajdź dostępne sieci|sprawdz dostepne sieci|sprawdź dostępne sieci",
     ["wifi_scan"]),
    (r"polacz z siecia|połącz z siecią|dolacz do sieci|dołącz do sieci", ["wifi_connect"]),
    (r"rozlacz z siecia|rozłącz z siecią|wyjdz z sieci|wyjdź z sieci", ["wifi_disconnect"]),
    (r"wylacz system|wyłącz system|zamknij system|restart systemu|zrestartuj|reset systemu",
     ["system_power"]),
    (r"raport", None),  # generowany skryptem, nie narzędziem tool-calling - pomiń
    (r"pogod", ["web_search"]),
    (r"co to jest|do czego sluzy|do czego służy|jak dziala|jak działa|porownaj|porównaj",
     ["search_knowledge"]),
    (r"najblisz|najbliż|adres najblisz", ["nearby_places"]),
    (r"oblicz|kalkulator", ["run_script"]),
    (r"kurs|dolar|euro|walut|przewalutowanie", ["web_search"]),
    (r"temperatur|procesor|cpu|pamie|pamię|zasob|zasięg|zasię|adres ip|podaj ip|swoje ip|npu|hailo",
     ["system_info"]),
]


def _parse_command_phrases(path=None):
    """Wyciąga realne frazy-komendy („hasła") z pliku must-have (linie ## / ###).

    `## wylacz system / zamknij system - opis` -> ["wylacz system", "zamknij system"]."""
    path = path or COMMANDS_FILE
    out = []
    try:
        with open(path, encoding="utf-8") as fh:
            for ln in fh:
                s = ln.strip()
                if s.startswith("### "):
                    body = s[3:].strip()
                elif s.startswith("## "):
                    body = s[2:].strip()
                else:
                    continue
                head = _re.split(r"\s*[-–—]{2,}\s*>\s*|\s*→\s*", body)[0]
                head = head.split(" - ", 1)[0]
                for part in head.split("/"):
                    p = " ".join(part.split()).strip(" .-–—")
                    p = _re.sub(r"\s*\([^)]*\)", "", p).strip()  # usuń wskazówki fonetyczne
                    p = _re.sub(r"\[[^\]]*\]", "", p).strip()  # usuń sloty [.zmienna.]
                    if not p or p.isupper() or "[" in p or "..." in p:
                        continue
                    if len(p) < 6 or len(p) > 120:
                        continue
                    out.append(p)
    except OSError:
        return []
    return list(dict.fromkeys(out))


def command_seed_hints(path=None):
    """Realne komendy must-have -> {cel: [narzędzia]} (tylko frazy mapowalne na narzędzie)."""
    out = {}
    for phrase in _parse_command_phrases(path):
        low = phrase.lower()
        for rx, tools in _CMD_HINT_RULES:
            if _re.search(rx, low):
                if tools:
                    out.setdefault(phrase, list(tools))
                break
    return out


def _canned():
    try:
        from astro.scripts.toolcall_gen import CANNED
        return CANNED
    except Exception:
        return {}


_TOOL_JSON_MARKERS = ("<tool_call", "<|dsml", "<|tool", "invoke name=", "[tool_calls]")
_KNOWN_TOOLS = None


def _known_tools():
    global _KNOWN_TOOLS
    if _KNOWN_TOOLS is None:
        try:
            _KNOWN_TOOLS = set(registry.names())
        except Exception:
            _KNOWN_TOOLS = set()
    return _KNOWN_TOOLS


def _call_from_obj(obj):
    """Pojedynczy obiekt JSON -> wywołanie narzędzia (tylko znane narzędzia) lub None."""
    if not isinstance(obj, dict):
        return None
    name, args = normalize_call(obj)
    if name in _known_tools():
        return {"name": name, "args": args}
    return None


def _iter_json_values(text):
    """Wydobywa kolejne wartości JSON z dowolnego tekstu (od { lub [)."""
    dec = json.JSONDecoder()
    i, n = 0, len(text)
    while i < n:
        if text[i] in "{[":
            try:
                val, end = dec.raw_decode(text[i:])
            except Exception:
                i += 1
                continue
            yield val
            i += end
        else:
            i += 1


def calls_from_content(text):
    """Odzyskuje wywołania narzędzi, gdy model zwrócił je w TREŚCI zamiast w `tool_calls`.

    Dotyczy głównie darmowych modeli (np. deepseek-v4.1-flash), które wstawiają JSON/DSML do
    treści. Bez tego `generate_trajectory` odrzucało je jako „brak wywołań" (główna strata
    wydajności z darmowej puli). Przyjmujemy tylko JEDNOZNACZNE przypadki: treść parsowalna jako
    JSON albo jawne bloki <tool_call>/DSML/[TOOL_CALLS]."""
    text = (text or "").strip()
    if not text:
        return []
    looks_call = (text[0] in "{[") or any(m in text.lower() for m in _TOOL_JSON_MARKERS)
    if not looks_call:
        return []
    out = []
    for val in _iter_json_values(text):
        items = val if isinstance(val, list) else [val]
        for it in items:
            if not isinstance(it, dict):
                continue
            nested = it.get("tool_calls")
            if isinstance(nested, list):
                for sub in nested:
                    c = _call_from_obj(sub)
                    if c:
                        out.append(c)
                continue
            c = _call_from_obj(it)
            if c:
                out.append(c)
    # Styl DSML: <|DSML|invoke name="run_command"><|DSML|parameter name="command">df -h</...>
    for m in _re.finditer(r'invoke\s+name\s*=\s*"([^"]+)"(.*?)(?:invoke\s*>|</)', text, _re.S | _re.I):
        name, body = m.group(1), m.group(2)
        args = {}
        for pm in _re.finditer(r'parameter\s+name\s*=\s*"([^"]+)"\s*>(.*?)(?:</|parameter\s*>|$)',
                               body, _re.S | _re.I):
            args[pm.group(1)] = pm.group(2).strip().strip('"')
        if name in _known_tools():
            out.append({"name": name, "args": args})
    seen, uniq = set(), []
    for c in out:
        key = (c["name"], json.dumps(c["args"], sort_keys=True, ensure_ascii=False))
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    return uniq


def parse_calls(msg):
    calls = []
    for i, tc in enumerate(msg.get("tool_calls") or []):
        name, args = normalize_call(tc)
        if name:
            calls.append({"name": name, "args": args, "id": tc.get("id") or f"call_{i}"})
    if not calls:
        for j, c in enumerate(calls_from_content(msg.get("content") or "")):
            calls.append({"name": c["name"], "args": c["args"], "id": f"call_{j}"})
    return calls


def _assistant_tool_calls(calls):
    """Odtwarza poprawne OpenAI `tool_calls` (z id) dla kontynuacji rozmowy."""
    out = []
    for i, c in enumerate(calls):
        cid = c.get("id") or f"call_{i}"
        c["id"] = cid
        out.append({"id": cid, "type": "function",
                    "function": {"name": c["name"],
                                 "arguments": json.dumps(c["args"], ensure_ascii=False)}})
    return out


def _type_ok(value, spec):
    t = (spec or {}).get("type")
    if t == "string":
        return isinstance(value, str)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "array":
        return isinstance(value, list)
    if t == "object":
        return isinstance(value, dict)
    return True


def validate_calls(calls, schema_map=None):
    schema_map = schema_map or {s["function"]["name"]: s["function"] for s in registry.schemas()}
    if not calls:
        return False, "brak wywołań"
    for c in calls:
        spec = schema_map.get(c["name"])
        if spec is None:
            return False, f"nieznane narzędzie: {c['name']}"
        params = (spec.get("parameters") or {}).get("properties") or {}
        required = (spec.get("parameters") or {}).get("required") or []
        args = c.get("args") or {}
        for req in required:
            if req not in args:
                return False, f"{c['name']}: brak wymaganego argumentu {req}"
        for key, val in args.items():
            if key in params and not _type_ok(val, params[key]):
                return False, f"{c['name']}: zły typ argumentu {key}"
    return True, ""


def _is_readonly(name):
    tool = registry.get(name)
    return bool(tool) and set(tool.scopes) <= {"read"}


def result_for(name, args, ctx, execute=True):
    if execute and _is_readonly(name):
        res = registry.execute(name, args, ctx)
        return str(getattr(res, "text", res)), bool(getattr(res, "ok", True))
    return _canned().get(name, "wynik narzędzia"), True


def make_ctx():
    return ToolContext(settings=config,
                       memory=Memory(os.path.join(tempfile.mkdtemp(), "t.db")),
                       confirmer=Confirmer(auto=True), registry=registry)


def generate_trajectory(goal, teacher, schemas, ctx, execute=True, max_steps=3, timeout=120,
                        hint=None, max_nudges=2):
    system = SYSTEM_PROMPT
    if hint:
        system += (f"\nDODATKOWA WSKAZÓWKA: w tym zadaniu użyj narzędzia/narzędzi: "
                   f"{', '.join(hint)} (zgodnie ze schematem). Nie używaj ask_user, chyba że "
                   f"naprawdę brakuje kluczowej informacji.")
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": goal}]
    steps = []
    # Wywołanie narzędzia = bardzo mało tokenów (nazwa+argumenty). Twardy limit chroni przed
    # odrzuceniem 402 u dostawców rozliczających `max_tokens` z góry (OpenRouter/DeepSeek).
    call_tokens = int(getattr(config, "TEACHER_TOOLCALL_TOKENS", 256) or 256)
    nudges = 0
    # Ponawiamy z KOREKTĄ zamiast od razu odrzucać: słabi nauczyciele (darmowa pula) często
    # zwracają wywołanie w treści albo z drobnym błędem — naprawa podnosi wydajność partii.
    for _ in range(max_steps + max_nudges):
        msg = teacher.chat(messages, tools=schemas, timeout=timeout, temperature=0.1,
                           max_tokens=call_tokens)
        calls = parse_calls(msg)
        content = (msg.get("content") or "").strip()
        if not calls:
            if steps and content:
                return {"goal": goal, "steps": steps, "answer": content,
                        "result": ", ".join(s["name"] for s in steps)}
            if nudges >= max_nudges:
                return None
            nudges += 1
            if steps:
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content":
                                 "Podaj teraz KRÓTKĄ finalną odpowiedź dla użytkownika po polsku, "
                                 "opartą na wynikach narzędzi (tekst, NIE wywołanie narzędzia)."})
            else:
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content":
                                 "To zadanie wymaga narzędzia. Wywołaj odpowiednie narzędzie "
                                 "(tool_calls) zgodnie ze schematem, z poprawnymi argumentami."})
            continue
        ok, why = validate_calls(calls)
        if not ok:
            if nudges >= max_nudges:
                return None
            nudges += 1
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content":
                             f"Twoje wywołanie było niepoprawne ({why}). Popraw je, używając "
                             f"dokładnej nazwy narzędzia i argumentów zgodnych ze schematem."})
            continue
        messages.append({"role": "assistant", "content": content,
                         "tool_calls": _assistant_tool_calls(calls)})
        for c in calls:
            text, tool_ok = result_for(c["name"], c["args"], ctx, execute=execute)
            steps.append({"name": c["name"], "args": c["args"], "ok": tool_ok, "result": text[:1500]})
            messages.append({"role": "tool", "tool_call_id": c["id"], "name": c["name"],
                             "content": text[:1500]})
    msg = teacher.chat(messages, timeout=timeout)
    answer = (msg.get("content") or "").strip()
    if steps and answer:
        return {"goal": goal, "steps": steps, "answer": answer,
                "result": ", ".join(s["name"] for s in steps)}
    return None


def judge(goal, steps, answer, teacher, timeout=120):
    summary = {"zadanie": goal,
               "dozwolone_narzedzia": registry.names(),
               "kroki": [{"narzedzie": s["name"], "argumenty": s["args"]} for s in steps],
               "odpowiedz": answer}
    msgs = [{"role": "system", "content": JUDGE_PROMPT},
            {"role": "user", "content": json.dumps(summary, ensure_ascii=False)}]
    try:
        msg = teacher.chat(msgs, fmt={"type": "json_object"}, timeout=timeout, temperature=0.0)
        data = json.loads(msg.get("content") or "{}")
    except Exception as e:
        return False, 0, f"błąd sędziego: {e}"
    score = int(data.get("score") or 0)
    return bool(data.get("ok")) and score >= 1, score, "; ".join(data.get("problems") or [])


def expand_seeds(seeds, teacher, n, timeout=120, pace=0.0):
    out = []
    total = len(seeds)
    for i, seed in enumerate(seeds, 1):
        if pace:
            time.sleep(pace)
        msgs = [{"role": "system", "content":
                 f"Podaj {n} innych, naturalnych po polsku sformułowań tego polecenia "
                 f"(to samo zadanie). Zwróć WYŁĄCZNIE JSON: {{\"paraphrases\": [\"...\"]}}"},
                {"role": "user", "content": seed}]
        try:
            msg = teacher.chat(msgs, fmt={"type": "json_object"}, timeout=timeout, temperature=0.7)
            data = json.loads(msg.get("content") or "{}")
            add = [p.strip() for p in (data.get("paraphrases") or [])
                   if isinstance(p, str) and _valid_goal(p)]
            out.extend(add)
            print(f"[teacher] expand {i}/{total}: +{len(add)} (razem {len(out)})", flush=True)
        except Exception as e:
            print(f"[teacher] expand {i}/{total}: błąd ({str(e)[:50]})", flush=True)
            continue
    return out


def store(mem, rec, score=0):
    return mem.add_trajectory(kind="agent", goal=rec["goal"], steps=rec["steps"],
                              result=rec.get("result", ""), answer=rec["answer"],
                              source="cloud_teacher", ok=True)


def print_usage(teacher):
    if not getattr(teacher, "usage", None):
        return
    print("[teacher] zużycie tokenów (per dostawca):")
    for label, row in sorted(teacher.usage.items()):
        print(f"  {label}: calls={row['calls']} prompt={row['prompt']} "
              f"completion={row['completion']} total={row['total']}")


def main():
    ap = argparse.ArgumentParser(description="Chmurowy nauczyciel: dane + judge (ASTRO)")
    ap.add_argument("--url", default=os.environ.get("ASTRO_TEACHER_URL", ""))
    ap.add_argument("--model", default=os.environ.get("ASTRO_TEACHER_MODEL", ""))
    ap.add_argument("--key", default=os.environ.get("ASTRO_TEACHER_KEY", ""))
    ap.add_argument("--api-file", default=config.API_FILE,
                    help="plik z kluczami ASTRO (domyślnie /etc/astro-secrets/API)")
    ap.add_argument("--seeds", default="", help="plik z pytaniami (inaczej wbudowane scenariusze)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--expand", type=int, default=0)
    ap.add_argument("--no-execute", action="store_true")
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--min-score", type=int, default=3)
    ap.add_argument("--judge-only", action="store_true")
    ap.add_argument("--probe", action="store_true", help="sprawdź dostawców i zakończ")
    ap.add_argument("--db", default=str(config.DB_PATH))
    ap.add_argument("--out", default=str(config.REPO / "datasets" / "cloud_teacher.jsonl"))
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--pace", type=float, default=0.0, help="przerwa (s) między seedami - mniej 429")
    ap.add_argument("--timeout", type=int, default=120, help="limit czasu pojedynczego wywołania (s)")
    ap.add_argument("--no-opencode", action="store_true",
                    help="nie używaj klucza opencode (tylko darmowe dostawcy)")
    ap.add_argument("--skip-known", action="store_true",
                    help="pomiń cele mające już trajektorię cloud_teacher")
    ap.add_argument("--guided", action="store_true",
                    help="podpowiedz nauczycielowi oczekiwane narzędzia (domyka trudne cele)")
    ap.add_argument("--parallel", action="store_true",
                    help="generuj RÓWNOLEGLE na wielu maszynach (--endpoint / ASTRO_TEACHER_ENDPOINTS)")
    ap.add_argument("--endpoint", action="append", default=[],
                    help="label=url|model|role (mnożne; rola: tools|chat)")
    ap.add_argument("--chat-seeds", default="",
                    help="plik pytań dla roli chat (polszczyzna/teoria/rozumowanie)")
    ap.add_argument("--expand-seeds", default="",
                    help="plik-seed ŹRÓDŁO parafraz (domyślnie = --seeds); pozwala rosnąć bankowi")
    ap.add_argument("--seed-bank", default="",
                    help="plik, do którego dopisujemy nowe parafrazy (trwały bank seedów)")
    ap.add_argument("--invent", type=int, default=0,
                    help="wygeneruj N NOWYCH celów (na podstawie schematów narzędzi) i dodaj do banku")
    ap.add_argument("--chat-invent", type=int, default=0,
                    help="wygeneruj N nowych pytań-rozmowy (polszczyzna/teoria) i dodaj do banku")
    ap.add_argument("--chat-bank", default="", help="trwały bank pytań-rozmowy (append)")
    ap.add_argument("--commands", action="store_true",
                    help="dołącz REALNE komendy/hasła z listy must-have (data/commands)")
    ap.add_argument("--commands-file", default="",
                    help="własny plik komend must-have (domyślnie data/commands/komendy_must-have.txt)")
    ap.add_argument("--chat-commands", action="store_true",
                    help="dołącz pytania o hasła/literowanie sekretów do roli chat")
    ap.add_argument("--avoid", default="",
                    help="lista „nie powtarzaj” (rotacja duplikatów → świeże; "
                         "domyślnie runtime/dups_avoid.txt)")
    args = ap.parse_args()

    # Rotacja duplikatów (reguła 2026-09-27): odrzucone duplikaty z dedup datasetu wracają jako
    # lista „nie powtarzaj" dla generatora — inwencja celów/pytań sięga świeżych obszarów.
    avoid_path = args.avoid or str(config.REPO / "runtime" / "dups_avoid.txt")
    avoid = []
    if os.path.isfile(avoid_path):
        try:
            with open(avoid_path, encoding="utf-8") as fh:
                avoid = [ln.strip() for ln in fh if ln.strip()]
        except OSError:
            avoid = []
        if avoid:
            print(f"[teacher] avoid (nie powtarzaj): {len(avoid)} z {avoid_path}")

    if args.parallel:
        config.ensure_dirs()
        mem = Memory(args.db)
        eps = _endpoints(args)
        if not eps:
            print("[teacher] brak endpointów (--endpoint albo ASTRO_TEACHER_ENDPOINTS).",
                  file=sys.stderr)
            return 2
        if args.seeds and os.path.isfile(args.seeds):
            with open(args.seeds, encoding="utf-8") as fh:
                tool_seeds = [ln.strip() for ln in fh if ln.strip()]
        else:
            tool_seeds = _tool_seeds()
        if args.limit:
            tool_seeds = tool_seeds[:args.limit]
        cmd_hints = {}
        if getattr(args, "commands", False):
            cmd_hints = command_seed_hints(args.commands_file or None)
            extra = [g for g in cmd_hints if g not in tool_seeds]
            tool_seeds = extra + tool_seeds
            print(f"[teacher] commands: +{len(extra)} realnych komend/haseł z listy must-have.")
        if args.chat_seeds and os.path.isfile(args.chat_seeds):
            with open(args.chat_seeds, encoding="utf-8") as fh:
                chat_seeds = [ln.strip() for ln in fh if ln.strip()]
        else:
            chat_seeds = list(DEFAULT_CHAT_SEEDS)
        if args.limit:
            chat_seeds = chat_seeds[:args.limit]
        if getattr(args, "chat_commands", False):
            chat_seeds = list(PASSWORD_CHAT_SEEDS) + [c for c in chat_seeds
                                                      if c not in PASSWORD_CHAT_SEEDS]
            print(f"[teacher] chat-commands: +{len(PASSWORD_CHAT_SEEDS)} pytań o hasła.")
        chat_eps = [e for e in eps if e.role == "chat"]
        if getattr(args, "chat_invent", 0) and chat_eps:
            cep = chat_eps[0]
            cteacher = Teacher([Provider(cep.url, cep.model, cep.key, cep.label)],
                               verbose=False)
            seen = set(chat_seeds)
            newc = []
            cper = min(10, args.chat_invent)
            crounds = max(2, (args.chat_invent + cper - 1) // cper + 2)
            for _ in range(crounds):
                for g in invent_chat_goals(cteacher, cper, avoid=avoid):
                    if g not in seen:
                        seen.add(g)
                        newc.append(g)
                if len(newc) >= args.chat_invent:
                    break
            chat_seeds = chat_seeds + newc
            print(f"[teacher] chat-invent({cep.label}): +{len(newc)} nowych pytań "
                  f"(pula {len(chat_seeds)}).")
            if getattr(args, "chat_bank", ""):
                with open(args.chat_bank, "a", encoding="utf-8") as fh:
                    for g in newc:
                        fh.write(g.strip() + "\n")
        if args.reset and not args.dry_run:
            mem.con.execute("DELETE FROM trajectories WHERE source='cloud_teacher'")
            mem.con.commit()
        schemas = registry.schemas()
        seed_tools = _seed_tools() if args.guided else {}
        seed_tools.update(cmd_hints)
        tasks = {}
        tools_eps = [e for e in eps if e.role != "chat"]
        if getattr(args, "invent", 0) and tools_eps:
            ep0 = tools_eps[0]
            inv_teacher = Teacher([Provider(ep0.url, ep0.model, ep0.key, ep0.label)],
                                  verbose=False)
            seen = set(tool_seeds)
            invented = []
            per = min(10, args.invent)
            rounds = max(2, (args.invent + per - 1) // per + 2)
            for round_i in range(rounds):
                batch = invent_goals(inv_teacher, schemas, per, avoid=avoid)
                add = 0
                for g in batch:
                    if g not in seen:
                        seen.add(g)
                        invented.append(g)
                        add += 1
                print(f"[teacher] invent r{round_i + 1}/{rounds}: +{add} "
                      f"(razem {len(invented)})", flush=True)
                if len(invented) >= args.invent:
                    break
            tool_seeds = tool_seeds + invented
            print(f"[teacher] invent({ep0.label}): +{len(invented)} nowych celów "
                  f"(pula {len(tool_seeds)}).")
            if getattr(args, "seed_bank", ""):
                with open(args.seed_bank, "a", encoding="utf-8") as fh:
                    for g in invented:
                        fh.write(g.strip() + "\n")
        expand_src = tool_seeds
        if getattr(args, "expand_seeds", "") and os.path.isfile(args.expand_seeds):
            with open(args.expand_seeds, encoding="utf-8") as fh:
                expand_src = [ln.strip() for ln in fh if ln.strip()]
        if args.expand and expand_src:
            ep0 = tools_eps[0] if tools_eps else eps[0]
            exp_teacher = Teacher([Provider(ep0.url, ep0.model, ep0.key, ep0.label)],
                                  verbose=False)
            extra = expand_seeds(expand_src, exp_teacher, args.expand,
                                 timeout=args.timeout, pace=args.pace)
            seen = set(tool_seeds)
            uniq = []
            for g in extra:
                if g and g not in seen:
                    seen.add(g)
                    uniq.append(g)
            tool_seeds = tool_seeds + uniq
            print(f"[teacher] expand({ep0.label}, {len(expand_src)} seedów): +{len(uniq)} "
                  f"nowych (pula {len(tool_seeds)}).")
            if getattr(args, "seed_bank", ""):
                with open(args.seed_bank, "a", encoding="utf-8") as fh:
                    for g in uniq:
                        fh.write(g.strip() + "\n")
        if args.skip_known:
            known = {r["goal"] for r in mem.con.execute(
                "SELECT goal FROM trajectories WHERE source='cloud_teacher'")}
            before = len(tool_seeds)
            tool_seeds = [g for g in tool_seeds if g not in known]
            print(f"[teacher] skip-known: pominięto {before - len(tool_seeds)} celów.")
        for i, g in enumerate(tool_seeds):
            if tools_eps:
                tasks.setdefault(tools_eps[i % len(tools_eps)].label, []).append(g)
        if args.skip_known:
            known_chat = {r["goal"] for r in mem.con.execute(
                "SELECT goal FROM trajectories WHERE source='cloud_teacher' AND "
                "(steps_json IS NULL OR steps_json='' OR steps_json='[]')")}
            before = len(chat_seeds)
            chat_seeds = [g for g in chat_seeds if g not in known_chat]
            print(f"[teacher] skip-known chat: pominięto {before - len(chat_seeds)} pytań.")
        chat_workers = [e for e in eps if e.role == "chat"]
        for i, g in enumerate(chat_seeds):
            if chat_workers:
                tasks.setdefault(chat_workers[i % len(chat_workers)].label, []).append(g)
        print("[teacher] równolegle: " + " | ".join(
            f"{e.label}:{e.model}({e.role})" for e in eps), flush=True)
        results = run_parallel(eps, tasks, args, mem, schemas, seed_tools)
        total = sum(s["added"] for s in results.values())
        print(f"[teacher] równolegle dodane={total} | kind=agent: "
              f"{mem.trajectory_count('agent')} | out={args.out}")
        for label, st in sorted(results.items()):
            print(f"  {label}: dodane={st['added']} odrzucone={st['rejected']} "
                  f"cele={st['goals']}")
        return 0

    providers = build_providers(args)
    if not providers:
        print("[teacher] brak dostawców (ATENA env / ASTRO_TEACHER_* / opencode auth).", file=sys.stderr)
        return 2
    print("[teacher] łańcuch: " + " -> ".join(f"{p.label}:{p.model}" for p in providers))
    teacher = Teacher(providers)

    if args.probe:
        msg = teacher.chat([{"role": "user", "content": "Odpowiedz jednym słowem: OK"}],
                           timeout=60)
        print("[probe] odpowiedź:", (msg.get("content") or "").strip()[:80])
        return 0

    config.ensure_dirs()
    mem = Memory(args.db)

    if args.judge_only:
        rows = mem.con.execute(
            "SELECT id, goal, steps_json, answer FROM trajectories "
            "WHERE source='cloud_teacher'").fetchall()
        kept = 0
        for r in rows:
            steps = json.loads(r["steps_json"] or "[]")
            ok, score, note = judge(r["goal"], steps, r["answer"], teacher)
            if ok and score >= args.min_score:
                kept += 1
            else:
                mem.con.execute("DELETE FROM trajectories WHERE id=?", (r["id"],))
                print(f"[judge] odrzucono (score={score}): {r['goal'][:60]} {note}")
        mem.con.commit()
        print(f"[judge] sprawdzono={len(rows)} zatrzymano={kept}")
        print_usage(teacher)
        return 0

    seeds = []
    if args.seeds and os.path.isfile(args.seeds):
        with open(args.seeds, encoding="utf-8") as fh:
            seeds = [ln.strip() for ln in fh if ln.strip()]
    else:
        seeds = _tool_seeds()
    if args.limit:
        seeds = seeds[:args.limit]
    cmd_hints = {}
    if getattr(args, "commands", False):
        cmd_hints = command_seed_hints(args.commands_file or None)
        extra = [g for g in cmd_hints if g not in seeds]
        seeds = extra + seeds
        print(f"[teacher] commands: +{len(extra)} realnych komend/haseł z listy must-have.")
    if args.expand:
        extra = expand_seeds(seeds, teacher, args.expand, pace=args.pace)
        seeds = seeds + extra
        print(f"[teacher] expand: +{len(extra)} parafraz (razem {len(seeds)} celów).")
    if args.skip_known:
        known = {r["goal"] for r in mem.con.execute(
            "SELECT goal FROM trajectories WHERE source='cloud_teacher'")}
        before = len(seeds)
        seeds = [g for g in seeds if g not in known]
        print(f"[teacher] skip-known: pominięto {before - len(seeds)} zrobionych celów.")
    if not seeds:
        print("[teacher] brak pytań-seedów.", file=sys.stderr)
        return 2

    if args.reset and not args.dry_run:
        mem.con.execute("DELETE FROM trajectories WHERE source='cloud_teacher'")
        mem.con.commit()

    schemas = registry.schemas()
    seed_tools = _seed_tools() if args.guided else {}
    seed_tools.update(cmd_hints)
    ctx = ToolContext(settings=config, memory=Memory(os.path.join(tempfile.mkdtemp(), "t.db")),
                      confirmer=Confirmer(auto=True), registry=registry)
    added = rejected = 0
    out_fh = None if args.dry_run else open(args.out, "a", encoding="utf-8")
    try:
        for goal in seeds:
            if args.pace:
                time.sleep(args.pace)
            try:
                hint = seed_tools.get(goal) if seed_tools else None
                rec = generate_trajectory(goal, teacher, schemas, ctx,
                                          execute=not args.no_execute, hint=hint)
            except Exception as e:
                print(f"[teacher] błąd ({goal[:40]}): {e}", file=sys.stderr)
                continue
            if not rec:
                rejected += 1
                continue
            score = 5
            if not args.no_judge:
                ok, score, note = judge(rec["goal"], rec["steps"], rec["answer"], teacher)
                if not ok or score < args.min_score:
                    rejected += 1
                    print(f"[teacher] odrzucone (score={score}): {goal[:55]} {note}")
                    continue
            if args.dry_run:
                print(f"[dry] {goal[:55]} -> {rec['result']} (score={score})")
                added += 1
                continue
            store(mem, rec, score)
            out_fh.write(json.dumps({"messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": rec["goal"]}],
                "steps": rec["steps"], "answer": rec["answer"], "score": score},
                ensure_ascii=False) + "\n")
            added += 1
    finally:
        if out_fh:
            out_fh.close()
    print(f"[teacher] dodane={added} odrzucone={rejected} | kind=agent: "
          f"{mem.trajectory_count('agent')} | out={args.out}")
    print_usage(teacher)
    return 0


if __name__ == "__main__":
    sys.exit(main())
