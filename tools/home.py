"""Home Assistant / MQTT: sterowanie domem przez whitelistę encji (z potwierdzeniem).

Konfiguracja `ASTRO_HA_CONFIG` (domyślnie `~/.astro-ha.json`):
    {"ha_url": "http://homeassistant.local:8123", "token": "<długotrwały token>",
     "entities": {"salon": "light.salon", "temperatura": "sensor.temp_salon"},
     "mqtt": {"host": "127.0.0.1", "port": 1883, "topic": "astro/set"}}

Bezpieczeństwo: wyłącznie encje z whitelisty; żadnych dowolnych komend; `home_command` jest
`gated` (głosowe „potwierdzam"). MQTT (paho) jest opcjonalne — gdy brak, używamy REST.
"""

import json
import os
import urllib.parse
import urllib.request

from .. import config
from .registry import ToolResult, tool

UA = "ASTRO/1.0 (+home; Raspberry Pi)"
_ON = {"on", "wlacz", "włącz", "turn_on", "zaświeć", "zaswiec", "otwórz", "otworz"}
_OFF = {"off", "wylacz", "wyłącz", "turn_off", "zgaś", "zgas", "zamknij"}


def load_ha(path=None):
    path = path or config.HA_CONFIG
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return None
    if not data.get("ha_url") or not data.get("token"):
        return None
    return data


def _entity(cfg, name):
    key = (name or "").strip().lower()
    entities = {str(k).lower(): v for k, v in (cfg.get("entities") or {}).items()}
    if key in entities:
        return entities[key]
    if key in entities.values():
        return key
    return None


def _ha_api(cfg, path, method="GET", data=None, timeout=None):
    url = cfg["ha_url"].rstrip("/") + path
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": f"Bearer {cfg['token']}", "Content-Type": "application/json",
        "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout or config.HA_TIMEOUT) as r:
        raw = r.read().decode("utf-8", "replace")
    return json.loads(raw) if raw else {}


def _mqtt_publish(cfg, payload):
    mqtt = cfg.get("mqtt") or {}
    if not mqtt.get("host"):
        return False
    try:
        import paho.mqtt.publish as publish
    except Exception:
        return False
    try:
        publish.single(mqtt.get("topic", "astro/set"), payload=json.dumps(payload),
                       hostname=mqtt["host"], port=int(mqtt.get("port", 1883)),
                       auth=({"username": mqtt["username"], "password": mqtt.get("password", "")}
                             if mqtt.get("username") else None))
        return True
    except Exception:
        return False


def _status_text(cfg, entity_id):
    state = _ha_api(cfg, f"/api/states/{urllib.parse.quote(entity_id)}")
    return f"{entity_id}: {state.get('state')}"

def register():
    @tool("home_status",
          "Stan urządzenia domowego (Home Assistant) z whitelisty, albo lista dostępnych.",
          {"type": "object", "properties": {"entity": {"type": "string"}}}, scopes=("read",))
    def home_status(ctx, entity=""):
        cfg = load_ha()
        if cfg is None:
            return ToolResult("Home Assistant nie jest skonfigurowany (~/.astro-ha.json).", ok=False)
        if not entity:
            keys = ", ".join(f"{k} -> {v}" for k, v in (cfg.get("entities") or {}).items())
            return ToolResult(f"Dostępne urządzenia: {keys or '(brak whitelisty)'}")
        entity_id = _entity(cfg, entity)
        if not entity_id:
            return ToolResult(f"encja spoza whitelisty: {entity}", ok=False)
        try:
            return ToolResult(_status_text(cfg, entity_id))
        except Exception as e:
            return ToolResult(f"błąd Home Assistant: {e}", ok=False)

    @tool("home_command",
          "Steruje urządzeniem domowym (Home Assistant) z whitelisty: on/off/toggle/status.",
          {"type": "object",
           "properties": {"entity": {"type": "string"},
                          "action": {"type": "string", "enum": ["on", "off", "toggle", "status"]}},
           "required": ["entity", "action"]},
          scopes=("gated",), confirm_text="Sterowanie urządzeniem domowym")
    def home_command(ctx, entity, action):
        cfg = load_ha()
        if cfg is None:
            return ToolResult("Home Assistant nie jest skonfigurowany (~/.astro-ha.json).", ok=False)
        entity_id = _entity(cfg, entity)
        if not entity_id:
            return ToolResult(f"encja spoza whitelisty: {entity}", ok=False)
        act = (action or "").strip().lower()
        if act in _ON:
            service = "turn_on"
        elif act in _OFF:
            service = "turn_off"
        elif act == "toggle":
            service = "toggle"
        elif act == "status":
            try:
                return ToolResult(_status_text(cfg, entity_id))
            except Exception as e:
                return ToolResult(f"błąd Home Assistant: {e}", ok=False)
        else:
            return ToolResult(f"nieznana akcja: {action}", ok=False)
        domain = entity_id.split(".", 1)[0]
        try:
            _ha_api(cfg, f"/api/services/{domain}/{service}", method="POST",
                    data={"entity_id": entity_id})
        except Exception as e:
            _mqtt_publish(cfg, {"entity_id": entity_id, "service": service})
            return ToolResult(f"REST zawiódł ({e}); wysłano przez MQTT (jeśli skonfigurowane).",
                              ok=True)
        return ToolResult(f"{entity_id}: {service}")
