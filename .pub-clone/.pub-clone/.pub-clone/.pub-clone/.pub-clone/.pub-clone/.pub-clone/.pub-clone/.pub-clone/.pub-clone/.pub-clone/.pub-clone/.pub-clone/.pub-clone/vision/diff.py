"""Monitor zmian kadru (Faza 2 „oczy"): ruch, zmiana sceny, wejście/wyjście z kadru.

Bez nowych modeli — tanie, deterministyczne przetwarzanie klatek (OpenCV), więc nie obciąża
NPU/CPU ponad próbkowanie watch. Trzyma kompaktowy „odcisk" klatki (miniaturka + histogram) i
porównuje z poprzednim cyklem:

  * `motion` — istotna zmiana pikselowa między klatkami (ktoś/coś się rusza),
  * `scene_change` — duża zmiana globalna (kamera obrócona, przedmiot pojawił się/znikł),
  * `empty`/`occupied` — liczba osób przeszła 0 <-> >0 (wejście/wyjście z kadru),
  * `appeared`/`disappeared` — pojawienie się/zniknięcie klasy obiektu (np. „ktoś przyszedł").

Czysta logika (`diff_frame`, `plan_change_events`) jest testowalna bez kamery.
"""

from __future__ import annotations

import json
import os

_STATE_FILE = "vision_diff.json"


def _fingerprint(image, size=64):
    """Odcisk klatki: mała szarość (uint8) + znormalizowany histogram (do porównań)."""
    import cv2
    import numpy as np
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (size, size), interpolation=cv2.INTER_AREA)
    hist = cv2.calcHist([gray], [0], None, [32], [0, 256]).reshape(-1)
    hist = hist / (float(hist.sum()) or 1.0)
    return small.astype("uint8"), hist.astype("float32")


def diff_frame(prev, cur):
    """Porównuje dwa odciski (small, hist). Zwraca dict z metrykami zmiany.

    `mean_abs` — średnia różnica jasności (0..255),
    `hist` — odległość histogramów (0..1, Bhattacharyya),
    `changed` — który próg przekroczony.
    """
    import cv2
    import numpy as np
    if prev is None:
        return {"mean_abs": 0.0, "hist": 0.0, "motion": False, "scene_change": False}
    p_small, p_hist = prev
    c_small, c_hist = cur
    mean_abs = float(np.mean(np.abs(p_small.astype("int16") - c_small.astype("int16"))))
    hist = float(cv2.compareHist(p_hist.reshape(-1, 1), c_hist.reshape(-1, 1),
                                 cv2.HISTCMP_BHATTACHARYYA))
    return {"mean_abs": mean_abs, "hist": hist,
            "motion": mean_abs >= 3.0,
            "scene_change": hist >= 0.35 or mean_abs >= 25.0}


def fingerprint_from_state(state):
    """Odtwarza odcisk z zapisanego stanu (mała lista) albo None."""
    import numpy as np
    small = state.get("small")
    hist = state.get("hist")
    if not small or not hist:
        return None
    try:
        return (np.asarray(small, dtype="uint8").reshape(64, 64),
                np.asarray(hist, dtype="float32").reshape(-1))
    except Exception:
        return None


def state_from_fingerprint(fp):
    small, hist = fp
    return {"small": small.astype("uint8").ravel().tolist(),
            "hist": [round(float(v), 5) for v in hist.ravel()]}


def plan_change_events(prev_labels, cur_labels, prev_occupied, cur_occupied,
                       motion, scene_change, cooldowns, now, cd_motion=120.0,
                       cd_change=180.0, cd_enter=60.0, cd_leave=90.0):
    """Czysta logika zdarzeń zmiany kadru. Zwraca (lista (kind,text), nowe_cooldowns).

    `prev_labels`/`cur_labels`: zbiory etykiet obiektów (COCO) w poprzedniej i bieżącej klatce.
    `prev_occupied`/`cur_occupied`: czy w kadrze były osoby (0 <-> >0).
    """
    texts = []
    cooldowns = dict(cooldowns or {})
    prev_labels = set(prev_labels or [])
    cur_labels = set(cur_labels or [])

    def ready(key, cd):
        return now - float(cooldowns.get(key, 0)) >= cd

    if cur_occupied and not prev_occupied and ready("enter", cd_enter):
        texts.append(("enter", "Ktoś wszedł do pokoju."))
        cooldowns["enter"] = now
    elif prev_occupied and not cur_occupied and ready("leave", cd_leave):
        texts.append(("leave", "Ktoś wyszedł z pokoju."))
        cooldowns["leave"] = now

    # Nowe obiekty istotne (bez „person" — to obsługują twarze/wejście).
    appeared = {l for l in (cur_labels - prev_labels) if l != "person"}
    disappeared = {l for l in (prev_labels - cur_labels) if l != "person"}
    if appeared and ready("appeared", cd_motion):
        pl = ", ".join(sorted(appeared)[:4])
        texts.append(("appeared", f"W kadrze pojawiło się: {pl}."))
        cooldowns["appeared"] = now
    elif disappeared and ready("disappeared", cd_motion):
        pl = ", ".join(sorted(disappeared)[:4])
        texts.append(("disappeared", f"Z kadru zniknęło: {pl}."))
        cooldowns["disappeared"] = now

    if scene_change and ready("scene_change", cd_change):
        texts.append(("scene_change", "Widok się zmienił."))
        cooldowns["scene_change"] = now
    elif motion and ready("motion", cd_motion):
        texts.append(("motion", "Widzę ruch w kadrze."))
        cooldowns["motion"] = now
    return texts, cooldowns


def state_path():
    from .. import config
    return os.path.join(str(config.RUNTIME_DIR), _STATE_FILE)


def load_state(path=None):
    try:
        with open(path or state_path(), encoding="utf-8") as fh:
            return json.load(fh) or {}
    except (OSError, ValueError):
        return {}


def save_state(state, path=None):
    try:
        p = path or state_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
    except OSError:
        pass
