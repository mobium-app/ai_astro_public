#!/usr/bin/env python3
"""E6 — generator zweryfikowanych trajektorii tool-calling dla ASTRO.

Buduje „złote" epizody: pytanie użytkownika -> wywołanie narzędzia z poprawnymi
argumentami -> wynik (realny dla narzędzi tylko-do-odczytu, inaczej kontrolowany)
-> finalna odpowiedź. Zapisuje je do `trajectories` w `memory.db` (kind=`agent`,
source=`toolcall_gen`), skąd `build_dataset.py` buduje zbiór treningowy na PC.

Dlaczego tak: poprzednie iteracje LoRA w Atenie uczyły się z samych planów i czatu
(tekst), bez par tool_call -> wynik, i dlatego degradowały tool-calling. Tu dane
zawierają dokładnie to, czego brakowało.

Użycie:
    python3 astro/scripts/toolcall_gen.py            # dopisz do memory.db
    python3 astro/scripts/toolcall_gen.py --dry-run  # pokaż, nie zapisuj
    python3 astro/scripts/toolcall_gen.py --list     # lista scenariuszy
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

from astro import config  # noqa: E402
from astro.memory import Memory  # noqa: E402
from astro.safety import Confirmer  # noqa: E402
from astro.tools import ToolContext, registry  # noqa: E402

CANNED = {
    "remember": "Zapisałam to w pamięci.",
    "write_file": "Zapisano 4 znaków do /home/user/astro-agent/notatka.txt",
    "append_file": "Dopisano do /home/user/astro-agent/notatka.txt",
    "run_command": "Filesystem      Size  Used Avail Use%\n/dev/root       470G   41G  406G   9%",
    "run_script": "(kod 0) Witaj z ASTRO",
    "check_script": "OK: brak błędów składni (py_compile/shellcheck)",
    "web_search": "Wyniki: Pan Tadeusz - autor Adam Mickiewicz (1798-1855).",
    "web_fetch": "Debian - Wikipedia: system operacyjny oparty na jądrze Linux.",
    "nearby_places": "Najbliższy paczkomat: InPost POZ03B (140 m), Szwajcarska 1, Poznań.",
    "system_task": "Plan: 1. instalacja nginx 2. włączenie usługi. Wymaga potwierdzenia.",
    "ask_user": "Pytanie zadane użytkownikowi.",
    "home_status": "light.salon: on",
    "home_command": "light.salon: turn_on",
    "camera_look": "Brak kamery (/dev/video*) - wizja nieaktywna.",
    "camera_move": "Obracam kamerę: left (x=-0.6, y=0.0).",
    "camera_home": "Ustawiam kamerę na wprost.",
    "camera_scene": "Widzę jedną osobę. Oświetlenie: umiarkowane światło.",
    "camera_people": "Widzę: Konrad.",
    "camera_ocr": "Odczytany tekst: Przeczytaj ten tekst Astro widzi 123",
    "person_enroll": "Zapamiętałem twarz: Anna.",
    "person_forget": "Usunięto 1 wpis(y) dla: Anna.",
    "person_list": "Znam 2: Anna, Konrad.",
    "person_sightings": "Widziany dziś: Kasia (2x, ostatnio 18:20); Michał (1x, ostatnio 18:05).",
    "vision_forget_unknowns": "Usunięto 5 zobaczeń nieznanych; wyczyszczono stare: 0.",
    "vision_events": "Ostatnie zdarzenia z kamery: 18:20: Ktoś wszedł do pokoju. | 18:05: Widzę ruch w kadrze.",
    "ocr_recent": "Ostatnie odczyty z kamery: o 17:40: KUP MLEKO.",
    "vision_status": "Wizja: kamera=on, twarze=on, rozpoznawanie=on, wiek/plec=on, znane osoby=1.",
    "system_power": "shutdown: wykonano (kod 0)",
    "make_dir": "utworzono katalog: /home/user/astro-agent/projekty",
    "wifi_scan": "Dostępne sieci Wi-Fi:\nDomWiFi:84:WPA2\nSasiad:51:WPA2\nGość:30:--",
    "wifi_connect": "Wi-Fi DomWiFi: podłączono",
    "wifi_disconnect": "rozłączono z siecią DomWiFi",
    "network_scan": "Skan sieci 192.168.0.0/24:\nHost: 192.168.0.1 (router)\nHost: 192.168.0.2",
    "update_system": "Aktualizacja zakończona: 0 zmienionych, 0 do aktualizacji.",
}

# (pytanie, narzędzie, argumenty, realne_wykonanie, szablon_odpowiedzi)
SCENARIOS = [
    {"q": "Jaka jest teraz temperatura procesora i ile jest wolnej pamięci?",
     "tool": "system_info", "args": {}, "real": True,
     "answer": "Sprawdziłam system: {result}"},
    {"q": "Przeczytaj plik /etc/hostname",
     "tool": "read_file", "args": {"path": "/etc/hostname"}, "real": True,
     "answer": "Zawartość /etc/hostname to: {result}"},
    {"q": "Wylistuj zawartość katalogu /etc",
     "tool": "list_dir", "args": {"path": "/etc"}, "real": True,
     "answer": "W /etc znajdują się między innymi: {result}"},
    {"q": "Znajdź w projekcie ASTRO pliki zawierające wzorzec ToolContext",
     "tool": "search_files", "args": {"pattern": "ToolContext", "path": "astro/tools"}, "real": True,
     "answer": "Znalazłam następujące dopasowania: {result}"},
    {"q": "Sprawdź stan NPU / Hailo",
     "tool": "npu_status", "args": {}, "real": True,
     "answer": "Stan akceleratora: {result}"},
    {"q": "Ile dokumentów jest w bazie wiedzy?",
     "tool": "knowledge_stats", "args": {}, "real": True,
     "answer": "Statystyki wiedzy: {result}"},
    {"q": "Co w bazie wiedzy wiadomo o systemd?",
     "tool": "search_knowledge", "args": {"query": "systemd"}, "real": True,
     "answer": "Z bazy wiedzy: {result}"},
    {"q": "Pokaż stronę man polecenia rsync",
     "tool": "man_page", "args": {"name": "rsync"}, "real": True,
     "answer": "Strona man rsync: {result}"},
    {"q": "Pokaż pomoc polecenia rsync (--help)",
     "tool": "cmd_help", "args": {"command": "rsync"}, "real": True,
     "answer": "Pomoc rsync: {result}"},
    {"q": "Zapamiętaj, że lubię zieloną herbatę",
     "tool": "remember", "args": {"text": "użytkownik lubi zieloną herbatę"}, "real": False,
     "answer": "Zapamiętałam, że lubisz zieloną herbatę."},
    {"q": "Zapisz w katalogu roboczym plik notatka.txt z treścią test",
     "tool": "write_file", "args": {"path": "notatka.txt", "content": "test"}, "real": False,
     "answer": "Zapisałam notatkę: {result}"},
    {"q": "Dopisz do pliku notatka.txt treść koniec",
     "tool": "append_file", "args": {"path": "notatka.txt", "content": "koniec"}, "real": False,
     "answer": "Dopisałam do notatki: {result}"},
    {"q": "Wykonaj polecenie df -h",
     "tool": "run_command", "args": {"command": "df -h"}, "real": False,
     "answer": "Wynik polecenia df -h: {result}"},
    {"q": "Wyszukaj w internecie, kto napisał Pana Tadeusza",
     "tool": "web_search", "args": {"query": "kto napisał Pana Tadeusza"}, "real": False,
     "answer": "Znalazłam w sieci: {result}"},
    {"q": "Pobierz treść strony https://pl.wikipedia.org/wiki/Debian",
     "tool": "web_fetch", "args": {"url": "https://pl.wikipedia.org/wiki/Debian"}, "real": False,
     "answer": "Pobrałam stronę: {result}"},
    {"q": "Jaki jest najbliższy paczkomat w pobliżu Poznań, ul. Byka 1?",
     "tool": "nearby_places", "args": {"kind": "paczkomat", "location": "Poznań, ul. Byka 1"},
     "real": False, "answer": "Najbliżej jest: {result}"},
    {"q": "Uruchom skrypt hello.sh z katalogu roboczego",
     "tool": "run_script", "args": {"path": "hello.sh"}, "real": False,
     "answer": "Uruchomiłam skrypt: {result}"},
    {"q": "Sprawdź poprawność skryptu hello.sh",
     "tool": "check_script", "args": {"path": "hello.sh"}, "real": False,
     "answer": "Wynik sprawdzenia: {result}"},
    {"q": "Zainstaluj i skonfiguruj serwer nginx",
     "tool": "system_task", "args": {"goal": "instalacja i konfiguracja serwera nginx"},
     "real": False, "answer": "Przygotowałam plan (wymaga Twojego potwierdzenia): {result}"},
    {"q": "Zapisz to w pliku",
     "tool": "ask_user", "args": {"question": "Jaką nazwę pliku i treść mam zapisać?"},
     "real": False, "answer": "{result} Poproszę o nazwę pliku i treść."},
    # --- skille (deterministyczne receptury wystawione jako narzędzia) ---
    {"q": "Jakie masz przepisy i skille?",
     "tool": "list_skills", "args": {}, "real": True,
     "answer": "Dostępne przepisy:\n{result}"},
    {"q": "Pokaż stan repozytorium git",
     "tool": "run_skill", "args": {"name": "git_status"}, "real": True,
     "answer": "Status repozytorium:\n{result}"},
    {"q": "Ile miejsca zajmuje katalog ~/astro/docs",
     "tool": "run_skill", "args": {"name": "dir_size", "params": {"path": "~/astro/docs"}},
     "real": True, "answer": "Rozmiar katalogu: {result}"},
    {"q": "Pokaż zamontowane dyski",
     "tool": "run_skill", "args": {"name": "mount_list"}, "real": True,
     "answer": "Zamontowane systemy plików:\n{result}"},
    {"q": "Pokaż pakiety w środowisku wirtualnym projektu",
     "tool": "run_skill", "args": {"name": "venv_packages"}, "real": True,
     "answer": "Pakiety w środowisku wirtualnym:\n{result}"},
    {"q": "Które procesy zużywają najwięcej pamięci RAM?",
     "tool": "run_skill", "args": {"name": "top_memory"}, "real": True,
     "answer": "Procesy z największym zużyciem RAM:\n{result}"},
    {"q": "Jakie porty są otwarte na tym komputerze?",
     "tool": "run_skill", "args": {"name": "listening_ports"}, "real": True,
     "answer": "Nasłuchujące porty:\n{result}"},
    {"q": "Pokaż ostatnie logi usługi astro",
     "tool": "run_skill", "args": {"name": "journal", "params": {"unit": "astro", "n": "10"}},
     "real": True, "answer": "Logi usługi astro:\n{result}"},
    {"q": "Jaki jest stan światła w salonie?",
     "tool": "home_status", "args": {"entity": "salon"}, "real": False,
     "answer": "Stan urządzenia: {result}"},
    {"q": "Włącz światło w salonie",
     "tool": "home_command", "args": {"entity": "salon", "action": "on"}, "real": False,
     "answer": "Wykonano sterowanie: {result}"},
    {"q": "Co widzisz w kamerze?",
     "tool": "camera_look", "args": {"question": "co widać?"}, "real": False,
     "answer": "Obraz z kamery: {result}"},
    {"q": "Obróć kamerę w lewo",
     "tool": "camera_move", "args": {"direction": "left"}, "real": False,
     "answer": "Obracam kamerę: {result}"},
    {"q": "Ustaw kamerę na wprost",
     "tool": "camera_home", "args": {}, "real": False,
     "answer": "Ustawiam kamerę: {result}"},
    {"q": "Oceń otoczenie",
     "tool": "camera_scene", "args": {}, "real": False,
     "answer": "Ocena otoczenia: {result}"},
    {"q": "Kto jest w pokoju?",
     "tool": "camera_people", "args": {}, "real": False,
     "answer": "Osoby w kadrze: {result}"},
    {"q": "Przeczytaj, co jest napisane na kartce",
     "tool": "camera_ocr", "args": {}, "real": False,
     "answer": "Czytam tekst: {result}"},
    {"q": "Zapamiętaj mnie jako Anna",
     "tool": "person_enroll", "args": {"name": "Anna"}, "real": False,
     "answer": "Zapamiętane: {result}"},
    {"q": "Zapomnij Annę",
     "tool": "person_forget", "args": {"name": "Anna"}, "real": False,
     "answer": "Usuwam: {result}"},
    {"q": "Kogo znasz?",
     "tool": "person_list", "args": {}, "real": False,
     "answer": "Znam osoby: {result}"},
    {"q": "Kto był dzisiaj?",
     "tool": "person_sightings", "args": {"period": "today"}, "real": False,
     "answer": "Zobaczenia: {result}"},
    {"q": "Wyczyść zobaczenia",
     "tool": "vision_forget_unknowns", "args": {}, "real": False,
     "answer": "Czyszczę historię: {result}"},
    {"q": "Co się działo przed kamerą?",
     "tool": "vision_events", "args": {}, "real": False,
     "answer": "Zdarzenia z kamery: {result}"},
    {"q": "Co było napisane na kartce?",
     "tool": "ocr_recent", "args": {}, "real": False,
     "answer": "Odczyty z kamery: {result}"},
    {"q": "Status wizji",
     "tool": "vision_status", "args": {}, "real": False,
     "answer": "Wizja: {result}"},
    # --- Priorytet: obsługa ASTRO bez ekranu (tylko głos) ---
    {"q": "Wyłącz system",
     "tool": "system_power", "args": {"action": "shutdown"}, "real": False,
     "answer": "Wymaga potwierdzenia. {result}"},
    {"q": "Zrestartuj system",
     "tool": "system_power", "args": {"action": "reboot"}, "real": False,
     "answer": "Wymaga potwierdzenia. {result}"},
    {"q": "Wyszukaj dostępne sieci Wi-Fi",
     "tool": "wifi_scan", "args": {}, "real": False,
     "answer": "Znalezione sieci:\n{result}"},
    {"q": "Połącz z siecią DomWiFi, hasło: małe a, duże B, slash, hashtag, małpa, wykrzyknik",
     "tool": "wifi_connect", "args": {"ssid": "DomWiFi", "password": "aB/#@!"}, "real": False,
     "answer": "Łączę z Wi-Fi: {result}"},
    {"q": "Rozłącz z siecią DomWiFi",
     "tool": "wifi_disconnect", "args": {"name": "DomWiFi"}, "real": False,
     "answer": "Rozłączam z Wi-Fi: {result}"},
    {"q": "Zaktualizuj repozytoria",
     "tool": "update_system", "args": {"action": "update"}, "real": False,
     "answer": "Aktualizuję repozytoria: {result}"},
    {"q": "Zaktualizuj programy i aplikacje",
     "tool": "update_system", "args": {"action": "upgrade"}, "real": False,
     "answer": "Aktualizuję pakiety: {result}"},
    {"q": "Znajdź urządzenia w sieci lokalnej",
     "tool": "network_scan", "args": {}, "real": False,
     "answer": "Urządzenia w sieci:\n{result}"},
    {"q": "Utwórz katalog projekty",
     "tool": "make_dir", "args": {"path": "projekty"}, "real": False,
     "answer": "Tworzę katalog: {result}"},
    {"q": "Udostępnij folder w sieci lokalnej",
     "tool": "system_task", "args": {"goal": "udostępnij folder w sieci przez Samba"},
     "real": False, "answer": "Plan udostępnienia: {result}"},
]

# Łańcuchy (dwa różne narzędzia + finalna odpowiedź) — uczą sekwencji, nie pojedynczego callu.
CHAINS = [
    {"q": "Sprawdź temperaturę procesora, a potem wyszukaj w internecie, jaka temperatura jest "
          "bezpieczna dla Raspberry Pi 5.",
     "steps": [
         {"tool": "system_info", "args": {}, "real": True},
         {"tool": "web_search", "args": {"query": "bezpieczna temperatura Raspberry Pi 5"},
          "real": False, "canned": "Raspberry Pi 5: zalecana temperatura pracy < 80°C; "
                                   "powyżej 80°C następuje throttling."}],
     "answer": "Temperatura Pi: {r0}\nW sieci: {r1}"},
    {"q": "Przeczytaj /etc/os-release i wyszukaj w internecie informacje o tej wersji systemu.",
     "steps": [
         {"tool": "read_file", "args": {"path": "/etc/os-release"}, "real": True},
         {"tool": "web_search", "args": {"query": "Debian 13 trixie informacje"},
          "real": False, "canned": "Debian 13 „trixie” to stabilne wydanie z 2025 r. "
                                   "z nowszym jądrem i aktualnymi pakietami."}],
     "answer": "System: {r0}\nW sieci: {r1}"},
    {"q": "Sprawdź stan NPU, a potem wyszukaj w bazie wiedzy co to jest Linux.",
     "steps": [
         {"tool": "npu_status", "args": {}, "real": True},
         {"tool": "search_knowledge", "args": {"query": "Linux system operacyjny"}, "real": True}],
     "answer": "NPU: {r0}\nZ wiedzy: {r1}"},
    {"q": "Pokaż stan repozytorium ASTRO, a potem pakiety w jego środowisku wirtualnym.",
     "steps": [
         {"tool": "run_skill", "args": {"name": "git_status"}, "real": True},
         {"tool": "run_skill", "args": {"name": "venv_packages"}, "real": True}],
     "answer": "Repozytorium: {r0}\nŚrodowisko: {r1}"},
    {"q": "Sprawdź rozmiar katalogu astro i największe pliki w nim.",
     "steps": [
         {"tool": "run_skill", "args": {"name": "dir_size", "params": {"path": "~/astro"}},
          "real": True},
         {"tool": "run_skill", "args": {"name": "find_large", "params": {"path": "~/astro"}},
          "real": True}],
     "answer": "Rozmiar: {r0}\nNajwiększe pliki: {r1}"},
    {"q": "Jakie usługi działają i jakie porty nasłuchują?",
     "steps": [
         {"tool": "run_skill", "args": {"name": "running_services"}, "real": True},
         {"tool": "run_skill", "args": {"name": "listening_ports"}, "real": True}],
     "answer": "Usługi: {r0}\nPorty: {r1}"},
]


def _clean(text, limit=400):
    return " ".join(str(text or "").split())[:limit]


def _run_tool(name, args, ctx):
    res = registry.execute(name, args, ctx)
    return str(getattr(res, "text", res)), bool(getattr(res, "ok", True))


def _store(mem, *, goal, steps, result, answer, source, ok, dry_run, verbose):
    if dry_run:
        if verbose:
            print(f"[dry] {source}: {goal[:60]} -> {answer[:80]}")
        return "added"
    try:
        mem.add_trajectory(kind="agent", goal=goal, steps=steps, result=result,
                           answer=answer, source=source, ok=ok)
        return "added"
    except Exception as e:
        print(f"[gen] błąd {goal[:40]}: {e}", file=sys.stderr)
        return "failed"


def generate(mem, dry_run=False, verbose=True):
    ctx = ToolContext(settings=config, memory=Memory(os.path.join(tempfile.mkdtemp(), "gen.db")),
                      confirmer=Confirmer(auto=True), registry=registry)
    added = failed = skipped = 0
    for sc in SCENARIOS:
        if sc["real"]:
            result, ok = _run_tool(sc["tool"], sc["args"], ctx)
        else:
            result, ok = CANNED.get(sc["tool"], "wynik narzędzia"), True
        if not ok:
            skipped += 1
            if verbose:
                print(f"[gen] pomijam (narzędzie zwróciło błąd): {sc['tool']}")
            continue
        answer = sc["answer"].format(result=_clean(result))
        steps = [{"name": sc["tool"], "args": sc["args"], "ok": ok, "result": result[:800]}]
        status = _store(mem, goal=sc["q"], steps=steps, result=sc["tool"], answer=answer,
                        source="toolcall_gen", ok=ok, dry_run=dry_run, verbose=verbose)
        added += status == "added"
        failed += status == "failed"

    for ch in CHAINS:
        results, steps, all_ok = [], [], True
        for st in ch["steps"]:
            name = st["tool"]
            if st.get("real"):
                result, ok = _run_tool(name, st["args"], ctx)
            else:
                result, ok = st.get("canned") or CANNED.get(name, "wynik narzędzia"), True
            all_ok = all_ok and ok
            results.append(_clean(result))
            steps.append({"name": name, "args": st["args"], "ok": ok, "result": result[:800]})
        if not all_ok:
            skipped += 1
            if verbose:
                print(f"[gen] pomijam łańcuch (krok zwrócił błąd): {ch['q'][:50]}")
            continue
        answer = ch["answer"].format(**{"r%d" % i: r for i, r in enumerate(results)})
        status = _store(mem, goal=ch["q"], steps=steps,
                        result=", ".join(s["name"] for s in steps), answer=answer,
                        source="toolcall_gen_chain", ok=True, dry_run=dry_run, verbose=verbose)
        added += status == "added"
        failed += status == "failed"
    return added, failed, skipped


def main():
    ap = argparse.ArgumentParser(description="Generator trajektorii tool-calling (E6)")
    ap.add_argument("--db", default=str(config.DB_PATH), help="baza docelowa (domyślnie ASTRO memory.db)")
    ap.add_argument("--dry-run", action="store_true", help="nie zapisuj, tylko pokaż")
    ap.add_argument("--list", action="store_true", help="tylko lista scenariuszy")
    ap.add_argument("--reset", action="store_true", help="usuń wcześniejsze wpisy source=toolcall_gen*")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if args.list:
        for sc in SCENARIOS:
            print(f"  {sc['tool']:16s} {sc['q']}")
        for ch in CHAINS:
            print(f"  {'chain':16s} {ch['q']}")
        return 0

    config.ensure_dirs()
    mem = Memory(args.db)
    if args.reset and not args.dry_run:
        mem.con.execute("DELETE FROM trajectories WHERE source LIKE 'toolcall_gen%'")
        mem.con.commit()
    before = mem.trajectory_count()
    added, failed, skipped = generate(mem, dry_run=args.dry_run, verbose=not args.quiet)
    after = mem.trajectory_count()
    print(f"[gen] scenariusze={len(SCENARIOS)}+{len(CHAINS)} dodane={added} błędy={failed} "
          f"pominięte={skipped} trajektorie: {before} -> {after} "
          f"(kind=agent: {mem.trajectory_count('agent')})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
