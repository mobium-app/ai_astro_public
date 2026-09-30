"""C4 w torze głosowym: mówienie PIERWSZEGO fragmentu odpowiedzi w trakcie generacji.

Gdy czat (bez narzędzi) jest generowany, deltki tekstu trafiają do bufora; po napotkaniu końca
zdania fragment idzie do kolejki, a wątek roboczy syntezuje i odtwarza go TTS — zanim model
skończy. Dzięki temu pierwsze słowa słychać wcześniej, a użytkownik nie czeka w ciszy.

Bezpieczeństwo (świadome ograniczenia):
* włączone tylko opt-in (`ASTRO_STREAM=1`) i tylko dla czatu/pytań BEZ narzędzi (pętla
  sprawdza `registry.select` przed dispatch) — kroki z narzędziami są pomijane
  (`ctx.stream_tools`);
* krótkie/niepewne odpowiedzi (np. „nie wiem") nie startują mówienia (`min_first_chars`),
  więc fallback remote-learn nie zostawia „na wpół powiedzianego" bełkotu;
* pętla po dispatch porównuje mówiony tekst z finalną odpowiedzią: przy niezgodności (np.
  odpowiedź z remote) przerywa TTS (`tts.stop`) i czyta pełną odpowiedź normalnym torem.

Klasycznie `feed` jest wołane w wątku generacji, a odtwarzanie dzieje się w wątku roboczym;
`finish()` czeka (join kolejki), by zachować kolejność przed ewentualnym „ogonem".
"""

import queue
import re
import threading

_SENT_END_RE = re.compile(r"[.!?](?=\s|$)")
_HARD_SPLIT = 200


def _split(buf):
    """Dzieli bufor na (fragment do końca zdania, reszta); przy braku kropki tnie po 200 znakach."""
    m = _SENT_END_RE.search(buf)
    if m:
        return buf[:m.end()], buf[m.end():]
    if len(buf) > _HARD_SPLIT:
        cut = buf.rfind(" ", 0, _HARD_SPLIT)
        if cut > 0:
            return buf[:cut], buf[cut:]
    return "", buf


class StreamSpeaker:
    """Kolejkuje fragmenty odpowiedzi i odtwarza je w tle (jeden wątek roboczy)."""

    def __init__(self, speak, is_blocked=None, min_first_chars=24, max_chars=600):
        self._speak = speak
        self._is_blocked = is_blocked or (lambda: False)
        self.min_first_chars = int(min_first_chars)
        self.max_chars = int(max_chars)
        self.raw = ""
        self._buf = ""
        self._started = False
        self._lock = threading.Lock()
        self._queue = queue.Queue()
        self._thread = threading.Thread(target=self._worker, name="astro-stream-tts", daemon=True)
        self._thread.start()

    def reset(self):
        """Nowy krok generacji: porzuć nie-wysłany bufor (już zagrane fragmenty zostają)."""
        with self._lock:
            self._buf = ""
            self.raw = ""
            self._started = False

    def feed(self, piece):
        """Callback deltki z backendu — nigdy nie rzuca (ochrona generacji)."""
        if not piece:
            return
        try:
            if self._is_blocked():
                return
            with self._lock:
                self.raw += piece
                self._buf += piece
                if len(self.raw) > self.max_chars:
                    return
                while True:
                    frag, rest = _split(self._buf)
                    if not frag:
                        break
                    if (not self._started and len(frag) < self.min_first_chars
                            and len(self.raw) < self.min_first_chars):
                        break
                    self._buf = rest
                    self._emit(frag)
        except Exception:
            pass

    def _emit(self, frag):
        frag = (frag or "").strip()
        if not frag:
            return
        self._started = True
        self._queue.put(frag)

    def finish(self):
        """Wysyła resztę bufora, czeka na odtworzenie i zwraca mówiony tekst ("" gdy nic)."""
        with self._lock:
            if self._started and self._buf.strip() and len(self.raw) <= self.max_chars:
                self._emit(self._buf)
            self._buf = ""
            started = self._started
        try:
            self._queue.join()
        except Exception:
            pass
        return self.raw if started else ""

    def close(self):
        try:
            self._queue.put(None)
            self._thread.join(timeout=0.5)
        except Exception:
            pass

    def _worker(self):
        while True:
            item = self._queue.get()
            try:
                if item is None:
                    return
                try:
                    self._speak(item)
                except Exception:
                    pass
            finally:
                try:
                    self._queue.task_done()
                except Exception:
                    pass
