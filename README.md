# ASTRO — self-hosted, self-improving voice AI agent

[![CI](https://github.com/mobium-app/ai_astro_public/actions/workflows/ci.yml/badge.svg)](https://github.com/mobium-app/ai_astro_public/actions)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](requirements.txt)
[![Tests](https://img.shields.io/badge/tests-passing-green)]()
[![Platform](https://img.shields.io/badge/platform-Raspberry%20Pi%205%20%7C%20Linux-AA0000)]()
[![Website](https://img.shields.io/badge/site-netrunner.edu.pl-0e8a16)](https://netrunner.edu.pl/projekt-astro)

**ASTRO** to samodzielny agent głosowy typu open-core: słyszy, mówi, widzi,
wykonuje komendy na swoim urządzeniu, uczy się w trakcie pracy i trenuje własne
modele (LoRA). Zbudowany od zera jako czysty, testowalny SDK — bez chmury
obowiązkowej (offline-first, NPU-first).

> 🌐 **Projekt ASTRO — strona komercyjna: [netrunner.edu.pl/projekt-astro](https://netrunner.edu.pl/projekt-astro)**

> To jest publiczne lustro projektu. Repozytorium źródłowe (prywatne) zawiera
> dane osobiste i logi, dlatego publiczny snapshot jest **sanityzowany**: IP,
> ścieżki i sekrety zastąpiono placeholderami. Kod jest w 100% realny i testowalny.

## Demo

![Demo terminala ASTRO](assets/astro_demo.gif)

🎧 **Próbka głosu ASTRO** (TTS Piper, profil „dziewczynka"): [posłuchaj](assets/astro_voice_sample.wav)

## 🚀 Szybki start — installer (zalecany)

**Jedno polecenie** na świeżym Raspberry Pi 5 albo Linuksie x86_64:

```bash
curl -fsSL https://raw.githubusercontent.com/mobium-app/ai_astro_public/main/setup.sh | bash
```

Installer prowadzi od zera do działającego ASTRO:

1. **zależności systemowe** (apt: Python, git, ffmpeg, ALSA…),
2. **klonuje repo** (jeśli uruchomiony spoza niego),
3. **diagnozuje sprzęt** (Pi / PC, Hailo NPU, audio, ffmpeg),
4. **konfiguruje** (adresy, kamera, drugi komputer — wszystko opcjonalne),
5. **pyta o klucze API** (opcjonalne; zapis 600 w `~/.astro-secrets/API.txt`),
6. **pobiera modele**: Ollama (+ `qwen2.5:7b`, `nomic-embed-text`), Vosk (STT), Piper (TTS),
7. **tworzy venv**, generuje `config/astro.env` + usługę systemd, robi self-test.

Tryby installera:

```bash
bash setup.sh            # interaktywny (Enter = domyślne)
bash setup.sh --check    # tylko diagnoza — nic nie zapisuje
bash setup.sh --yes      # domyślne bez pytań (klucze API pomijane)
bash setup.sh --update   # SYNCHRO: git pull + zależności + modele + restart usługi
```

📖 **Pełna instrukcja krok po kroku → [`docs/INSTALL.md`](docs/INSTALL.md)**
(wymagania, modele, warstwy opcjonalne, macierz odporności, troubleshooting).

<details>
<summary>Alternatywa: instalacja ręczna</summary>

```bash
# UWAGA: katalog docelowy musi nazywać się `astro` (pakiet Python importuje `astro.*`)
git clone https://github.com/mobium-app/ai_astro_public.git astro
cd astro
python3 -m venv venv && venv/bin/pip install -r requirements.txt

# testy (hermetyczne, bez sprzętu)
python3 tests/run_tests.py

# czat tekstowy
python3 scripts/astro_repl.py
```
</details>

## Co działa BEZ czego (odporność)

ASTRO jest **warstwowy** i sam degraduje, gdy warstwa padnie:

| Brak… | Co dalej działa |
|---|---|
| internetu | pełny tryb offline |
| drugiego komputera (PC) | tryb offline (auto-fallback) |
| kluczy API | tryb offline |
| Hailo NPU | CPU (wspierany tryb) |
| mikrofonu/głośnika | tryb tekstowy (`astro_repl.py`) |
| kamery | reszta asystenta |
| **Ollamy** | *jedyna twarda zależność* (lokalny serwer LLM) |

Tryby pracy (przełączane głosem): **offline** → **komputer** (Ollama na PC)
→ **remote_ai** (darmowe chmury) → **premium** (OpenCode Go; darmowe modele).

## Po co istnieje
- **Prywatny asystent w domu**: budzi się na „Hej Astro", rozumie polską mowę
  (Vosk + Whisper na NPU), odpowiada głosem (Piper), wykonuje komendy systemowe.
- **Samodoskonalenie**: pętla nauki zadaje pytania, zbiera wiedzę do lokalnej
  bazy (`learned`), destyluje trajektorie i trenuje własne adaptery LoRA.
- **Widzi otoczenie**: kamera sieciowa (ONVIF/RTSP), detekcja obiektów i twarzy,
  rozpoznawanie osób, OCR, wiek/płeć, zdarzenia ruchu, opis sceny VLM.
- **Offline-first**: na Raspberry Pi z Hailo-10H NPU działa bez internetu;
  PC/klucze chmurowe są opcjonalne (wspomaganie, nie wymóg).

## Wymagany sprzęt (referencyjny)
| Komponent | Referencja | Uwagi |
|---|---|---|
| SBC | Raspberry Pi 5 (8 GB+) | ARM64, Debian 13 / RPi OS |
| Alternatywa | dowolny Linux x86_64 | działa bez NPU (CPU + Ollama) |
| NPU | Hailo-10H (AI HAT+ 2) | *opcjonalny* — STT Whisper, VLM, YOLO/SCRFD |
| Audio | mikrofon/głośnik (np. WM8960 HAT) | *opcjonalny* — bez niego tryb tekstowy |
| Kamera | dowolna IP (ONVIF/RTSP) | *opcjonalna* — ocena otoczenia, twarze, OCR |
| PC z GPU | RTX 4060+ (opcjonalnie) | trening LoRA, nauczyciel (tryb „komputer") |

## Architektura (skrót)
- `backends/` — silniki: CPU, NPU (Hailo), PC (Ollama), remote (chmury), tryby offline/komputer/premium.
- `core/` — pętla observe→act→verify, dispatch intencji, osobowość, kontekst trwały, inicjatywa.
- `tools/` — rejestr narzędzi (system, sieć, pliki, kamera, wiedza) + bramki bezpieczeństwa.
- `audio/` — wake word, STT (Vosk/Whisper NPU/CPU), TTS (Piper), streaming.
- `vision/` — detekcja (YOLO/SCRFD na NPU lub CPU), twarze (SFace), OCR, wiek/płeć, VLM.
- `memory/` — SQLite `memory.db`: wiedza wektorowa (`learned`), trajektorie, sesje, biometria (AES-GCM).
- `safety/` — reguły: komendy nigdy do chmury, twarde odmowy, ochrona sekretów, filtr jakości nauki.
- `persona/`, `affect/` — temperament, emocje (PAD), humor, relacja.
- `skills/` — receptury komend deterministycznych (must-have, bez modelu).
- `scripts/` — installer (`setup.sh` w root), bramki jakości (E1–E9), trening LoRA, destylacja.

## Testy i jakość
```bash
python3 tests/run_tests.py            # hermetyczne testy (stdlib unittest)
python3 scripts/must_have_audit.py    # audyt komend głosowych
python3 scripts/e6_gate.py --model <tag> --url http://127.0.0.1:11434 \
  --runtime-prompt --max-tools 6 --temp 0 --seed 42 --no-baseline --quick
```
Promocja modelu odbywa się wyłącznie po zaliczeniu bramek (tools/chain/chat) —
bez regresji względem baseline.

## Jak pomóc
- Zgłoś błąd / pomysł: issue lub PR (patrz `CONTRIBUTING.md`).
- Luki bezpieczeństwa: `SECURITY.md` (nie w publicznych issue).
- Najbardziej przydatne obszary: STT/TTS, nowe narzędzia, komendy PL, trening LoRA.

## Licencja
MIT — patrz `LICENSE`.

## Projekt komercyjny
ASTRO to także komercyjny projekt — strona projektu: **[netrunner.edu.pl/projekt-astro](https://netrunner.edu.pl/projekt-astro)**.

## Status
**v1.0.0** (snapshot `public-2026-10-03`). Publiczne repo jest aktualizowane
skryptem mirrorującym; prywatny rdzeń może zawierać postęp ponad snapshot.
