"""Minimalny klient MCP (Model Context Protocol) — transport stdio, JSON-RPC 2.0.

Pozwala ASTRO podłączyć gotowe serwery MCP (Home Assistant, system plików, …) i wystawić
ich narzędzia jako narzędzia ASTRO. Bez zewnętrznych zależności (tylko stdlib).
"""

import json
import os
import select
import subprocess
import time

PROTOCOL_VERSION = "2024-11-05"


class MCPError(Exception):
    pass


class StdioMCPClient:
    def __init__(self, command, args=(), env=None, timeout=30, cwd=None):
        self.timeout = float(timeout)
        full_env = dict(os.environ)
        full_env.update(env or {})
        self.proc = subprocess.Popen(
            [command, *list(args or [])], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1, env=full_env, cwd=cwd)
        self._id = 0

    def _write(self, obj):
        self.proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def _read(self):
        ready, _, _ = select.select([self.proc.stdout], [], [], self.timeout)
        if not ready:
            raise MCPError("timeout odpowiedzi MCP")
        line = self.proc.stdout.readline()
        if not line:
            raise MCPError("serwer MCP zamknął strumień")
        try:
            return json.loads(line)
        except ValueError as e:
            raise MCPError(f"niepoprawny JSON MCP: {e}") from e

    def request(self, method, params=None):
        self._id += 1
        rid = self._id
        self._write({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            msg = self._read()
            if msg.get("id") == rid:
                if "error" in msg:
                    raise MCPError(str(msg.get("error")))
                return msg.get("result")
        raise MCPError(f"brak odpowiedzi na {method}")

    def notify(self, method, params=None):
        self._write({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def initialize(self):
        result = self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "astro", "version": "1.0"}})
        self.notify("notifications/initialized")
        return result

    def list_tools(self):
        result = self.request("tools/list", {}) or {}
        return result.get("tools", [])

    def call_tool(self, name, arguments=None):
        return self.request("tools/call", {"name": name, "arguments": arguments or {}})

    def close(self):
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=2)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


def content_text(result):
    """Wynik `tools/call` MCP -> tekst dla ASTRO."""
    if not isinstance(result, dict):
        return str(result)
    parts = []
    for item in result.get("content") or []:
        if isinstance(item, dict):
            if item.get("type") == "text":
                parts.append(item.get("text") or "")
            else:
                parts.append(json.dumps(item, ensure_ascii=False))
    text = "\n".join(p for p in parts if p)
    if not text:
        text = json.dumps({k: v for k, v in result.items() if k != "content"},
                          ensure_ascii=False)[:1000]
    return text
