#!/usr/bin/env python3
"""Audyt komend „must-have": porównuje `/etc/astro-secrets/komendy_must-have` ze stanem ASTRO.

Dla każdej frazy z listy sprawdza (czysto, bez efektów ubocznych), czy ASTRO ją rozpozna:
must-have (nowy fast-path) → Wi-Fi → profil → szybkie ścieżki (czas/zasoby/zasilanie/...)
→ humor → agent/remote. Wypisuje OK / BRAK, żeby po każdej aktualizacji listy wiedzieć,
co jeszcze wdrożyć (komenda użytkownika „aktualizuj komendy").

Użycie:
  python3 scripts/must_have_audit.py [--file ŚCIEŻKA] [--verbose]
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from astro import config  # noqa: E402
from astro import wifi  # noqa: E402
from astro.core import must_have  # noqa: E402
from astro.core import fast_tools, profiling, skynet  # noqa: E402
from astro.persona import humor  # noqa: E402
from astro.safety import classify_request, normalize_command  # noqa: E402

DEFAULT_FILE = getattr(config, "MUSTHAVE_FILE", "/etc/astro-secrets/komendy_must-have")
_FAST = (("czas", fast_tools.TIME_RE), ("data", fast_tools.DATE_RE),
         ("temperatura", fast_tools.TEMP_RE),
         ("raport", fast_tools.REPORT_RE), ("zasoby", fast_tools.RESOURCE_RE),
         ("status-aktualizacji", fast_tools.UPDATE_STATUS_RE),
         ("pogoda", fast_tools.WEATHER_RE), ("waluta", fast_tools.CURRENCY_RE),
         ("głośność", fast_tools.VOLUME_RE),
         ("usługa", fast_tools.SERVICE_RE), ("npu", fast_tools.NPU_RE),
         ("system-info", fast_tools.INFO_RE))


def coverage(text):
    """Etykieta trasy obsługującej frazę albo "" (brak). Bez I/O."""
    r = skynet.intent(text)
    if r:
        return "skynet:" + r
    r = must_have.intent(text)
    if r:
        return "must-have:" + r
    wi = wifi.intent(text)
    if wi:
        return "wifi:" + wi.get("action", "")
    low = normalize_command(text)
    if (profiling.TRIGGER_RE.search(low) or profiling.QUERY_RE.search(low)
            or profiling.FORGET_RE.search(low)):
        return "profil"
    if not fast_tools.POWER_NEG_RE.search(low) and (
            fast_tools.POWER_SHUTDOWN_RE.search(low) or fast_tools.POWER_REBOOT_RE.search(low)):
        return "fast:zasilanie"
    if fast_tools.update_action(low):
        return "fast:aktualizacja"
    for name, rx in _FAST:
        if rx.search(low):
            return "fast:" + name
    if fast_tools.MATH_TRIGGER_RE.search(low) and not fast_tools.CURRENCY_RE.search(low):
        return "fast:math"
    # Skille/receptury (deterministyczne skrypty) — np. „ping", „lista dysków", „status git".
    # Kolejność jak w dispatchu: fast-tools PRZED skillami. Od 2026-09-29 skille działają też dla
    # wypowiedzi pytających (realne komendy, np. „ile jest wolnego miejsca") — bez bramki „question".
    try:
        from astro.skills import match_skill
        m = match_skill(text)
        if m:
            return "skill:" + m[0].name
    except Exception:
        pass
    if humor.is_joke_request(text):
        return "humor"
    cls = classify_request(text)
    if cls in ("command", "question", "chat"):
        return "agent:" + cls
    return ""


# Osierocone słowa po usunięciu slotu [.zmienna.]/[.host.] — same nie są komendami
# (np. „ping" z „ping [.host.]", „logi usługi" z „logi usługi [.nazwa.]").
_SLOT_RESIDUE = {
    "ping", "dns", "logi usługi", "logi uslugi", "dziennik usługi", "dziennik uslugi",
    "zajętość katalogu", "zajetosc katalogu", "adres ip dla", "rozwiń nazwę", "rozwIn nazwe",
    "przetłumacz na", "co się zmieniło w", "co sie zmienilo w", "twoje ulubione",
}


def phrases_from_file(path):
    """[(sekcja, [frazy])] z pliku must-have (1:1, odporne na opisy/nawiasy).

    Konwencja pliku: `#` = sekcja, `##`/`###` = komenda, zwykłe linie = opisy (pomijane).
    Nagłówki kategorii (np. `## KALKULATOR`, `## PRZEWALUTOWANIE`) nie są komendami.
    """
    out = []
    section = ""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            if not stripped.startswith("#"):
                continue  # opisy/notatki (np. „Astro odpowiada w formie...")
            hashes = len(stripped) - len(stripped.lstrip("#"))
            body = stripped.lstrip("#").strip()
            if hashes == 1:
                # sekcja może nieść opis po „ - " (np. „# SYSTEM - ... prefix 'terminal'")
                section = body.split(" - ")[0].strip().upper()
                continue
            if not body:
                continue
            # nagłówek kategorii: wersaliki (WI-FI, KALKULATOR, ZNAJDZ MIEJSCE, ...) — nie komenda
            if hashes == 2 and body.isupper():
                continue
            body = re.sub(r"\([^)]*\)?", "", body)  # nawiasy (także niedomknięte)
            # Opis oddzielony strzałką („---->", „→") — bierzemy część przed strzałką.
            body = re.split(r"\s*[-–—]{2,}\s*>\s*|\s*→\s*", body)[0]
            body = re.sub(r"\s+-\s+", " - ", body)  # ujednolić myślniki opisów („1- laczy")
            body = body.split(" - ")[0]  # odetnij opis
            body = body.replace("[...]", "paczkomat")
            # [a/b/c] -> pierwszy wariant; [notatka] -> usuń
            body = re.sub(r"\[([^\]]*)\]",
                          lambda m: m.group(1).split("/")[0] if "/" in m.group(1) else "", body)
            parts = [p.strip() for p in re.split(r"\s*/\s*", body) if p.strip()]
            # Odfiltruj resztki slotów: puste, same „[", lub osierocone słowa-po-slocie
            # (np. „twoje ulubione" po usunięciu [.zmienna.], „najbliższy" po [.zmienna.]).
            parts = [p for p in parts if not p.startswith("[")
                     and not p.upper().startswith("ASTRO ODPOWIADA")
                     and not re.fullmatch(r"(?:twoje|najbli[zż]szy|podaj\s+adres\s+najbli[zż]szego)",
                                          p.strip().lower())
                     and p.strip().lower() not in _SLOT_RESIDUE]
            if parts:
                out.append((section, parts))
    return out


def main():
    ap = argparse.ArgumentParser(description="Audyt komend must-have (ASTRO)")
    ap.add_argument("--file", default=DEFAULT_FILE)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--strict", action="store_true",
                    help="sekcje SYSTEM/WI-FI muszą mieć deterministyczny fast-path (nie agent)")
    args = ap.parse_args()

    if not os.path.isfile(args.file):
        print(f"[audyt] brak pliku: {args.file}")
        return 2

    total = missing = weak = 0
    for section, parts in phrases_from_file(args.file):
        for phrase in parts:
            total += 1
            route = coverage(phrase)
            if not route:
                missing += 1
            elif args.strict and section and section != "SMAL-TALK" and route.startswith("agent:"):
                missing += 1
                weak += 1
                route += "  (OCZEKIWANO fast-path)"
            mark = "OK " if route and "OCZEKIWANO" not in route else "BRAK"
            if route or args.verbose:
                print(f"  [{mark}] {section or '-':9} {phrase!r:55} -> {route or '-'}")
    msg = f"\n[audyt] fraz: {total}, obsłużonych: {total - missing}, BRAK: {missing}"
    if args.strict:
        msg += f" (w tym agent zamiast fast-path: {weak})"
    print(msg)
    return 0 if missing == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
