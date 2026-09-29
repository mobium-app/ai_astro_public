#!/usr/bin/env python3
"""ASTRO — API wizji („oczy"): podgląd z ramkami, detekcje, galeria osób.

Lekki serwis na Pi (gdzie są modele AI i pamięć ASTRO) dla panelu na Kali. Kamera jest
bez logowania (LAN), a serwis binduje się do sieci lokalnej — nie wystawiaj go publicznie.

Endpointy:
  GET  /                      strona podglądu (ramki + galeria)
  GET  /stream.mjpg           MJPEG z narysowanymi ramkami (twarze/obiekty)
  GET  /annotated.jpg         pojedyncza klatka z ramkami
  GET  /detect.json           JSON: twarze (z imionami) + obiekty + opis
  GET  /faces                 galeria osób
  POST /enroll?name=X         zapamiętaj twarz z kamery pod imieniem
  POST /forget?name=X         usuń osobę
  GET  /health                status

Uruchomienie:  python3 scripts/vision_api.py --host 0.0.0.0 --port 8099
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.dirname(os.path.dirname(_HERE)), os.path.dirname(_HERE), _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from flask import Flask, Response, jsonify, request  # noqa: E402

from astro import config  # noqa: E402
from astro.memory import default_memory  # noqa: E402
from astro.tools import ToolContext, registry, vision  # noqa: E402
from astro.vision import engine, scene  # noqa: E402

app = Flask(__name__)

WIDTH = int(os.environ.get("ASTRO_VISION_API_W", "1280"))
DETECT_EVERY = float(os.environ.get("ASTRO_VISION_API_DETECT_S", "0.7"))
FPS = int(os.environ.get("ASTRO_VISION_API_FPS", "10"))
JPEG_Q = int(os.environ.get("ASTRO_VISION_API_JPEG_Q", "80"))
BOUNDARY = "frame"

_MEM = None
_MEM_LOCK = threading.Lock()
_DRAW_LOCK = threading.Lock()
_FLIP = {"mode": None}


def _flip_active():
    mode = _FLIP["mode"] or str(getattr(config, "CAMERA_FLIP", "none") or "none")
    return mode.lower() in ("180", "1", "true", "yes", "on", "rotate180", "hflip", "vflip")


def _flip(img):
    mode = (_FLIP["mode"] or str(getattr(config, "CAMERA_FLIP", "none") or "none")).lower()
    import cv2
    if mode in ("180", "1", "true", "yes", "on", "rotate180"):
        return cv2.rotate(img, cv2.ROTATE_180)
    if mode == "hflip":
        return cv2.flip(img, 1)
    if mode == "vflip":
        return cv2.flip(img, 0)
    return img


def memory():
    global _MEM
    with _MEM_LOCK:
        if _MEM is None:
            _MEM = default_memory()
        return _MEM


def _ctx():
    return ToolContext(settings=config, memory=memory(), registry=registry)


def _flip(img):
    flip = str(getattr(config, "CAMERA_FLIP", "none") or "none").lower()
    import cv2
    if flip in ("180", "1", "true", "yes", "on", "rotate180"):
        return cv2.rotate(img, cv2.ROTATE_180)
    if flip == "hflip":
        return cv2.flip(img, 1)
    if flip == "vflip":
        return cv2.flip(img, 0)
    return img


def _frames():
    """Dekoduje RTSP (PyAV) i zwraca klatki BGR (z obróceniem)."""
    import av
    import cv2
    container = av.open(config.CAMERA_RTSP,
                        options={"rtsp_transport": "tcp", "stimeout": "5000000"})
    stream = next((s for s in container.streams if s.type == "video"), None)
    if stream is None:
        container.close()
        return
    try:
        for frame in container.decode(stream):
            img = frame.to_ndarray(format="bgr24")
            h, w = img.shape[:2]
            if w > WIDTH:
                s = WIDTH / float(w)
                img = cv2.resize(img, (WIDTH, int(h * s)), interpolation=cv2.INTER_AREA)
            yield _flip(img)
    finally:
        try:
            container.close()
        except Exception:
            pass


def _analyze(img, expression=False):
    """Twarze (z dopasowaniem do galerii) + obiekty, przycięte do sensownych rozmiarów."""
    info = {"faces": [], "objects": [], "persons": 0, "expression": ""}
    area = float(img.shape[0] * img.shape[1])
    biggest = None
    if engine.available("face"):
        try:
            faces = [f for f in engine.detect_faces(img)
                     if f["box"][2] * f["box"][3] >= 0.004 * area]
        except Exception:
            faces = []
        if faces:
            biggest = max(faces, key=lambda f: f["box"][2] * f["box"][3])
        for f in faces:
            name, score = None, 0.0
            if engine.available("recognize"):
                try:
                    emb = engine.face_embedding(img, f)
                    if emb is not None:
                        name, score = memory().match_face(
                            emb, getattr(config, "FACE_MATCH_THRESHOLD", 0.40))
                except Exception:
                    name, score = None, 0.0
            info["faces"].append({"box": [float(v) for v in f["box"]],
                                  "score": round(float(f["score"]), 2),
                                  "name": name, "match": round(float(score), 2)})
    if engine.available("objects"):
        try:
            info["objects"] = engine.detect_objects(img)
        except Exception:
            info["objects"] = []
    info["persons"] = max(sum(1 for o in info["objects"] if o["label"] == "person"),
                          len(info["faces"]))
    # Sylwetka (re-ID) — rozpoznanie, gdy twarzy nie widać. Tylko gdy są zapisane sylwetki.
    info["bodies"] = []
    if (getattr(config, "BODY_ENABLED", True) and engine.available("bodies")
            and memory().list_bodies()):
        seen = {f["name"] for f in info["faces"] if f.get("name")}
        for o in info["objects"]:
            if o["label"] != "person":
                continue
            try:
                emb = engine.person_embedding(img, o["box"])
            except Exception:
                emb = None
            if emb is None:
                continue
            name, score = memory().match_body(emb, getattr(config, "BODY_MATCH_THRESHOLD", 0.55))
            if name and name not in seen:
                info["bodies"].append({"box": [float(v) for v in o["box"]], "name": name,
                                       "match": round(float(score), 2)})
                seen.add(name)
    if expression and biggest is not None and engine.available("expression"):
        try:
            info["expression"] = engine.expression(img, biggest)
        except Exception:
            info["expression"] = ""
    return info


def _assess_from_info(info, brightness):
    known = [{"name": f["name"], "score": f["match"]} for f in info["faces"] if f["name"]]
    unknown = sum(1 for f in info["faces"] if not f["name"])
    return {"persons": info["persons"], "known": known, "unknown": unknown,
            "objects": info["objects"], "expression": info.get("expression", ""),
            "brightness": brightness}


def _draw(img, info):
    import cv2
    for f in info.get("faces", []):
        x, y, w, h = [int(v) for v in f["box"]]
        known = bool(f.get("name"))
        color = (0, 220, 0) if known else (0, 165, 255)
        cv2.rectangle(img, (x, y), (x + w, y + h), color, 2)
        label = (f["name"] or "nieznany") + (f" {f['match']:.2f}" if known else "")
        _text(img, label, x, y - 6, color)
    for o in info.get("objects", []):
        if o["label"] == "person":
            continue
        x1, y1, x2, y2 = [int(v) for v in o["box"]]
        color = (255, 200, 0)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 1)
        _text(img, o["label"], x1, y1 - 4, color)
    for b in info.get("bodies", []):
        x1, y1, x2, y2 = [int(v) for v in b["box"]]
        color = (0, 255, 180)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        _text(img, f"{b['name']} (sylwetka {b['match']:.2f})", x1, y1 - 4, color)
    return img


def _text(img, text, x, y, color):
    import cv2
    y = max(14, y)
    cv2.putText(img, text, (max(0, x), y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 3,
                cv2.LINE_AA)
    cv2.putText(img, text, (max(0, x), y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 1,
                cv2.LINE_AA)


def _jpeg(img, quality=None):
    import cv2
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY),
                                         int(quality or JPEG_Q)])
    return buf.tobytes() if ok else b""


def _stream():
    last_t, last_emit = 0.0, 0.0
    interval = 1.0 / max(1, FPS)
    info = {"faces": [], "objects": [], "persons": 0}
    for img in _frames():
        now = time.time()
        if now - last_emit < interval:
            continue
        last_emit = now
        if now - last_t >= DETECT_EVERY:
            with _DRAW_LOCK:
                info = _analyze(img)
            last_t = now
        with _DRAW_LOCK:
            vis = _draw(img, info)
        data = _jpeg(vis)
        if not data:
            continue
        yield (b"--" + BOUNDARY.encode() + b"\r\nContent-Type: image/jpeg\r\n"
               b"Content-Length: " + str(len(data)).encode() + b"\r\n\r\n" + data + b"\r\n")


@app.route("/")
def index():
    return Response(_HTML, mimetype="text/html; charset=utf-8")


@app.route("/stream.mjpg")
def stream():
    return Response(_stream(), mimetype=f"multipart/x-mixed-replace; boundary={BOUNDARY}")


@app.route("/annotated.jpg")
def annotated():
    for img in _frames():
        info = _analyze(img)
        return Response(_jpeg(_draw(img, info)), mimetype="image/jpeg")
    return Response("brak obrazu", status=503)


@app.route("/detect.json")
def detect_json():
    for img in _frames():
        info = _analyze(img, expression=True)
        info["text"] = scene.describe(_assess_from_info(info, float(img.mean())))
        return jsonify(ok=True, **info)
    return jsonify(ok=False, error="brak obrazu"), 503


@app.route("/faces")
def faces():
    return jsonify(ok=True, faces=memory().list_faces(), bodies=memory().list_bodies())


@app.route("/events")
def events():
    """Ostatnie zdarzenia nasłuchu (Faza 2) z `runtime/vision_events.jsonl` (najnowsze pierwsze)."""
    limit = int(request.args.get("limit", "50") or 50)
    path = os.path.join(str(config.RUNTIME_DIR), "vision_events.jsonl")
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return jsonify(ok=True, events=list(reversed(rows))[:limit])


@app.route("/audit")
def audit():
    """Audyt dostępu do biometrii (Faza 6): ostatnie operacje na twarzach/sylwetkach."""
    from astro.vision import privacy
    limit = int(request.args.get("limit", "50") or 50)
    return jsonify(ok=True, watch_off=privacy.watch_off(), events=privacy.audit_tail(limit))


@app.route("/sightings")
def sightings():
    period = (request.args.get("period") or "today").lower()
    if period in ("week", "tydzien", "7"):
        since = time.time() - 7 * 86400
    elif period in ("all", "wszystko"):
        since = 0
    else:
        lt = time.localtime()
        since = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    summary = memory().sightings_summary(day_start=since)
    # dopisz zobaczenia z bieżącej klatki (dopóki nasłuch nie zrobił tego sam)
    try:
        for img in _frames():
            info = _analyze(img)
            for f in info["faces"]:
                if f.get("name"):
                    memory().add_sighting(f["name"], f.get("match", 0.0), known=True)
            for b in info.get("bodies", []):
                memory().add_sighting(b["name"], b.get("match", 0.0), known=True)
            break
    except Exception:
        pass
    summary = memory().sightings_summary(day_start=since)
    return jsonify(ok=True, period=period, sightings=summary)


@app.route("/caption")
def caption():
    """Opis sceny po polsku przez VLM (Ollama). Może potrwać kilka sekund."""
    question = request.args.get("q", "")
    for img in _frames():
        import cv2
        path = "/tmp/astro-vision-caption.jpg"
        try:
            cv2.imwrite(path, img)
        except Exception as e:
            return jsonify(ok=False, error=str(e)), 500
        text = vision._vlm_caption(path, question)
        return jsonify(ok=bool(text), caption=text, vlm=getattr(config, "VLM_MODEL", "") or "")
    return jsonify(ok=False, error="brak obrazu"), 503


@app.route("/enroll", methods=["GET", "POST"])
def enroll():
    name = (request.values.get("name") or "").strip()
    if not name:
        return jsonify(ok=False, error="brak imienia"), 400
    res = registry.execute("person_enroll", {"name": name}, _ctx())
    return jsonify(ok=bool(res.ok), text=res.text, name=name)


@app.route("/forget", methods=["GET", "POST"])
def forget():
    name = (request.values.get("name") or "").strip()
    if not name:
        return jsonify(ok=False, error="brak imienia"), 400
    n = memory().forget_face(name)
    return jsonify(ok=bool(n), text=f"usunięto: {n}", name=name)


@app.route("/flip")
def flip():
    if request.args.get("toggle"):
        _FLIP["mode"] = "none" if _flip_active() else "180"
    mode = request.args.get("mode")
    if mode is not None:
        _FLIP["mode"] = mode
    return jsonify(ok=True, flip=(_FLIP["mode"] or getattr(config, "CAMERA_FLIP", "none")))


@app.route("/cameras")
def cameras():
    """Lista skonfigurowanych kamer (wielokamera, Faza 3): nazwa, host, PTZ, osiągalność."""
    from astro.tools import vision
    out = []
    for i, cam in enumerate(vision.camera_sources(), start=1):
        reachable = False
        try:
            reachable = vision.camera_reachable(cam, timeout=0.8)
        except Exception:
            reachable = False
        out.append({"index": i, "name": cam["name"], "host": cam["host"],
                    "ptz": bool(cam["ptz"]), "reachable": reachable})
    return jsonify(cameras=out, count=len(out))


@app.route("/health")
def health():
    def probe():
        for img in _frames():
            info = _analyze(img)
            return {"ok": True, "persons": info["persons"], "faces": len(info["faces"])}
        return {"ok": False, "error": "brak obrazu"}
    return jsonify(camera=config.CAMERA_HOST, width=WIDTH,
                   models=engine.available("all"), **probe())


_HTML = """<!doctype html><html lang="pl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ASTRO — oczy (API)</title>
<style>body{background:#0b1622;color:#dbeafe;font-family:system-ui,Arial;margin:0;padding:16px}
img{max-width:100%;border:1px solid #1e3350;border-radius:10px}h1{color:#22d3ee;font-size:18px}
code{color:#22d3ee}a{color:#22d3ee}</style></head><body>
<h1>ASTRO — oczy (API wizji)</h1>
<p>Podgląd z ramkami: <img src="/stream.mjpg" alt="stream"></p>
<p>Galeria: <code>/faces</code> · detekcje: <code>/detect.json</code> ·
   zapis: <code>/enroll?name=Imię</code> · usuń: <code>/forget?name=Imię</code></p>
</body></html>"""


def main():
    ap = argparse.ArgumentParser(description="ASTRO — API wizji (oczy)")
    ap.add_argument("--host", default=os.environ.get("ASTRO_VISION_API_HOST", "0.0.0.0"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("ASTRO_VISION_API_PORT",
                                                                   "8099")))
    args = ap.parse_args()
    print(f"[vision-api] kamera={config.CAMERA_HOST} http://{args.host}:{args.port}/")
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
