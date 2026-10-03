"""Pętla głosowa ASTRO: nasłuch -> wake „Hej Astro" -> agent -> odpowiedź głosem (pół-duplex).

Wake wykrywa Vosk z gramatyką (pewnie, bez halucynacji), polecenie transkrybuje STT
(NPU Whisper), a gdy STT zwróci pustkę — Vosk. Mikrofon jest zajęty tylko podczas nasłuchu.
"""

import os
import re
import shutil
import tempfile
import threading
import time

from .. import config, mirror, wifi
from .. import log as astro_log
from .. import log as astro_log
from ..core import command_match
from ..core import create_agent, dispatch, fast_tools, must_have, profiling
from ..core import initiative as initiative_mod
from ..safety import classify_request, is_confirmation, normalize_command, normalize_facts
from ..spelling import parse_spelled_secret
from . import capture, express, signals, stream_speech, whisper_cpu
from .stt import STT
from .tts import TTS
from .wake import WakeDetector, is_wake, strip_wake

SLEEP_THANKS_RE = re.compile(
    r"^\s*(?:bardzo\s+|serdecznie\s+|slicznie\s+|pieknie\s+)?(?:dziekuje|dzieki)"
    r"(?:\s+(?:ci|bardzo|serdecznie|slicznie|pieknie|wielkie|z\s+gory)){0,2}\s*[.!?]?\s*$")
SLEEP_REPLY = "Nie ma za co. Wracam do czuwania."


def is_sleep(text):
    """True dla pożegnalnego „dziękuję" (cała wypowiedź) - kończy sesję."""
    return bool(SLEEP_THANKS_RE.match(normalize_facts(text or "")))


def _known_score(text):
    """Ocena, jak konkretnie tekst trafia w znane, deterministyczne polecenie ASTRO (bez I/O).

    3 = konkretna intencja (Wi-Fi, zasilanie, profil, zasoby, aktualizacje, usługa, czas...),
    2 = sam czasownik wykonawczy, 1 = samo ogólne słowo systemowe („system", „pamięć"),
    0 = brak dopasowania. Wyższa ocena = lepsza transkrypcja i mniejsza potrzeba ratunku."""
    if not text:
        return 0
    if must_have.intent(text):
        return 3
    if wifi.intent(text):
        return 3
    low = normalize_command(text)
    if (fast_tools.TIME_RE.search(low) or fast_tools.DATE_RE.search(low)
            or fast_tools.TEMP_RE.search(low)
            or fast_tools.REPORT_RE.search(low) or fast_tools.RESOURCE_RE.search(low)
            or fast_tools.UPDATE_STATUS_RE.search(low) or fast_tools.WEATHER_RE.search(low)
            or fast_tools.VOLUME_RE.search(low) or fast_tools.SERVICE_RE.search(low)
            or fast_tools.update_action(low)):
        return 3
    if not fast_tools.POWER_NEG_RE.search(low) and (
            fast_tools.POWER_SHUTDOWN_RE.search(low) or fast_tools.POWER_REBOOT_RE.search(low)):
        return 3
    if (profiling.TRIGGER_RE.search(low) or profiling.QUERY_RE.search(low)
            or profiling.FORGET_RE.search(low)):
        return 3
    if classify_request(text) == "command":
        return 2
    if fast_tools.INFO_RE.search(low) or fast_tools.NPU_RE.search(low):
        return 1
    return 0


def _same_command(text, canonical):
    """True, gdy tekst po rekonstrukcji diakrytyków jest identyczny z kanonem must-have.

    Rozróżnia „STT zgubił ogonki" (ta sama komenda → nie pytamy o potwierdzenie) od realnie
    przybliżonego dopasowania (inna komenda/`remote`→`remont` → potwierdzamy)."""
    tn = command_match.normalize(command_match.canonicalize(command_match.restore_diacritics(text or "")))
    cn = command_match.normalize(canonical or "")
    return bool(tn) and tn == cn


def _rescuable(text):
    """Czy wolno nadpisać transkrypcję innym silnikiem/gramatyką?

    NIE ruszamy zdań rozpoznanych już jako pytanie/rozmowa ani jako komenda (mają pierwszeństwo -
    inaczej gramatyka komend podmieniłaby np. „uruchom htop" na „która godzina"). Ratujemy tylko
    puste, nieznane i same ogólne trafienia (1), np. „Pokrasz zasobl"."""
    if classify_request(text) in ("question", "chat", "command"):
        return False
    return _known_score(text) < 3


def _weak_transcript(text):
    """True, gdy transkrypcja jest pusta/niejasna i warto spróbować drugiego silnika STT."""
    return True if not text else _rescuable(text)


def _fuzzy_score(text):
    """Podobieństwo tekstu do najlepszej znanej komendy (0 gdy brak/niekomendowalne)."""
    try:
        return command_match.best(text, threshold=0.0)[1]
    except Exception:
        return 0.0


def _pick_transcript(npu_text, vosk_text):
    """Wybiera lepszą transkrypcję: wygrywa tekst najbliższy realnej komendzie (przy remisie NPU).

    Pomiar na realnych nagraniach (2026-09-23): Vosk small PL rozpoznaje krótkie komendy lepiej
    niż NPU Whisper-Base (82% vs 68% „do znanej komendy"). Dlatego Vosk bierzemy zawsze pod uwagę,
    a wybór robimy po podobieństwie do listy must-have + deterministycznej intencji."""
    candidates = [c for c in (npu_text, vosk_text) if c]
    if not candidates:
        return ""
    # Nie podmieniaj rozpoznanego PYTANIA/rozmowy na komendę: Vosk bywa bliższy must-have
    # fuzzy („jaka pogoda" -> „podaj ip"), a wtedy pętla pytałaby o zgodę na komendę, której
    # użytkownik nie wypowiedział. Pytanie/rozmowa NPU ma pierwszeństwo - CHYBA że Vosk sam
    # słyszy pytanie/rozmowę i jest wyraźnie bliższy znanej frazie (NPU to bełkot, np.
    # „która disa ga" vs poprawne „który dzisiaj dzień"). Wtedy bierzemy lepszy Vosk.
    if npu_text and classify_request(npu_text) in ("question", "chat"):
        if (vosk_text and classify_request(vosk_text) in ("question", "chat")
                and _fuzzy_score(vosk_text) > _fuzzy_score(npu_text)):
            return vosk_text
        return npu_text
    return max(candidates, key=lambda c: (_fuzzy_score(c), _known_score(c),
                                          classify_request(c) == "command"))


class VoiceLoop:
    def __init__(self, agent=None, stt=None, tts=None, wake_detector=None,
                 listen_s=None, command_s=None, session_s=None, barge_in=None,
                 initiative=None):
        self.agent = agent or create_agent()
        self.stt = stt or STT()
        self.tts = tts or TTS()
        self.initiative = initiative if initiative is not None else initiative_mod.Initiative()
        self.wake_det = wake_detector if wake_detector is not None else WakeDetector()
        self.listen_s = listen_s or config.VOICE_LISTEN_S
        self.command_s = command_s or config.VOICE_SESSION_S
        self.session_s = session_s or config.VOICE_SESSION_S
        self.active_until = 0.0
        self.barge_in = config.BARGE_IN if barge_in is None else bool(barge_in)
        self.barge_threshold = config.BARGE_THRESHOLD
        self.barge_warmup_s = config.BARGE_WARMUP_S
        # (c) Trwały strumień mikrofonu (opcjonalny, ASTRO_MIC_PERSISTENT=1) — jeden arecord.
        self._mic = None
        self.log = astro_log.get_logger("voice")

    def _open_mic(self):
        if getattr(config, "MIC_PERSISTENT", 0) and self._mic is None:
            try:
                self._mic = capture.PersistentMic()
                self.log.info("trwały strumień mikrofonu (MIC_PERSISTENT)")
            except Exception:
                self._mic = None
        return self._mic

    def can_listen(self):
        return self.wake_det.available() or self.stt.available()

    def _can_barge(self):
        return (self.barge_in and self.can_listen() and self._mic is None
                and hasattr(self.tts, "synthesize") and hasattr(self.tts, "play")
                and hasattr(self.tts, "stop"))

    def _barge_listen(self, stop_evt):
        """Wątek: nasłuch podczas TTS. Zwraca przez słownik wykrycie + klatkę mowy.

        Wymaga 2 kolejnych klatek nad progiem (odporniej na echo głośnika) i pomija
        początkowy warmup, w którym mikrofon łapie start odtwarzania.
        """
        hit = {"yes": False, "pcm": None}
        try:
            gen = capture.stream_pcm()
        except Exception:
            return hit
        over = 0
        start = time.time()
        try:
            for chunk in gen:
                if stop_evt.is_set():
                    return hit
                if time.time() - start < self.barge_warmup_s:
                    continue
                if capture.level(chunk) >= self.barge_threshold:
                    over += 1
                    if over >= 2:
                        hit["yes"] = True
                        hit["pcm"] = chunk
                        return hit
                else:
                    over = 0
        except Exception:
            return hit
        finally:
            try:
                gen.close()
            except Exception:
                pass
        return hit

    def _voice_plan(self):
        """Wspólny plan barwy głosu (nastrój + bazowy ton) dla WSZYSTKICH torów mowy."""
        return express.plan_for_affect(getattr(self.agent, "memory", None), "")

    def say(self, text, barge=None):
        """Mówi tekst. Zwraca (przerwano?, pcm) — przy barge-in przerywa i zbiera mowę."""
        mirror.reply(text)
        plan = self._voice_plan()
        plan["text"] = text
        barge = self.barge_in if barge is None else bool(barge)
        if not (barge and self._can_barge()):
            self.tts.speak(text, fx=plan["fx"], model=plan["model"])
            time.sleep(plan["pause"])
            return False, None
        try:
            out_wav = os.path.join(tempfile.mkdtemp(), "astro-tts.wav")
            wav = self.tts.synthesize(text, out_wav, fx=plan["fx"], model=plan["model"])
        except Exception:
            wav = None
        if not wav:
            self.tts.speak(text, fx=plan["fx"], model=plan["model"])
            time.sleep(plan["pause"])
            return False, None
        stop_evt = threading.Event()
        box = {}
        worker = threading.Thread(target=lambda: box.update(self._barge_listen(stop_evt)),
                                  daemon=True)
        worker.start()
        try:
            self.tts.play(wav)
        finally:
            stop_evt.set()
            worker.join(timeout=0.5)
            shutil.rmtree(os.path.dirname(wav), ignore_errors=True)
        if not box.get("yes"):
            return False, None
        self.tts.stop()
        tail = self._record_speech()
        trigger = box.get("pcm")
        pcm = tail
        try:
            import numpy as _np
            if trigger is not None and getattr(tail, "size", 0):
                pcm = _np.concatenate([_np.asarray(trigger, dtype="float32"), tail])
            elif trigger is not None and not getattr(tail, "size", 0):
                pcm = _np.asarray(trigger, dtype="float32")
        except Exception:
            pcm = tail
        return True, pcm

    def transcribe_ex(self, pcm):
        """Jak `transcribe`, ale zwraca (tekst, niepewna?).

        `niepewna=True`, gdy wynik pochodzi ze słabszej ścieżki: pusty NPU Whisper (oparliśmy się
        na Vosku) albo ratunek gramatyką komend (gramatyka WYMUSZA jedną z fraz). Wtedy przy
        komendach wykonawczych pętla czyta rozpoznanie i prosi o potwierdzenie (M3.4)."""
        if pcm is None:
            return "", False
        npu_text = self.stt.transcribe(pcm) if self.stt.available() else ""
        text = npu_text
        uncertain = False
        grammar_used = False
        grammar_from_text = ""
        # Vosk dorzucamy, gdy NPU nie dał JEDNOZNACZNEJ znanej komendy (na krótkich komendach
        # Vosk wypada lepiej; pomiar 2026-09-23). Wybór robi `_pick_transcript` (must-have).
        if self.wake_det.available() and _known_score(npu_text) < 3:
            conf = None
            if hasattr(self.wake_det, "transcribe_conf"):
                alt, conf = self.wake_det.transcribe_conf(pcm)
            else:
                alt = self.wake_det.transcribe(pcm)
            if alt:
                chosen = _pick_transcript(npu_text, alt)
                if chosen and chosen != npu_text:
                    uncertain = True  # wybrano inny silnik niż NPU Whisper
                # Niska pewność Voska (M3.3) -> niepewna, nawet gdy tekst jest znaną komendą.
                if chosen == alt and conf is not None and \
                        conf < float(getattr(config, "STT_CONF_MIN", 0.6)):
                    uncertain = True
                text = chosen or npu_text
            elif not npu_text:
                uncertain = True
        if self.wake_det.available() and _rescuable(text):
            pre_grammar = text
            grammar = self.wake_det.command_check(pcm)
            if grammar and _known_score(grammar) > _known_score(text):
                text = grammar
                uncertain = True  # gramatyka komend wymusza frazę
                grammar_used = True
                grammar_from_text = pre_grammar
        text = (text or "").strip()
        # Dokładny fallback CPU (faster-whisper, ~7 s) TYLKO dla niepewnych/niejasnych krótkich
        # komend. Wcześniej bramka (len<=8 i score<0.92) odpalała go przy większości tur — także
        # dla pewnych znanych komend (known_score=3) i krótkich pytań, co dawało ~7 s narzutu.
        fast = float(getattr(config, "STT_COMMAND_FAST", 0.92))
        if (text and getattr(config, "STT_WHISPER_ENABLED", True)
                and _known_score(text) < 3 and classify_request(text) != "question"
                and len(text.split()) <= 8):
            _cmd, score = command_match.best(text, threshold=0.0)
            if score < fast:
                w = whisper_cpu.transcribe(pcm)
                if w:
                    _wcmd, wscore = command_match.best(w, threshold=0.0)
                    if wscore > score:
                        text, uncertain = w, True
        # Ostatnia warstwa: dopasuj zniekształcone rozpoznanie do ZNANEJ komendy must-have
        # („pokaż zafoby w dalne" -> „pokaż zasoby zdalne"). Gdy rozpoznanie JUŻ jest znaną
        # komendą (`known_score==3`), tekstu nie nadpisujemy, ale i tak liczymy trafienie, by
        # skasować niepewność przy pewnym dopasowaniu (mniej pytań o potwierdzenie).
        min_score = float(getattr(config, "STT_COMMAND_MATCH_MIN", 0.0) or 0.0)
        confirm_min = float(getattr(config, "STT_CONFIRM_MIN", 0.95))
        cmd, score = command_match.best(text, threshold=0.0) if text else ("", 0.0)
        already_known = _known_score(text) >= 3
        if text and min_score > 0 and score >= min_score and not already_known:
            text = cmd
        if cmd and score >= confirm_min and not grammar_used:
            # (d) Pewne trafienie do znanej komendy z WŁASNEJ transkrypcji (nie z gramatyki,
            # która potrafi wymusić frazę na szumie) -> nie pytamy o potwierdzenie.
            uncertain = False
        elif grammar_used and cmd and score >= confirm_min and _same_command(grammar_from_text, cmd):
            # Gramatyka ZNALAZŁA tę samą znaną komendę, którą słyszała JUŻ transkrypcja przed
            # ratunkiem (zgodność po rekonstrukcji diakrytyków) — to potwierdzenie, nie wymuszenie
            # na szumie. Nie pytamy (np. „temperatura cpu" rozpoznana identycznie).
            uncertain = False
        elif min_score > 0 and score >= min_score and not already_known and score < 0.92:
            # Ta sama intencja, ale STT zgubił diakrytyki/akcent („podaj godzine" vs „podaj
            # godzinę") — po rekonstrukcji diakrytyków tekst zgadza się z kanonem, więc NIE
            # pytamy o potwierdzenie. Ratunek gramatyką nadal wymaga potwierdzenia (grammar_used).
            if cmd and _same_command(text, cmd):
                uncertain = False
            else:
                uncertain = True  # dopasowanie przybliżone -> potwierdź przy komendach
        return text, uncertain

    def transcribe(self, pcm):
        """Transkrypcja polecenia: NPU Whisper + Vosk + ratunek gramatyką komend.

        Kolejność: NPU Whisper -> gdy wynik słaby, Vosk swobodny (wybieramy kandydata mapowalnego
        na znane polecenie) -> gdy nadal słabo, Vosk z gramatyką komend (kanoniczna fraza).
        Bez tego Whisper-Base zwracał bełkot („Pols na imię", „Restaart Systemu")."""
        return self.transcribe_ex(pcm)[0]

    def confirm_uncertain(self, command, attempts=2):
        """Czyta niepewne rozpoznanie i prosi o potwierdzenie. True = wykonuj.

        Bezpieczeństwo (M3.4): przy transkrypcji z niskiej pewności (gramatyka/ratunek) i komendzie
        wykonawczej NIE działamy od razu — najpierw słowny odczyt i zgoda użytkownika.

        Po pytaniu MUSI zagrać beep (jak w pętli głównej) — bez niego użytkownik nie wie, że ma
        odpowiadać, a krótkie okno kończyło się cichym „Dobrze, pomijam". Słuchamy pełnego okna
        sesji i ponawiamy przy ciszy, zamiast poddawać się po pierwszej próbie."""
        self.say(f"Nie jestem pewna, czy dobrze usłyszałam: {command}. Mam to wykonać?")
        for _ in range(max(1, attempts)):
            signals.done_signal()
            pcm = self._record_speech(self.command_s)
            ans, _u = self.transcribe_ex(pcm)
            if not ans:
                continue
            if is_confirmation(ans):
                return True
            break
        self.say("Dobrze, pomijam.")
        return False

    def _record_speech(self, max_s=None):
        """Nasłuch komendy z VAD: nagrywa do końca wypowiedzi (+krótki ogon ciszy)."""
        if self._mic is not None:
            return self._mic.record(max_s=max_s if max_s is not None else self.command_s)
        return capture.record_speech(max_s=max_s if max_s is not None else self.command_s)

    def _stream_eligible(self, command):
        """Czy wolno mówić pierwszy fragment (C4)? Tylko czat/pytanie (nie komenda), opt-in.

        Uwaga: NIE bramkujemy po `registry.select()` — rdzeń (`system_info`/`ask_user`) jest
        zawsze obecny, więc lista nigdy nie jest pusta. Ochronę przed mówieniem kroków
        narzędziowych daje agent (deltki treści przy wywołaniu narzędzia są puste, a przy
        niezgodności pętla przerywa TTS i czyta pełną odpowiedź)."""
        if not getattr(config, "STREAM", False):
            return False
        if getattr(self.agent, "ctx", None) is None:
            return False
        try:
            return classify_request(command) in ("question", "chat")
        except Exception:
            return False

    def _dispatch(self, command):
        """dispatch + opcjonalne mówienie pierwszego fragmentu (C4). Zwraca (resp, spoken)."""
        speaker = None
        ctx = getattr(self.agent, "ctx", None)
        if ctx is not None and self._stream_eligible(command):
            plan = self._voice_plan()
            speaker = stream_speech.StreamSpeaker(
                speak=lambda t: self.tts.speak(t, fx=plan["fx"], model=plan["model"]))
            try:
                ctx.stream_sink = speaker.feed
            except Exception:
                speaker = None
        try:
            resp = dispatch(command, self.agent)
        finally:
            if speaker is not None:
                try:
                    ctx.stream_sink = None
                except Exception:
                    pass
        if speaker is None:
            return resp, ""
        spoken = speaker.finish()
        speaker.close()
        return resp, spoken

    @staticmethod
    def _matches_streamed(reply, spoken):
        """Czy finalna odpowiedź zgadza się z tym, co już powiedziano (streaming)? """
        r = (reply or "").strip()
        s = (spoken or "").strip()
        if not s:
            return False
        return r.startswith(s[:40]) or s[:40].startswith(r[:40])

    def _say_or_finish_stream(self, reply, resp, spoken):
        """Mówi odpowiedź: dokańcza ogon po streamingu albo czyta całość. Zwraca (barged, pcm)."""
        if (spoken and not str(getattr(resp, "route", "")).startswith("remote")
                and self._matches_streamed(reply, spoken)):
            mirror.reply(reply)
            tail = (reply or "")[len(spoken):].strip()
            if tail:
                plan = self._voice_plan()
                self.tts.speak(tail, fx=plan["fx"], model=plan["model"])
            return False, None
        if spoken:
            self.tts.stop()
        return self.say(reply)

    def handle_text(self, text):
        """Obsługa rozpoznanego tekstu (testowalna bez sprzętu). None gdy brak wake/sesji."""
        if not text:
            return None
        if is_wake(text):
            command = strip_wake(text)
            self.active_until = time.time() + self.session_s
        elif time.time() < self.active_until:
            command = text.strip()
            self.active_until = time.time() + self.session_s
        else:
            return None
        if not command:
            self.say("Słucham?")
            return "Słucham?"
        resp, spoken = self._dispatch(command)
        reply = resp.reply
        self._say_or_finish_stream(reply, resp, spoken)
        return reply

    def _wifi_password_flow(self):
        """Zbiera literowane hasło (beep po każdej literce); „koniec"/„zatwierdzam" kończy."""
        state = getattr(self.agent.ctx, "wifi_pending", None) or {}
        ssid = state.get("ssid")
        self.say("Podaj hasło. Literuj znaki. Powiedz koniec, gdy skończysz.")
        buf = ""
        for _ in range(20):
            pcm = self._record_speech(self.listen_s)
            text = self.transcribe(pcm)
            if not text:
                continue
            norm = normalize_facts(text)
            if re.search(r"\b(koniec|zatwierdzam|potwierdzam|gotowe)\b", norm):
                prefix = re.split(r"\b(koniec|zatwierdzam|potwierdzam|gotowe)\b", norm)[0]
                add = parse_spelled_secret(prefix)
                buf += add
                for _ch in add:
                    signals.tick_signal()
                break
            if re.search(r"\b(anuluj|przerwij|stop)\b", norm):
                self.agent.ctx.wifi_pending = None
                return "anulowałam łączenie z Wi-Fi"
            add = parse_spelled_secret(text)
            if not add:
                self.say("Nie rozpoznałam. Literuj pojedynczo, na przykład małe a, duże Be, hasztag.")
                continue
            buf += add
            for _ch in add:
                signals.tick_signal()
        self.agent.ctx.wifi_pending = None
        if not buf:
            return "nie podano hasła"
        _ok, msg = wifi.connect(ssid, buf)
        return msg

    def run_forever(self, max_turns=None):
        if not self.can_listen():
            raise RuntimeError("brak STT/wake (Vosk lub NPU Whisper) — nie mogę nasłuchiwać")
        self._open_mic()
        try:
            return self._run_loop(max_turns)
        finally:
            if self._mic is not None:
                self._mic.close()
                self._mic = None

    def _flush_announcements(self):
        """Komunikaty systemowe z kolejki (monitoring premium) — mów przy najbliższym wake.

        `scripts/premium_check.py` dopisuje tu „Straciłam połączenie z …"/„… przywrócone";
        konsumujemy max 3 zaległe wpisy i kasujemy plik kolejki."""
        import json as _json
        from .. import config as _config
        q = _config.RUNTIME_DIR / "announce_queue.jsonl"
        try:
            lines = q.read_text(encoding="utf-8").strip().splitlines()
        except Exception:
            return []
        notes = []
        for ln in lines[-3:]:
            try:
                text = ((_json.loads(ln) or {}).get("text") or "").strip()
            except Exception:
                text = ""
            if text:
                notes.append(text)
        if notes:
            try:
                q.unlink()
            except Exception:
                pass
        return notes

    def _run_loop(self, max_turns=None):
        turns = 0
        while max_turns is None or turns < max_turns:
            try:
                if self._mic is not None:
                    gen = self._mic.chunks()
                else:
                    gen = capture.stream_pcm()
                try:
                    woke = self.wake_det.stream_detect(gen)
                finally:
                    if self._mic is None:
                        gen.close()
                if not woke:
                    continue
                self.log.info("wake „Hej Astro\" wykryty")
                # Komunikaty systemowe (monitoring premium) — np. „straciłam połączenie z …".
                for note in self._flush_announcements():
                    self.log.info("alert systemowy: %s", note)
                    self.say(note)
                    signals.done_signal()
                # Proaktywne, kontekstowe powitanie (pora dnia, imię, nastrój); fallback klasyczny.
                greet = self.initiative.greeting(getattr(self.agent, "memory", None)) or "Melduję się"
                self.say(greet)
                joke = self.initiative.spontaneous_joke(getattr(self.agent, "memory", None))
                if joke:
                    self.say(joke)
                signals.done_signal()
                time.sleep(0.2)
                session_end = time.time() + self.session_s
                next_pcm = None
                empty_streak = 0
                while time.time() < session_end:
                    if next_pcm is not None:
                        pcm, next_pcm = next_pcm, None
                    else:
                        pcm = self._record_speech()
                    command, uncertain = self.transcribe_ex(pcm)
                    if not command:
                        empty_streak += 1
                        # Proaktywny zaczep „idle" (opcjonalny: ASTRO_INITIATIVE_IDLE>0).
                        if (empty_streak == 1 and getattr(config, "INITIATIVE_IDLE_S", 0) > 0):
                            rem = self.initiative.remark("idle")
                            if rem:
                                self.log.info("inicjatywa: zaczep idle")
                                self.say(rem)
                                signals.done_signal()
                                session_end = time.time() + self.session_s
                                continue
                        break
                    empty_streak = 0
                    if is_sleep(command):
                        self.log.info("dziękuję -> koniec sesji")
                        self.say(SLEEP_REPLY)
                        signals.done_signal()
                        break
                    self.log.info("polecenie: %r", command)
                    # Niepewne rozpoznanie + komenda wykonawcza -> odczyt i potwierdzenie.
                    if uncertain and classify_request(command) == "command":
                        if not self.confirm_uncertain(command):
                            signals.done_signal()
                            continue
                    resp, spoken = self._dispatch(command)
                    reply = (self._wifi_password_flow() if resp.route == "wifi-password"
                             else resp.reply)
                    self.log.info("odpowiedź: %r", reply)
                    barged, barge_pcm = self._say_or_finish_stream(reply, resp, spoken)
                    signals.done_signal()
                    if barged:
                        self.log.info("barge-in: przerwano, słucham dalej")
                        next_pcm = barge_pcm
                    turns += 1
                    session_end = time.time() + self.session_s
            except KeyboardInterrupt:
                raise
            except Exception as e:
                self.log.warning("błąd pętli: %s", e)
                time.sleep(1)
        return turns
