"""Trwały temperament ASTRO: JSON poza repo (600), atomowy zapis, odporny na brak/uszkodzenie."""

import json
import os
import tempfile
from pathlib import Path

from . import persona as P


class PersonaStore:
    def __init__(self, path=None):
        from .. import config
        self.path = Path(path or config.PERSONA_FILE)

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            return P.defaults()
        if isinstance(data, dict) and "traits" in data:
            data = data["traits"]
        return P.normalize(data)

    def save(self, traits):
        p = P.normalize(traits)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"schema_version": 1, "traits": p}, fh, ensure_ascii=False, indent=2)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
        return p

    def get(self):
        return self.load()

    def set_trait(self, trait, value):
        traits, ok = P.set_trait(self.load(), trait, value)
        if ok:
            self.save(traits)
        return traits, ok

    def adjust(self, trait, delta):
        if trait not in P.TRAITS:
            return self.load(), False
        traits = P.adjust(self.load(), trait, delta)
        self.save(traits)
        return traits, True

    def reset(self):
        return self.save(P.defaults())
