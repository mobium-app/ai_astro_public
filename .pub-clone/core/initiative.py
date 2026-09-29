"""Proaktywność ASTRO (M4): inicjatywa — powitanie, spontaniczny humor, tryb cichy.

Deterministyczna warstwa decydująca, CZY i CO ASTRO może powiedzieć z własnej inicjatywy.
Dziś ASTRO odzywa się tylko w reakcji na wake+komendę (`audio/loop.py`); ten moduł daje
pierwszą warstwę inicjatywy (bez modelu i sieci):

- **Powitanie na wejście** (`greeting`) — kontekstowe: pora dnia, imię, nastrój; z cooldownem
  i poszanowaniem ciszy nocnej.
- **Spontaniczny humor** (`spontaneous_joke`) — tylko gdy `humor.can_joke` pozwala (nastrój,
  temperament, kontekst, cooldown w `HumorStore`).
- **Tryb cichy** (`set_quiet`/`is_quiet`) — „nie odzywaj się bez pytania" wyłącza inicjatywę.
- **Zdarzenia** (`remark`) — zaczepy pod przyszłe triggery (obecność/twarz, alerty systemu).

Polityka: cooldown globalny, limit na godzinę, cisza nocna, twarde wyłączenie. Stan trwały w
`runtime/initiative.json` (poza repo). Wszystko testowalne (wstrzykiwane `now`, ścieżka stanu).
"""

import json
import os
import random
import re
import time

from .. import config
from ..persona import current as current_persona
from ..persona import humor as persona_humor
from ..safety import normalize_facts

# Powitania wg pory dnia (baza + krótki ogon).
_GREETING = {
    "morning": ("Dzień dobry", "Zaczynam dzień gotowa do pracy"),
    "day": ("Dzień dobry", "Słucham, czego potrzebujesz"),
    "evening": ("Dobry wieczór", "W czym mogę pomóc"),
    "night": ("Dobra noc", "Nie śpię, więc pytaj śmiało"),
}
# Zaczepy zdarzeniowe (pod przyszłe triggery: kamera/obecność, alerty systemu).
_REMARKS = {
    "idle": "Jestem, gdybyś czegoś potrzebował.",
    "return": "Widzę, że jesteś. W czym pomóc?",
    "task_done": "Gotowe. Coś jeszcze?",
    "alert": "Uwaga, coś wymaga Twojej decyzji.",
}

_QUIET_ON_RE = re.compile(
    r"\b(?:tryb\s+cichy|nie\s+odzywaj\s+sie(?:\s+bez\s+pytania)?|badz\s+cicho|nie\s+mow\s+nic|"
    r"wy[lł]acz\s+inicjatyw\w*|zamilcz|cisza)\b")
_QUIET_OFF_RE = re.compile(
    r"\b(?:wroc\s+do\s+rozmowy|mozesz\s+sie\s+odzywac|odzywaj\s+sie|wlacz\s+inicjatyw\w*|"
    r"koniec\s+trybu\s+cichego)\b")


def _time_bucket(hour):
    if 5 <= hour < 11:
        return "morning"
    if 11 <= hour < 18:
        return "day"
    if 18 <= hour < 22:
        return "evening"
    return "night"


def _profile_name(memory):
    try:
        store = getattr(memory, "profiles", None)
        prof = store.get() if store is not None else {}
        for key in ("name", "imie", "imię", "first_name"):
            val = (prof or {}).get(key)
            if val:
                return str(val).strip().split()[0]
    except Exception:
        pass
    return ""


class Initiative:
    def __init__(self, state_path=None, enabled=None, quiet=None, rng=None):
        self.path = state_path or getattr(
            config, "INITIATIVE_STATE_FILE", os.path.join(str(config.RUNTIME_DIR),
                                                          "initiative.json"))
        self.enabled = getattr(config, "INITIATIVE_ENABLED", True) if enabled is None else bool(enabled)
        self.rng = rng or random
        self._state = self._load()
        if quiet is not None:
            self._state["quiet"] = bool(quiet)
            self._save()

    # --- stan trwały ---------------------------------------------------------------
    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                d = json.load(fh) or {}
            return {"quiet": bool(d.get("quiet", False)),
                    "last_greet": float(d.get("last_greet") or 0),
                    "last_spoke": float(d.get("last_spoke") or 0),
                    "spoke_times": [float(x) for x in (d.get("spoke_times") or [])][-50:]}
        except (OSError, ValueError):
            return {"quiet": False, "last_greet": 0.0, "last_spoke": 0.0, "spoke_times": []}

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(self._state, fh)
        except OSError:
            pass

    # --- tryb cichy ----------------------------------------------------------------
    def is_quiet(self):
        return bool(self._state.get("quiet"))

    def set_quiet(self, on):
        self._state["quiet"] = bool(on)
        self._save()
        return self.is_quiet()

    # --- polityka ------------------------------------------------------------------
    def _quiet_hours(self, now):
        start = int(getattr(config, "INITIATIVE_QUIET_START", 22))
        end = int(getattr(config, "INITIATIVE_QUIET_END", 7))
        if start == end:
            return False
        hour = time.localtime(now).tm_hour
        return (hour >= start or hour < end) if start > end else (start <= hour < end)

    def can_speak(self, kind="any", now=None):
        now = time.time() if now is None else float(now)
        if not self.enabled or self.is_quiet():
            return False
        # Cisza nocna dotyczy tylko inicjatyw NIEWYWOŁANYCH (idle/alert/obecność);
        # powitanie po wake jest reakcją na użytkownika, więc nie blokujemy go nocą.
        if kind in ("idle", "return", "task_done", "alert") and self._quiet_hours(now):
            return False
        if kind == "greeting":
            if now - self._state["last_greet"] < float(
                    getattr(config, "INITIATIVE_GREETING_COOLDOWN", 21600)):
                return False
        if now - self._state["last_spoke"] < float(
                getattr(config, "INITIATIVE_COOLDOWN", 600)):
            return False
        recent = [t for t in self._state["spoke_times"] if now - t < 3600]
        if len(recent) >= int(getattr(config, "INITIATIVE_MAX_PER_HOUR", 6)):
            return False
        return True

    def _note(self, now, kind):
        self._state["last_spoke"] = now
        self._state["spoke_times"] = (self._state["spoke_times"] + [now])[-50:]
        if kind == "greeting":
            self._state["last_greet"] = now
        self._save()

    # --- treści --------------------------------------------------------------------
    def greeting(self, memory=None, now=None, name=""):
        """Kontekstowe powitanie albo None (cooldown/cisza/tryb cichy)."""
        now = time.time() if now is None else float(now)
        if not self.can_speak("greeting", now):
            return None
        base, tail = _GREETING[_time_bucket(time.localtime(now).tm_hour)]
        who = name or _profile_name(memory)
        mood = ""
        try:
            store = getattr(memory, "affect", None) if memory is not None else None
            if store is not None:
                label, _guidance = store.load().describe()
                if label in ("zmartwiona", "zmęczona"):
                    mood = " Wyglądasz na zmęczonego — zrobię, co mogę, żeby odciążyć."
                elif label in ("radosna", "zadowolona"):
                    mood = " Dobrze Cię widzieć."
        except Exception:
            pass
        text = f"{base}{', ' + who if who else ''}. {tail}.{mood}"
        # Spontaniczne zbieranie kontekstu: JEDNO krótkie pytanie o brakujące pole profilu
        # (nie długi wywiad); respektuje ciszę nocną i cooldown powitań.
        ask = self._profile_prompt(memory, now)
        if ask:
            text = text.rstrip() + " " + ask
        self._note(now, "greeting")
        return text

    def _profile_prompt(self, memory, now):
        """Krótkie, brakujące pole profilu do spontanicznego dopytania (albo "")."""
        if memory is None or not getattr(config, "INITIATIVE_PROFILE_ASK", True):
            return ""
        if self._quiet_hours(now):
            return ""
        try:
            store = getattr(memory, "profiles", None)
            prof = (store.get() if store is not None else {}) or {}
        except Exception:
            return ""
        try:
            from ..user import intake
        except Exception:
            return ""
        for key, q, _hint in intake.QUESTIONS:
            if not prof.get(key):
                return q
        return ""

    def spontaneous_joke(self, memory=None, text="", now=None):
        """Spontaniczny żart albo None (reguły humoru + cooldown inicjatywy)."""
        now = time.time() if now is None else float(now)
        if not self.enabled or not getattr(config, "INITIATIVE_HUMOR", True):
            return None
        if not self.can_speak("joke", now):
            return None
        store = getattr(memory, "humor", None) if memory is not None else None
        aff = None
        try:
            a = getattr(memory, "affect", None) if memory is not None else None
            aff = a.load() if a is not None else None
        except Exception:
            aff = None
        if not persona_humor.can_joke(current_persona(), aff, text, store=store, now=now):
            return None
        avoid = store.recent_ids() if store is not None else None
        joke = persona_humor.pick(avoid=avoid, rng=self.rng)
        if store is not None:
            store.mark(joke["id"], now=now)
        self._note(now, "joke")
        return joke["text"]

    def remark(self, event, now=None):
        """Krótki zaczep na zdarzenie (idle/return/task_done/alert) albo None."""
        now = time.time() if now is None else float(now)
        if event not in _REMARKS or not self.can_speak(event, now):
            return None
        self._note(now, event)
        return _REMARKS[event]

    def event(self, text, kind="alert", now=None):
        """Zdarzenie z własną treścią (np. wizja: „widzę nieznaną osobę").

        Respektuje politykę inicjatywy (tryb cichy, cisza nocna, cooldown, limit/h).
        Zwraca tekst do wypowiedzenia albo None (gdy nie wolno).
        """
        now = time.time() if now is None else float(now)
        if not text or not self.can_speak(kind, now):
            return None
        self._note(now, kind)
        return text


def handle_command(text, agent=None):
    """Deterministyczna obsługa trybu cichego (bez modelu). Zwraca (reply, route) albo None."""
    low = normalize_facts(text or "")
    if not low:
        return None
    memory = getattr(agent, "memory", None)
    init = Initiative()
    if _QUIET_ON_RE.search(low):
        init.set_quiet(True)
        return "Dobrze, przechodzę w tryb cichy. Odezwę się tylko, gdy mnie zapytasz.", "initiative-quiet"
    if _QUIET_OFF_RE.search(low):
        init.set_quiet(False)
        return "Wracam do rozmowy. Chętnie się odezwę.", "initiative-loud"
    return None


__all__ = ["Initiative", "handle_command"]
