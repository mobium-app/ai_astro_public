"""Temperament ASTRO (E7.1): schemat cech + render do kontekstu. Bez modelu i bez sieci.

Cechy są autorskie (nie „Big Five" mierzone testami), w zakresie 0..1, sterowalne komendą.
To warstwa stabilna osobowości; stany afektywne (nastrój) żyją w `affect/`.
"""

TRAITS = {
    "energy": {"label": "energia", "low": "spokojna", "mid": "umiarkowana",
               "high": "żywiołowa"},
    "warmth": {"label": "ciepło", "low": "rzeczowe", "mid": "umiarkowane",
               "high": "serdeczne"},
    "formality": {"label": "formalność", "low": "swobodna", "mid": "umiarkowana",
                  "high": "oficjalna"},
    "humor": {"label": "humor", "low": "poważny", "mid": "umiarkowany", "high": "żartobliwy"},
    "curiosity": {"label": "ciekawość", "low": "powściągliwa", "mid": "umiarkowana",
                  "high": "dociekliwa"},
    "caution": {"label": "ostrożność", "low": "śmiała", "mid": "umiarkowana",
                "high": "ostrożna"},
    "verbosity": {"label": "zwięzłość", "low": "zwięzła", "mid": "umiarkowana",
                  "high": "szczegółowa"},
}
DEFAULT = {
    "energy": 0.6, "warmth": 0.7, "formality": 0.4, "humor": 0.5,
    "curiosity": 0.6, "caution": 0.5, "verbosity": 0.4,
}


def defaults():
    return dict(DEFAULT)


def _clamp(v):
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return 0.0


def normalize(persona):
    """Wypełnia brakujące cechy domyślnymi i przycina do 0..1."""
    out = defaults()
    for k, v in (persona or {}).items():
        if k in TRAITS:
            out[k] = _clamp(v)
    return out


def bucket(value):
    return "low" if value < 0.34 else ("high" if value >= 0.67 else "mid")


def qualifier(trait, value):
    spec = TRAITS.get(trait, {})
    return spec.get(bucket(value), "umiarkowana")


def set_trait(persona, trait, value):
    if trait not in TRAITS:
        return normalize(persona), False
    out = normalize(persona)
    out[trait] = _clamp(value)
    return out, True


def adjust(persona, trait, delta):
    out = normalize(persona)
    out[trait] = _clamp(out[trait] + float(delta))
    return out


def describe(persona):
    p = normalize(persona)
    return [f"{TRAITS[k]['label']}: {p[k]:.2f} ({qualifier(k, p[k])})" for k in TRAITS]


def context_block(persona):
    """Fragment systemowego kontekstu opisujący temperament ASTRO."""
    p = normalize(persona)
    traits = ", ".join(f"{TRAITS[k]['label']} {qualifier(k, p[k])}" for k in TRAITS)
    return ("TEMPERAMENT ASTRO (zachowuj spójnie): " + traits + ".")
