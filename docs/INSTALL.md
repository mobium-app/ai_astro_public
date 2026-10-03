# ASTRO — instrukcja instalacji krok po kroku

> Ten dokument prowadzi od zera do działającego ASTRO na **Twojej** maszynie.
> Wszystko, co lokalne (Ollama, głos, kamera), konfigurujesz w `setup.sh`;
> warstwy zdalne (drugi komputer, chmury, tryb premium) są **opcjonalne**.

---

## 1. Co to jest ASTRO (w skrócie)

ASTRO to samodzielny asystent domowy: słucha (STT), myśli (LLM), mówi (TTS),
opcjonalnie patrzy (kamera) i pamięta (baza wiedzy). Zbudowany jest **warstwowo** —
każda warstwa jest opcjonalna i ma lokalny fallback:

| Warstwa | Co daje | Czego wymaga | Fallback |
|---|---|---|---|
| **offline** | pełna praca bez internetu | Raspberry Pi 5 (lub PC) + Ollama | — (to baza) |
| **komputer** | mocniejszy „mózg" (np. bielik-11b) | drugi komputer z Ollamą w sieci | wraca do offline |
| **remote_ai** | wiedza z darmowych chmur | klucze API (darmowe konta) | wraca do offline |
| **premium** | płynny small-talk (duże modele) | klucz OpenCode Go (darmowe modele) | wraca do offline |

**Ważne:** ASTRO pobrany 1:1 **nie zakłada niczyjej sieci** — adresy, klucze i modele
konfigurujesz u siebie. Domyślnie działa w trybie **offline** (lokalnie), a warstwy
zdalne włączasz świadomie.

---

## 2. Wymagania

### Minimalne (tryb offline + tryb tekstowy)
- **Raspberry Pi 5** (8/16 GB) *albo* dowolny **Linux x86_64** (Debian 12+ / Ubuntu 22.04+)
- **Python 3.11+**, `git`, ok. 8 GB wolnego miejsca (system + modele)
- **Ollama** (lokalny serwer LLM): <https://ollama.com>

### Do trybu głosowego (STT/TTS)
- mikrofon i głośnik (USB albo HAT, np. WM8960) — ALSA (`arecord`/`aplay`)
- modele: **Vosk** (STT) i **Piper** (TTS) — patrz §6

### Opcjonalne
- **Hailo-8/10H** (HAT AI) — przyspiesza STT/wizję (bez tego działa CPU)
- **kamera sieciowa ONVIF/RTSP** — „oczy" (podgląd + opis sceny)
- **drugi komputer z Ollamą** — tryb „komputer"
- **klucze API** — tryby „remote_ai" i „premium"

---

## 3. Instalacja krok po kroku

### Krok 1 — zależności systemowe

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git ffmpeg alsa-utils
```

> Na Raspberry Pi OS dodatkowo (jeśli używasz Hailo): sterowniki `hailort` i HEF-y
> — patrz §9. Bez Hailo **nic dodatkowego nie trzeba**.

### Krok 2 — pobierz ASTRO

```bash
git clone https://github.com/mobium-app/ai_astro_public.git ~/astro
cd ~/astro
```

### Krok 3 — uruchom instalator

```bash
bash setup.sh
```

Instalator (bezpieczny — nic nie nadpisuje bez kopii `.bak-<data>`):
1. **diagnozuje** środowisko (Pi/PC, Hailo, audio, ffmpeg, Python, Ollama),
2. **pyta** o ustawienia (Enter = domyślne): adres Ollamy, model, kamerę, drugi komputer,
3. **pyta o klucze API** (opcjonalne; wpisywane bez echa, zapis 600 w `~/.astro-secrets/API.txt`),
4. **generuje** `config/astro.env` (ustawienia runtime) i `astro.service` (unit systemd),
5. **tworzy venv** i instaluje zależności (`pip install -r requirements.txt`),
6. robi self-test i wypisuje następne kroki.

Warianty: `bash setup.sh --check` (tylko diagnoza), `bash setup.sh --yes` (domyślne bez pytań).

### Krok 4 — Ollama i modele

```bash
# instalacja Ollamy (jeśli nie masz): https://ollama.com/download
curl -fsSL https://ollama.com/install.sh | sh

# modele (nazwy możesz zmienić w config/astro.env):
ollama pull qwen2.5:7b        # czat (na Pi 8GB — spokojnie; na 16GB możesz większy)
ollama pull nomic-embed-text  # embeddingi do pamięci (wymagany)
# opcjonalnie — opis obrazu (VLM):
ollama pull qwen2.5vl:3b
```

### Krok 5 — test w trybie tekstowym (bez mikrofonu)

```bash
cd ~ && source ~/astro/config/astro.env
~/astro/venv/bin/python -m astro.scripts.astro_repl "czat Cześć, kim jesteś?"
```

Powinieneś dostać odpowiedź po polsku. Jeśli tak — rdzeń działa. 🎉

### Krok 6 — modele głosu (STT/TTS)

```bash
mkdir -p ~/astro/models/vosk ~/astro/models/piper

# STT — Vosk (mały polski model ~50 MB):
wget -q https://alphacephei.com/vosk/models/vosk-model-small-pl-0.22.zip -O /tmp/vosk.zip
unzip -q /tmp/vosk.zip -d ~/astro/models/vosk/

# TTS — Piper (głos żeński, ~60 MB):
wget -q https://huggingface.co/rhasspy/piper-voices/resolve/main/pl/pl_PL/gosia/medium/pl_PL-gosia-medium.onnx \
     -O ~/astro/models/piper/pl_PL-gosia-medium.onnx
wget -q https://huggingface.co/rhasspy/piper-voices/resolve/main/pl/pl_PL/gosia/medium/pl_PL-gosia-medium.onnx.json \
     -O ~/astro/models/piper/pl_PL-gosia-medium.onnx.json
```

Potem uzupełnij w `config/astro.env`:
```bash
ASTRO_STT=vosk
ASTRO_TTS_MODEL=/home/TWOJ_USER/astro/models/piper/pl_PL-gosia-medium.onnx
ASTRO_AUDIO_DEVICE=plughw:CARD=TwojaKarta,DEV=0   # sprawdź: arecord -l
```

### Krok 7 — tryb głosowy

```bash
cd ~/astro && source config/astro.env
venv/bin/python scripts/astro_voice.py
```

Powiedz **„Hej Astro"**, a potem np. „która godzina". Zakończ: „dziękuję".

### Krok 8 — autostart (usługa systemd)

```bash
sudo cp ~/astro/astro.service /etc/systemd/system/astro.service
sudo systemctl daemon-reload
sudo systemctl enable --now astro
journalctl -fu astro        # podgląd na żywo
```

---

## 4. Co działa BEZ czego (macierz odporności)

To najważniejsza sekcja przy przenoszeniu ASTRO na inną maszynę/sieć:

| Brak… | Co przestaje działać | Co działa dalej |
|---|---|---|
| internetu | remote_ai, premium | wszystko lokalne (offline) |
| drugiego komputera (PC) | tryb „komputer" | offline; ASTRO sam wraca na CPU |
| kluczy API | remote_ai, premium | offline |
| Hailo | akceleracja NPU | CPU (wolniej, ale stabilnie) |
| mikrofonu/głośnika | tryb głosowy | tryb tekstowy (`astro_repl.py`) |
| kamery | „spójrz / co widzisz" | reszta asystenta |
| Ollamy | czat modelowy | nic — **to jedyna twarda zależność** |

**Tryby przełączasz głosem:** „tryb offline" / „tryb komputer" / „tryb premium".
ASTRO **sam degraduje** — gdy warstwa padnie, schodzi niżej (premium → komputer → offline).

---

## 5. Warstwy zdalne — konfiguracja szczegółowa

### 5a. Tryb „komputer" (drugi PC z Ollamą)

Najprostszy wariant — Ollama na drugim komputerze w tej samej sieci:

```bash
# na drugim komputerze (np. laptop z NVIDIA):
ollama serve   # domyślnie 0.0.0.0:11434
ollama pull SpeakLeash/bielik-11b-v3.0-instruct:Q4_K_M   # albo własny model
```

W `config/astro.env` na maszynie ASTRO:
```bash
ASTRO_PC_URL=http://192.168.1.50:11434
ASTRO_PC_MODEL=SpeakLeash/bielik-11b-v3.0-instruct:Q4_K_M
```

Test: powiedz „tryb komputer" — ASTRO potwierdzi status. Weryfikacja:
```bash
venv/bin/python scripts/preflight.py --endpoint "pc=http://192.168.1.50:11434|SpeakLeash/bielik-11b-v3.0-instruct:Q4_K_M"
```

> **Tunel SSH (zaawansowane):** jeśli komputer jest poza siecią lokalną, zrób tunel:
> `ssh -N -L 11434:127.0.0.1:11434 user@komputer` i ustaw `ASTRO_PC_URL=http://127.0.0.1:11434`.

### 5b. Tryb „remote_ai" (darmowe chmury)

W `setup.sh` podaj klucze (albo uzupełnij `~/.astro-secrets/API.txt` ręcznie):

```
Gemini
    Key: TWOJ_KLUCZ
Groq
    Key: TWOJ_KLUCZ
```

Darmowe konta: [Google AI Studio](https://aistudio.google.com/api-keys),
[Groq](https://console.groq.com/keys), [OpenRouter](https://openrouter.ai),
[HuggingFace](https://huggingface.co/settings/tokens).

### 5c. Tryb „premium" (OpenCode Go — darmowe modele)

1. Załóż konto na [opencode.ai](https://opencode.ai) i subskrybuj plan **Go**
   (darmowe modele `space-bunny-free` i `longcat-2.5-preview-free` są w cenie planu).
2. Skopiuj klucz API (format `oc_sk_...`) do `~/.astro-secrets/API.txt`:
   ```
   OpenCode
       Key: oc_sk_TWOJ_KLUCZ
   ```
3. Sprawdź: `venv/bin/python -c "import astro.remote_support as r; print(r.opencode_chain()[:1])"`
4. Powiedz „tryb premium" — ASTRO potwierdzi „Status premium - gotowe".

> **Monitor kosztów wbudowany:** komendy głosem „premium zużycie" i „premium limity"
> pokazują tokeny/koszt; przy przekroczeniu dziennego bezpiecznika ASTRO uprzedzi głosem.

### 5d. Kamera (ONVIF/RTSP) — opcjonalnie

W `setup.sh` odpowiedz „t” przy pytaniu o kamerę, albo wpisz ręcznie:
```bash
ASTRO_CAMERA_HOST=192.168.1.60
ASTRO_CAMERA_RTSP=rtsp://192.168.1.60:554/live/ch0
ASTRO_CAMERA_FLIP=180
```
Test: powiedz „spójrz, co widzisz" (opcjonalny opis sceny przez VLM/LLM).

---

## 6. Testy i współtworzenie

```bash
cd ~ && python3 -m unittest discover -s astro/tests -q   # testy jednostkowe
```

- Zbiór treningowy: `venv/bin/python scripts/build_dataset.py`
- Bramki jakości: `scripts/polish_gate.py`, `scripts/e9_gate.py`
- Eksperymenty LoRA: `scripts/train_lora_hf.py` (wymaga GPU; na Pi odpada)

---

## 7. Rozwiązywanie problemów

| Objaw | Przyczyna / rozwiązanie |
|---|---|
| „odpowiedź pusta" / dziwne znaki | model „thinking" zużył budżet na rozumowanie — zwiększ `max_tokens`; albo Ollama nie ma modelu: `ollama pull ...` |
| brak dźwięku (arecord: Device busy) | mikrofon zajęty przez inny proces: `sudo fuser -v /dev/snd/*`; restart usługi: `sudo systemctl restart astro` |
| wolne odpowiedzi | model za duży na CPU — użyj mniejszego (`qwen2.5:3b`) albo trybu „komputer"/„premium" |
| kamera nie odpowiada | sprawdź `ping`, port 554: `ffprobe rtsp://...`; poprawny adres w `ASTRO_CAMERA_RTSP` |
| tryb premium „Pracuję lokalnie" | brak/niepoprawny klucz w API.txt; sprawdź `~/.astro-secrets/API.txt` i log usługi |
| `import astro` nie działa | uruchamiaj z katalogu **nadrzędnego** repo (`cd ~ && python3 -m ...`) lub zainstaluj zależności |
| usługa systemd nie startuje | `journalctl -u astro -n 50`; sprawdź `config/astro.env` (ścieżki!) |

---

## 8. Bezpieczeństwo i higiena

- **Sekrety trzymaj w `~/.astro-secrets/`** (600) — nigdy w repo (`.gitignore` pilnuje `secrets/`, `*.env`).
- Klucze API wgrane do czatu/logów — **rotuj** (unieważnij i wygeneruj nowe).
- Pamięć (baza wiedzy) rośnie w `runtime/` — możesz ją czyścić/backupować osobno.
- Tryby zdalne wysyłają teksty rozmów (a premium-vision — obrazy z kamery) do chmury.
  Informacje o retencji: opencode.ai/docs (modele free: 0 dni).

## 9. Hailo (opcjonalnie, tylko Raspberry Pi 5)

Jeśli masz HAT AI z Hailo:
```bash
# sterowniki: https://github.com/hailo-ai/hailort (lub pakiet hailort z RPi)
# modele HEF:
bash scripts/fetch_hailo_vision.sh    # YOLOv8s + SCRFD (obiekty/twarze)
bash scripts/fetch_hailo_vlm.sh       # Qwen3-VL (opis obrazu, eksperymentalny)
```
W `config/astro.env`: `ASTRO_NPU=1`, `ASTRO_STT=npu` (Whisper HEF) — sprawdź
`ls /dev/hailo*` i `hailortcli fw-control identify`.

---

*Powodzenia! Jeśli coś nie działa — zajrzyj do sekcji 7 albo zgłoś Issue w repo.* 🤖
