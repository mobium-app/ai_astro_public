"""Obecność użytkownika (M5): kamera/twarz jako trigger inicjatywy — szkielet + polityka.

Docelowo: kamera + detekcja twarzy daje sygnał „ktoś przyszedł/odszedł", a `initiative`
reaguje powitaniem („widzę, że jesteś"). Dziś sprzętu brak, więc moduł jest **gotowym,
testowalnym interfejsem**: detektor jest wstrzykiwany (domyślnie: obecność urządzenia
`/dev/video*`), a `Presence` zamienia stan na zdarzenia `enter`/`leave` z histerezą.

Świadomie NIE wpięty jeszcze w pętlę głosową: na WM8960 (pół-duplex) mówienie z osobnego
wątku w trakcie nasłuchu mogłoby zagłuszyć mikrofon. Wpięcie nastąpi po dołożeniu kamery i
zdecydowaniu o prywatności (patrz `docs/PLAN_DOSKONALENIA.md`, M5).

Prywatność: przetwarzanie lokalne, brak zapisu obrazu bez zgody, `ASTRO_PRESENCE=0` wyłącza.
"""

import glob

from .. import config


def camera_present():
    """Domyślny detektor: czy jest jakiekolwiek urządzenie kamery (v4l2)."""
    return bool(glob.glob("/dev/video*"))


class Presence:
    def __init__(self, detector=None, enabled=None):
        self.detector = detector or camera_present
        self.enabled = getattr(config, "PRESENCE_ENABLED", False) if enabled is None else bool(enabled)
        self._last = False

    def poll(self):
        """Zwraca 'enter' | 'leave' | None na podstawie zmiany obecności."""
        if not self.enabled:
            return None
        try:
            now = bool(self.detector())
        except Exception:
            now = False
        prev, self._last = self._last, now
        if now and not prev:
            return "enter"
        if prev and not now:
            return "leave"
        return None

    def greeting(self, initiative, memory=None, now=None):
        """Powitanie na wejście (przez `initiative.greeting`), albo None."""
        return initiative.greeting(memory, now=now) if initiative is not None else None


__all__ = ["Presence", "camera_present"]
