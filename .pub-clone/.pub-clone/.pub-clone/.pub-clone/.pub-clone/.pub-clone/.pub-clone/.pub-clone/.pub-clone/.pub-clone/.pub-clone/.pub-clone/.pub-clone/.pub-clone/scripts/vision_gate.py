#!/usr/bin/env python3
"""Bramka „oczy na NPU": pomiar detekcji obiektów CPU (NanoDet/ONNX) vs Hailo NPU (YOLOv8).

Mierzy ms/klatkę oraz udział CPU (% procesora względem czasu ściennego). Wymaga wolnego NPU —
jeśli `astro.service` trzyma urządzenie, najpierw `sudo systemctl stop astro.service`
(potem start). Kod wyjścia: 0 = PASS, 1 = FAIL (NPU wolniejszy), 2 = SKIP (NPU niedostępny).

    python3 astro/scripts/vision_gate.py [--image plik.jpg] [--frames 15]
"""

import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

import numpy as np  # noqa: E402

from astro import config  # noqa: E402
from astro.vision import engine  # noqa: E402
from astro.vision.hailo import HailoDetector, HailoFaceDetector, hef_path, face_hef_path  # noqa: E402


def load_image(path):
    import cv2
    if path and os.path.exists(path):
        return cv2.imread(path)
    snap = os.path.join(str(config.RUNTIME_DIR), "camera", "last.jpg")
    if os.path.exists(snap):
        return cv2.imread(snap)
    return np.full((720, 1280, 3), 128, dtype=np.uint8)


def bench(fn, frames):
    fn()  # rozgrzewka
    c0, w0 = time.process_time(), time.time()
    n = 0
    for _ in range(frames):
        n = len(fn())
    wall = time.time() - w0
    cpu = time.process_time() - c0
    return wall / frames * 1000.0, (cpu / wall * 100.0 if wall else 0.0), n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default="")
    ap.add_argument("--frames", type=int, default=15)
    args = ap.parse_args()

    img = load_image(args.image)
    if img is None:
        print("[gate] brak obrazu testowego")
        return 1
    h, w = img.shape[:2]
    print(f"[gate] obraz {w}x{h}, klatek={args.frames}, HEF={hef_path() or 'brak'}, "
          f"twarze={face_hef_path() or 'brak'}")

    cpu_ms, cpu_pct, cpu_n = bench(lambda: engine._detect_objects_cpu(img, 0.45), args.frames)
    print(f"[gate] CPU NanoDet : {cpu_ms:7.1f} ms/klatkę, CPU {cpu_pct:5.0f}%, detekcje={cpu_n}")

    det = HailoDetector()
    if not det.available():
        print("[gate] NPU SKIP — brak HEF/hailo_platform")
        return 2
    try:
        det._ensure()
    except Exception as exc:
        print(f"[gate] NPU SKIP — urządzenie zajęte/niedostępne ({exc})")
        return 2
    npu_ms, npu_pct, npu_n = bench(lambda: det.detect_objects(img, 0.45), args.frames)
    det.close()
    print(f"[gate] NPU YOLOv8s : {npu_ms:7.1f} ms/klatkę, CPU {npu_pct:5.0f}%, detekcje={npu_n}")

    # Twarze: YuNet (CPU) vs SCRFD (NPU) — raport pomocniczy (nie decyduje o PASS).
    fdet = HailoFaceDetector()
    if engine.available("face") and fdet.available():
        try:
            fdet._ensure()
        except Exception as exc:
            print(f"[gate] twarze NPU SKIP — {exc}")
        else:
            c_ms, c_pct, c_n = bench(lambda: engine._detect_faces_cpu(img, 0.6), args.frames)
            f_ms, f_pct, f_n = bench(lambda: fdet.detect_faces(img, 0.5), args.frames)
            fdet.close()
            print(f"[gate] CPU YuNet   : {c_ms:7.1f} ms/klatkę, CPU {c_pct:5.0f}%, twarze={c_n}")
            print(f"[gate] NPU SCRFD   : {f_ms:7.1f} ms/klatkę, CPU {f_pct:5.0f}%, twarze={f_n}")

    speedup = cpu_ms / npu_ms if npu_ms else 0.0
    print(f"[gate] przyspieszenie: x{speedup:.1f} (CPU %.1f%% -> NPU %.1f%%)" % (cpu_pct, npu_pct))
    ok = npu_ms < cpu_ms
    print("[gate]", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
