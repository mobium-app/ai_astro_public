"""Embedder przez lokalną Ollamę (nomic-embed-text) z bezpiecznym wyłącznikiem."""

import json
import time
import urllib.request


class OllamaEmbedder:
    def __init__(self, url, model, timeout=15, cooldown=60, max_fails=3):
        self.url = url.rstrip("/") + "/api/embeddings"
        self.model = model
        self.timeout = timeout
        self.cooldown = cooldown
        self.max_fails = max_fails
        self.fails = 0
        self.disabled_until = 0.0

    def __call__(self, text):
        if time.time() < self.disabled_until:
            return None
        payload = json.dumps({"model": self.model, "prompt": text or ""}).encode("utf-8")
        req = urllib.request.Request(self.url, data=payload,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                vec = json.loads(r.read().decode("utf-8")).get("embedding")
            self.fails = 0
            return vec
        except Exception:
            self.fails += 1
            if self.fails >= self.max_fails:
                self.disabled_until = time.time() + self.cooldown
                self.fails = 0
            return None
