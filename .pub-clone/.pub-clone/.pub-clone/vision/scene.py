"""Ocena sceny („oczy" ASTRO): osoby + rozpoznane twarze + przedmioty + emocja -> opis.

Łączy wynik detekcji/rozpoznawania w czytelny opis (do czatu i głosu). Działa lokalnie;
opcjonalny opis naturalny przez VLM dołożony jest w `tools/vision.py` (gdy skonfigurowany).
"""

from __future__ import annotations

from .. import config
from . import engine

_OBJ_PL = {
    "person": "osoba", "bicycle": "rower", "car": "samochód", "motorcycle": "motocykl",
    "bus": "autobus", "truck": "ciężarówka", "bottle": "butelka", "wine glass": "kieliszek",
    "cup": "kubek", "fork": "widelec", "knife": "nóż", "spoon": "łyżka", "bowl": "miska",
    "chair": "krzesło", "couch": "kanapa", "bed": "łóżko", "dining table": "stół",
    "laptop": "laptop", "mouse": "mysz", "keyboard": "klawiatura", "cell phone": "telefon",
    "tv": "telewizor", "book": "książka", "clock": "zegar", "vase": "wazon",
    "potted plant": "roślina", "backpack": "plecak", "handbag": "torebka", "suitcase": "walizka",
    "cat": "kot", "dog": "pies", "bird": "ptak", "refrigerator": "lodówka",
    "microwave": "mikrofalówka", "sink": "zlew", "toilet": "toaleta", "umbrella": "parasol",
    "remote": "pilot", "scissors": "nożyczki", "teddy bear": "pluszak", "toothbrush": "szczoteczka",
}


def _brightness(image):
    try:
        return float(image.mean())
    except Exception:
        return 0.0


def _brightness_word(value):
    if value < 45:
        return "ciemno"
    if value < 110:
        return "umiarkowane światło"
    return "jasno"


def assess(image, memory=None, faces=True, objects=True, expressions=True):
    """Ocena klatki BGR. Zwraca dict z ludźmi, twarzami, przedmiotami i emocją."""
    out = {"faces": 0, "persons": 0, "known": [], "unknown": 0, "objects": [],
           "expression": "", "age_gender": None, "brightness": _brightness(image)}
    face_list = []
    if faces and getattr(config, "VISION_AI_ENABLED", True) and engine.available("face"):
        try:
            face_list = engine.detect_faces(image)
        except Exception:
            face_list = []
    out["faces"] = len(face_list)
    largest = None
    if face_list:
        largest = max(face_list, key=lambda f: f["box"][2] * f["box"][3])
    recognize = bool(getattr(config, "FACE_ENABLED", True)) and memory is not None
    for f in face_list:
        name, score = None, 0.0
        if recognize and engine.available("recognize"):
            try:
                emb = engine.face_embedding(image, f)
                if emb is not None:
                    name, score = memory.match_face(emb, getattr(config, "FACE_MATCH_THRESHOLD",
                                                                 0.40))
            except Exception:
                name, score = None, 0.0
        if name:
            out["known"].append({"name": name, "score": round(float(score), 2)})
            if getattr(config, "FACE_LOG", True):
                try:
                    memory.add_sighting(name, score, known=True)
                except Exception:
                    pass
        else:
            out["unknown"] += 1
            if recognize and getattr(config, "FACE_LOG", True):
                try:
                    memory.add_sighting("?", score, known=False)
                except Exception:
                    pass
    if expressions and largest is not None and engine.available("expression"):
        try:
            out["expression"] = engine.expression(image, largest)
        except Exception:
            out["expression"] = ""
    if (largest is not None and getattr(config, "AGEGENDER_ENABLED", True)
            and engine.available("agegender")):
        try:
            out["age_gender"] = engine.age_gender(image, largest)
        except Exception:
            out["age_gender"] = None
    if objects and getattr(config, "VISION_AI_ENABLED", True) and engine.available("objects"):
        try:
            out["objects"] = engine.detect_objects(image)
        except Exception:
            out["objects"] = []
    person_objs = sum(1 for o in out["objects"] if o["label"] == "person")
    out["persons"] = max(person_objs, out["faces"])
    # Sylwetka (person re-ID): rozpoznanie, gdy twarzy nie widać (osoba odwrócona/oddalona).
    out["body_known"] = []
    if (objects and memory is not None and getattr(config, "BODY_ENABLED", True)
            and engine.available("bodies")):
        seen = {k["name"] for k in out["known"]}
        for o in out["objects"]:
            if o["label"] != "person":
                continue
            try:
                emb = engine.person_embedding(image, o["box"])
            except Exception:
                emb = None
            if emb is None:
                continue
            name, score = memory.match_body(emb, getattr(config, "BODY_MATCH_THRESHOLD", 0.55))
            if name and name not in seen:
                out["body_known"].append({"name": name, "score": round(float(score), 2)})
                seen.add(name)
    return out


def _known_names(out):
    names = [k["name"] for k in (out.get("known") or [])]
    for b in (out.get("body_known") or []):
        if b["name"] not in names:
            names.append(b["name"])
    return names


def describe(out):
    """Zamienia ocenę na krótki opis po polsku."""
    parts = []
    n = int(out.get("persons", 0))
    if n == 0:
        parts.append("Nie widzę teraz nikogo.")
    elif n == 1:
        parts.append("Widzę jedną osobę.")
    else:
        parts.append(f"Widzę {n} osoby." if n < 5 else f"Widzę {n} osób.")
    names = _known_names(out)
    if names:
        parts.append("Rozpoznaję: " + ", ".join(names) + ".")
    unknown = int(out.get("unknown", 0))
    if unknown:
        parts.append("Jest też " + ("ktoś nieznany." if unknown == 1
                                    else f"{unknown} nieznane osoby."))
    if out.get("expression"):
        parts.append("Najbliższa osoba wygląda na " + engine.EXPRESSIONS_PL.get(
            out["expression"], out["expression"]) + ".")
    ag = out.get("age_gender")
    if ag:
        age_pl = engine.AGE_RANGES_PL.get(ag.get("age"), ag.get("age", ""))
        parts.append(f"Najbliższa osoba to najpewniej {ag.get('gender', '')} w wieku {age_pl}.")
    labels = []
    for o in out.get("objects") or []:
        if o["label"] == "person":
            continue
        pl = _OBJ_PL.get(o["label"], o["label"])
        if pl not in labels:
            labels.append(pl)
    if labels:
        parts.append("W otoczeniu widzę: " + ", ".join(labels[:6]) + ".")
    parts.append("Oświetlenie: " + _brightness_word(out.get("brightness", 0)) + ".")
    return " ".join(parts)


def who(out):
    """Krótka odpowiedź na „kto to / kogo widzisz"."""
    names_list = _known_names(out)
    unknown = int(out.get("unknown", 0))
    persons = int(out.get("persons", 0))
    faces = int(out.get("faces", 0))
    known = bool(names_list)
    names = ", ".join(names_list)
    if known and not unknown:
        return f"Widzę: {names}."
    if known and unknown:
        tail = "oraz 1 nieznaną osobę" if unknown == 1 else f"oraz {unknown} nieznane osoby"
        return f"Widzę: {names} {tail}."
    if unknown:
        return ("Widzę osobę, ale jej nie rozpoznaję." if unknown == 1
                else f"Widzę {unknown} nieznane osoby.")
    if persons and not faces:
        return ("Widzę osobę, ale nie widzę jej twarzy — jest odwrócona albo poza kadrem."
                if persons == 1 else
                f"Widzę {persons} osoby, ale nie widzę ich twarzy.")
    return "Nie widzę teraz nikogo."
