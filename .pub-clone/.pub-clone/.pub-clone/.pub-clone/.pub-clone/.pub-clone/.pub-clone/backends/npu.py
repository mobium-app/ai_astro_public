"""Backend NPU (Hailo-10H): koncept in-process NpuEngine (genai LLM + Speech2Text).

HailoRT daje urządzenie na wyłączność jednemu procesowi — ASTRO otwiera VDevice tylko,
gdy jest właścicielem NPU (żaden inny proces nie trzyma węzła urządzenia).

Nazwa węzła zależy od wersji HailoRT: 5.1.1 → `/dev/hailo0`, 5.3.0 → `/dev/h1x-0`.
"""

import glob
import json
import os
import re
import subprocess
import sys
import threading
import time

from .. import config
from .base import Backend, BackendResult
from .telemetry import NPU_TELEMETRY

STOP_TOKENS = ("<|im_end|>", "<|endoftext|>", "<|eot_id|>")

# VLM (Faza 4): opis sceny po polsku, zwięźle, na NPU (Qwen2-VL-2B).
VLM_QUESTION_PL = (
    "Odpowiedz po polsku, w jednym lub dwóch zdaniach, co widzisz na obrazie: ile jest osób, "
    "co robią i jakie ważne przedmioty są w otoczeniu."
)


def hailo_platform_available():
    try:
        import hailo_platform  # noqa: F401
        return True
    except Exception:
        pass
    for extra in ("/usr/lib/python3/dist-packages",):
        if extra not in sys.path:
            sys.path.append(extra)
    try:
        import hailo_platform  # noqa: F401
        return True
    except Exception:
        return False


def resolve_npu_llm_hef(model=None):
    """Ścieżka do HEF LLM: env, potem manifesty hailo-ollama (prefer qwen2.5-instruct)."""
    env = os.environ.get("ASTRO_NPU_LLM_HEF", "")
    if env and os.path.exists(env):
        return env
    manifests = glob.glob("/usr/share/hailo-ollama/models/manifests/*/*/manifest.json")

    def rank(path):
        return (0 if "qwen2.5-instruct" in path else 1, path)

    for man in sorted(manifests, key=rank):
        try:
            with open(man, encoding="utf-8") as f:
                hef = json.load(f).get("hef_h10h")
        except Exception:
            continue
        for name in (f"sha256_{hef}", hef):
            blob = f"/usr/share/hailo-ollama/models/blob/{name}"
            if hef and os.path.exists(blob):
                return blob
    family, _, tag = (model or "qwen2.5-instruct:1.5b").partition(":")
    manif = f"/usr/share/hailo-ollama/models/manifests/{family}/{tag or '1.5b'}/manifest.json"
    try:
        with open(manif, encoding="utf-8") as f:
            hef = json.load(f).get("hef_h10h")
        for name in (f"sha256_{hef}", hef):
            blob = f"/usr/share/hailo-ollama/models/blob/{name}"
            if hef and os.path.exists(blob):
                return blob
    except Exception:
        pass
    return ""


def resolve_vlm_hef():
    """Ścieżka do HEF VLM: env `ASTRO_VLM_HEF`, potem Qwen3-VL-2B (preferowany), na końcu Qwen2-VL-2B."""
    env = os.environ.get("ASTRO_VLM_HEF", "") or getattr(config, "VLM_HEF", "")
    if env and os.path.exists(env):
        return env
    for name in ("Qwen3-VL-2B-Instruct.hef", "Qwen2-VL-2B-Instruct.hef"):
        p = config.REPO / "models" / "hailo" / name
        if p.exists():
            return str(p)
    return ""


def strip_stop_tokens(text, stops=STOP_TOKENS):
    t = text or ""
    for s in stops:
        i = t.find(s)
        if i != -1:
            t = t[:i]
    return t.strip()


def clean_npu_asr(text):
    t = re.sub(r"<\|[^|<>]*\|>", " ", text or "")
    t = re.sub(r"\s+", " ", t).strip(" .,-")
    if len(t) < 2:
        return ""
    words = t.lower().split()
    if len(words) >= 6:
        from collections import Counter
        w, n = Counter(words).most_common(1)[0]
        if len(w) >= 2 and n / len(words) > 0.5:
            return ""
    return t


DEVICE_GLOBS = ("/dev/hailo*", "/dev/h1x*")


def device_paths():
    """Węzły urządzenia Hailo obecne w systemie (5.1.1: /dev/hailo0, 5.3.0: /dev/h1x-0)."""
    paths = []
    for pat in DEVICE_GLOBS:
        paths.extend(glob.glob(pat))
    return sorted(paths)


def device_present():
    if device_paths():
        return True
    try:
        out = subprocess.run(["lspci"], capture_output=True, text=True, timeout=10)
        return "hailo" in (out.stdout or "").lower()
    except Exception:
        return False


def device_holders():
    holders = []
    try:
        pids = [p for p in os.listdir("/proc") if p.isdigit()]
    except Exception:
        return holders
    for pid in pids:
        fddir = f"/proc/{pid}/fd"
        try:
            fds = os.listdir(fddir)
        except Exception:
            continue
        for fd in fds:
            try:
                target = os.readlink(os.path.join(fddir, fd))
            except Exception:
                continue
            if target.startswith(("/dev/hailo", "/dev/h1x")):
                comm = ""
                try:
                    with open(f"/proc/{pid}/comm", encoding="utf-8") as f:
                        comm = f.read().strip()
                except Exception:
                    pass
                holders.append({"pid": int(pid), "comm": comm})
                break
    return holders


def device_busy():
    return bool(device_holders())


def firmware_version():
    try:
        out = subprocess.run(["hailortcli", "fw-control", "identify"], capture_output=True,
                             text=True, timeout=15)
        for line in (out.stdout or "").splitlines():
            if "Firmware Version:" in line:
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return "?"


def available_hefs():
    whisper = os.environ.get("ASTRO_NPU_HEF") or config.NPU_HEF
    llm = config.NPU_LLM_HEF or resolve_npu_llm_hef(config.NPU_MODEL)
    vlm = resolve_vlm_hef()
    return {
        "whisper": {"path": whisper, "exists": bool(whisper) and os.path.exists(whisper)},
        "llm": {"path": llm, "exists": bool(llm) and os.path.exists(llm)},
        "vlm": {"path": vlm, "exists": bool(vlm) and os.path.exists(vlm)},
    }


class NpuGate:
    """Priorytetowa kolejka dostępu do NPU (Faza 4: „kolejka VDevice").

    HailoRT-owe wywołania są blokujące — nie da się przerwać trwającej inferencji, ale
    kolejka porządkuje CZEKAJĄCYCH: wyższy priorytet (mniejsza liczba) wyprzedza niższe,
    a w obrębie tego samego priorytetu obowiązuje FIFO. Dzięki temu STT (interaktywny,
    ~0,4 s) nie czeka za długim opisem VLM albo detekcją; detekcja nie wywłaszcza czatu.

    Priorytety: STT=0 (najpilniejsze), LLM/chat=1, wizja (VLM/detekcja)=2.
    """

    PRIO_STT = 0
    PRIO_LLM = 1
    PRIO_VISION = 2

    def __init__(self):
        self._cond = threading.Condition()
        self._holder = None
        self._depth = 0
        self._waiters = []
        self._seq = 0
        self._stats = {"acquires": 0, "waits": 0}

    def _acquire(self, prio):
        with self._cond:
            self._stats["acquires"] += 1
            me = threading.get_ident()
            # Reentrancja: ten sam wątek może wejść zagnieżdżone (np. wizja trzyma bramkę
            # i woła `get_vdevice`, który też ją bierze). Bez tego — martwy punkt (deadlock).
            if self._holder == me:
                self._depth += 1
                return
            if self._holder is None and not self._waiters:
                self._holder = me
                self._depth = 1
                return
            self._stats["waits"] += 1
            entry = (int(prio), self._seq, me)
            self._seq += 1
            self._waiters.append(entry)
            try:
                # Przechodzi wyłącznie CZOŁÓWKA posortowanej kolejki — `notify_all` budzi
                # wszystkich, ale tylko front sprawdza swój wpis (atomowo pod condition).
                while True:
                    if self._holder is None and self._waiters[0] == entry:
                        self._holder = me
                        self._depth = 1
                        self._waiters.remove(entry)
                        self._cond.notify_all()  # kolejka się zmieniła — obudź następnych
                        break
                    self._cond.wait()
            finally:
                if entry in self._waiters:
                    self._waiters.remove(entry)

    def _release(self):
        with self._cond:
            if self._holder is None:
                return
            self._depth -= 1
            if self._depth > 0:
                return
            self._holder = None
            if self._waiters:
                self._waiters.sort(key=lambda e: (e[0], e[1]))
                self._cond.notify_all()

    def __call__(self, prio=1):
        """Zwraca kontekstmenadżer bramki o danym priorytecie: `with gate(prio):`."""
        return _GateAcquire(self, prio)

    def summary(self):
        with self._cond:
            return dict(self._stats)


class _GateAcquire:
    __slots__ = ("_gate", "_prio")

    def __init__(self, gate, prio):
        self._gate = gate
        self._prio = prio

    def __enter__(self):
        self._gate._acquire(self._prio)
        return self

    def __exit__(self, *exc):
        self._gate._release()


class NpuEngine:
    """Jeden VDevice i modele genai w procesie ASTRO. Ładowanie leniwe, wątek-bezpieczne.

    Wszystkie operacje na NPU (STT/LLM/VLM) idą przez współdzieloną, priorytetową kolejkę
    `self.gate` — także detekcja YOLO/SCRFD z `vision/hailo.py` (ten sam proces).
    """

    def __init__(self, llm_hef="", whisper_hef=""):
        self.llm_hef = llm_hef or config.NPU_LLM_HEF or resolve_npu_llm_hef(config.NPU_MODEL)
        self.whisper_hef = whisper_hef or os.environ.get("ASTRO_NPU_HEF", "") or config.NPU_HEF
        self.vlm_hef = resolve_vlm_hef()
        self._vd = None
        self._llm = None
        self._s2t = None
        self._vlm = None
        self.gate = NpuGate()
        self._warmed = False
        # C3 (opt-in): poprzednia konwersacja do ewentualnego reuse KV (bez `clear_context`).
        self._kv_conv = None

    def whisper_ready(self):
        return hailo_platform_available() and bool(self.whisper_hef) \
            and os.path.exists(self.whisper_hef)

    def llm_ready(self):
        return hailo_platform_available() and bool(self.llm_hef) and os.path.exists(self.llm_hef)

    def vlm_ready(self):
        return hailo_platform_available() and bool(self.vlm_hef) \
            and os.path.exists(self.vlm_hef)

    def vlm_input_shape(self, ensure=False):
        """Oczekiwany kształt klatki VLM (h, w) wg modelu, albo None.

        Różne HEF-y mają różne wejście: Qwen2-VL-2B = kwadrat 336×336,
        Qwen3-VL-2B = 512×288 (prostokąt). `ensure=True` ładuje model (bramka NPU),
        jeśli jeszcze nie otwarty — kształt jest znany dopiero po załadowaniu.
        """
        try:
            if self._vlm is None and ensure:
                with self.gate(NpuGate.PRIO_VISION):
                    self._ensure_vlm()
            if self._vlm is None:
                return None
            shape = list(self._vlm.input_frame_shape() or [])
            if len(shape) >= 3 and shape[0] and shape[1]:
                return (int(shape[0]), int(shape[1]))
        except Exception:
            pass
        return None

    def available(self):
        return self.llm_ready() or self.whisper_ready() or self.vlm_ready()

    def _open(self):
        if self._vd is not None:
            return
        if not hailo_platform_available():
            raise RuntimeError("hailo_platform niedostępny")
        from hailo_platform import VDevice
        self._vd = VDevice()

    def get_vdevice(self):
        """Współdzielony VDevice (Hailo-10H = wyłączność procesu). Otwiera go leniwie.

        Używane przez inne sieci na NPU (np. detekcja YOLO w `vision/hailo.py`) — jedna
        instancja VDevice w procesie astro.service, więc nie ma konfliktu urządzenia.
        """
        with self.gate(NpuGate.PRIO_VISION):
            self._open()
            return self._vd

    def _ensure_s2t(self):
        if self._s2t is None:
            self._open()
            from hailo_platform.genai import Speech2Text
            self._s2t = Speech2Text(self._vd, self.whisper_hef)
        return self._s2t

    def _ensure_llm(self):
        if self._llm is None:
            self._open()
            if not self.llm_ready():
                raise RuntimeError("brak HEF LLM dla NPU")
            from hailo_platform.genai import LLM
            self._llm = LLM(self._vd, self.llm_hef)
        return self._llm

    def _ensure_vlm(self):
        if self._vlm is None:
            self._open()
            if not self.vlm_ready():
                raise RuntimeError("brak HEF VLM dla NPU")
            from hailo_platform.genai import VLM
            self._vlm = VLM(self._vd, self.vlm_hef)
        return self._vlm

    @staticmethod
    def _fit_context(conv, budget=5500):
        if sum(len(m["content"]) for m in conv) <= budget:
            return conv
        sysmsgs = [m for m in conv if m["role"] == "system"]
        rest = [m for m in conv if m["role"] != "system"]
        used = sum(len(m["content"]) for m in sysmsgs)
        keep = []
        for m in reversed(rest):
            c = m["content"]
            if used + len(c) > budget:
                c = c[:max(0, budget - used)]
                if c:
                    keep.append({"role": m["role"], "content": c})
                break
            keep.append(m)
            used += len(c)
        return sysmsgs + list(reversed(keep))

    def warm(self):
        """Rozgrzewa silniki NPU niezależnie (STT i LLM), raz, w tle.

        STT rozgrzewamy PRZED LLM i w osobnej próbie — brak HEF LLM nie może blokować
        wczytania Whisper-S2T (wcześniej jeden `try` przerywał warm przy `_ensure_llm`)."""
        if self._warmed:
            return
        self._warmed = True
        for ensure in (self._ensure_s2t, self._ensure_llm):
            try:
                with self.gate(NpuGate.PRIO_VISION):
                    ensure()
            except Exception:
                pass

    def transcribe(self, audio_f32, language="pl"):
        start = time.time()
        ok = True
        try:
            with self.gate(NpuGate.PRIO_STT):
                s2t = self._ensure_s2t()
                txt = s2t.generate_all_text(audio_data=audio_f32, language=language,
                                            timeout_ms=30000)
            return clean_npu_asr(txt)
        except Exception:
            ok = False
            raise
        finally:
            NPU_TELEMETRY.record("stt", time.time() - start, ok=ok,
                                 model=os.path.basename(self.whisper_hef) or "whisper")

    def _context_feed(self, llm, conv):
        """C3: zdecyduj, czy oddać pełną konwersację, czy tylko nowe tury (reuse KV).

        Reuse tylko gdy włączone (`ASTRO_NPU_KV_REUSE=1`) i konwersacja jest ŚCISŁYM rozszerzeniem
        poprzedniej (ten sam prefiks). W przeciwnym razie czyścimy kontekst — bezpiecznie."""
        reuse = (getattr(config, "NPU_KV_REUSE", False) and self._kv_conv is not None
                 and len(conv) > len(self._kv_conv) and conv[:len(self._kv_conv)] == self._kv_conv)
        if reuse:
            return conv[len(self._kv_conv):]
        try:
            llm.clear_context()
        except Exception:
            pass
        return conv

    def chat(self, messages, max_tokens=150, on_token=None, temperature=0.7):
        start = time.time()
        ok = True
        try:
            with self.gate(NpuGate.PRIO_LLM):
                llm = self._ensure_llm()
                conv = [{"role": m.get("role"), "content": m.get("content") or ""}
                        for m in messages if m.get("role") in ("system", "user", "assistant")]
                conv = self._fit_context(conv)
                feed = self._context_feed(llm, conv)
                try:
                    if on_token:
                        buf = []
                        with llm.generate(feed, temperature=temperature, top_p=0.8, top_k=20,
                                          max_generated_tokens=max_tokens) as gen:
                            for tok in gen:
                                buf.append(tok)
                                on_token(tok)
                                if any(s in "".join(buf[-4:]) for s in STOP_TOKENS):
                                    break
                        out = strip_stop_tokens("".join(buf))
                    else:
                        raw = llm.generate_all(feed, temperature=temperature, top_p=0.8, top_k=20,
                                               max_generated_tokens=max_tokens, timeout_ms=120000)
                        out = strip_stop_tokens(raw or "")
                    self._kv_conv = conv
                    return out
                except Exception:
                    self._kv_conv = None  # nie ufamy stanowi kontekstu po błędzie
                    raise
        except Exception:
            ok = False
            raise
        finally:
            NPU_TELEMETRY.record("chat", time.time() - start, ok=ok,
                                 model=os.path.basename(self.llm_hef) or "npu-llm")

    def describe_frame(self, image_rgb, question="", max_tokens=None):
        """Opis klatki (numpy RGB, uint8) przez VLM na NPU. Pojedynczy, świeży kontekst."""
        start = time.time()
        ok = True
        try:
            with self.gate(NpuGate.PRIO_VISION):
                vlm = self._ensure_vlm()
                try:
                    vlm.clear_context()
                except Exception:
                    pass
                prompt = [
                    {"role": "user", "content": [
                        {"type": "image"},
                        {"type": "text", "text": question or VLM_QUESTION_PL}]},
                ]
                out = vlm.generate_all(
                    prompt=prompt, frames=[image_rgb],
                    temperature=float(getattr(config, "VLM_TEMPERATURE", 0.1)),
                    top_p=float(getattr(config, "VLM_TOP_P", 0.8)),
                    top_k=int(getattr(config, "VLM_TOP_K", 20)),
                    frequency_penalty=float(getattr(config, "VLM_REPEAT_PENALTY", 1.15)),
                    do_sample=bool(getattr(config, "VLM_DO_SAMPLE", False)),
                    seed=42,
                    max_generated_tokens=int(max_tokens or getattr(config, "VLM_MAX_TOKENS", 96)))
            out = strip_stop_tokens(out or "")
            # Mały VLM (Qwen3-VL-2B) bywa „pusty" (od razu <|im_end|>) — jedna ponowna próba
            # z próbkowaniem (temperature 0.4) ratuje opis bez obciążania pozostałych ścieżek.
            if not out.strip():
                try:
                    vlm.clear_context()
                except Exception:
                    pass
                out = strip_stop_tokens(vlm.generate_all(
                    prompt=prompt, frames=[image_rgb],
                    temperature=0.4, top_p=0.9, top_k=40,
                    frequency_penalty=float(getattr(config, "VLM_REPEAT_PENALTY", 1.15)),
                    do_sample=True, seed=42,
                    max_generated_tokens=int(max_tokens or getattr(config, "VLM_MAX_TOKENS", 96))
                ) or "")
            return out
        except Exception:
            ok = False
            raise
        finally:
            NPU_TELEMETRY.record("vlm", time.time() - start, ok=ok,
                                 model=os.path.basename(self.vlm_hef) or "npu-vlm")

    def release(self):
        with self.gate(NpuGate.PRIO_STT):
            for obj in (self._s2t, self._llm, self._vlm):
                try:
                    if obj is not None:
                        obj.release()
                except Exception:
                    pass
            self._s2t = self._llm = self._vlm = None
            self._vd = None


NPU_ENGINE = NpuEngine()


def npu_status():
    hefs = available_hefs()
    holders = device_holders()
    return {
        "device_present": device_present(),
        "firmware": firmware_version(),
        "holders": holders,
        "busy": bool(holders),
        "hailo_platform": hailo_platform_available(),
        "hefs": hefs,
        "llm_ready": NPU_ENGINE.llm_ready(),
        "whisper_ready": NPU_ENGINE.whisper_ready(),
        "vlm_ready": NPU_ENGINE.vlm_ready(),
        "gate": NPU_ENGINE.gate.summary(),
        "telemetry": NPU_TELEMETRY.summary(),
        "telemetry_totals": NPU_TELEMETRY.totals(),
    }


def npu_status_text():
    s = npu_status()
    dev = "obecne" if s["device_present"] else "brak"
    fw = s["firmware"]
    busy = ("zajęte przez " + ", ".join(f"{h['comm']}({h['pid']})" for h in s["holders"])
            if s["busy"] else "wolne")
    w = s["hefs"]["whisper"]
    l = s["hefs"]["llm"]
    v = s["hefs"]["vlm"]
    lines = [
        f"NPU Hailo: urządzenie {dev} (FW {fw}, {busy}); hailo_platform: "
        f"{'OK' if s['hailo_platform'] else 'brak'}.",
        f"HEF Whisper: {'jest' if w['exists'] else 'brak'} ({w['path'] or '-'}).",
        f"HEF LLM: {'jest' if l['exists'] else 'brak'} ({l['path'] or '-'}).",
        f"HEF VLM: {'jest' if v['exists'] else 'brak'} ({v['path'] or '-'}).",
        f"Silniki: LLM {'gotowy' if s['llm_ready'] else 'niegotowy'}, "
        f"STT {'gotowy' if s['whisper_ready'] else 'niegotowy'}, "
        f"VLM {'gotowy' if s['vlm_ready'] else 'niegotowy'}.",
        NPU_TELEMETRY.text(),
    ]
    return " ".join(lines)


class NpuBackend(Backend):
    name = "npu"
    capabilities = {"chat"}

    def __init__(self, engine=None, model="qwen2.5-instruct:1.5b"):
        self.engine = engine or NPU_ENGINE
        self.model = model

    def ready(self):
        return self.engine.llm_ready()

    def run(self, messages, *, tools=None, fmt=None, max_tokens=150, temperature=0.7,
            on_token=None):
        if tools or fmt:
            raise RuntimeError("NPU nie obsługuje narzędzi/JSON")
        text = self.engine.chat(messages, max_tokens=max_tokens, on_token=on_token,
                                temperature=temperature)
        return BackendResult(text=text)
