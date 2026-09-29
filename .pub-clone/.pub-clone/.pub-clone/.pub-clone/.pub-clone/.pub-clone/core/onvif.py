"""Minimalny klient ONVIF (SOAP 1.2 / HTTP) dla kamery sieciowej ASTRO.

Bez zależności zewnętrznych (tylko standardowa biblioteka) — ten sam plik działa w runtime
ASTRO na Pi oraz w podglądzie/sterowaniu na PC-Kali. Obsługuje PTZ: ruch ciągły (ContinuousMove),
Stop, powrót do pozycji domowej (GotoHomePosition) i odczyt pozycji (GetStatus).

Kamera ASTRO (2026-09-28) to moduł sieciowy z ONVIF na porcie 8899 — bez logowania, ale
obsługa WS-Security (UsernameToken/PasswordDigest) jest przygotowana, gdyby włączono auth.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import time
import urllib.error
import urllib.request
from xml.sax.saxutils import escape

PTZ_NS = "http://www.onvif.org/ver20/ptz/wsdl"
TT_NS = "http://www.onvif.org/ver10/schema"
SOAP_NS = "http://www.w3.org/2003/05/soap-envelope"
WSSE_NS = ("http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-"
           "wssecurity-secext-1.0.xsd")
WSU_NS = ("http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-"
          "wssecurity-utility-1.0.xsd")
PASSWORD_DIGEST = ("http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-"
                   "username-token-profile-1.0#PasswordDigest")
NONCE_ENCODING = ("http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-"
                  "message-security-1.0#Base64Binary")
VELOCITY_SPACE = "http://www.onvif.org/ver10/tptz/PanTiltSpaces/VelocityGenericSpace"


class OnvifError(RuntimeError):
    """Błąd komunikacji/odpowiedzi ONVIF."""


# Kierunki -> wektor (x = pan: +prawo/-lewo, y = tilt: +góra/-dół).
DIRECTIONS = {
    "left": (-1.0, 0.0),
    "right": (1.0, 0.0),
    "up": (0.0, 1.0),
    "down": (0.0, -1.0),
    "upleft": (-0.7, 0.7),
    "upright": (0.7, 0.7),
    "downleft": (-0.7, -0.7),
    "downright": (0.7, -0.7),
    "center": (0.0, 0.0),
}

# Normalizacja aliasów (PL/EN, z myślnikami i bez).
_ALIASES = {
    "lewo": "left", "wlewo": "left", "lewa": "left", "west": "left",
    "prawo": "right", "wprawo": "right", "prawa": "right", "east": "right",
    "gora": "up", "gore": "up", "wgore": "up", "góra": "up", "górę": "up",
    "dol": "down", "dol": "down", "wdol": "down", "dół": "down",
    "gorealewo": "upleft", "gore-lewo": "upleft", "gora-lewo": "upleft",
    "goreprawo": "upright", "gore-prawo": "upright",
    "dollewo": "downleft", "dol-lewo": "downleft",
    "dolprawo": "downright", "dol-prawo": "downright",
    "srodek": "center", "środek": "center", "center": "center", "neutral": "center",
}


def resolve_direction(direction):
    """Zwraca kanoniczny kierunek z DIRECTIONS albo podnosi ValueError."""
    key = str(direction or "").strip().lower().replace(" ", "").replace("_", "-")
    key = _ALIASES.get(key, key)
    if key in DIRECTIONS:
        return key
    raise ValueError(f"nieznany kierunek: {direction!r}")


def direction_xy(direction, speed=0.6):
    """Wektor prędkości (x, y) dla kierunku, przeskalowany przez `speed`."""
    x, y = DIRECTIONS[resolve_direction(direction)]
    s = max(0.0, min(1.0, float(speed)))
    return round(x * s, 3), round(y * s, 3)


def _wsse_header(user, password, nonce=None, created=None):
    if not user:
        return ""
    nonce = nonce or os.urandom(16)
    created = created or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    digest = base64.b64encode(
        hashlib.sha1(nonce + created.encode() + password.encode()).digest()).decode()
    return (f'<s:Header><wsse:Security xmlns:wsse="{WSSE_NS}" xmlns:wsu="{WSU_NS}">'
            f'<wsse:UsernameToken>'
            f'<wsse:Username>{escape(user)}</wsse:Username>'
            f'<wsse:Password Type="{PASSWORD_DIGEST}">{digest}</wsse:Password>'
            f'<wsse:Nonce EncodingType="{NONCE_ENCODING}">'
            f'{base64.b64encode(nonce).decode()}</wsse:Nonce>'
            f'<wsu:Created>{created}</wsu:Created>'
            f'</wsse:UsernameToken></wsse:Security></s:Header>')


def envelope(body, user="", password=""):
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            f'<s:Envelope xmlns:s="{SOAP_NS}" xmlns:tptz="{PTZ_NS}" xmlns:tt="{TT_NS}">'
            f'{_wsse_header(user, password)}'
            f'<s:Body>{body}</s:Body></s:Envelope>')


def soap(url, body, user="", password="", timeout=6.0):
    """Wysyła SOAP i zwraca treść odpowiedzi. Podnosi OnvifError przy błędzie."""
    data = envelope(body, user, password).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": 'application/soap+xml; charset="utf-8"'},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        payload = e.read().decode("utf-8", "replace")
        raise OnvifError(f"HTTP {e.code}: {payload[:300]}") from e
    except Exception as e:  # URLError/timeout
        raise OnvifError(f"{type(e).__name__}: {e}") from e


def _is_fault(reply):
    return ("Fault" in reply and "Body" in reply) or "NotAuthorized" in reply


# --- budowa żądań ---------------------------------------------------------------------------
def move_body(profile, x, y, zoom=None):
    zoom_el = ""
    if zoom is not None:
        zoom_el = (f'<tptz:Zoom><tt:Zoom x="{float(zoom):.3f}" '
                   f'space="{VELOCITY_SPACE}"/></tptz:Zoom>')
    return (f'<tptz:ContinuousMove>'
            f'<tptz:ProfileToken>{escape(profile)}</tptz:ProfileToken>'
            f'<tptz:Velocity>'
            f'<tt:PanTilt x="{float(x):.3f}" y="{float(y):.3f}" space="{VELOCITY_SPACE}"/>'
            f'{zoom_el}</tptz:Velocity></tptz:ContinuousMove>')


def stop_body(profile):
    return (f'<tptz:Stop><tptz:ProfileToken>{escape(profile)}</tptz:ProfileToken>'
            f'<tptz:PanTilt>true</tptz:PanTilt><tptz:Zoom>false</tptz:Zoom></tptz:Stop>')


def status_body(profile):
    return (f'<tptz:GetStatus><tptz:ProfileToken>{escape(profile)}</tptz:ProfileToken>'
            f'</tptz:GetStatus>')


def home_body(profile):
    return (f'<tptz:GotoHomePosition>'
            f'<tptz:ProfileToken>{escape(profile)}</tptz:ProfileToken>'
            f'</tptz:GotoHomePosition>')


def set_home_body(profile):
    return (f'<tptz:SetHomePosition>'
            f'<tptz:ProfileToken>{escape(profile)}</tptz:ProfileToken>'
            f'</tptz:SetHomePosition>')


# --- operacje -------------------------------------------------------------------------------
def move(ptz_url, profile, x, y, zoom=None, user="", password="", timeout=6.0):
    reply = soap(ptz_url, move_body(profile, x, y, zoom), user, password, timeout)
    if _is_fault(reply):
        raise OnvifError(f"ContinuousMove: {reply[:300]}")
    return reply


def stop(ptz_url, profile, user="", password="", timeout=6.0):
    reply = soap(ptz_url, stop_body(profile), user, password, timeout)
    if _is_fault(reply):
        raise OnvifError(f"Stop: {reply[:300]}")
    return reply


def home(ptz_url, profile, user="", password="", timeout=6.0):
    reply = soap(ptz_url, home_body(profile), user, password, timeout)
    if _is_fault(reply):
        raise OnvifError(f"GotoHomePosition: {reply[:300]}")
    return reply


def set_home(ptz_url, profile, user="", password="", timeout=6.0):
    reply = soap(ptz_url, set_home_body(profile), user, password, timeout)
    if _is_fault(reply):
        raise OnvifError(f"SetHomePosition: {reply[:300]}")
    return reply


def status(ptz_url, profile, user="", password="", timeout=6.0):
    """Zwraca dict {"x": float|None, "y": float|None, "moving": bool}. None gdy brak danych."""
    reply = soap(ptz_url, status_body(profile), user, password, timeout)
    if _is_fault(reply):
        raise OnvifError(f"GetStatus: {reply[:300]}")
    out = {"x": None, "y": None, "moving": ("Moving" in reply or ">MOVING<" in reply
                                            or "moving" in reply)}
    m = re.search(r'<tt:PanTilt\s+x="([-\d.]+)"\s+y="([-\d.]+)"', reply)
    if m:
        try:
            out["x"], out["y"] = float(m.group(1)), float(m.group(2))
        except ValueError:
            pass
    return out


def nudge(ptz_url, profile, direction, ms=600, speed=0.6, user="", password="",
          timeout=6.0, sleeper=time.sleep):
    """Ruch „o krok": ContinuousMove -> sen(ms) -> Stop. Zwraca (x, y)."""
    x, y = direction_xy(direction, speed)
    if direction == "center" or (x == 0.0 and y == 0.0):
        stop(ptz_url, profile, user, password, timeout)
        return 0.0, 0.0
    move(ptz_url, profile, x, y, None, user, password, timeout)
    try:
        sleeper(max(0, int(ms)) / 1000.0)
    finally:
        stop(ptz_url, profile, user, password, timeout)
    return x, y
