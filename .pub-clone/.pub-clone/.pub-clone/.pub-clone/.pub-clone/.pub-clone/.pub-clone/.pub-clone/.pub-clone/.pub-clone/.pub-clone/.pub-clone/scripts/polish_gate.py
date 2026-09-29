#!/usr/bin/env python3
"""Bramka polszczyzny ASTRO: sprawdza wymowę (TTS) na zestawie przypadków.

Uruchomienie:
    python3 astro/scripts/polish_gate.py

Kod wyjścia 0 tylko gdy wszystkie przypadki PASS. Bez modelu i bez sieci.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from astro.audio.text import prepare_speech  # noqa: E402

# (wejście, fragmenty które MUSZĄ wystąpić)
CASES = (
    ("5 plik", ("5 plików",)),
    ("2 błąd", ("2 błędy",)),
    ("za 5 minut", ("za pięć minut",)),
    ("10 minut temu", ("dziesięć minut temu",)),
    ("1 maja", ("pierwszego maja",)),
    ("15:00", ("godzina piętnasta",)),
    ("o 15:30", ("o godzinie piętnastej trzydzieści",)),
    ("z 5 plikami", ("z pięcioma plikami",)),
    ("o 3 godzinach", ("o trzech godzinach",)),
    ("w 2 plikach", ("w dwóch plikach",)),
    ("1. miejsce", ("pierwsze miejsce",)),
    ("XXI wiek", ("dwudziesty pierwszy wiek",)),
    ("w XX wieku", ("w dwudziestym wieku",)),
    ("w styczeń", ("w styczniu",)),
    ("5 km", ("pięć kilometrów",)),
    ("50 km/h", ("kilometrów na godzinę",)),
    ("4,50 zł", ("cztery złote pięćdziesiąt groszy",)),
    ("2,01 USD", ("dwa dolary jeden cent",)),
    ("-5°C", ("minus pięć stopni Celsjusza",)),
    ("3,5%", ("trzy przecinek pięć procent",)),
    ("1/2", ("pół",)),
    ("2026 r.", ("2026 roku",)),
    ("od 5 do 10", ("od pięciu do dziesięciu",)),
    ("15. rocznica", ("piętnasta rocznica",)),
    ("31. edycja", ("trzydziesta pierwsza edycja",)),
    ("5 ha", ("pięć hektarów",)),
    ("10 kW", ("dziesięć kilowatów",)),
    ("20 m²", ("metrów kwadratowych",)),
    ("w środa", ("w środę",)),
    ("w niedziela", ("w niedzielę",)),
    ("wg. mnie", ("według",)),
    ("5 mld", ("miliardów",)),
    ("3 × 4", ("razy",)),
    ("21 wiek", ("dwudziesty pierwszy wiek",)),
    ("2 dzieci", ("dwoje dzieci",)),
    ("0,5 l", ("pół litra",)),
    ("o 15.30", ("o godzinie piętnastej trzydzieści",)),
    ("do 5 plików", ("do pięciu plików",)),
    ("od 1 do 5", ("od jednego do pięciu",)),
    ("10 m/s", ("metrów na sekundę",)),
    ("100 Mbps", ("megabitów na sekundę",)),
    ("5 kWh", ("kilowatogodzin",)),
    ("70°F", ("stopni Fahrenheita",)),
    ("10 CHF", ("franków",)),
    ("5 tys. zł", ("złotych",)),
    ("½", ("pół",)),
    ("24/7", ("całodobowo",)),
    ("gen. Nowak", ("generał",)),
    # Leksykon wymowy: akronimy (dokładne) i nazwy własne.
    ("sprawdź IP", ("i pe",)),
    ("temperatura CPU", ("ce pe u",)),
    ("stan Hailo", ("hajlo",)),
    ("uruchom Ollama", ("olama",)),
    ("plik JSON", ("dżejson",)),
    ("model GGUF", ("gie gie u ef",)),
    ("Raspberry Pi", ("raspberi",)),
)
# (wejście, fragmenty które NIE MOGĄ wystąpić — nazwy znaków)
NOT_CASES = (
    ("jan@example.com", ("małpa",)),
    ("#hashtag", ("kratka",)),
    ("/etc/hosts", ("ukośnik",)),
    ("2^3", ("daszek",)),
    ("a|b", ("pionowa",)),
)


def main():
    results = []
    for text, expected in CASES:
        out = prepare_speech(text)
        missing = [e for e in expected if e not in out]
        results.append((f"wymowa: {text!r}", not missing, out, missing))
    for text, banned in NOT_CASES:
        out = prepare_speech(text)
        found = [b for b in banned if b in out]
        results.append((f"bez znaków: {text!r}", not found, out, found))

    width = max(len(name) for name, *_ in results)
    ok_all = True
    for name, ok, out, bad in results:
        ok_all = ok_all and ok
        detail = "ok" if ok else f"brak/źle: {bad} -> {out!r}"
        print(f"[{'PASS' if ok else 'FAIL'}] {name:<{width}}  {detail}")
    passed = sum(1 for _n, ok, _o, _b in results if ok)
    print(f"\nPOLISH GATE: {passed}/{len(results)} {'PASS' if ok_all else 'FAIL'}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
