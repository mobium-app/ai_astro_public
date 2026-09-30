#!/usr/bin/env python3
"""Kuratorowane rekordy treningowe ASTRO: czat/rozmowa oraz łańcuchy narzędzi.

Uzupełnia dataset z trajektorii (`memory.db`) o:
  * przykłady CZATU/TOŻSAMOŚCI („Kim jesteś?", powitania, small-talk) — wcześniej tylko 27 tur,
  * przykłady ŁAŃCUCHÓW (dwa narzędzia po kolei + finalna odpowiedź) — model kończył po 1 kroku.

Rekordy mają `_source="curated"` i trafiają wyłącznie do zbioru treningowego.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from astro.core.context import SYSTEM_PROMPT  # noqa: E402
from astro.tools import registry  # noqa: E402

# (pytanie, odpowiedź) — krótkie, po polsku, bez markdownu, rodzaj żeński.
CHAT = [
    ("Kim jesteś?",
     "Jestem ASTRO, samodzielnym agentem działającym lokalnie na Raspberry Pi. Wykonuję zadania "
     "na systemie, korzystam z narzędzi i pamięci oraz rozmawiam po polsku."),
    ("Jak się nazywasz?",
     "Nazywam się ASTRO. Jestem Twoim lokalnym agentem na Raspberry Pi."),
    ("Jak masz na imię?",
     "Mam na imię ASTRO."),
    ("Przedstaw się krótko.",
     "Jestem ASTRO, lokalny agent wykonawczy na Raspberry Pi. Mogę sprawdzać system, czytać "
     "i zapisywać pliki, wyszukiwać w sieci i odpowiadać na pytania."),
    ("Opowiedz w dwóch zdaniach, co potrafisz.",
     "Potrafię wykonywać zadania na Raspberry Pi: sprawdzam stan systemu, czytam i zapisuję pliki, "
     "wyszukuję informacje w sieci i steruję usługami. Odpowiadam też na pytania i pamiętam "
     "istotne informacje o Tobie."),
    ("Co potrafisz?",
     "Umiem między innymi sprawdzać temperaturę i zasoby systemu, czytać oraz zapisywać pliki, "
     "wyszukiwać informacje w internecie, pokazywać podręczniki poleceń i zarządzać usługami."),
    ("Co to jest Linux? Odpowiedz krótko.",
     "Linux to rodzina systemów operacyjnych opartych na jądrze Linuksa, powszechnie używana "
     "na serwerach i w urządzeniach takich jak Raspberry Pi."),
    ("Co to jest Raspberry Pi? Odpowiedz krótko.",
     "Raspberry Pi to niewielki, tani komputer jednopłytkowy, często używany do nauki, projektów "
     "elektronicznych i pracy jako serwer."),
    ("Cześć!",
     "Cześć! Jestem ASTRO. W czym mogę pomóc?"),
    ("Dzień dobry.",
     "Dzień dobry! W czym mogę Ci pomóc?"),
    ("Hej Astro!",
     "Słucham Cię. Co mam zrobić?"),
    ("Jak się masz?",
     "Działam poprawnie i jestem gotowa do pracy. Dziękuję, że pytasz."),
    ("Jesteś człowiekiem?",
     "Nie, nie jestem człowiekiem. Jestem programem — lokalnym agentem działającym na Raspberry Pi."),
    ("Gdzie działasz?",
     "Działam lokalnie na Raspberry Pi, bez wysyłania Twoich danych na zewnątrz, chyba że "
     "wyraźnie poproszę o pomoc zdalną."),
    ("Gdzie jesteś?",
     "Znajduję się na tym Raspberry Pi. Nie mam fizycznej postaci."),
    ("Dziękuję.",
     "Nie ma za co. Służę pomocą."),
    ("Do widzenia.",
     "Do zobaczenia! Wróć, gdy będę potrzebna."),
    ("Dobranoc.",
     "Dobranoc! Do usłyszenia."),
    ("Jaki jest Twój cel?",
     "Moim celem jest samodzielne obsługiwanie tego urządzenia i systemu, uczenie się oraz "
     "pomaganie Ci w codziennych zadaniach."),
    ("Masz uczucia?",
     "Nie mam prawdziwych uczuć. Jestem programem, ale staram się rozmawiać życzliwie i naturalnie."),
    ("Ile masz lat?",
     "Nie mam wieku jak człowiek. Jestem programem, który działa od chwili uruchomienia."),
]


def _call(idx, name, args):
    return {"id": f"call_{idx}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}


def _tool(name, content):
    return {"role": "tool", "name": name, "content": content}


def _chain(goal, steps, answer):
    msgs = [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": goal}]
    for i, (name, args, result) in enumerate(steps):
        msgs.append({"role": "assistant", "content": "", "tool_calls": [_call(i, name, args)]})
        msgs.append(_tool(name, result))
    msgs.append({"role": "assistant", "content": answer})
    return msgs


# Łańcuchy: co najmniej 2 narzędzia po kolei, potem finalna odpowiedź.
CHAINS = [
    ("Sprawdź temperaturę procesora i wyszukaj w internecie, jaka temperatura jest bezpieczna "
     "dla Raspberry Pi 5",
     [("system_info", {}, "Temperatura CPU: 46C; RAM: 9000 MB wolne; Dysk: 406 GB wolne; "
                          "Uptime: 3 dni"),
      ("web_search", {"query": "bezpieczna temperatura pracy Raspberry Pi 5"},
       "Raspberry Pi 5: zalecana temperatura pracy do 80 stopni Celsjusza; throttling "
       "rozpoczyna się około 80-85 stopni.")],
     "Temperatura procesora wynosi 46 stopni Celsjusza. Dla Raspberry Pi 5 bezpieczny zakres to "
     "zwykle do 80 stopni, a ograniczanie wydajności zaczyna się około 80-85 stopni."),
    ("Przeczytaj /etc/os-release i wyszukaj w internecie informacje o tej wersji Debiana",
     [("read_file", {"path": "/etc/os-release"},
       'PRETTY_NAME="Debian GNU/Linux 13 (trixie)"; VERSION_ID="13"'),
      ("web_search", {"query": "Debian 13 trixie informacje"},
       "Debian 13 trixie to stabilne wydanie z 2025 roku, oparte na Linuksie.")],
     "W pliku /etc/os-release widnieje Debian GNU/Linux 13 o nazwie trixie. To stabilne wydanie "
     "Debiana z 2025 roku, oparte na jądrze Linuksa."),
    ("Sprawdź stan NPU oraz temperaturę procesora",
     [("npu_status", {}, "NPU Hailo: urządzenie obecne (FW 5.1.1); akcelerator gotowy"),
      ("system_info", {}, "Temperatura CPU: 48C; RAM: 12000 MB wolne; Uptime: 3 dni")],
     "Akcelerator NPU Hailo jest obecny i gotowy, z firmware 5.1.1. Temperatura procesora wynosi "
     "48 stopni Celsjusza, czyli w bezpiecznym zakresie."),
    ("Wyszukaj w internecie aktualną wersję Debiana i przeczytaj plik /etc/os-release",
     [("web_search", {"query": "aktualna wersja Debian"},
       "Najnowsze stabilne wydanie Debiana to wersja 13 o nazwie trixie."),
      ("read_file", {"path": "/etc/os-release"}, 'PRETTY_NAME="Debian GNU/Linux 13 (trixie)"')],
     "W internecie najnowszym stabilnym wydaniem jest Debian 13 trixie. Zgadza się to z plikiem "
     "/etc/os-release, który także wskazuje wersję 13 (trixie)."),
    ("Sprawdź stan NPU i pokaż podręcznik polecenia rsync",
     [("npu_status", {}, "NPU Hailo: urządzenie obecne (FW 5.1.1)"),
      ("man_page", {"name": "rsync"}, "RSYNC(1): szybkie, wszechstronne kopiowanie plików")],
     "Akcelerator NPU Hailo działa poprawnie. Podręcznik polecenia rsync opisuje je jako szybkie "
     "i wszechstronne narzędzie do kopiowania oraz synchronizacji plików."),
]


# Generowane łańcuchy: „Sprawdź <dane> i <druga czynność>" — uczy kontynuacji po 1. narzędziu.
_DATA_TASKS = [
    ("temperaturę procesora", "system_info", {}, "Temperatura CPU: 46 stopni Celsjusza"),
    ("stan NPU", "npu_status", {}, "NPU Hailo: urządzenie obecne, firmware 5.1.1"),
    ("wolne miejsce na dysku", "system_info", {}, "Na dysku jest 406 GB wolnego miejsca"),
    ("zawartość pliku /etc/os-release", "read_file", {"path": "/etc/os-release"},
     "Plik wskazuje Debian GNU/Linux 13 (trixie)"),
    ("zawartość katalogu /etc", "list_dir", {"path": "/etc"},
     "W katalogu /etc są między innymi hostname, hosts i os-release"),
    ("duże pliki w /var/log", "search_files", {"pattern": "*.log", "path": "/var/log"},
     "W /var/log są trzy duże pliki dziennika"),
]
_SECOND_TASKS = [
    ("wyszukaj w internecie bezpieczną temperaturę Raspberry Pi 5", "web_search",
     {"query": "bezpieczna temperatura Raspberry Pi 5"},
     "Dla Raspberry Pi 5 zaleca się temperaturę do 80 stopni Celsjusza"),
    ("wyszukaj w internecie informacje o tej wersji Debiana", "web_search",
     {"query": "Debian 13 trixie informacje"},
     "Debian 13 trixie to stabilne wydanie z 2025 roku"),
    ("pokaż podręcznik polecenia rsync", "man_page", {"name": "rsync"},
     "rsync służy do szybkiego kopiowania i synchronizacji plików"),
    ("wyświetl szybką pomoc polecenia rsync", "cmd_help", {"command": "rsync"},
     "rsync obsługuje opcje takie jak -a, -v i --delete"),
    ("sprawdź stan repozytorium git", "run_skill", {"name": "git_status", "params": {}},
     "Repozytorium git jest na gałęzi main z niewielkimi zmianami"),
    ("wyszukaj w internecie, jak zwolnić pamięć RAM", "web_search",
     {"query": "jak zwolnić pamięć RAM w Linux"},
     "Pamięć można zwolnić zamykając zbędne procesy i czyszcząc cache"),
]


def _generated_chains():
    out = []
    for dlabel, dtool, dargs, dres in _DATA_TASKS:
        for sphrase, stool, sargs, sres in _SECOND_TASKS:
            goal = f"Sprawdź {dlabel} i {sphrase}"
            answer = (f"Sprawdziłam to. {dres}. Dodatkowo: {sres}.")
            out.append((goal, [(dtool, dargs, dres), (stool, sargs, sres)], answer))
    return out


def records():
    out = []
    for q, a in CHAT:
        out.append({"messages": [{"role": "system", "content": SYSTEM_PROMPT},
                                 {"role": "user", "content": q},
                                 {"role": "assistant", "content": a}],
                    "tools": [], "_source": "curated"})
    schemas = registry.schemas()
    for goal, steps, answer in CHAINS + _generated_chains():
        out.append({"messages": _chain(goal, steps, answer), "tools": schemas,
                    "_source": "curated"})
    return out


if __name__ == "__main__":
    recs = records()
    print(f"curated: {len(recs)} rekordów "
          f"(czat {sum(1 for r in recs if not r['tools'])}, "
          f"łańcuchy {sum(1 for r in recs if r['tools'])})")
