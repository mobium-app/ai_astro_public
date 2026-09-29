"""Walidacja planów wykonania (przeniesione z Ateny, zachowanie 1:1)."""

import re
import shutil
import subprocess

from .commands import DANGEROUS_CMD
from .normalize import normalize_facts
from . import verbs

DIAG_GOAL_RE = re.compile(
    r"\b(przeanalizuj|zdiagnozuj|diagnoz\w*|sprawdz|sprawd[źz]|wykryj|status|logi|log\b|"
    r"co sie dzieje|zbadaj|analiza|monitoruj|ile|jaki|jaka)\b", re.I)
INSTALL_CMD_RE = re.compile(r"\b(apt(-get)?\s+(install|-y install)|pip3?\s+install|snap\s+install)\b",
                            re.I)
# Definicje czasowników celów planu: `safety/verbs.py` (C7).
RUN_GOAL_RE = verbs.run_goal_re()
SETUP_GOAL_RE = verbs.setup_goal_re()
INSTALL_PKG_RE = re.compile(
    r"\bapt(?:-get)?\s+(?:-y\s+)?install\s+(?:-y\s+)?(?:--no-install-recommends\s+)?"
    r"([a-z0-9][a-z0-9.+-]*)", re.I)
# Metaznaki łańcuchowania/podstawiania: krok planu ma być POJEDYNCZYM poleceniem. Odrzucamy
# `, $(, ;, &&, || i nowe linie (możliwość przemytu drugiego polecenia po potwierdzeniu).
# Pojedynczy `|` (potok) i proste przekierowania zostawiamy — bywają potrzebne i są potwierdzane.
PLAN_CHAIN_RE = re.compile(r"`|\$\(|;|&&|\|\||\n|\r")


def already_installed(pkg):
    pkg = (pkg or "").strip()
    if not pkg:
        return False
    if shutil.which(pkg):
        return True
    try:
        out = subprocess.run(["dpkg-query", "-W", "-f=${Status}", pkg],
                             capture_output=True, text=True, timeout=10)
        return "install ok installed" in (out.stdout or "")
    except Exception:
        return False


def validate_plan(steps, goal=""):
    """Zwraca komunikat odrzucenia albo None. Pilnuje DANGEROUS_CMD, diagnostyki bez instalacji
    i nieinstalowania pakietów, które już istnieją."""
    nrm_goal = normalize_facts(goal or "")
    diagnostic = bool(DIAG_GOAL_RE.search(nrm_goal))
    setup_goal = bool(SETUP_GOAL_RE.search(nrm_goal))
    run_only = bool(RUN_GOAL_RE.search(nrm_goal)) and not setup_goal
    for s in steps:
        cmd = s.get("command", "")
        if PLAN_CHAIN_RE.search(cmd):
            return (f"odrzucono: plan nie może łączyć poleceń ani podstawiać wyników "
                    f"(metaznaki powłoki): {cmd}")
        low = cmd.lower()
        if any(d in low for d in DANGEROUS_CMD):
            return f"odrzucono niebezpieczne polecenie: {s['command']}"
        if INSTALL_CMD_RE.search(low):
            if diagnostic:
                return ("odrzucono: zadanie diagnostyczne nie moze instalowac pakietow "
                        f"({s['command']})")
            mi = INSTALL_PKG_RE.search(low)
            pkg = mi.group(1) if mi else ""
            if pkg and already_installed(pkg):
                return (f"odrzucono: {pkg} jest już zainstalowany - nie ma potrzeby go instalować")
            if run_only:
                return (f"odrzucono: cel '{goal}' to uruchomienie, a krok instaluje "
                        f"{pkg or 'pakiet'} - najpierw sprawdź, czy program już nie istnieje")
    return None
