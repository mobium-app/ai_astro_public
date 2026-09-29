"""Wi-Fi ASTRO w 100% offline (NetworkManager / nmcli): skan, łączenie z literowanym hasłem,
rozłączanie, weryfikacja REALNEGO połączenia. Bez modelu i bez sieci.

Używane przez fast-path dispatch (głos) oraz przez `scripts/wifi.py` („na gotowo").
"""

import difflib
import re
import shutil
import subprocess
import time

from . import mirror
from .safety import normalize_command, normalize_facts


def available():
    return bool(shutil.which("nmcli"))


def _run(argv, timeout=40):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, errors="replace", timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, f"przekroczono limit {timeout}s"
    except Exception as e:
        return 1, str(e)


def _split_escaped(line):
    """nmcli -t: pola rozdzielone ':', a ':' w polu jest eskejpowane jako '\\:'."""
    out, cur, i = [], "", 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            cur += line[i + 1]
            i += 2
            continue
        if c == ":":
            out.append(cur)
            cur = ""
            i += 1
            continue
        cur += c
        i += 1
    out.append(cur)
    return out


def scan():
    """Lista {ssid, signal, security} (posortowana po sile)."""
    if not available():
        return []
    code, out = _run(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list",
                      "--rescan", "yes"], timeout=35)
    if code != 0 and not out:
        return []
    rows, seen = [], set()
    for line in out.splitlines():
        parts = _split_escaped(line)
        if len(parts) < 3:
            continue
        ssid = parts[0].strip()
        if not ssid or ssid in seen:
            continue
        seen.add(ssid)
        try:
            signal = int(parts[1].strip() or 0)
        except ValueError:
            signal = 0
        rows.append({"ssid": ssid, "signal": signal, "security": parts[2].strip()})
    rows.sort(key=lambda r: -r["signal"])
    return rows


def is_open(security):
    return (security or "").strip() in ("", "--")


# Ostatni skan (dla „połącz z siecią numer N"). Cache w pamięci procesu; kluczowy dla głosu,
# gdzie użytkownik słyszy numerowaną listę i potem mówi numer.
_LAST_SCAN = {"ts": 0.0, "rows": []}


def scan_numbered():
    """Skan + zapis do cache (numerowana lista od najsilniejszego sygnału)."""
    rows = scan()
    _LAST_SCAN["ts"] = time.time()
    _LAST_SCAN["rows"] = rows
    return rows


def last_scan(max_age=900):
    if time.time() - _LAST_SCAN["ts"] > max_age:
        return []
    return list(_LAST_SCAN["rows"])


def connect_by_index(n):
    """Zwraca (ssid, "") dla numeru z ostatniego skanu albo (None, komunikat)."""
    rows = last_scan()
    if not rows:
        rows = scan_numbered()
    if not rows:
        return None, "brak dostępnych sieci w zasięgu"
    try:
        n = int(n)
    except (TypeError, ValueError):
        return None, "nie rozpoznałam numeru sieci"
    if not (1 <= n <= len(rows)):
        return None, f"nie ma sieci o numerze {n} (dostępne 1-{len(rows)})"
    return rows[n - 1]["ssid"], ""


def scan_text():
    if not available():
        return "Brak narzędzia nmcli (NetworkManager) - nie mogę skanować sieci Wi-Fi."
    rows = scan_numbered()
    if not rows:
        return "brak dostępnych sieci w zasięgu"
    lines = ["Dostępne sieci Wi-Fi (od najsilniejszej):", "│"]
    for i, r in enumerate(rows, 1):
        arm = "└─" if i == len(rows) else "├─"
        sec = "otwarta" if is_open(r["security"]) else r["security"]
        lines.append(f"{arm} {i}. {r['ssid']}   ({r['signal']}%, {sec})")
    lines.append("Powiedz: połącz z siecią numer <N>.")
    text = "\n".join(lines)
    mirror.wall_write(text)
    return text


# Słowa-cyfry (STT często zapisuje „2" jako „dwa"): pozwalają dopasować „kapibara dwa"
# do SSID „Kapibara_2G" mimo separatorów i odmiennej pisowni.
_DIGIT_WORDS = {"zero": "0", "jeden": "1", "dwa": "2", "trzy": "3", "cztery": "4",
                "piec": "5", "szesc": "6", "siedem": "7", "osiem": "8", "dziewiec": "9",
                "dziesiec": "10"}


def _ssid_key(text):
    """Klucz SSID do dopasowania przybliżonego: bez separatorów, z cyframi słownymi."""
    low = normalize_facts(text or "").replace("_", " ").replace("-", " ")
    tokens = [_DIGIT_WORDS.get(t, t) for t in low.split()]
    return "".join(tokens)


def resolve(name):
    """Dopasowuje nazwę mówioną (może być częścią) do rzeczywistego SSID."""
    name = (name or "").strip().strip("\"'")
    if not name:
        return None
    rows = scan()
    if not rows:
        return None
    low = normalize_facts(name)
    exact = [r for r in rows if normalize_facts(r["ssid"]) == low]
    if exact:
        return exact[0]["ssid"]
    part = [r for r in rows if low and low in normalize_facts(r["ssid"])]
    if part:
        return max(part, key=lambda r: r["signal"])["ssid"]
    # Klucz znormalizowany (separatory + cyfry słowne) - odporny na zniekształcenia STT.
    keys = {_ssid_key(r["ssid"]): r for r in rows}
    key = _ssid_key(name)
    if key and key in keys:
        return keys[key]["ssid"]
    close = difflib.get_close_matches(key, list(keys), n=1, cutoff=0.72) if key else []
    if close:
        return keys[close[0]]["ssid"]
    close = difflib.get_close_matches(name, [r["ssid"] for r in rows], n=1, cutoff=0.6)
    return close[0] if close else None


def security_of(ssid):
    for r in scan():
        if r["ssid"] == ssid:
            return r["security"]
    return ""


def is_secured(ssid):
    return not is_open(security_of(ssid))


def active_ssid():
    code, out = _run(["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi", "list"], timeout=15)
    for line in out.splitlines():
        parts = _split_escaped(line)
        if len(parts) >= 2 and parts[0].strip() == "yes":
            return parts[1].strip()
    return ""


def _has_default_route():
    code, out = _run(["ip", "route", "show", "default"], timeout=5)
    return code == 0 and "default" in out


def verify(ssid, timeout=12):
    """REALNE połączenie: aktywne SSID zgodne i jest trasa domyślna."""
    for _ in range(max(1, timeout)):
        if active_ssid() == ssid and _has_default_route():
            return True
        time.sleep(1)
    return False


def _reason(out, password):
    low = (out or "").lower()
    if "secrets were required" in low or "psk" in low or "secret" in low or "password" in low:
        return "błędnego hasła"
    if "no network with ssid" in low or "not found" in low:
        return "brak sieci w zasięgu"
    if "timeout" in low or "timed out" in low:
        return "przekroczenia czasu połączenia"
    if "ip configuration" in low or "dhcp" in low or "could not be" in low:
        return "problemu z konfiguracją adresu IP"
    if "not authorized" in low or "permission" in low:
        return "braku uprawnień"
    return "nieznanego błędu"


def connect(ssid, password=None, timeout=60):
    """Łączy z siecią i weryfikuje realne połączenie. Zwraca (ok, komunikat)."""
    if not available():
        return False, "brak nmcli - nie mogę łączyć z Wi-Fi"
    cmd = ["nmcli", "dev", "wifi", "connect", ssid]
    if password:
        cmd += ["password", password]
    code, out = _run(["sudo", "-n"] + cmd, timeout=timeout)
    if code != 0:
        code, out = _run(cmd, timeout=timeout)
    if code == 0 and verify(ssid):
        return True, f"podłączyłem do sieci {ssid}"
    return False, (f"nie udało się uzyskać połączenia z siecią {ssid} "
                   f"z powodu {_reason(out, password)}")


def disconnect(name):
    """Rozłącza aktywne połączenie Wi-Fi pasujące do nazwy (może być częścią SSID)."""
    if not available():
        return False, "brak nmcli - nie mogę rozłączać Wi-Fi"
    name = (name or "").strip().strip("\"'")
    low = normalize_facts(name)
    code, out = _run(["nmcli", "-t", "-f", "NAME,TYPE,ACTIVE", "connection", "show"], timeout=15)
    active, all_wifi = [], []
    for line in out.splitlines():
        p = _split_escaped(line)
        if len(p) < 3 or not p[1].startswith("802-11-wireless"):
            continue
        all_wifi.append(p[0].strip())
        if p[2].strip() == "yes":
            active.append(p[0].strip())
    if not low and len(active) == 1:
        target = active[0]
    else:
        cand = [c for c in active if low and low in normalize_facts(c)]
        if not cand:
            cand = [c for c in all_wifi if low and low in normalize_facts(c)]
        target = max(cand, key=len) if cand else None
    if not target:
        return False, f"nie znalazłam połączenia z siecią {name or '(aktywne)'}"
    code, out = _run(["sudo", "-n", "nmcli", "connection", "down", target], timeout=30)
    if code != 0:
        code, out = _run(["nmcli", "connection", "down", target], timeout=30)
    if code == 0:
        return True, f"rozłączyłem z siecią {target}"
    return False, f"nie udało się rozłączyć z siecią {name}"


# --- rozpoznawanie intencji (kosmetyka składni) -----------------------------------------
_SCAN_RE = re.compile(
    r"(?:wyszukaj|zeskanuj|skanuj|szukaj|pokaz|wy[sś]wietl|sprawdz|jakie|dost[eę]pne|znajdz|lista)"
    r"[^.!?]{0,30}(?:sieci|siec|wifi|wi-fi|bezprzewodow)|\b(?:skan|lista)\s+(?:sieci|wifi|wi-fi)|"
    r"\bsieci\s+(?:wifi|wi-fi|bezprzewodowe)\b|\bjakie\s+sa\s+sieci\b")
_CONNECT_RE = re.compile(
    r"\b(?:podl[aą]cz|pol[aą]cz|przyl[aą]cz|we[zź]|l[aą]cz)\w*"
    r"[^.!?]{0,25}?(?:sie[cć]\w*|wifi|wi-fi)(?:\s+o\s+nazwie)?\s+(.+)$")
_DISCONNECT_RE = re.compile(
    r"\b(?:rozl[aą]cz|odl[aą]cz|wyl[aą]cz|wyjd[źz])\w*"
    r"[^.!?]{0,25}?(?:sie[cć]\w*|wifi|wi-fi)(?:\s+o\s+nazwie)?\s*(.*)$")
_PASSWORD_HINT_RE = re.compile(r"\b(?:haslo|has[łl]o|password|klucz)\b")
# Ratunek dla zniekształconego STT: czasownik łączenia zapisany fonetycznie + słowo sieci.
_NET_RE = re.compile(r"sie[cć]\w*|\bwifi\b|wi-?fi|bezprzewodow\w*")
_NET_TAIL_RE = re.compile(
    r"(?:sie[cć]\w*|wifi|wi-?fi|bezprzewodow\w*)(?:\s+o\s+nazwie)?\s+(.+)$")
_CONNECT_STEMS = ("polacz", "podlacz", "przylacz")


def _clean_name(raw):
    raw = (raw or "").strip().strip("\"'.,!?")
    raw = re.sub(r"^(?:o\s+nazwie|nazwa|zwana|zwany)\s+", "", raw)
    return raw.strip()


def _fuzzy_connect_verb(low):
    """True, gdy któryś token jest fonetycznie blisko „połącz/podłącz/przylącz" (błąd STT)."""
    for tok in re.findall(r"[a-z0-9]+", low or ""):
        if len(tok) < 4:
            continue
        for stem in _CONNECT_STEMS:
            if difflib.SequenceMatcher(None, tok, stem).ratio() >= 0.72:
                return True
    return False


def intent(text):
    """Zwraca {action, ...} albo None. Offline, bez modelu."""
    low = normalize_command(text or "")
    if not low:
        return None
    if _DISCONNECT_RE.search(low):
        m = _DISCONNECT_RE.search(low)
        return {"action": "disconnect", "name": _clean_name(m.group(1) if m.groups() else "")}
    m = _CONNECT_RE.search(low)
    if m:
        target = _clean_name(m.group(1))
        password = None
        hint = _PASSWORD_HINT_RE.search(target)
        if hint:
            password = target[hint.end():].strip()
            target = target[:hint.start()].strip()
        return {"action": "connect", "ssid": target, "password": password}
    if _SCAN_RE.search(low):
        return {"action": "scan"}
    if _NET_RE.search(low) and _fuzzy_connect_verb(low):
        m = _NET_TAIL_RE.search(low)
        if m:
            target = _clean_name(m.group(1))
            if target:
                return {"action": "connect", "ssid": target, "password": None}
    return None
