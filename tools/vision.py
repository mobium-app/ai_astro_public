"""Wizja ASTRO: kamera sieciowa (ONVIF/RTSP) + AI (twarze/osoby/przedmioty/emocje).

Kamera sieciowa podłączona na stałe (`config.CAMERA_*`): klatka przez ffmpeg/PyAV z RTSP,
sterowanie położeniem (pan/tilt) przez ONVIF (`core.onvif`). AI (`astro.vision`) rozpoznaje
 osoby (baza twarzy w pamięci), ocenia otoczenie (obiekty COCO) i emocje. Opcjonalny opis
naturalny przez VLM (`ASTRO_VLM_MODEL`, Ollama). Gdy brak modeli — czytelny komunikat.
"""

import base64
import glob
import json
import os
import socket
import subprocess
import urllib.request

from .. import config
from ..core import onvif
from .registry import ToolResult, tool

_REGISTERED = False


def _camera_cfg(camera=None):
    """Konfiguracja wybranej kamery (dict). `camera` = indeks (1..N), nazwa lub słowo.

    Indeks 0 = główna kamera (`CAMERA_*`); dalsze z `CAMERA_SOURCES`
    („nazwa=rtsp|ptz|profil"). Bez argumentu — główna (kompatybilność wstecz).
    """
    if isinstance(camera, dict) and camera.get("rtsp"):
        return camera
    sources = camera_sources()
    if camera in (None, "", 0):
        return sources[0]
    sel = _camera_by_spec(camera, sources)
    return sel


_ORDINALS = {"pierwsza": 1, "pierwszej": 1, "pierwszym": 1, "druga": 2, "drugiej": 2,
             "drugim": 2, "trzecia": 3, "trzeciej": 3, "trzecim": 3, "czwarta": 4,
             "czwartej": 4, "czwartym": 4, "piata": 5, "piąta": 5, "piatej": 5,
             "piątej": 5, "piątym": 5, "piatym": 5}


def camera_sources():
    """Lista kamer: [0] = główna (`CAMERA_*`), dalej z `CAMERA_SOURCES`."""
    out = [{
        "enabled": bool(getattr(config, "CAMERA_ENABLED", False)),
        "host": getattr(config, "CAMERA_HOST", ""),
        "name": getattr(config, "CAMERA_NAME", "kamera"),
        "rtsp": getattr(config, "CAMERA_RTSP", ""),
        "ptz": getattr(config, "CAMERA_PTZ_URL", ""),
        "profile": getattr(config, "CAMERA_PROFILE", "profile_0"),
        "user": getattr(config, "CAMERA_USER", ""),
        "password": getattr(config, "CAMERA_PASS", ""),
        "speed": float(getattr(config, "CAMERA_SPEED", 0.6)),
        "move_ms": int(getattr(config, "CAMERA_MOVE_MS", 600)),
        "timeout": float(getattr(config, "CAMERA_TIMEOUT", 6)),
        "snapshot": getattr(config, "CAMERA_SNAPSHOT", "/tmp/astro-vision.jpg"),
        "index": 0,
    }]
    raw = str(getattr(config, "CAMERA_SOURCES", "") or "")
    for i, entry in enumerate(raw.split(","), start=1):
        entry = entry.strip()
        if not entry:
            continue
        name, _, rest = entry.partition("=")
        fields = [f.strip() for f in rest.split("|")] if rest else []
        rtsp = fields[0] if fields else ""
        ptz = fields[1] if len(fields) > 1 else ""
        profile = fields[2] if len(fields) > 2 else "profile_0"
        if not rtsp:
            continue
        out.append({
            "enabled": True, "host": _rtsp_host(rtsp),
            "name": name.strip() or f"kamera {i}",
            "rtsp": rtsp, "ptz": ptz,
            "profile": profile or "profile_0",
            "user": getattr(config, "CAMERA_USER", ""),
            "password": getattr(config, "CAMERA_PASS", ""),
            "speed": float(getattr(config, "CAMERA_SPEED", 0.6)),
            "move_ms": int(getattr(config, "CAMERA_MOVE_MS", 600)),
            "timeout": float(getattr(config, "CAMERA_TIMEOUT", 6)),
            "snapshot": os.path.join(os.path.dirname(
                str(getattr(config, "CAMERA_SNAPSHOT", "/tmp/astro-vision.jpg"))),
                f"astro-vision-{i}.jpg"),
            "index": i,
        })
    return out


def _rtsp_host(rtsp):
    from urllib.parse import urlparse
    try:
        return urlparse(rtsp).hostname or ""
    except Exception:
        return ""


def camera_count():
    """Liczba skonfigurowanych kamer (główna + `CAMERA_SOURCES`)."""
    return len(camera_sources())


def camera_names():
    return [c["name"] for c in camera_sources()]


def _camera_by_spec(spec, sources=None):
    """Rozpoznaje kamerę po numerze („1"/„2"), słowie („druga") lub nazwie („ogród").

    Podnosi ValueError z czytelnym komunikatem. 1..N (indeks źródła, 1 = główna).
    """
    sources = sources if sources is not None else camera_sources()
    s = str(spec or "").strip().lower()
    if not s:
        return sources[0]
    if s.isdigit():
        idx = int(s)
        if 1 <= idx <= len(sources):
            return sources[idx - 1]
        raise ValueError(f"mam tylko {len(sources)} kamer{'ę' if len(sources) == 1 else 'y'}")
    if s in _ORDINALS:
        idx = _ORDINALS[s]
        if 1 <= idx <= len(sources):
            return sources[idx - 1]
        raise ValueError(f"mam tylko {len(sources)} kamer{'ę' if len(sources) == 1 else 'y'}")
    for c in sources:
        if c["name"].lower() == s or s in c["name"].lower():
            return c
    raise ValueError(f"nie znam kamery: {spec!r}")


def camera_select(spec):
    """Bezpieczny wybór kamery: zwraca (kam, komunikat_ok) albo (None, błąd)."""
    try:
        return _camera_by_spec(spec), ""
    except ValueError as e:
        return None, str(e)


def network_camera_enabled():
    """Czy jakakolwiek kamera sieciowa jest skonfigurowana (główna lub dodatkowe źródła)."""
    return any(c["enabled"] and c["host"] and c["rtsp"] for c in camera_sources())


def local_camera_present():
    return bool(glob.glob("/dev/video*"))


def camera_present():
    return network_camera_enabled() or local_camera_present()


def camera_reachable(camera=None, timeout=1.5):
    """Szybki test: czy kamera sieciowa odpowiada (ONVIF:8899 albo port RTSP)."""
    cfg = _camera_cfg(camera)
    if not (cfg["enabled"] and cfg["host"]):
        return False
    port = 8899
    try:
        if cfg.get("ptz"):
            from urllib.parse import urlparse
            port = urlparse(cfg["ptz"]).port or 8899
        else:
            from urllib.parse import urlparse
            port = urlparse(cfg["rtsp"]).port or 554
    except Exception:
        pass
    try:
        with socket.create_connection((cfg["host"], port), timeout=timeout):
            return True
    except OSError:
        return False


def vlm_ready():
    return (_premium_vision_ready()
            or bool(getattr(config, "VLM_MODEL", "")) or _hailo_vlm_ready())


def _premium_vision_ready():
    """Czy premium vision dostępny: tryb premium + klucze OpenCode Go (2026-10-03)."""
    try:
        from ..backends import modes
        if modes.get_mode() != modes.PREMIUM:
            return False
        from .. import remote_support
        return bool(remote_support.load_keys().get("opencode"))
    except Exception:
        return False


def _vlm_caption_premium(frame_path, question=""):
    """Opis klatki przez modele premium (OpenCode Go, multimodalny format OpenAI).

    Wysyła zmniejszony JPEG (`_image_b64`, ~896 px) — mniej tokenów obrazu; modele darmowe
    (space-bunny/longcat) mają vision. Pusty przy błędzie/nie-polskiej odpowiedzi."""
    try:
        from .. import remote_support
    except Exception:
        return ""
    try:
        b64 = _image_b64(frame_path)
        if not b64:
            return ""
        prompt = question or (
            "Opisz po polsku krótko (2-3 zdania), co widzisz na zdjęciu z kamery domowej: "
            "główna scena, osoby i ich wygląd, przedmioty, nastrój/ekspresja jeśli widoczna.")
        messages = [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
        ]}]
        res = remote_support.ask_full(messages, max_tokens=500, temperature=0.1,
                                      chain=remote_support.opencode_chain(), kind="vision")
        if not res:
            return ""
        text = (res[0] or "").strip()
        return text if _looks_polish(text) else ""
    except Exception:
        return ""


def vlm_backend():
    """Który backend opisuje scenę: 'hailo' (NPU, offline) albo 'ollama' albo 'off'."""
    hailo = _hailo_vlm_ready()
    ollama = bool(getattr(config, "VLM_MODEL", ""))
    if str(getattr(config, "VLM_PREFER", "ollama")).lower() == "hailo":
        return "hailo" if hailo else ("ollama" if ollama else "off")
    return "ollama" if ollama else ("hailo" if hailo else "off")


def _hailo_vlm_ready():
    if not getattr(config, "VLM_HAILO", False):
        return False
    try:
        from ..backends import npu
        return npu.NPU_ENGINE.vlm_ready()
    except Exception:
        return False


def _ollama_reachable(timeout=1.0):
    """Szybki test: czy serwer VLM (Ollama, tunel do Kali) odpowiada na porcie."""
    if not getattr(config, "VLM_MODEL", ""):
        return False
    try:
        from urllib.parse import urlparse
        u = urlparse(config.VLM_URL)
        host = u.hostname or "127.0.0.1"
        port = u.port or 11434
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _flip_filter():
    flip = str(getattr(config, "CAMERA_FLIP", "none") or "none").lower()
    if flip in ("180", "1", "true", "yes", "on", "rotate180"):
        return "hflip,vflip"
    if flip in ("hflip", "vflip"):
        return flip
    return ""


def _snapshot_rtsp(url, path, timeout=15):
    """Zapisuje jedną klatkę z RTSP (najpierw ffmpeg, potem PyAV). Zwraca path lub None."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass
    import shutil
    if shutil.which("ffmpeg"):
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-rtsp_transport", "tcp", "-i", url]
        vf = _flip_filter()
        if vf:
            cmd += ["-vf", vf]
        cmd += ["-frames:v", "1", "-q:v", "3", path]
        try:
            subprocess.run(cmd, capture_output=True, timeout=timeout)
            if os.path.isfile(path) and os.path.getsize(path) > 0:
                return path
        except Exception:
            pass
    try:
        import av  # PyAV
        container = av.open(url, options={"rtsp_transport": "tcp", "stimeout": "5000000"})
        stream = next((s for s in container.streams if s.type == "video"), None)
        if stream is not None:
            for frame in container.decode(stream):
                image = frame.to_image()
                if _flip_filter() == "hflip,vflip":
                    from PIL import Image
                    image = image.transpose(Image.ROTATE_180)
                image.save(path, "JPEG", quality=85)
                break
        container.close()
    except Exception:
        return None
    return path if os.path.isfile(path) and os.path.getsize(path) > 0 else None


def _snapshot_local(path):
    import shutil
    cameras = sorted(glob.glob("/dev/video*"))
    if not cameras:
        return None
    device = cameras[0]
    if shutil.which("fswebcam"):
        cmd = ["fswebcam", "-d", device, "-r", "1280x720", "--no-banner", path]
    elif shutil.which("ffmpeg"):
        cmd = ["ffmpeg", "-y", "-f", "v4l2", "-i", device, "-frames:v", "1", path]
    else:
        return None
    try:
        subprocess.run(cmd, capture_output=True, timeout=20)
    except Exception:
        return None
    return path if os.path.isfile(path) else None


def capture_frame(path=None, timeout=15, camera=None):
    """Zapisuje klatkę z wybranej kamery (sieciowa -> lokalna). Zwraca ścieżkę lub None.

    `camera` = indeks („2"), słowo („druga") lub nazwa; domyślnie główna (`CAMERA_*`).
    """
    cfg = _camera_cfg(camera)
    path = path or cfg["snapshot"]
    if cfg["enabled"] and cfg["host"] and cfg["rtsp"]:
        return _snapshot_rtsp(cfg["rtsp"], path, timeout)
    if camera is None and local_camera_present():
        return _snapshot_local(path)
    return None


def ptz_nudge(direction, ms=None, camera=None):
    """Ruch kamery w kierunku przez `ms`. Zwraca (x, y). Podnosi onvif.OnvifError."""
    cfg = _camera_cfg(camera)
    onvif.resolve_direction(direction)
    return onvif.nudge(cfg["ptz"], cfg["profile"], direction,
                       ms if ms is not None else cfg["move_ms"], cfg["speed"],
                       cfg["user"], cfg["password"], cfg["timeout"])


def ptz_home(camera=None):
    cfg = _camera_cfg(camera)
    onvif.home(cfg["ptz"], cfg["profile"], cfg["user"], cfg["password"], cfg["timeout"])


# --- AI: ocena sceny / rozpoznawanie osób ----------------------------------------------------
def _load_bgr(path):
    try:
        import cv2
        return cv2.imread(path)
    except Exception:
        return None


def _overlap(face_box, person_box):
    """Pole przecięcia twarzy [x,y,w,h] z ramką osoby [x1,y1,x2,y2]."""
    fx1, fy1 = face_box[0], face_box[1]
    fx2, fy2 = face_box[0] + face_box[2], face_box[1] + face_box[3]
    px1, py1, px2, py2 = person_box[0], person_box[1], person_box[2], person_box[3]
    ix = max(0.0, min(fx2, px2) - max(fx1, px1))
    iy = max(0.0, min(fy2, py2) - max(fy1, py1))
    return ix * iy


def face_entries(img, memory=None, min_area=0.003):
    """Twarze w klatce z embeddingiem i dopasowaniem do galerii (name|None, score)."""
    from ..vision import engine
    out = []
    if not engine.available("recognize"):
        return out
    area = float(img.shape[0] * img.shape[1])
    try:
        faces = engine.detect_faces(img, score=0.6)
    except Exception:
        return out
    faces = [f for f in faces if f["box"][2] * f["box"][3] >= min_area * area]
    for f in faces:
        try:
            emb = engine.face_embedding(img, f)
        except Exception:
            emb = None
        name, score = None, 0.0
        if emb is not None and memory is not None:
            try:
                name, score = memory.match_face(emb, getattr(config, "FACE_MATCH_THRESHOLD",
                                                             0.40))
            except Exception:
                name, score = None, 0.0
        out.append({"face": f, "emb": emb, "name": name, "score": score})
    return out


def assess_current(memory=None, objects=True, faces=True, camera=None):
    """Robie klatkę i ocenia scenę. Zwraca (frame_path, assessment|None)."""
    frame = capture_frame(camera=camera)
    if not frame:
        return None, None
    img = _load_bgr(frame)
    if img is None:
        return frame, None
    from ..vision import scene
    assess = scene.assess(img, memory=memory, objects=objects, faces=faces)
    # Loguj zobaczenia rozpoznanych osób (pod „kto był dziś"); pomiń przy enroll w toku.
    if memory is not None and getattr(config, "FACE_LOG", True):
        for k in (assess.get("known") or []):
            try:
                memory.add_sighting(k["name"], k.get("score", 0.0), known=True)
            except Exception:
                pass
    # Wyraz twarzy -> stan afektywny (Faza 3): radość/smutek/gniew w kadrze podbija lub
    # studzi emocję i nastrój ASTRO (PAD). Tylko lokalnie, bez modelu i bez sieci.
    if memory is not None and getattr(config, "AFFECT_VISION", True) and assess.get("expression"):
        try:
            from ..affect import appraisal
            state = memory.affect.load()
            state.apply(*appraisal.expression_pad(assess["expression"]))
            memory.affect.save(state)
        except Exception:
            pass
    return frame, assess


def describe_frame(frame_path, question=""):
    """Publiczny opis klatki dla warstw wyżej (premium → lokalny fallback). 2026-10-03."""
    return _vlm_caption(frame_path, question)


def _vlm_caption(frame_path, question=""):
    """Opis klatki: w trybie premium — chmura (OC Go, vision), dalej lokalny fallback."""
    if _premium_vision_ready():
        text = _vlm_caption_premium(frame_path, question)
        if text:
            return text
    prefer = str(getattr(config, "VLM_PREFER", "ollama")).lower()
    order = ("hailo", "ollama") if prefer == "hailo" else ("ollama", "hailo")
    for backend in order:
        if backend == "hailo" and _hailo_vlm_ready():
            text = _vlm_caption_hailo(frame_path, question)
        elif backend == "ollama" and _ollama_reachable():
            text = _vlm_caption_ollama(frame_path, question)
        else:
            text = ""
        if text:
            return text
    return ""


def _vlm_caption_ollama(frame_path, question=""):
    """Opis klatki przez VLM na Ollama (Kali/PC). Pusty, gdy model nieustawiony/błąd."""
    if not getattr(config, "VLM_MODEL", ""):
        return ""
    try:
        b64 = _image_b64(frame_path)
        if not b64:
            return ""
        prompt = question or ("Opisz jednym lub dwoma zdaniami po polsku, co widzisz: ile osób, "
                              "co robią, jakie przedmioty.")
        payload = json.dumps({
            "model": config.VLM_MODEL, "prompt": prompt, "images": [b64], "stream": False,
            "options": {"temperature": 0.1, "repeat_penalty": 1.2, "num_predict": 160,
                        "num_ctx": int(getattr(config, "VLM_NUM_CTX", 8192))}}).encode()
        req = urllib.request.Request(
            config.VLM_URL.rstrip("/") + "/api/generate", data=payload,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=getattr(config, "VLM_TIMEOUT", 120)) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        return (data.get("response") or "").strip()
    except Exception:
        return ""


def _image_rgb(path, size=336):
    """Klatka jako numpy RGB uint8 (kwadrat `size`×`size` albo prostokąt (H,W)).

    Skaluje z zachowaniem proporcji i kadruje centralnie (jak `convert_resize_image` z
    hailo-apps) — zwykłe rozciągnięcie zniekształca obraz i psuje opis. Rozmiar może być
    parą (h, w) — np. Qwen3-VL na Hailo oczekuje 512×288, Qwen2-VL kwadratu 336×336."""
    try:
        import cv2
        img = cv2.imread(path)
        if img is None:
            return None
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        h, w = img.shape[:2]
        if isinstance(size, (tuple, list)) and len(size) == 2:
            th, tw = int(size[0]), int(size[1])
        else:
            th = tw = int(size)
        if th <= 0 or tw <= 0:
            return None
        scale = max(tw / float(w), th / float(h))
        nw, nh = int(round(w * scale)), int(round(h * scale))
        img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
        x, y = (nw - tw) // 2, (nh - th) // 2
        img = img[y:y + th, x:x + tw]
        return img.astype("uint8")
    except Exception:
        return None


def _vlm_caption_hailo(frame_path, question=""):
    """Opis klatki przez VLM na NPU Hailo (in-process, wspólny VDevice ze STT/LLM)."""
    try:
        from ..backends import npu
        engine = npu.NPU_ENGINE
        if not engine.vlm_ready():
            return ""
        # Kształt klatki wg modelu (np. Qwen3-VL: 512×288, Qwen2-VL: 336×336) albo env.
        # `ensure=True` — kształt znamy dopiero po załadowaniu VLM (ładuje i tak opis).
        shape = engine.vlm_input_shape(ensure=True)
        if not shape:
            px = int(getattr(config, "VLM_HAILO_IMAGE_PX", 336))
            shape = (px, px)
        img = _image_rgb(frame_path, shape)
        if img is None:
            return ""
        out = engine.describe_frame(img, question)
        # Mały VLM (2B) czasem „ucieka" w angielski/odmowy lub zaczyna od śmieci — czyścimy.
        out = _clean_caption(out)
        return out if _looks_polish(out) else ""
    except Exception:
        return ""


_EN_MARKERS = (" the ", " and ", " you ", " this ", " image", " please ", " sorry")
_PL_LETTERS = "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"


def _looks_polish(text):
    """Heurystyka: czy opis jest po polsku (odrzuca angielskie odmowy, CJK i zapętlenia)."""
    t = (text or "").strip()
    if not t:
        return False
    if any("\u4e00" <= ch <= "\u9fff" for ch in t):
        return False
    # Mały VLM (2B) potrafi wejść w pętlę — odrzucamy powtarzające się fragmenty.
    if len(t) > 36:
        for i in range(len(t) - 12):
            if t.count(t[i:i + 12]) >= 3:
                return False
    if any(ch in _PL_LETTERS for ch in t):
        return True
    low = " " + t.lower() + " "
    return not any(w in low for w in _EN_MARKERS)


def _clean_caption(text):
    """Usuwa artefakty dekodowania VLM (śmieciowe prefiksy, ucięte/zapętlone ogony).

    Mały model 2B zaczyna czasem od tokenów-specjalnych („!Zobacz:", „Assistant:") lub kończy
    listą bez sensu — czyścimy brzegi, nie zmieniając sensu."""
    t = (text or "").strip()
    # Zdejmij śmieciowe prefiksy i wiodące znaki, ale zachowaj końcową interpunkcję zdania.
    t = t.lstrip("!¡ \t\n")
    for junk in ("Assistant:", "assistant:", "Asystent:", "Odpowiedź:", "Response:"):
        if t.startswith(junk):
            t = t[len(junk):].strip()
    t = t.lstrip("!¡ ").strip()
    # ucięte ogony typu „... ważne przedmioty takie jak" (spójnik na końcu)
    t = _trim_dangling_tail(t)
    return t.strip()


_DANGLING = ("takie jak", "tak jak", "na przykład", "np.", "także", "oraz", "i", "a", "że",
             "które", "który", "jest", "są", "to", "w", "na", "z", "do", "o", "że")


def _trim_dangling_tail(text):
    """Obcina końcowy niedokończony fragment (spójnik/przyimek bez dopełnienia)."""
    t = (text or "").strip()
    # Zachowaj końcową interpunkcję zdania — obcinamy tylko wiszące słowa funkcjonalne.
    tail_punct = t[-1] if t and t[-1] in ".!?…" else ""
    if tail_punct:
        t = t[:-1].rstrip()
    for _ in range(4):
        low = t.lower()
        cut = None
        for w in _DANGLING:
            suffix = " " + w
            if low.endswith(suffix):
                cut = len(t) - len(suffix)
                break
        if cut is None:
            break
        t = t[:cut].rstrip(" ,;:-")
    if tail_punct:
        return t + tail_punct
    if len(t) > 15:
        t += "."
    return t


def _image_b64(path, max_side=None):
    """Wczytuje obraz i zwraca base64 (JPEG), zmniejszony do `ASTRO_VLM_IMAGE_PX` (dom. 896)."""
    max_side = max_side or int(getattr(config, "VLM_IMAGE_PX", 896))
    try:
        import io
        from PIL import Image
        im = Image.open(path)
        im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        try:
            with open(path, "rb") as fh:
                return base64.b64encode(fh.read()).decode()
        except OSError:
            return ""


def register():
    global _REGISTERED
    if _REGISTERED:
        return
    _REGISTERED = True

    @tool("camera_look",
          "Patrzy przez kamerę: rozpoznaje osoby, ocenia otoczenie (obiekty, emocje) i opisuje.",
          {"type": "object", "properties": {"question": {"type": "string"},
                                            "camera": {"type": "string"}}}, scopes=("read",))
    def camera_look(ctx, question="", camera=None):
        cam, err = camera_select(camera)
        if err:
            return ToolResult(err, ok=False)
        if not camera_present():
            return ToolResult("Brak kamery (sieciowej ani /dev/video*) — wizja nieaktywna.",
                              ok=False)
        if not (cam["enabled"] and cam["host"] and cam["rtsp"]):
            return ToolResult(f"Brak kamery {cam['name']} (sieciowej ani /dev/video*) — "
                              f"wizja nieaktywna.", ok=False)
        if network_camera_enabled() and not camera_reachable(cam):
            return ToolResult(f"Kamera {cam['name']} nie odpowiada ({cam['host']}).", ok=False)
        frame, assessment = assess_current(getattr(ctx, "memory", None), camera=cam)
        if not frame:
            return ToolResult("Kamera obecna, ale nie mogę zapisać klatki (ffmpeg/PyAV).",
                              ok=False)
        if assessment is not None:
            from ..vision import scene
            text = scene.describe(assessment)
        else:
            text = "Zapisałem klatkę (analiza AI niedostępna — brak modeli wizji)."
        caption = _vlm_caption(frame, question)
        if caption:
            text += " " + caption
        return ToolResult(text, data={"frame": frame, "assessment": assessment})

    @tool("camera_move",
          "Obraca kamerę w kierunku (left/right/up/down/up-left/up-right/down-left/down-right).",
          {"type": "object", "properties": {
              "direction": {"type": "string"},
              "duration_ms": {"type": "integer"},
              "camera": {"type": "string"}}}, scopes=("read",))
    def camera_move(ctx, direction="", duration_ms=None, camera=None):
        cam, err = camera_select(camera)
        if err:
            return ToolResult(err, ok=False)
        if not cam["ptz"]:
            return ToolResult(f"Kamera {cam['name']} nie ma sterowania PTZ.", ok=False)
        try:
            x, y = ptz_nudge(direction, duration_ms, camera=cam)
        except (onvif.OnvifError, ValueError) as e:
            return ToolResult(f"Nie udało się obrócić kamery: {e}", ok=False)
        return ToolResult(f"Obracam kamerę {cam['name']}: {direction} (x={x}, y={y}).",
                          data={"x": x, "y": y})

    @tool("camera_home",
          "Ustawia kamerę w pozycji domowej (na wprost).",
          {"type": "object", "properties": {"camera": {"type": "string"}}}, scopes=("read",))
    def camera_home(ctx, camera=None):
        cam, err = camera_select(camera)
        if err:
            return ToolResult(err, ok=False)
        if not cam["ptz"]:
            return ToolResult(f"Kamera {cam['name']} nie ma sterowania PTZ.", ok=False)
        try:
            ptz_home(camera=cam)
        except onvif.OnvifError as e:
            return ToolResult(f"Nie udało się wrócić do pozycji domowej: {e}", ok=False)
        return ToolResult(f"Ustawiam kamerę {cam['name']} na wprost.")

    @tool("camera_scene",
          "Ocenia otoczenie z kamery: ile osób, jakie przedmioty, emocja, oświetlenie.",
          {"type": "object", "properties": {"camera": {"type": "string"}}}, scopes=("read",))
    def camera_scene(ctx, camera=None):
        cam, err = camera_select(camera)
        if err:
            return ToolResult(err, ok=False)
        if not (cam["enabled"] and cam["host"] and cam["rtsp"]):
            return ToolResult("Brak kamery — nie mogę ocenić otoczenia.", ok=False)
        _frame, assessment = assess_current(getattr(ctx, "memory", None), camera=cam)
        if assessment is None:
            return ToolResult("Nie mogę pobrać/analizować obrazu z kamery.", ok=False)
        from ..vision import scene
        return ToolResult(scene.describe(assessment), data={"assessment": assessment})

    @tool("camera_ocr",
          "Czyta tekst widoczny w kamerze (np. z kartki, ekranu, dokumentu) po polsku.",
          {"type": "object", "properties": {"camera": {"type": "string"}}}, scopes=("read",))
    def camera_ocr(ctx, camera=None):
        from ..vision import ocr
        if not ocr.available():
            return ToolResult("Brak silnika OCR (zainstaluj `tesseract-ocr`).", ok=False)
        cam, err = camera_select(camera)
        if err:
            return ToolResult(err, ok=False)
        if not (cam["enabled"] and cam["host"] and cam["rtsp"]):
            return ToolResult("Brak kamery — nie mogę odczytać tekstu.", ok=False)
        frame = capture_frame(camera=cam)
        if not frame:
            return ToolResult("Nie mogę pobrać obrazu z kamery.", ok=False)
        text = ocr.read_text(frame)
        if not text:
            return ToolResult("Nie widzę czytelnego tekstu w obrazie z kamery.",
                              data={"frame": frame})
        # Spięcie OCR z kontekstem (Faza 5): zapisujemy odczyt w `vision_notes`, by dało się
        # wrócić do niego („co było napisane") i mieć ślad w pamięci długoterminowej.
        memory = getattr(ctx, "memory", None)
        if memory is not None:
            try:
                memory.add_vision_note("ocr", text)
            except Exception:
                pass
        return ToolResult(f"Odczytany tekst: {text}", data={"frame": frame, "text": text})

    @tool("ocr_recent",
          "Przypomina, co ostatnio przeczytałaś z kamery (OCR) — ostatnie odczyty.",
          {"type": "object", "properties": {}}, scopes=("read",))
    def ocr_recent(ctx):
        import time as _t
        memory = getattr(ctx, "memory", None)
        if memory is None:
            return ToolResult("Brak pamięci odczytów.", ok=False)
        rows = memory.recent_vision_notes(limit=3, kinds=("ocr",))
        if not rows:
            return ToolResult("Jeszcze nic nie czytałam z kamery.", data={"notes": []})
        parts = []
        for r in rows:
            hm = _t.strftime("%H:%M", _t.localtime(r["ts"]))
            parts.append(f"o {hm}: {r['text']}")
        return ToolResult("Ostatnie odczyty z kamery: " + " | ".join(parts) + ".",
                          data={"notes": rows})

    @tool("vision_events",
          "Co się ostatnio działo przed kamerą: wejścia, wyjścia, ruch, zmiany sceny.",
          {"type": "object", "properties": {"limit": {"type": "integer"}}}, scopes=("read",))
    def vision_events(ctx, limit=5):
        import time as _t
        path = os.path.join(str(config.RUNTIME_DIR), "vision_events.jsonl")
        try:
            with open(path, encoding="utf-8") as fh:
                lines = [l for l in fh if l.strip()]
        except OSError:
            return ToolResult("Brak zapisanych zdarzeń z kamery.", data={"events": []})
        n = max(1, min(int(limit or 5), 50))
        events = []
        for line in lines[-n:]:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            events.append(ev)
        if not events:
            return ToolResult("Brak zapisanych zdarzeń z kamery.", data={"events": []})
        parts = []
        for ev in events:
            hm = _t.strftime("%H:%M", _t.localtime(float(ev.get("ts") or 0)))
            parts.append(f"{hm}: {ev.get('text') or ev.get('kind')}")
        return ToolResult("Ostatnie zdarzenia z kamery: " + " | ".join(parts) + ".",
                          data={"events": events})

    @tool("camera_people",
          "Mówi, kto jest widoczny w kamerze (rozpoznane osoby + nieznane).",
          {"type": "object", "properties": {"camera": {"type": "string"}}}, scopes=("read",))
    def camera_people(ctx, camera=None):
        cam, err = camera_select(camera)
        if err:
            return ToolResult(err, ok=False)
        _frame, assessment = assess_current(getattr(ctx, "memory", None),
                                            objects=True, faces=True, camera=cam)
        if assessment is None:
            return ToolResult("Nie mogę pobrać obrazu z kamery.", ok=False)
        from ..vision import scene
        return ToolResult(scene.who(assessment), data={"assessment": assessment})

    @tool("person_enroll",
          "Zapamiętuje osobę z kamery pod podanym imieniem (rozpoznawanie twarzy + sylwetki).",
          {"type": "object", "properties": {"name": {"type": "string"}}}, scopes=("read",))
    def person_enroll(ctx, name=""):
        from ..memory.store import normalize_name
        name = normalize_name(name)
        if not name:
            return ToolResult("Podaj imię, pod którym mam zapamiętać osobę.", ok=False)
        memory = getattr(ctx, "memory", None)
        if memory is None:
            return ToolResult("Brak pamięci — nie mogę zapisać osoby.", ok=False)
        frame = capture_frame()
        img = _load_bgr(frame) if frame else None
        if img is None:
            return ToolResult("Nie mogę pobrać obrazu z kamery.", ok=False)
        # Detekcję robimy na klatce przeskalowanej do ~1280 px (lepsza pewność i spójność).
        if max(img.shape[:2]) > 1280:
            import cv2
            s = 1280.0 / max(img.shape[:2])
            img = cv2.resize(img, (int(img.shape[1] * s), int(img.shape[0] * s)),
                             interpolation=cv2.INTER_AREA)
        from ..vision import engine
        if not engine.available("recognize"):
            return ToolResult("Brak modeli rozpoznawania twarzy (models/vision).", ok=False)
        try:
            entries = face_entries(img, memory)
        except Exception as e:
            return ToolResult(f"Błąd rozpoznawania twarzy: {e}", ok=False)
        if not entries:
            return ToolResult("Nie widzę twarzy — stań twarzą do kamery i powtórz.", ok=False)
        # Priorytet: największa twarz, która NIE jest jeszcze rozpoznana (dodanie nowej osoby,
        # gdy ktoś znany też jest w kadrze — np. żona obok mnie). Gdy wszystkie znane — największa.
        unmatched = [e for e in entries if not e["name"]]
        pool = unmatched or entries
        target = max(pool, key=lambda e: e["face"]["box"][2] * e["face"]["box"][3])
        emb = target["emb"]
        if emb is None:
            return ToolResult("Nie udało się policzyć cech twarzy.", ok=False)
        memory.add_face(name, emb, source="voice-enroll")
        try:
            from ..vision import privacy
            privacy.audit("enroll", target=name, note="twarz")
        except Exception:
            pass
        # Sylwetka (re-ID): zapisz też ciało, by rozpoznawać osobę, gdy twarzy nie widać.
        body_saved = False
        if getattr(config, "BODY_ENABLED", True) and engine.available("bodies"):
            try:
                boxes = engine.person_boxes(img)
                if boxes:
                    fbox = target["face"]["box"]
                    best = max(boxes, key=lambda b: _overlap(fbox, b))
                    if _overlap(fbox, best) <= 0:
                        best = max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
                    bemb = engine.person_embedding(img, best)
                    if bemb is not None:
                        memory.add_body(name, bemb, source="voice-enroll")
                        body_saved = True
            except Exception:
                body_saved = False
        known = sorted({e["name"] for e in entries if e["name"]} - {name})
        text = f"Zapamiętałem: {name}." + (" (twarz i sylwetka)" if body_saved else " (twarz)")
        if known:
            text += " W kadrze rozpoznaję też: " + ", ".join(known) + "."
        others = len(unmatched) - (1 if target in unmatched else 0)
        if others > 0:
            text += f" W kadrze jest jeszcze {others} nieznana twarz — powtórz dla niej zapis."
        return ToolResult(text, data={"name": name, "body": body_saved})

    @tool("person_forget",
          "Usuwa zapamiętaną osobę (twarz i sylwetkę) z rozpoznawania.",
          {"type": "object", "properties": {"name": {"type": "string"}}}, scopes=("read",))
    def person_forget(ctx, name=""):
        memory = getattr(ctx, "memory", None)
        name = (name or "").strip()
        if memory is None or not name:
            return ToolResult("Podaj imię osoby do usunięcia.", ok=False)
        n = memory.forget_person(name)
        try:
            from ..vision import privacy
            privacy.audit("forget", target=name, note=f"usunieto={n}")
        except Exception:
            pass
        return ToolResult(f"Usunięto {n} wpis(y) dla: {name}." if n
                          else f"Nie znam osoby: {name}.", ok=bool(n))

    @tool("person_list",
          "Lista osób zapamiętanych w rozpoznawaniu (twarz/sylwetka).",
          {"type": "object", "properties": {}}, scopes=("read",))
    def person_list(ctx):
        memory = getattr(ctx, "memory", None)
        names = []
        if memory is not None:
            for f in memory.list_faces():
                if f["name"] not in names:
                    names.append(f["name"])
            for b in memory.list_bodies():
                if b["name"] not in names:
                    names.append(b["name"])
        if not names:
            return ToolResult("Nie znam jeszcze nikogo — powiedz „zapamiętaj, to jest <imię>\".")
        return ToolResult(f"Znam {len(names)}: {', '.join(names)}.", data={"names": names})

    @tool("person_sightings",
          "Kto był widziany (dziś/ostatnio): imiona, ile razy i o której ostatnio.",
          {"type": "object", "properties": {"period": {"type": "string"}}}, scopes=("read",))
    def person_sightings(ctx, period="today"):
        import time as _t
        memory = getattr(ctx, "memory", None)
        if memory is None:
            return ToolResult("Brak pamięci zobaczeń.", ok=False)
        now = _t.time()
        low = (period or "today").lower()
        if low in ("week", "tydzien", "tydzień", "7dni", "7"):
            since = now - 7 * 86400
        elif low in ("all", "wszystko", "kiedykolwiek"):
            since = 0
        else:
            lt = _t.localtime(now)
            since = _t.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
        summary = memory.sightings_summary(day_start=since)
        if not summary:
            return ToolResult("Nie widziałem dziś nikogo.", data={"sightings": []})
        parts = []
        for s in summary:
            hm = _t.strftime("%H:%M", _t.localtime(s["last"]))
            parts.append(f"{s['name']} ({s['count']}x, ostatnio {hm})")
        label = {"week": "przez ostatni tydzień", "all": "kiedykolwiek"}.get(low, "dziś")
        return ToolResult(f"Widziany {label}: " + "; ".join(parts) + ".",
                          data={"sightings": summary})

    @tool("vision_status",
          "Status wizji: dostępne modele (twarze/obiekty/emocje/wiek-płeć/sylwetka), VLM, nastrój.",
          {"type": "object", "properties": {}}, scopes=("read",))
    def vision_status(ctx):
        from ..vision import engine
        from ..memory import biocrypto
        memory = getattr(ctx, "memory", None)
        known = memory.list_faces() if memory is not None else []
        bodies = memory.list_bodies() if memory is not None else []
        cam_n = len(camera_sources())
        parts = [f"kamera={'on' if network_camera_enabled() else 'off'}"
                 + (f" ({cam_n})" if cam_n > 1 else ""),
                 f"twarze={'on' if engine.available('face') else 'off'}",
                 f"rozpoznawanie={'on' if engine.available('recognize') else 'off'}",
                 f"sylwetka={'on' if engine.available('bodies') else 'off'}",
                 f"obiekty={'on' if engine.available('objects') else 'off'}",
                 f"emocje={'on' if engine.available('expression') else 'off'}",
                 f"wiek/plec={'on' if engine.available('agegender') else 'off'}",
                 f"VLM={vlm_backend()}",
                 f"biometria_szyfrowana={'on' if biocrypto.available() else 'off'}",
                 f"znane osoby={len(known)} (sylwetki={len(bodies)})"]
        if memory is not None:
            try:
                mood = memory.affect.load().describe()[0]
                parts.append(f"nastroj={mood}")
            except Exception:
                pass
        try:
            from ..vision import privacy
            parts.append(f"nasłuch={'off' if privacy.watch_off() else 'on'}")
        except Exception:
            pass
        return ToolResult("Wizja: " + ", ".join(parts) + ".",
                          data={"known": known, "bodies": bodies})

    @tool("vision_forget_unknowns",
          "Czyści zobaczenia nieznanych osób (i stare wg retencji).",
          {"type": "object", "properties": {}}, scopes=("read",))
    def vision_forget_unknowns(ctx):
        memory = getattr(ctx, "memory", None)
        if memory is None:
            return ToolResult("Brak pamięci zobaczeń.", ok=False)
        n = memory.con.execute("DELETE FROM face_sightings WHERE name='?'").rowcount
        memory.con.commit()
        purged = memory.purge_sightings()
        try:
            from ..vision import privacy
            privacy.audit("purge_sightings", note=f"usunieto={n},stare={purged}")
        except Exception:
            pass
        return ToolResult(f"Usunięto {n} zobaczeń nieznanych; wyczyszczono stare: {purged}.",
                          data={"deleted": n, "purged": purged})
