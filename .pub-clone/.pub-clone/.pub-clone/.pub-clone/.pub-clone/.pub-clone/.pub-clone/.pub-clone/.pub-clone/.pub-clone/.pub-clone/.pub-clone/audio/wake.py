"""Wake word ASTRO („Astro"): dopasowanie tekstu oraz detektor Vosk z gramatyką.

Whisper-Base (NPU) bywa zawodny na krótkim wake (w realnych logach: „Znij", „O 3"), dlatego
wake wykrywamy deterministycznie przez Vosk z zawężoną gramatyką (szybko, bez halucynacji),
a transkrypcję poleceń robi STT (NPU Whisper). Gdy Vosk niedostępny, działa dopasowanie tekstu.
"""

import difflib
import json
import os
import re
import time

from .. import config
from ..safety import normalize_facts

# Wake = FRAZA (może być wielowyrazowa). Domyślnie „hej astro" — pomiar 2026-09-20:
# fraza dwusłowna daje ~2,5% fałszywych wybudzeń na tle (vs 51% dla 1-słownego „astro").
# Konfiguracja: ASTRO_WAKE_WORD="hej astro" (albo pojedyncze słowo, np. "astro").
WAKE_PHRASE = tuple(w for w in re.findall(r"\w+", normalize_facts(
    config.WAKE_WORD or "hej astro")) if w)
WAKE_WORD = " ".join(WAKE_PHRASE)
# Warianty ograniczone do pełnej frazy (koniec z pojedynczymi „edy/edii/eddie" — fałszywki).
WAKE_VARIANTS = (WAKE_WORD,)
WAKE_TOKENS = set(WAKE_PHRASE)
VOSK_WORDS = (WAKE_WORD,)
WAKE_GRAMMAR = list(VOSK_WORDS) + ["[unk]"]

# Vosk/Kaldi domyślnie wypisuje setki linii diagnostycznych na stderr („LOG (VoskAPI:…)”) —
# w usłudze stderr jest dopisywany do astro.log, co napompowało plik do >1 GB (2026-09-26).
# Wyciszamy raz, przed utworzeniem pierwszego Modelu.
_VOSK_SILENCED = False


def silence_vosk():
    """Wycisza natywne logi Vosk/Kaldi (idempotentnie, bez wyjątku)."""
    global _VOSK_SILENCED
    if _VOSK_SILENCED:
        return
    _VOSK_SILENCED = True
    try:
        import vosk
        vosk.SetLogLevel(-1)
    except Exception:
        pass

# Gramatyka KOMEND (drugi przebieg Vosk dla swobodnego STT): gdy Whisper-Base zwróci bełkot
# („Pols na imię", „Restaart Systemu"), Vosk z zawężoną listą fraz rozpoznaje właściwe polecenie
# i zwraca jego KANONICZNĄ postać. To mechanizm sprawdzony w Atenie (0/5 swobodnie vs 5/5 z gramatyką).
COMMAND_PHRASES = [
    # profil
    "poznaj mnie", "poznajmy się", "co o mnie wiesz", "pokaż mój profil", "kim jestem",
    "zapomnij o mnie", "zapomnij wszystko",
    # zasilanie (zawsze za potwierdzeniem)
    "wyłącz system", "wyłącz komputer", "wyłącz malinę", "zamknij system", "wyłącz urządzenie",
    "restart systemu", "restartuj system", "zrestartuj system", "uruchom ponownie system",
    "zresetuj system", "reset systemu", "resetuj system",
    # sieć / Wi-Fi
    "wyszukaj sieci", "zeskanuj sieci", "pokaż dostępne sieci", "wyszukaj dostępne sieci",
    "połącz z siecią", "połącz się z siecią", "podłącz do sieci", "rozłącz z siecią",
    "rozłącz się z siecią", "wyłącz wifi", "włącz wifi",
    # zasoby / system
    "pokaż zasoby", "pokaż zasoby systemu", "zasoby systemu", "stan systemu",
    "temperatura procesora", "jaka temperatura procesora", "pokaż temperaturę",
    "podaj temperaturę procesora", "podaj temperaturę cpu",
    "stan dysku", "wolne miejsce na dysku", "stan pamięci", "ile wolnej pamięci",
    "która godzina", "która jest godzina", "podaj godzinę", "jaka jest data", "jaki dziś dzień",
    "podaj datę", "który dzisiaj dzień", "data",
    "stan poczty", "sprawdź pocztę",
    # aktualizacje / usługi
    "aktualizuj repozytoria", "zaktualizuj repozytoria", "odśwież repozytoria",
    "aktualizuj system", "zaktualizuj system", "zaktualizuj pakiety", "sprawdź aktualizacje",
    "status usługi", "stan usługi", "uruchom usługę", "zatrzymaj usługę", "zrestartuj usługę",
    # głośność
    "głośniej", "ciszej", "przycisz", "podgłośnij", "wycisz", "ustaw głośność",
    # informacje / tożsamość / wiedza
    "jaki mam adres ip", "moje ip", "kim jesteś", "jak się nazywasz", "co potrafisz", "pomoc",
    "jaka pogoda", "jaka jest pogoda", "podaj pogodę",
    "co to jest", "czym jest", "jak to działa", "wyjaśnij", "oblicz", "policz",
    # must-have (lista /etc/astro-secrets/komendy_must-have) - ratunek przy zniekształconej wymowie
    "podaj swoje ip", "podaj ip", "moje ip", "adres ip", "pokaż ip", "wyświetl ip",
    "pokaż zasoby zdalne", "wyświetl zasoby zdalne", "zużycie tokenów",
    "otwórz opencode", "uruchom opencode", "opencode", "opencołd",
    "znajdź dostępne sieci", "sprawdź dostępne sieci", "połącz z siecią numer",
    "rozłącz z siecią", "wyjdź z sieci",
    "zbieraj dane", "generuj raport zasoby", "raport zasoby",
    "najbliższy paczkomat", "najbliższa apteka", "najbliższy bankomat", "najbliższy sklep",
    "zaproponuj obiad", "co na obiad", "zaproponuj kolację", "co na kolację",
    "instaluj program", "zainstaluj aplikację", "aktualizuj źródła", "aktualizuj aplikacje",
    "jaki poziom dźwięku", "ścisz głos", "podgłoś dźwięk",
    # potwierdzenia / sterujące (bez samotnego „nie"/„tak" - gramatyka by je wymuszała)
    "potwierdzam", "anuluj", "przerwij", "zatrzymaj", "koniec",
    "dobrze", "okej", "super", "tak trzymaj", "źle", "błąd",
    "[unk]",
]
COMMAND_GRAMMAR = json.dumps(COMMAND_PHRASES)


def _must_have_phrases(path=None):
    """Frazy komend z listy must-have (`/etc/astro-secrets/komendy_must-have`) do gramatyki Voska.

    Trzyma rozpoznawanie w zgodzie z autorytatywną listą komend (M3.2). Parser odporny na
    opisy/nawiasy; brak pliku = brak dodatków (bez wyjątku).
    """
    path = path or getattr(config, "MUSTHAVE_FILE", "/etc/astro-secrets/komendy_must-have")
    lines = None
    for cand in (path, path + ".txt"):
        try:
            with open(cand, encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
            break
        except OSError:
            continue
    if lines is None:
        return []
    out = []
    section = ""
    for line in lines:
        s = line.strip()
        if not s.startswith("#"):
            continue
        hashes = len(s) - len(s.lstrip("#"))
        body = s.lstrip("#").strip()
        if hashes == 1:
            # Trzymamy CAŁY nagłówek sekcji (z opisem) — prefiks kanału bywa w opisie
            # (np. „# SYSTEM - ... prefix glosowym 'terminal' ...").
            section = body
            continue
        if not body:
            continue
        # nagłówek kategorii (np. ## KALKULATOR, ## ZNAJDZ MIEJSCE) nie jest komendą
        if hashes == 2 and body.isupper():
            continue
        body = re.sub(r"\([^)]*\)?", "", body)
        body = re.sub(r"\s*-\s+", " - ", body).split(" - ")[0]
        body = body.replace("[...]", "").strip()
        body = re.sub(r"\[([^\]]*)\]",
                      lambda m: m.group(1).split("/")[0] if "/" in m.group(1) else "", body)
        prefix = _section_prefix(section)
        for part in re.split(r"\s*/\s*", body):
            part = normalize_facts(part.strip())
            if len(part) >= 3 and not part.startswith("["):
                out.append(part)
                # Wariant z prefiksem kanału (must-have 2026-09-27): „skrypt …", „terminal …",
                # „czat …" — żeby gramatyka Voska rozpoznawała nową składnię głosową.
                if prefix:
                    out.append(normalize_facts(prefix + " " + part))
    return out


def _section_prefix(section):
    """Prefiks kanału wynikający z sekcji pliku must-have (SYSTEM/SMAL-TALK/SKRYPTY)."""
    s = (section or "").upper()
    if "SKRYPT" in s:
        return "skrypt"
    if "TERMINAL" in s:
        return "terminal"
    if "CZAT" in s or "SMAL" in s or "SMALL" in s:
        return "czat"
    return ""


def build_command_grammar(extra=None, musthave_path=None):
    """Gramatyka komend = wbudowane frazy + must-have + `ASTRO_COMMAND_EXTRA` (+ [unk])."""
    phrases = list(COMMAND_PHRASES)
    phrases += ["skrypt", "terminal", "czat"]  # same prefiksy kanału (must-have 2026-09-27)
    phrases += _must_have_phrases(musthave_path)
    env_extra = getattr(config, "COMMAND_EXTRA", "") or ""
    phrases += [normalize_facts(p) for p in env_extra.split(",") if p.strip()]
    phrases += [normalize_facts(p) for p in (extra or [])]
    uniq = list(dict.fromkeys(p for p in phrases if p))
    if "[unk]" not in uniq:
        uniq.append("[unk]")
    return json.dumps(uniq)


_CMD_GRAMMAR_CACHE = {"key": None, "grammar": None}


def build_command_grammar_cached(musthave_path=None):
    """`build_command_grammar` z inwalidacją cache po zmianie pliku must-have.

    Gramatyka komend zależy od `/etc/astro-secrets/komendy_must-have`; wcześniej była budowana
    raz na starcie, więc edycja listy nie działała bez restartu usługi. Teraz klucz cache
    zawiera mtime pliku — po jego zmianie gramatyka jest przebudowywana (M: cache invalidation)."""
    path = musthave_path or getattr(config, "MUSTHAVE_FILE", "")
    try:
        mtime = os.path.getmtime(path) if path else None
    except OSError:
        mtime = None
    key = (path, mtime, getattr(config, "COMMAND_EXTRA", "") or "")
    if _CMD_GRAMMAR_CACHE["key"] != key or _CMD_GRAMMAR_CACHE["grammar"] is None:
        _CMD_GRAMMAR_CACHE["key"] = key
        _CMD_GRAMMAR_CACHE["grammar"] = build_command_grammar(musthave_path=musthave_path)
    return _CMD_GRAMMAR_CACHE["grammar"]


def _phrase_regex(phrase):
    """Regex całej frazy wake: słowa rozdzielone separatorami (spacja/przecinek/kropka)."""
    parts = [re.escape(w) for w in phrase.split()]
    return re.compile(r"(?<!\w)" + r"[\s,.\-–—]*".join(parts) + r"(?!\w)", re.I)


WAKE_RE = _phrase_regex(WAKE_WORD)


def is_wake(text):
    """True, gdy w wypowiedzi jest CAŁA fraza wake (np. „Hej Astro, ...")."""
    return bool(WAKE_RE.search(normalize_facts(text or "")))


def strip_wake(text):
    """Usuwa pierwsze wystąpienie frazy wake i zwraca resztę polecenia."""
    m = WAKE_RE.search(text or "")
    if not m:
        return (text or "").strip(" ,.!?")
    rest = (text[:m.start()] + " " + text[m.end():]).strip(" ,.!?")
    return re.sub(r"\s{2,}", " ", rest).strip()


def wake_tokens(text):
    """Tokeny frazy wake, gdy cała fraza występuje (dla wyniku Vosk z gramatyką)."""
    return list(WAKE_PHRASE) if is_wake(text) else []


# Ostatni token frazy wake („astro") - dystynktywny; używany do weryfikacji swobodnym Vosk,
# że to NAPRAWDĘ wypowiedziano wake, a nie że mała gramatyka wymusiła go na tle (patrz stream_detect).
_WAKE_ANCHOR = normalize_facts(WAKE_PHRASE[-1]) if WAKE_PHRASE else ""


def _anchor_present(text):
    """True, gdy w swobodnej transkrypcji jest token frazy wake (np. „astro")."""
    if not _WAKE_ANCHOR:
        return True
    for tok in re.findall(r"[a-z0-9]+", normalize_facts(text or "")):
        if tok == _WAKE_ANCHOR:
            return True
        if len(tok) >= 4 and difflib.SequenceMatcher(None, tok, _WAKE_ANCHOR).ratio() >= 0.78:
            return True
    return False


class WakeDetector:
    """Detektor wake na Vosk (gramatyka ograniczona do wariantów „Astro")."""

    def __init__(self, model_path=None, words=None, rate=None):
        self.model_path = model_path or config.VOSK_MODEL
        self.words = list(words or VOSK_WORDS)
        self.rate = int(rate or config.SAMPLE_RATE)
        self._model = None
        self._grammar = json.dumps(self.words + ["[unk]"])
        self._command_grammar = build_command_grammar()

    def available(self):
        return bool(self.model_path) and os.path.isdir(self.model_path)

    def _ensure(self):
        if self._model is None:
            silence_vosk()
            from vosk import Model
            self._model = Model(self.model_path)
        return self._model

    def warm(self):
        """Ładuje model Vosk do pamięci (raz), by pierwsze wybudzenie nie czekało ~1 s.

        Bezpieczne do wołania w tle; nic nie robi, gdy brak modelu. Zwraca True, gdy model jest
        w pamięci po wywołaniu."""
        if not self.available():
            return False
        try:
            self._ensure()
            return True
        except Exception:
            return False

    def detect(self, pcm_f32):
        """pcm: float32 mono 16 kHz. True, gdy usłyszano wake word."""
        if not self.available():
            return False
        import numpy as np
        from vosk import KaldiRecognizer
        audio = np.asarray(pcm_f32, dtype="float32").reshape(-1)
        if audio.size == 0:
            return False
        pad = np.zeros(int(self.rate * 0.3), dtype="float32")
        audio = np.concatenate([pad, audio, pad])
        pcm16 = (np.clip(audio, -1.0, 1.0) * 32767).astype("int16").tobytes()
        rec = KaldiRecognizer(self._ensure(), self.rate, self._grammar)
        rec.AcceptWaveform(pcm16)
        text = json.loads(rec.FinalResult()).get("text", "")
        if not wake_tokens(text):
            return False
        return self._verify_free(pcm16)

    def _verify_free(self, pcm16):
        """Weryfikacja swobodnym Vosk (bez gramatyki): czy padło słowo-fraza wake.

        Sama mała gramatyka („hej astro" + [unk]) wymusza tę frazę na tle (zmierzone: tło
        „dzisiaj jest piękna pogoda..." -> partial „hej astro"). Swobodny Vosk na tym samym
        audio zwraca treść tła (bez „astro"), więc odsiewa fałszywe wybudzenia."""
        if not _WAKE_ANCHOR:
            return True
        from vosk import KaldiRecognizer
        rec = KaldiRecognizer(self._ensure(), self.rate)
        rec.AcceptWaveform(pcm16)
        text = json.loads(rec.FinalResult()).get("text", "")
        return _anchor_present(text)

    def transcribe(self, pcm_f32):
        """Pełna transkrypcja Vosk (bez gramatyki) - fallback dla poleceń."""
        if not self.available():
            return ""
        import numpy as np
        from vosk import KaldiRecognizer
        audio = np.asarray(pcm_f32, dtype="float32").reshape(-1)
        pcm16 = (np.clip(audio, -1.0, 1.0) * 32767).astype("int16").tobytes()
        rec = KaldiRecognizer(self._ensure(), self.rate)
        rec.AcceptWaveform(pcm16)
        return json.loads(rec.FinalResult()).get("text", "").strip()

    def command_check(self, pcm_f32):
        """Drugi przebieg Vosk z gramatyką komend: zwraca kanoniczną frazę polecenia albo "".

        Używane jako ratunek, gdy swobodne STT (Whisper-Base) zwróci bełkot. Ograniczenie do
        listy fraz sprawia, że Vosk trafia w znane polecenie nawet przy zniekształconej wymowie."""
        if not self.available():
            return ""
        import numpy as np
        from vosk import KaldiRecognizer
        audio = np.asarray(pcm_f32, dtype="float32").reshape(-1)
        if audio.size == 0:
            return ""
        pcm16 = (np.clip(audio, -1.0, 1.0) * 32767).astype("int16").tobytes()
        rec = KaldiRecognizer(self._ensure(), self.rate, build_command_grammar_cached())
        rec.AcceptWaveform(pcm16)
        text = json.loads(rec.FinalResult()).get("text", "").strip()
        return "" if text == "[unk]" or not text else text

    def transcribe_conf(self, pcm_f32):
        """Jak `transcribe` (swobodny Vosk), ale zwraca (tekst, pewność 0..1 lub None).

        Pewność = średnia `conf` słów z Vosk; brak danych = None (nie zgadujemy)."""
        if not self.available():
            return "", None
        import numpy as np
        from vosk import KaldiRecognizer
        audio = np.asarray(pcm_f32, dtype="float32").reshape(-1)
        if audio.size == 0:
            return "", None
        pcm16 = (np.clip(audio, -1.0, 1.0) * 32767).astype("int16").tobytes()
        rec = KaldiRecognizer(self._ensure(), self.rate)
        rec.AcceptWaveform(pcm16)
        data = json.loads(rec.FinalResult())
        text = (data.get("text") or "").strip()
        confs = [float(w.get("conf", -1)) for w in (data.get("result") or [])
                 if float(w.get("conf", -1)) >= 0]
        conf = sum(confs) / len(confs) if confs else None
        return text, conf

    def stream_detect(self, chunks, timeout=None):
        """Ciągły nasłuch: True, dopiero gdy ZAKOŃCZONY segment to fraza wake + weryfikacja.

        Świadomie NIE reagujemy na wyniki częściowe (partial) - mała gramatyka wymuszała
        „hej astro" na tle (fałszywe wybudzenia). Dodatkowo wymagamy, by swobodny Vosk na
        tym samym fragmencie usłyszał słowo-frazę wake („astro")."""
        if not self.available():
            return False
        import numpy as np
        from vosk import KaldiRecognizer
        rec = KaldiRecognizer(self._ensure(), self.rate, self._grammar)
        max_bytes = self.rate * 2 * 3  # bufor ~3 s (int16) do weryfikacji
        buf = bytearray()
        start = time.time()
        for chunk in chunks:
            if timeout and (time.time() - start) > timeout:
                break
            pcm16 = (np.clip(np.asarray(chunk, dtype="float32"), -1.0, 1.0)
                     * 32767).astype("int16").tobytes()
            buf += pcm16
            if len(buf) > max_bytes:
                del buf[:len(buf) - max_bytes]
            if rec.AcceptWaveform(pcm16):
                if wake_tokens(json.loads(rec.Result()).get("text", "")):
                    if self._verify_free(bytes(buf)):
                        return True
        return False
