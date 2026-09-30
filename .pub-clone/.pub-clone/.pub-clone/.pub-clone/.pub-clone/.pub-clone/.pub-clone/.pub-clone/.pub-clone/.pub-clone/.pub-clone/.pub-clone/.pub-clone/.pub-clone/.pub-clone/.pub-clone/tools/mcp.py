"""MCP: rejestracja narzędzi serwerów MCP jako narzędzi ASTRO.

Konfiguracja `ASTRO_MCP_CONFIG` (domyślnie `~/.astro-mcp.json`):
    {"servers": [
      {"name": "ha", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-home-assistant"],
       "read_only": true, "env": {"HA_URL": "...", "HA_TOKEN": "..."}}
    ]}

Serwery startują leniwie przy `ensure_mcp()` (start agenta), nie przy imporcie. Narzędzia
mutujące (domyślnie wszystkie poza `read_only`) rejestrujemy jako `gated` — wymagają
potwierdzenia, więc MCP nie omija warstwy bezpieczeństwa ASTRO.
"""

import json
import os
import re

from .. import config
from .registry import ToolResult

_CLIENTS = []


def _load_config(path=None):
    path = path or config.MCP_CONFIG
    if not path or not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return []
    if isinstance(data, dict):
        data = data.get("servers") or []
    return [s for s in data if isinstance(s, dict) and s.get("command")]


def _safe(name):
    return re.sub(r"[^a-zA-Z0-9_]+", "_", str(name or "")).strip("_").lower() or "srv"


def register_mcp_tools(registry_obj, path=None):
    """Startuje serwery MCP i rejestruje ich narzędzia. Zwraca listę nazw ASTRO."""
    from ..mcp_client import StdioMCPClient, content_text

    registered = []
    for server in _load_config(path):
        try:
            client = StdioMCPClient(server["command"], server.get("args") or [],
                                    env=server.get("env"), timeout=config.MCP_TIMEOUT,
                                    cwd=server.get("cwd"))
            client.initialize()
            tools = client.list_tools()
        except Exception:
            try:
                client.close()
            except Exception:
                pass
            continue
        _CLIENTS.append(client)
        label = _safe(server.get("name") or os.path.basename(server["command"]))
        read_only = bool(server.get("read_only"))
        for spec in tools:
            tname = spec.get("name")
            if not tname:
                continue
            astro_name = f"mcp_{label}_{_safe(tname)}"
            if astro_name in registry_obj.names():
                continue
            description = (spec.get("description") or f"MCP {label}: {tname}")[:300]
            parameters = spec.get("inputSchema") or {"type": "object", "properties": {}}
            scopes = {"read"} if read_only else {"gated"}

            def make(cl=client, remote=tname):
                def call(ctx=None, **kwargs):
                    try:
                        result = cl.call_tool(remote, kwargs or {})
                    except Exception as e:
                        return ToolResult(f"MCP {remote}: błąd {e}", ok=False)
                    ok = not (isinstance(result, dict) and result.get("isError"))
                    return ToolResult(content_text(result), ok=ok)
                return call

            registry_obj.register(astro_name, description, parameters, make(), scopes,
                                  confirm_text=f"Wywołać narzędzie MCP {astro_name}?")
            registered.append(astro_name)
    return registered


def ensure_mcp(registry_obj):
    """Rejestruje narzędzia MCP, gdy włączone (`ASTRO_MCP=1`) albo gdy istnieje plik konfiguracji."""
    if not config.MCP_ENABLED and not os.path.isfile(config.MCP_CONFIG):
        return []
    return register_mcp_tools(registry_obj)


def close_all():
    for client in list(_CLIENTS):
        try:
            client.close()
        except Exception:
            pass
    _CLIENTS.clear()
