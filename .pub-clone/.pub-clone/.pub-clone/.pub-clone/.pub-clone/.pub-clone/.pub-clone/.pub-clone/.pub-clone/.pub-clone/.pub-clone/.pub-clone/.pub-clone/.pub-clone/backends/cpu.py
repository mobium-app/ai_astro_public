"""Backend CPU: lokalna Ollama (domyślny runtime ASTRO)."""

import json
import urllib.error
import urllib.request

from .base import Backend, BackendResult


class CpuBackend(Backend):
    name = "cpu"
    capabilities = {"chat", "tools", "json", "plan"}

    def __init__(self, url, model, threads=3, keep_alive="24h", timeout=900, name="cpu"):
        self.name = name
        self.url = url.rstrip("/")
        self.model = model
        self.threads = threads
        self.keep_alive = keep_alive
        self.timeout = timeout

    def _post(self, path, payload, timeout=None):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.url + path, data=data,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def ready(self):
        try:
            req = urllib.request.Request(self.url + "/api/tags")
            with urllib.request.urlopen(req, timeout=3) as r:
                return r.status == 200
        except Exception:
            return False

    def run(self, messages, *, tools=None, fmt=None, max_tokens=400, temperature=0.2,
            on_token=None):
        payload = {
            "model": self.model,
            "stream": bool(on_token),
            "messages": messages,
            "keep_alive": self.keep_alive,
            "options": {"num_predict": max_tokens, "num_ctx": 4096,
                        "temperature": temperature, "num_thread": self.threads},
        }
        if tools:
            payload["tools"] = tools
        if fmt:
            payload["format"] = fmt
        if on_token:
            return self._run_stream(payload, on_token)
        try:
            out = self._post("/api/chat", payload)
        except urllib.error.URLError as e:
            raise RuntimeError(f"CPU/Ollama niedostępna: {e}")
        msg = out.get("message", {}) or {}
        return BackendResult(text=msg.get("content") or "", tool_calls=msg.get("tool_calls") or [])

    def _run_stream(self, payload, on_token):
        """Streamowanie NDJSON z Ollama `/api/chat` (stream=true).

        Deltki treści pchamy do `on_token`; składamy pełny tekst i (jeśli są) `tool_calls`
        z ostatnich chunków. Wyjątek `on_token` nigdy nie przerywa generacji."""
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.url + "/api/chat", data=data,
                                     headers={"Content-Type": "application/json"})
        parts, calls = [], []
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                for raw in r:
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        continue
                    msg = obj.get("message", {}) or {}
                    piece = msg.get("content") or ""
                    if piece:
                        parts.append(piece)
                        try:
                            on_token(piece)
                        except Exception:
                            pass
                    if msg.get("tool_calls"):
                        calls = msg.get("tool_calls")
                    if obj.get("done"):
                        break
        except urllib.error.URLError as e:
            raise RuntimeError(f"CPU/Ollama niedostępna: {e}")
        return BackendResult(text="".join(parts), tool_calls=calls)
