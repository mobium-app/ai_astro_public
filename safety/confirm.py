"""Potwierdzenia akcji (bramka 'gated'). Bezpieczna, testowalna, bez sprzętu."""

import difflib
import time
import unicodedata

from .commands import CANCEL_RE, CONFIRM_RE, CONFIRM_SHORT_RE, CONFIRM_WORDS


def _plain(text):
    """Małe litery bez diakrytyków (do porównań odpornych na STT)."""
    return "".join(c for c in unicodedata.normalize("NFKD", str(text or "").lower())
                   if not unicodedata.combining(c))


_CONFIRM_FUZZY = tuple(dict.fromkeys(
    [_plain(w) for w in CONFIRM_WORDS] + ["potwierdzam", "zatwierdzam"]))


def is_confirm_like(text):
    """True, gdy krótka wypowiedź to potwierdzenie (także zniekształcone przez STT).

    Whisper gubi „d": „Potwierzam" zamiast „potwierdzam" - wcześniej taka odpowiedź
    przepadała (pending był czyszczony, a tekst szedł do modelu).
    """
    toks = [t.strip(" .,!?") for t in _plain(text).split()]
    toks = [t for t in toks if t]
    if not toks or len(toks) > 4:
        return False
    for t in toks:
        for w in _CONFIRM_FUZZY:
            if t == w:
                return True
            if len(t) >= 5 and difflib.SequenceMatcher(None, t, w).ratio() >= 0.8:
                return True
    return False


def is_confirmation(text):
    """Pełne rozpoznanie zgody: krótkie „tak/ok/no/jasne" (cała wypowiedź) + dłuższe formy
    + zniekształcenia STT. To właściwa bramka dla głosowego „Mam to wykonać?"."""
    return bool(CONFIRM_SHORT_RE.match(text or "") or CONFIRM_RE.search(text or "")
                or is_confirm_like(text))


class Confirmer:
    """Zbiera zgodę na akcję. `auto=True` (testy/--yes) potwierdza od razu; inaczej zapisuje
    oczekującą akcję i czeka na `answer()` z tekstem użytkownika."""

    def __init__(self, auto=False, ttl=300, policy=None):
        self.auto = bool(auto)
        self.ttl = ttl
        self.policy = policy
        self.pending = None

    def require_confirm(self, announce, kind, payload=None):
        if self.policy is not None:
            ok = bool(self.policy(announce, kind, payload))
            if ok:
                return True
        if self.auto:
            return True
        self.pending = {"announce": announce, "kind": kind, "payload": payload,
                        "ts": time.time()}
        return False

    def _expired(self):
        return (self.pending is not None
                and (time.time() - self.pending.get("ts", 0)) > self.ttl)

    def answer(self, text):
        """Obsługuje odpowiedź na oczekującą akcję. Zwraca (handled, ok, pending)."""
        if self.pending is None:
            return False, False, None
        if self._expired():
            self.pending = None
            return True, False, None
        pending = self.pending
        if is_confirmation(text):
            self.pending = None
            return True, True, pending
        if CANCEL_RE.search(text or ""):
            self.pending = None
            return True, False, pending
        return False, False, None

    def clear(self):
        self.pending = None
