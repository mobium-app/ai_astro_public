#!/usr/bin/env python3
"""ASTRO Wi-Fi — samodzielny, w 100% offline (nmcli). „Na gotowo", bez modelu.

Użycie:
    python3 astro/scripts/wifi.py scan
    python3 astro/scripts/wifi.py connect "MojaSiec" --password "tajne"
    python3 astro/scripts/wifi.py connect "MojaSiec" --spell "małe a, duże Be, hasztag, koniec"
    python3 astro/scripts/wifi.py disconnect "MojaSiec"
    python3 astro/scripts/wifi.py status

`--spell` dekoduje literowanie i odtwarza beep po każdej literce (aplay).
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from astro import wifi  # noqa: E402
from astro.audio import signals  # noqa: E402
from astro.spelling import parse_spelled_secret  # noqa: E402


def _beep_each(text, decoded):
    for _ in decoded:
        try:
            signals.tick_signal()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser(description="ASTRO Wi-Fi (offline)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("scan")
    sub.add_parser("status")

    pc = sub.add_parser("connect")
    pc.add_argument("ssid")
    pc.add_argument("--password", default="")
    pc.add_argument("--spell", default="")
    pc.add_argument("--no-beep", action="store_true")

    pd = sub.add_parser("disconnect")
    pd.add_argument("name", nargs="?", default="")

    args = ap.parse_args()

    if args.cmd == "scan":
        print(wifi.scan_text())
        return 0

    if args.cmd == "status":
        ssid = wifi.active_ssid()
        print(f"aktywne Wi-Fi: {ssid}" if ssid else "brak aktywnego połączenia Wi-Fi")
        return 0

    if args.cmd == "disconnect":
        ok, msg = wifi.disconnect(args.name)
        print(msg)
        return 0 if ok else 1

    if args.cmd == "connect":
        target = wifi.resolve(args.ssid) or args.ssid
        password = args.password
        if args.spell:
            decoded = parse_spelled_secret(args.spell)
            if not args.no_beep:
                _beep_each(args.spell, decoded)
            password = decoded or password
        if not password and wifi.is_secured(target):
            print("sieć zabezpieczona. podaj hasło (--password albo --spell)")
            return 2
        ok, msg = wifi.connect(target, password or None)
        print(msg)
        return 0 if ok else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
