#!/usr/bin/env python3
"""Wykorzystanie DARMOWYCH remote_ai do wiedzy/polszczyzny (bez opencode) -> `learned`.

Zasady:
  * **Nowość, nie dublowanie**: kandydat-pytanie jest odrzucany, jeśli semantycznie pokrywa się
    z istniejącym `learned` (cosine po embeddingu, próg `--threshold`); unikamy też powtórzeń
    w ramach partii i podajemy modelowi listę „nie powtarzaj".
  * **Do wyczerpania limitów**: pętla generuje nowe pytania (`--invent`), odpowiada i zapisuje,
    dopóki nie osiągniemy `--target` albo kolejne rundy nie przynoszą nic nowego / dostawcy
    zwracają 429/402/quota (`--max-fail`). Na końcu raport: dodane / duble / błędy / wyczerpanie.
  * Nauczyciel (`--teacher`): `free` (Gemini -> Groq -> OpenRouter -> HuggingFace -> DeepSeek ->
    Grok, BEZ opencode), `pc` (Kali/bielik-11b przez tunel, bez limitów) albo `all` (pc + free).

Użycie:
    python3 astro/scripts/remote_knowledge.py --target 200
    python3 astro/scripts/remote_knowledge.py --teacher pc --target 500    # uczy bielik z Kali
    python3 astro/scripts/remote_knowledge.py --include-pc --target 500    # pc + darmowe chmury
    python3 astro/scripts/remote_knowledge.py --dry-run --invent 10 --limit 3
"""

import argparse
import os
import random
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from astro import config, remote_support  # noqa: E402
from astro.memory import default_memory  # noqa: E402

SYSTEM = ("Jesteś nauczycielem wiedzy dla lokalnego asystenta ASTRO. Odpowiadaj PO POLSKU, "
          "zwięźle i rzeczowo (2-4 zdania), jak fakt do zapamiętania. Bez markdownu, bez emoji, "
          "bez odwołań do siebie i bez komend systemowych.")

_Q_STARTS = ("co to", "czym", "jak", "dlaczego", "ile", "kto", "gdzie", "kiedy", "czy ",
             "wyjaśnij", "opowiedz", "wymień", "podaj", "jakie", "jaki", "jaka")
_RATE_MARKERS = ("429", "402", "quota", "rate limit", "rate-limit", "credits", "insufficient",
                 "exceeded", "too many", "billing")

# Rotacja dziedzin: bez tego model wymyśla w kółko te same pytania (wysoki `dup`).
# DZIEDZINY PRIORYTETOWE (decyzja użytkownika 2026-09-28): ~80% rund; ogólne ~20%.
_PRIORITY_TOPICS = (
    "polityka bieżąca w Polsce i na świecie (prezydent, premier, Sejm, Senat, marszałek, partie "
    "polityczne, aktualne poparcie w sondażach, nastroje społeczne, bieżące wydarzenia)",
    "finanse osobiste i bankowość (aktywa, pasywa, inwestycje, banki, rachunki, kredyty, długi, "
    "budżet domowy, podatki, oszczędzanie, emerytury)",
    "sztuczna inteligencja (jak działa, co potrafi, aktualne modele i ich możliwości, przyszłość, "
    "perspektywy, agenci AI, SDK, uczenie maszynowe, LLM)",
    "samoocena i możliwości ASTRO (co potrafi, jaki sprzęt, rozbudowa Raspberry Pi 5, HAT-y, "
    "parametry techniczne, porty i gniazda, kamera, rozpoznawanie twarzy, Hailo, NPU)",
    "informatyka, terminal oraz Linux i Windows (do czego służą ważne komendy, podstawy Linux, "
    "podstawy Windows, aktualne komercyjne podzespoły komputerowe, sieci, bezpieczeństwo)",
    "Docker i kontenery (jak działa, do czego służy, zarządzanie, budowanie obrazów, sterowanie "
    "kontenerami, docker-compose, wolumeny, sieci)",
)
_GENERAL_TOPICS = (
    "nauka i przyroda (biologia, chemia, fizyka)",
    "historia Polski i świata (daty, postacie, wydarzenia)",
    "geografia (państwa, stolice, rzeki, góry, klimat)",
    "technologia i komputery (sprzęt, sieci, programowanie)",
    "zdrowie i medycyna (profilaktyka, choroby, leki)",
    "kultura i sztuka (literatura, muzyka, malarstwo, film)",
    "psychologia i relacje społeczne",
    "ekonomia i finanse (podatki, oszczędzanie, giełda)",
    "kuchnia i codzienność (produkty, przepisy, sprzątanie)",
    "motoryzacja i transport",
    "sport i rekreacja",
    "prawo i administracja w Polsce",
    "język polski (gramatyka, ortografia, etymologia)",
    "matematyka (pojęcia, twierdzenia, zadania)",
    "astronomia i kosmos",
    "ekologia i ochrona środowiska",
    "bezpieczeństwo cyfrowe i prywatność",
    "podróże i ciekawe miejsca",
    "rzemiosło, majsterkowanie i naprawy domowe",
    "zwierzęta domowe i hodowla",
    "geologia, minerały i skały",
    "botanika, drzewa i ogrodnictwo",
    "mikrobiologia, wirusy i bakterie",
    "fizyka zjawisk codziennych",
    "elektronika, prąd i obwody",
    "architektura i budownictwo",
    "mitologia i religie świata",
    "wojskowość, broń i historia militarna",
    "lotnictwo, statki i żegluga",
    "rolnictwo, wieś i uprawy",
    "kryptografia, szyfry i zagadki logiczne",
    "pierwsza pomoc i medycyna ratunkowa",
    "ptaki, owady i grzyby",
    "marketing, handel i organizacja pracy",
    "DevOps, CI/CD i automatyzacja wdrożeń",
    "chmura, serwery i usługi SaaS",
    "bazy danych SQL i NoSQL oraz ich wydajność",
    "programowanie (Python, JavaScript, C)",
    "hardware PC, podzespoły i składanie komputerów",
    "sieci bezprzewodowe i standardy Wi-Fi",
    "kryptowaluty, blockchain i fintech",
    "energetyka, OZE i magazynowanie energii",
    "praca zdalna, produktywność i narzędzia",
    "prawo IT, RODO i umowy",
    "gry, gamifikacja i projektowanie rozgrywki",
    "kosmos, eksploracja i technologie satelitarne",
)
_TOPICS = _PRIORITY_TOPICS + _GENERAL_TOPICS
_N_PRIORITY = len(_PRIORITY_TOPICS)
# Waga: na każde 5 kolejnych rund maks. 1 ogólna (≈80% priorytet / 20% ogólne).
_PRIORITY_PER_BLOCK = 4

# Rotacja dziedzin (PERSYSTENTNA między uruchomieniami pętli nauki) — reguła 2026-09-27:
# nowy bieg nie może zaczynać od dziedzin użytych w poprzednim biegu (wysoki `dup`). Kolejność
# dziedzin w biegu jest LOSOWA (bez powtórzeń w obrębie permutacji), a pierwsza dziedzina jest
# różna od ostatnio użytej. Stan: `runtime/knowledge_topic.cursor` (indeks ostatniej dziedziny).
_CURSOR = config.REPO / "runtime" / "knowledge_topic.cursor"


def _load_last_topic():
    try:
        return int(_CURSOR.read_text(encoding="utf-8").strip()) % len(_TOPICS)
    except Exception:
        return -1


def _save_last_topic(idx):
    try:
        _CURSOR.write_text(str(int(idx) % len(_TOPICS)), encoding="utf-8")
    except Exception:
        pass


def _excluded_topics():
    """Dziedziny chwilowo wykluczone (np. wyeksploatowane). Env: ASTRO_EXCLUDE_TOPICS
    (lista fragmentów nazw rozdzielona przecinkami, bez rozróżniania wielkości liter)."""
    raw = os.environ.get("ASTRO_EXCLUDE_TOPICS", "")
    return [s.strip().lower() for s in raw.split(",") if s.strip()]


def _is_excluded(topic):
    low = (topic or "").lower()
    return any(x in low for x in _excluded_topics())


def _topic_sequence():
    """Kolejność dziedzin na bieg: ~80% priorytetowych / ~20% ogólnych (bloki 4+1).

    Priorytet: bloki 5 rund = 4 dziedziny priorytetowe + 1 ogólna (maks. 20% ogólnych w każdym
    oknie). W obrębie bloku kolejność losowa; pierwsza dziedzina != ostatnio użytej (rotacja).
    Dziedziny z `ASTRO_EXCLUDE_TOPICS` są pomijane (profil „mniej duplikatów")."""
    priority = [i for i in range(_N_PRIORITY) if not _is_excluded(_TOPICS[i])]
    general = [i for i in range(_N_PRIORITY, len(_TOPICS)) if not _is_excluded(_TOPICS[i])]
    if not priority:
        priority = list(range(_N_PRIORITY))
    if not general:
        general = list(range(_N_PRIORITY, len(_TOPICS)))
    rnd = random.Random()
    p_order = rnd.sample(priority, len(priority)) or [0]
    g_order = rnd.sample(general, len(general)) or [0]
    seq, pi, gi = [], 0, 0
    while len(seq) < 240:
        # 4 RÓŻNE dziedziny priorytetowe (przesunięcie o k), nie 4× ta sama (błąd naprawiony).
        block = [p_order[(pi + k) % len(p_order)] for k in range(_PRIORITY_PER_BLOCK)]
        pi += _PRIORITY_PER_BLOCK
        block.append(g_order[gi % len(g_order)])
        gi += 1
        rnd.shuffle(block)
        seq.extend(block)
    last = _load_last_topic()
    if seq and seq[0] == last and len(seq) > 1:
        for i in range(1, len(seq)):
            if seq[i] != last:
                seq[0], seq[i] = seq[i], seq[0]
                break
    return seq


def free_chain():
    """Darmowi dostawcy wg kolejności (BEZ opencode/płatnych)."""
    return [p for p in remote_support.provider_chain(include_pc=False) if p.label != "opencode"]


def teacher_chain(kind="free"):
    """Łańcuch nauczyciela: `free` (darmowe chmury), `pc` (Kali/bielik przez tunel), `all`."""
    if kind == "free":
        return free_chain()
    pc = [p for p in remote_support.provider_chain(include_pc=True) if p.label == "pc"]
    if kind == "pc":
        return pc
    return pc + free_chain()          # all: najpierw lokalny Kali (bez limitów), potem chmury


def generator_chain(kind="quality", path=None):
    """Łańcuch do GENEROWANIA (inwencji) świeżych pytań — jakość > koszt (rotacja duplikatów).

    Bielik bywa powtarzalny, więc inwencję robimy mocniejszymi modelami z `remote_ai`:
      * `quality` (domyślnie) = darmowe chmury (`remote_ai`) + OpenCode Go;
      * `free` = tylko darmowe chmury; `opencode` = tylko OpenCode; `pc` = tylko Kali/bielik;
      * `same` = łańcuch nauczyciela (zachowanie historyczne).
    """
    if kind == "same":
        return None
    if kind == "pc":
        return teacher_chain("pc")
    if kind == "opencode":
        return remote_support.opencode_chain(path)
    if kind == "free":
        return free_chain()
    return free_chain() + remote_support.opencode_chain(path)   # quality


def is_question(line):
    low = (line or "").strip().lower()
    return low.endswith("?") or low.startswith(_Q_STARTS)


def _clean_question(line):
    q = re.sub(r"^\s*[-•*\d]+\s*[.)\-]?\s*", "", (line or "").strip()).strip()
    return q


def _is_novel(mem, question, threshold):
    """True, gdy pytanie NIE pokrywa się semantycznie z istniejącym `learned`."""
    if not mem.embedder:
        return True
    try:
        hits = mem.search_learned_semantic(question, k=1, min_score=threshold)
    except Exception:
        hits = []
    return not hits


def _classify(errors):
    rate = sum(1 for e in errors if any(m in e.lower() for m in _RATE_MARKERS))
    return rate, len(errors)


def _parse_questions(text):
    """Wyodrębnia pytania z odpowiedzi modelu (jedno w linii, bez numeracji)."""
    out = []
    for ln in (text or "").splitlines():
        q = _clean_question(ln)
        if q and is_question(q) and q not in out:
            out.append(q)
    return out


def _invent_questions(chain, n, avoid, timeout, topic=None):
    domain = topic or ("różnorodnych dziedzin (nauka, historia, geografia, technologia, zdrowie, "
                       "kultura, codzienność, psychologia, ekonomia)")
    prompt = (f"Wygeneruj {n} RÓŻNORODNYCH pytań wiedzy po polsku z zakresu: {domain}. "
              "Preferuj KONKRETNE, niszowe fakty (nazwy, daty, liczby, mechanizmy), a nie pytania "
              "ogólne typu „co to jest...”. Jedno pytanie w linii, bez numeracji i komentarzy.")
    if avoid:
        prompt += ("\nNIE powtarzaj pytań podobnych do tych (mocny zakaz — szukaj NOWYCH kątów, "
                   "innych faktów, liczb i mechanizmów): " + "; ".join(avoid[-60:]))
    messages = [{"role": "system", "content": "Tworzysz pytania do bazy wiedzy asystenta."},
                {"role": "user", "content": prompt}]
    # JAKOŚĆ > KOSZT (rotacja duplikatów): sprawdzaj dostawców po kolei i przyjmij odpowiedź
    # dopiero gdy da sensowną partię pytań. Dzięki temu jeden „skąpy" darmowy dostawca (np. 1
    # pytanie) nie blokuje — schodzimy do kolejnego (remote_ai), a w końcu do OpenCode.
    min_ok = max(3, (n + 1) // 3)
    best = []
    for provider in chain:
        res = remote_support.ask(messages, max_tokens=max(500, n * 25),
                                 chain=[provider], timeout=timeout)
        if not res:
            continue
        out = _parse_questions(res[0])
        if len(out) > len(best):
            best = out
        if len(best) >= min_ok:
            break
    return best


# Pytania o stan BIEŻĄCY (polityka, poparcie, aktualne modele, kursy...) — bez web-groundingu
# bielik odpowiadałby z nieaktualnej wiedzy. `--web` dokłada świeże wyniki wyszukiwania jako źródło.
_CURRENT_RE = re.compile(
    r"\b(?:20(?:2[4-9]|3\d))\b|\b(?:aktualn\w*|obecn\w*|biez\w*|dzis\w*|teraz|najnowsz\w*|"
    r"poparci\w*|sondaz\w*|prezydent\w*|premier\w*|marsza[lł]k\w*|sejm|senat|parti\w*|"
    r"rzad\w*|wybor\w*|notowan\w*|kurs\w*|inflacj\w*|oprocentowan\w*)\b", re.I)


def _needs_web(q):
    return bool(_CURRENT_RE.search(q or ""))


def _web_context(q, limit=5):
    """Świeże wyniki wyszukiwania jako tekst źródłowy ("" gdy brak)."""
    try:
        from astro.tools.web import web_search_text
        txt = web_search_text(q, limit=limit)
    except Exception:
        return ""
    if not txt or txt.startswith(("brak", "Nie mam", "Nie udało")):
        return ""
    return txt


def main():
    ap = argparse.ArgumentParser(description="Remote-ai -> wiedza/polszczyzna w `learned` (bez opencode)")
    ap.add_argument("--file", default=str(config.REPO / "runtime" / "chat_bank.txt"),
                    help="dodatkowe pytania z pliku (opcjonalnie)")
    ap.add_argument("--invent", type=int, default=60, help="ile pytań prosić remote na rundę")
    ap.add_argument("--target", type=int, default=200, help="ile odpowiedzi dodać w tym uruchomieniu")
    ap.add_argument("--limit", type=int, default=0, help="(alias) ograniczenie łącznej liczby pytań-wejść")
    ap.add_argument("--threshold", type=float, default=0.90, help="próg podobieństwa (dublowanie)")
    ap.add_argument("--pace", type=float, default=0.8)
    ap.add_argument("--min-chars", type=int, default=40)
    ap.add_argument("--max-fail", type=int, default=15, help="kolejnych niepowodzeń = limity wyczerpane")
    ap.add_argument("--max-rounds", type=int, default=80)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--all", action="store_true", help="nie filtruj pliku do pytań wiedzy")
    ap.add_argument("--teacher", choices=("free", "pc", "all"), default="free",
                    help="kto uczy: free (darmowe chmury), pc (Kali/bielik), all (pc + free)")
    ap.add_argument("--include-pc", action="store_true", help="alias dla --teacher all")
    ap.add_argument("--unknowns", type=int, default=0,
                    help="doucz N najczęstszych pytań z tabeli `unknowns` (pętla samodoskonalenia)")
    ap.add_argument("--web", action="store_true",
                    help="dla pytań o stan BIEŻĄCY (polityka/poparcie/aktualne) dołóż świeże "
                         "wyniki wyszukiwania jako źródło (web-grounding)")
    ap.add_argument("--gen-chain", choices=("quality", "free", "opencode", "pc", "same"),
                    default="quality",
                    help="kto GENERUJE świeże pytania (rotacja duplikatów): quality=darmowe+OpenCode")
    ap.add_argument("--rotate-rounds", type=int, default=4,
                    help="ile prób rotacji duplikatów -> świeże pytania na jedną rundę inwencji")
    args = ap.parse_args()

    chain = teacher_chain("all" if args.include_pc else args.teacher)
    if not chain:
        print("[remote-know] brak nauczyciela (klucze? tunel PC?)", file=sys.stderr)
        return 2
    print("[remote-know] dostawcy: " + " -> ".join(p.name() for p in chain))
    gen_chain = generator_chain(args.gen_chain)
    if gen_chain is None:
        gen_chain = chain
    gen_labels = " -> ".join(dict.fromkeys(p.name() for p in gen_chain)) or "?"
    print(f"[remote-know] generator pytań ({args.gen_chain}): {gen_labels}")
    target = args.limit or args.target

    mem = default_memory()  # z embedderem (nowość semantyczna + wektory przy zapisie)
    known = {r["title"] for r in mem.con.execute("SELECT title FROM learned")}
    unknown_qs = [t for t, _h in mem.top_unknowns(args.unknowns)] if args.unknowns > 0 else []
    unknown_set = set(unknown_qs)
    if unknown_qs:
        print(f"[remote-know] unknowns: {len(unknown_qs)} pytań z kolejki samodoskonalenia")
    file_qs = []
    if os.path.isfile(args.file):
        with open(args.file, encoding="utf-8") as fh:
            file_qs = [ln.strip() for ln in fh if ln.strip()]
        if not args.all:
            file_qs = [q for q in file_qs if is_question(q)]

    added = dup = failed = rate_fail = 0
    consec_fail = 0
    labels = {}
    avoid = list(known)[-200:]
    rejected = []            # duplikaty odrzucone w tej sesji -> lista „nie powtarzaj" dla generatora
    round_no = 0
    topic_seq = _topic_sequence()   # losowa kolejność dziedzin na ten bieg (pierwsza != ostatnia)

    queue = []

    def _remember_reject(q):
        """Zapamiętaj odrzucony duplikat, by generator rotował na coś innego (twardy sygnał)."""
        if q and q not in rejected:
            rejected.append(q)

    def _invent_fill(desired=None):
        """ROTACJA DUPLIKATÓW -> ŚWIEŻE PYTANIA: powtarza inwencję (nowa dziedzina + lista
        „nie powtarzaj" zbudowana z odrzuconych duplikatów) aż zbierze `desired` świeżych pytań
        albo wyczerpie `--rotate-rounds` prób. Dzięki temu `dup` nie kończy rundy bez zamiennika."""
        nonlocal round_no, dup
        desired = args.invent if desired is None else desired
        fresh_total = 0
        attempts = 0
        while fresh_total < desired and attempts < args.rotate_rounds:
            attempts += 1
            round_no += 1
            topic_idx = topic_seq[(round_no - 1) % len(topic_seq)]
            topic = _TOPICS[topic_idx]
            _save_last_topic(topic_idx)
            want = args.invent    # jedna partia na próbę; rotacja powtarza aż zbierze `desired`
            cands = _invent_questions(gen_chain, want, avoid + rejected, timeout=90, topic=topic)
            round_fresh = 0
            for q in cands:
                if q in known or q in queue or q in rejected:
                    dup += 1
                    _remember_reject(q)
                    continue
                if _is_novel(mem, q, args.threshold):
                    queue.append(q)
                    fresh_total += 1
                    round_fresh += 1
                else:
                    dup += 1
                    _remember_reject(q)
            print(f"[remote-know] runda {round_no} [{topic.split(' (')[0]}]: pytań={len(cands)} "
                  f"świeżych={round_fresh} (dup={dup}, próba {attempts}/{args.rotate_rounds})",
                  flush=True)
            if not cands:
                break
        return fresh_total

    # 1) unknowns — realne braki z runtime (zawsze pierwsze)
    for q in unknown_qs:
        if q not in known and q not in queue:
            queue.append(q)
    # 2) plik: DEDUP SEMANTYCZNY **przed** treningiem — duplikaty odrzucamy, zamiast marnować
    #    wywołania nauczyciela na pytania już pokryte w `learned`.
    before = dup
    file_kept = 0
    for q in file_qs:
        if q in known or q in queue:
            dup += 1
            continue
        if _is_novel(mem, q, args.threshold):
            queue.append(q)
            file_kept += 1
        else:
            dup += 1
            _remember_reject(q)   # duplikat z pliku -> generator dostanie go na listę „nie powtarzaj"
    print(f"[remote-know] plik: {len(file_qs)} kandydatów -> {file_kept} świeżych "
          f"(odrzucone dup/istniejące={dup - before})", flush=True)
    # 3) ROTACJA: uzupełnij odrzucone świeżymi pytaniami (invent), zanim zaczniemy trening.
    baseline = len(unknown_qs) + len(file_qs)
    empty = 0
    while len(queue) < baseline and round_no < args.max_rounds and empty < 3:
        if _invent_fill(baseline - len(queue)) == 0:
            empty += 1
        else:
            empty = 0

    while (added < target) and queue and consec_fail < args.max_fail:
        q = queue.pop(0)
        if q in known:
            dup += 1
            continue
        if args.pace:
            time.sleep(args.pace)
        user_content = q
        if args.web and _needs_web(q):
            ctx_web = _web_context(q)
            if ctx_web:
                user_content = (
                    f"Pytanie: {q}\n\nŚwieże wyniki z internetu (użyj ich jako źródła faktów, "
                    f"nie wymyślaj):\n{ctx_web}\n\nOdpowiedz zwięźle po polsku, wyłącznie na "
                    f"podstawie powyższych faktów. Jeśli brak danych, napisz: brak danych.")
        errors = []
        res = remote_support.ask([{"role": "system", "content": SYSTEM},
                                  {"role": "user", "content": user_content}],
                                 max_tokens=400, chain=chain, timeout=60, errors_out=errors)
        rate, total = _classify(errors)
        rate_fail += rate
        if not res:
            failed += 1
            consec_fail += 1
            if consec_fail >= args.max_fail:
                print(f"[remote-know] {consec_fail} niepowodzeń z rzędu (rate={rate_fail}) "
                      f"— LIMITY WYCZERPANE", flush=True)
                break
            continue
        ans, label, _usage = res
        labels[label] = labels.get(label, 0) + 1
        if len(ans) < args.min_chars:
            failed += 1
            continue
        if args.dry_run:
            print(f"[dry] {q[:55]} -> {label}: {ans[:80]}")
        else:
            remote_support.learn_from_remote(mem, q, ans, source=f"remote_knowledge:{label}")
            known.add(q)
            avoid.append(q)
            if q in unknown_set:
                mem.delete_unknown(q)  # odpowiedź zapamiętana — zdejmij z kolejki braków
        added += 1
        consec_fail = 0
        # Dobierz świeże pytania, gdy kolejka się kończy, a target nieosiągnięty (nic się nie marnuje).
        if not queue and added < target:
            if _invent_fill(args.invent) == 0:
                empty += 1
                if empty >= 3:
                    break
            else:
                empty = 0

    print(f"[remote-know] KONIEC dodane={added} duble={dup} nieudane={failed} "
          f"(rate_limit={rate_fail}) rund={round_no}")
    print(f"[remote-know] dostawcy: {labels}")
    if consec_fail >= args.max_fail:
        print("[remote-know] STATUS: darmowe limity prawdopodobnie WYCZERPANE")
    else:
        print("[remote-know] STATUS: zakończono (osiągnięto target/plik wyczerpany)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
