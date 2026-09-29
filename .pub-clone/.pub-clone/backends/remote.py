"""Backend zdalny (opt-in): zgodny z OpenAI /chat/completions.

Domyślnie WYŁĄCZONY. Rejestrowany tylko przy ASTRO_REMOTE=1 i podanym URL. Nie jest
wymagany do runtime; służy jako świadomie włączone wsparcie (np. świeża wiedza).
"""

import json
import urllib.error
import urllib.request

from .base import Backend, BackendResult


class RemoteBackend(Backend):
    name = "remote"
    capabilities = {"chat", "tools", "json", "plan", "fresh"}

    def __init__(self, url, model, key="", timeout=120):
        self.url = (url or "").rstrip("/")
        self.model = model or ""
        self.key = key or ""
        self.timeout = timeout

    def endpoint(self):
        u = self.url
        if not u:
            return ""
        if u.endswith("/chat/completions"):
            return u
        if u.endswith(("/v1", "/api/v1", "/v1beta", "/openai/v1")):
            return u + "/chat/completions"
        return u + "/v1/chat/completions"

    def ready(self):
        return bool(self.url and self.model)

    def run(self, messages, *, tools=None, fmt=None, max_tokens=400, temperature=0.2,
            on_token=None):
        if not self.ready():
            raise RuntimeError("remote backend nieaktywny (brak URL/modelu)")
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
        if fmt == "json":
            payload["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json", "User-Agent": "ASTRO/1.0"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        req = urllib.request.Request(self.endpoint(), data=json.dumps(payload).encode("utf-8"),
                                     headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"remote HTTP {e.code}: {e.read()[:200]!r}")
        except Exception as e:
            raise RuntimeError(f"remote błąd: {e}")
        choices = data.get("choices") or []
        msg = (choices[0].get("message") if choices else {}) or {}
        return BackendResult(text=msg.get("content") or "", tool_calls=msg.get("tool_calls") or [])
