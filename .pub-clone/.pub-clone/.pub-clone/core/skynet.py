"""Prefiks `skajnet` (must-have): zadania wykonywane na Pi4-SKYNET.

Sekcja SKAJNET listy `/etc/astro-secrets/komendy_must-have` — komendy uruchamiane z prefiksem
głosowym „skajnet" wykonują zadania na Pi4-skynet (host kontenerów netrunner.edu.pl). Wszystko
przez STAŁY tunel `astro-pi4-tunnel` (127.0.0.1:2200 -> Pi4:2222) i `scripts/pi4.sh` — determinizm
bez modelu i bez chmury.

Zasada jak w pozostałych sekcjach must-have: operacje zmieniające system zdalny (shutdown, reboot,
apt update/upgrade, instalacja) wymagają potwierdzenia („potwierdzam"/„anuluj"), identycznie jak
lokalne odpowiedniki (`fast_tools`/`must_have`).
"""

import os
import re
import subprocess
import sys

from .. import config, mirror
from ..safety import normalize_command

# --- rozpoznawanie intencji (na tekście znormalizowanym, bez diakrytyków) ----------------------
_DOCKER_RE = re.compile(r"\b(?:jaki\s+)?status\s+doker\b")
_SHUTDOWN_RE = re.compile(
    r"\b(?:wylacz|zamknij|zgas|shutdown)\w*\s+(?:system|serwer|urzadz\w*)|"
    r"\b(?:wylacz|zamknij)\s+sie\b")
_REBOOT_RE = re.compile(
    r"\b(?:restart|restaart|zrestartuj|restartuj|reset|resetuj|zresetuj|reboot)\w*\s*"
    r"(?:system|serwer|urzadz\w*)|\b(?:reset|resetuj|zresetuj|restart)\w*\s+sie\b")
_RESOURCES_RE = re.compile(
    r"\b(?:pokaz|wyswietl)\s+zasoby\s+systemowe\b|\bzasoby\s+systemowe\b|"
    r"\bdrzewko\s+zasob\w*\s+skajnet\b")
_REMOTE_RES_RE = re.compile(
    r"\b(?:zasoby\s+(?:zdalne|remote|remolt)|remote\s+zasoby|wyswietl\s+zasoby\s+remolt)\b")
_UPDATE_REPO_RE = re.compile(
    r"\b(?:aktualizuj|uaktualnij|odswiez|updejt|update)\w*\s+(?:repozytoria|zrodla|repo)\b|"
    r"\bupdejt\s+repo\b")
_UPDATE_APPS_RE = re.compile(
    r"\b(?:aktualizuj|uaktualnij|odswiez|updejt|update)\w*\s+(?:aplikacje|programy|apps)\b|"
    r"\bupdejt\s+apps?\b")
_INSTALL_RE = re.compile(
    r"\b(?:instaluj|zainstaluj)\s+(?:mi\s+)?"
    r"(?:aplikacj\w*|program\w*|pakiet\w*)?\s*"
    r"([a-z0-9][a-z0-9.+-]{1,40})")
_INSTALL_STOPWORDS = {"mi", "do", "na", "za", "sie", "prosze", "jakas", "jakis", "nowa", "nowy",
                      "program", "programy", "programu", "aplikacje", "aplikacja", "aplikacje",
                      "pakiet", "pakiety", "pakietu", "apke", "apka"}
_TEMP_RE = re.compile(
    r"\btemperatur\w*\s+(?:procesora|cpu|ce\s+pe\s+u|ce-pe-u)\b")

_PI4_SH = os.path.join(str(config.REPO), "scripts", "pi4.sh")
_CONFIRM_LABELS = {
    "power-shutdown": "Wyłączyć Skajnet (shutdown)?",
    "power-reboot": "Zrestartować Skajnet (reboot)?",
    "update-repo": "Zaktualizować repozytoria na Skajnecie (apt update)?",
    "update-apps": "Zaktualizować aplikacje na Skajnecie (apt upgrade)?",
    "install": "Zainstalować pakiet na Skajnecie (apt install)?",
}


def intent(text):
    """Czysty klasyfikator komend SKAJNET (bez I/O): etykieta trasy albo ""."""
    low = normalize_command(text or "")
    if not low:
        return ""
    if _DOCKER_RE.search(low):
        return "docker-status"
    if _SHUTDOWN_RE.search(low):
        return "power-shutdown"
    if _REBOOT_RE.search(low):
        return "power-reboot"
    if _RESOURCES_RE.search(low):
        return "resources"
    if _REMOTE_RES_RE.search(low):
        return "remote-resources"
    if _UPDATE_REPO_RE.search(low):
        return "update-repo"
    if _UPDATE_APPS_RE.search(low):
        return "update-apps"
    if _INSTALL_RE.search(low):
        return "install"
    if _TEMP_RE.search(low):
        return "temp"
    return ""


def _pi4(*args, timeout=45):
    """Wykonuje polecenie na Pi4 przez `scripts/pi4.sh` (tunel). Zwraca (code, output)."""
    try:
        p = subprocess.run(["bash", _PI4_SH, *args], capture_output=True, text=True,
                           errors="replace", timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"przekroczono limit {timeout}s na połączenie z Pi4"
    except Exception as e:
        return 1, str(e)


def _ssh_remote_cmd(cmd, sudo=False):
    """Buduje krok lokalny: `bash scripts/pi4.sh sh '<komenda>'` (wykonywany po potwierdzeniu)."""
    prefix = "sudo -n " if sudo else ""
    return {"command": f"bash {_PI4_SH} sh '{prefix}{cmd}'", "root": False}


def _docker_status():
    code, out = _pi4("sh",
                     "docker ps --format '{{.Names}} ({{.Image}}) {{.Status}}' 2>/dev/null; "
                     "echo; echo 'running='$(docker ps -q | wc -l)'; total='$(docker ps -aq | wc -l)")
    if code != 0:
        return f"Nie mogę odczytać statusu dokera na Skajnecie: {out.strip()[:200]}", "docker-status"
    names = [l for l in out.splitlines() if l and "running=" not in l and "total=" not in l]
    counts = re.search(r"running=(\d+).*?total=(\d+)", out.replace("\n", " "))
    if not names:
        return "Na Skajnecie nie działa żaden kontener.", "docker-status"
    summary = ", ".join(n.split(" ")[0] for n in names)
    text = (f"Na Skajnecie działa {len(names)} kontener{'ów' if len(names) != 1 else ''}: "
            f"{summary}.")
    try:
        mirror.wall_write("SKAJNET docker:\n" + "\n".join(names)
                          + (f"\n({counts.group(0)})" if counts else ""))
    except Exception:
        pass
    return text, "docker-status"


def _resources():
    code, out = _pi4("status", timeout=60)
    if code != 0:
        return f"Nie mogę odczytać zasobów Skajneta: {out.strip()[:200]}", "resources"
    try:
        mirror.wall_write("Zasoby SKAJNET (Pi4):\n" + out.strip())
    except Exception:
        pass
    parts = []
    m = re.search(r"temp=([\d.]+)", out)
    if m:
        parts.append(f"CPU {m.group(1)} stopni")
    m = re.search(r"ram: uzyte ([\w.]+[GM]?) / ([\w.]+[GM]?)", out)
    if m:
        parts.append(f"RAM {m.group(1)} z {m.group(2)}")
    m = re.search(r"dysk: ([\w.]+[GM]?) / ([\w.]+[GM]?) \(([\d]+)%\)", out)
    if m:
        parts.append(f"dysk zajęty w {m.group(3)} procent")
    m = re.search(r"docker: (\d+) running", out)
    if m:
        parts.append(f"doker: {m.group(1)} kontenerów działa")
    return ("Zasoby Skajneta: " + ", ".join(parts) + ". Drzewko pokazuję na terminalu."), "resources"


def _remote_resources():
    script = os.path.join(str(config.REPO), "scripts", "remote_usage.py")
    try:
        p = subprocess.run([sys.executable, script, "--all", "--summary"], capture_output=True,
                           text=True, errors="replace", timeout=60)
        summary = (p.stdout or "").strip()
    except Exception as e:
        summary = ""
    if not summary:
        return "Brak danych o zużyciu zdalnych modeli.", "remote-resources"
    try:
        tree_p = subprocess.run([sys.executable, script, "--all", "--no-color"], capture_output=True,
                                text=True, errors="replace", timeout=60)
        if tree_p.stdout:
            mirror.wall_write(tree_p.stdout)
    except Exception:
        pass
    return summary, "remote-resources"


def _temp():
    code, out = _pi4("sh", "vcgencmd measure_temp 2>/dev/null | cut -d= -f2")
    if code != 0 or not out.strip():
        return "Nie mogę odczytać temperatury procesora Skajneta.", "temp"
    return f"Temperatura procesora Skajneta wynosi {out.strip()} stopni Celsjusza.", "temp"


def handle(text, agent=None):
    """Zwraca (reply, route) albo None. Deterministyczny; bez modelu."""
    route = intent(text)
    if not route:
        return None
    if route == "docker-status":
        return _docker_status()
    if route == "resources":
        return _resources()
    if route == "remote-resources":
        return _remote_resources()
    if route == "temp":
        return _temp()
    low = normalize_command(text or "")
    if route == "power-shutdown":
        return _ask_confirm(agent, route, ["shutdown now", True])
    if route == "power-reboot":
        return _ask_confirm(agent, route, ["reboot now", True])
    if route == "update-repo":
        return _ask_confirm(agent, route, ["apt-get update", True])
    if route == "update-apps":
        return _ask_confirm(agent, route, ["apt-get -y upgrade", True])
    if route == "install":
        m = _INSTALL_RE.search(low)
        pkg = m.group(1) if m else ""
        if pkg in _INSTALL_STOPWORDS or not re.match(r"^[a-z0-9][a-z0-9.+-]{1,40}$", pkg):
            return "Jaki pakiet mam zainstalować na Skajnecie? Podaj nazwę.", "install"
        return _ask_confirm(agent, route, [f"apt-get install -y {pkg}", True])
    return None


def _ask_confirm(agent, route, cmd_spec):
    """Komenda zdalna z bramką potwierdzenia; po „potwierdzam" wznawiana przez `pending`."""
    cmd, sudo = cmd_spec
    ctx = getattr(agent, "ctx", None)
    label = _CONFIRM_LABELS.get(route, "Wykonać na Skajnecie?")
    steps = [_ssh_remote_cmd(cmd, sudo=sudo)]
    if ctx is not None and getattr(ctx, "confirmer", None) is not None \
            and not getattr(ctx, "assume_confirmed", False):
        if not ctx.confirmer.require_confirm(f"{label} — wykonać?", "system_task",
                                             {"steps": steps, "goal": f"skajnet:{route}"}):
            return f"Wymaga potwierdzenia: {label}", route
    from ..tools.tasks import execute_steps
    res = execute_steps(ctx, f"skajnet:{route}", steps)
    return res.text, route


__all__ = ["intent", "handle"]