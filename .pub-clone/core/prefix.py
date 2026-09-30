"""Prefiks kanału wypowiedzi (must-have 2026-09-27): `terminal` / `czat` / `skrypt` / `skajnet`.

Użytkownik jawnie deklaruje charakter wypowiedzi na początku, co NADPISUJE heurystyczną
klasyfikację intencji:

* **terminal** — polecenie systemowe/tool-calling (ścieżka komend; potwierdzenia i `local_only`
  bez zmian),
* **czat**    — rozmowa/wiedza (agent + RAG + remote); NIGDY nie wykonuje komend,
* **skrypt**  — tylko przygotowane, deterministyczne skrypty (Wi-Fi, kalkulator, waluta, miejsca…);
  jeśli brak trafienia — mówi wprost, nie zgaduje i nie woła modelu,
* **skajnet** — sekcja SKAJNET listy must-have: zadania wykonywane na Pi4-SKYNET (doker, zasoby,
  aktualizacje, temperatura, zasilanie) przez stały tunel.

Brak prefiksu = dotychczasowy auto-routing (pełna zgodność wstecz).
"""

import re

TERMINAL = "terminal"
CZAT = "czat"
SKRYPT = "skrypt"
SKAJNET = "skajnet"

# Tylko na POCZĄTKU wypowiedzi; toleruje warianty fonetyczne/zapisowe i interpunkcję po prefiksie.
# „skajnet": STT (Whisper/Vosk) słyszy różne warianty — kalibracja 2026-09-30 zarejestrowała
# „steimet", „skajnij", „skinette", „stejnet"… Wszystkie mapujemy na kanał SKAJNET.
_PREFIX_RE = re.compile(
    r"^\s*(terminal|terminalu|czat|chat|czacie|czacik|"
    r"skrypt|skryp|skrypcie|skrypcik|skript|script|scrypt|"
    r"skajnet|skynet|skajnetu|skynetu|skajnec|"
    r"steimet|stejmet|stejnet|stajnet|skajnij|skinette|skinet|skajnac|skajniet|skajnite|"
    r"zdalne|zdalnie|skajmy|skyit|sky it|sky-it|sky met|skajmet)\b[\s,:;.!\-—]*",
    re.I)
_MAP = {
    "terminal": TERMINAL, "terminalu": TERMINAL,
    "czat": CZAT, "chat": CZAT, "czacie": CZAT, "czacik": CZAT,
    "skrypt": SKRYPT, "skryp": SKRYPT, "skrypcie": SKRYPT, "skrypcik": SKRYPT,
    "skript": SKRYPT, "script": SKRYPT, "scrypt": SKRYPT,
    "skajnet": SKAJNET, "skynet": SKAJNET, "skajnetu": SKAJNET,
    "skynetu": SKAJNET, "skajnec": SKAJNET,
    "steimet": SKAJNET, "stejmet": SKAJNET, "stejnet": SKAJNET, "stajnet": SKAJNET,
    "skajnij": SKAJNET, "skinette": SKAJNET, "skinet": SKAJNET,
    "skajnac": SKAJNET, "skajniet": SKAJNET, "skajnite": SKAJNET,
    "zdalne": SKAJNET, "zdalnie": SKAJNET, "skajmy": SKAJNET,
    "skyit": SKAJNET, "sky it": SKAJNET, "sky-it": SKAJNET,
    "sky met": SKAJNET, "skajmet": SKAJNET,
}


def parse(text):
    """Zwraca (kanał, treść bez prefiksu). Kanał "" gdy brak prefiksu."""
    raw = text or ""
    m = _PREFIX_RE.match(raw)
    if not m:
        return "", raw.strip()
    channel = _MAP.get(m.group(1).lower(), "")
    return channel, raw[m.end():].strip()


__all__ = ["TERMINAL", "CZAT", "SKRYPT", "SKAJNET", "parse"]
