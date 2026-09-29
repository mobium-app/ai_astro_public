"""Konfiguracja ASTRO: ścieżki, backendy, opcje środowiskowe. Brak logiki."""

import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _env(name, default):
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _flag(name, default="0"):
    return _env(name, default).strip().lower() in ("1", "true", "yes", "on")


RUNTIME_DIR = Path(_env("ASTRO_RUNTIME", str(Path.home() / "astro" / "runtime")))
LOGS_DIR = RUNTIME_DIR / "logs"
DB_PATH = Path(_env("ASTRO_DB", str(RUNTIME_DIR / "memory.db")))
WORKSPACE = Path(_env("ASTRO_WORKSPACE", str(Path.home() / "astro-agent")))
KNOWLEDGE_DIR = Path(_env("ASTRO_KNOWLEDGE", str(REPO / "knowledge")))
FACTS_FILE = KNOWLEDGE_DIR / "facts.txt"
FIRST_AID_FILE = KNOWLEDGE_DIR / "first_aid.txt"

LLM_URL = _env("ASTRO_LLM_URL", "http://127.0.0.1:11434")
LLM_MODEL = _env("ASTRO_LLM", "qwen2.5:7b")
LLM_TOOLS_MODEL = _env("ASTRO_TOOLS_MODEL", "qwen2.5:3b")
LLM_THREADS = int(_env("ASTRO_THREADS", "3"))
LLM_KEEP_ALIVE = _env("ASTRO_KEEP_ALIVE", "24h")
# Przeznaczenie -> model + tryb (switch „po przeznaczeniu", Faza E). Tryb dotyczy modeli
# hybrydowych (Qwen3: /think|/no_think); dla pozostałych to metadane polityki.
MODEL_CHAT = _env("ASTRO_MODEL_CHAT", LLM_MODEL)
MODEL_TOOLS = _env("ASTRO_MODEL_TOOLS", LLM_TOOLS_MODEL)
MODE_CHAT = _env("ASTRO_MODE_CHAT", "quality")
MODE_TOOLS = _env("ASTRO_MODE_TOOLS", "no_think")
EMBED_MODEL = _env("ASTRO_EMBED", "nomic-embed-text")

PC_ENABLED = _flag("ASTRO_PC")
# PC-Kali jako wsparcie RUNTIME (nie tylko nauczyciel offline): rejestruje backend `pc`.
# Opt-in (0) — jak dotąd PC/remote nie są domyślnie w runtime; włącz w drop-inie usługi
# (`ASTRO_PC_RUNTIME=1`), by tryb „komputer" i awaryjny offline korzystały z PC przez tunel.
# Gdy tunel/PC jest niedostępny, `ready()` szybko zwraca False (HTTP timeout 3 s).
PC_RUNTIME = _flag("ASTRO_PC_RUNTIME", "0")
PC_URL = _env("ASTRO_PC_URL", "http://127.0.0.1:11435")
# PC-Kali = nauczyciel polszczyzny/teorii (decyzja użytkownika, 2026-09-23): bielik-11b.
PC_MODEL = _env("ASTRO_PC_MODEL", "SpeakLeash/bielik-11b-v3.0-instruct:Q4_K_M")
# Ollama trzyma model w RAM po odpowiedzi; domyślne 5 min wyładowywało 11B między pytaniami
# (zimny start = kilka-kilkanaście s). PC jest teraz pierwszy w łańcuchu, więc trzymamy ciepło.
PC_KEEP_ALIVE = _env("ASTRO_PC_KEEP_ALIVE", "30m")
PC_WARM = _flag("ASTRO_PC_WARM", "1")

REMOTE_ENABLED = _flag("ASTRO_REMOTE")
REMOTE_URL = _env("ASTRO_REMOTE_URL", "")
REMOTE_MODEL = _env("ASTRO_REMOTE_MODEL", "")
REMOTE_KEY = _env("ASTRO_REMOTE_KEY", "")
REMOTE_TIMEOUT = int(_env("ASTRO_REMOTE_TIMEOUT", "120"))
# Plik z kluczami API dostawców zdalnych (ASTRO, nie Atena). Format: atena-share/API.
# Uwaga: na tym urządzeniu plik jest jako `API.txt` — akceptujemy obie nazwy (kolejność: env,
# `API`, `API.txt`), żeby brak rozszerzenia nie wyzerował całego łańcucha dostawców.
def _api_file():
    explicit = os.environ.get("ASTRO_API_FILE", "")
    if explicit:
        return explicit
    for cand in ("/etc/astro-secrets/API", "/etc/astro-secrets/API.txt"):
        if Path(cand).is_file():
            return cand
    return "/etc/astro-secrets/API"


API_FILE = _api_file()
# Limit generacji NAUCZYCIELA (`cloud_teacher`). Darmowe konta (OpenRouter/HF) mają mały budżet
# na request (np. „afford 625" przy max_tokens=2048 → HTTP 402). 512 wystarcza na wywołanie
# narzędzia i finalną odpowiedź; dla czatu (Ollama/bielik) można podnieść env-em.
TEACHER_MAX_TOKENS = int(_env("ASTRO_TEACHER_MAX_TOKENS", "512"))
# Osobny, mniejszy limit na samą turę WYWOŁANIA NARZĘDZIA (nazwa+argumenty = mało tokenów).
# Chroni przed 402 u dostawców, którzy rezerwują `max_tokens` z góry (OpenRouter/DeepSeek).
TEACHER_TOOLCALL_TOKENS = int(_env("ASTRO_TEACHER_TOOLCALL_TOKENS", "256"))


# Mirror pracy ASTRO na terminale (zalogowane sesje SSH/konsola) + (opcjonalnie) VT/console.
MIRROR = _flag("ASTRO_MIRROR", "1")
MIRROR_VT = _flag("ASTRO_MIRROR_VT", "1")

NPU_ENABLED = _flag("ASTRO_NPU")
NPU_MODEL = _env("ASTRO_NPU_MODEL", "qwen2.5-instruct:1.5b")
# Czat na NPU (1.5B) jest szybki, ale ma słabą polszczyznę. Domyślnie 0 = jakość (CPU 7B);
# NPU zostaje dla STT. Ustaw ASTRO_NPU_CHAT=1, by wrócić do NPU-first czatu (E5).
NPU_CHAT = _flag("ASTRO_NPU_CHAT")
# C3 (C3 = P1.5): reuse kontekstu KV na NPU między turami (bez `clear_context`). Opt-in i ostrożnie
# — API Hailo genai nie dokumentuje przyrostowego kontekstu, więc domyślnie 0 (clear co turę).
NPU_KV_REUSE = _flag("ASTRO_NPU_KV_REUSE", "0")


def _first_existing(*candidates):
    for c in candidates:
        if c and Path(c).exists():
            return str(c)
    return str(candidates[0]) if candidates else ""


NPU_HEF = _first_existing(
    _env("ASTRO_NPU_WHISPER_HEF", ""),
    _env("ASTRO_NPU_HEF", ""),
    str(REPO / "models" / "hailo" / "Whisper-Base.hef"),
    str(Path.home() / "voice-assistant" / "models" / "hailo" / "Whisper-Base.hef"),
)
NPU_LLM_HEF = _env("ASTRO_NPU_LLM_HEF", "")

AGENT_MAX_STEPS = int(_env("ASTRO_AGENT_MAX_STEPS", "6"))
# Streaming odpowiedzi (C4, opt-in): tokeny czatu lecą na `ctx.stream_sink` (np. stdout w REPL),
# zamiast czekać na całość. Dotyczy WYŁĄCZNIE czatu (bez narzędzi) — tool-calling zostaje
# niezmieniony (bezpieczeństwo). Domyślnie 0 (zachowanie jak dotąd).
STREAM = _flag("ASTRO_STREAM", "0")
CONFIRM_TTL = int(_env("ASTRO_CONFIRM_TTL", "300"))
# Cache `backend.ready()` (P1.4): ile sekund ufać ostatniemu wynikowi (0 = bez cache).
BACKEND_READY_TTL = float(_env("ASTRO_BACKEND_READY_TTL", "3"))
# Limit cache wektorów trajektorii (LRU, C2): 0 = bez limitu.
TRAJ_CACHE_MAX = int(_env("ASTRO_TRAJ_CACHE_MAX", "512"))
# Mirror (C5): okno deduplikacji identycznych zapisów (s) i limit ścieżek VT (0 = bez limitu).
MIRROR_DEDUP_S = float(_env("ASTRO_MIRROR_DEDUP_S", "0.8"))
MIRROR_VT_MAX = int(_env("ASTRO_MIRROR_VT_MAX", "64"))
MAX_TOOLS = int(_env("ASTRO_MAX_TOOLS", "6"))
# Nauka w runtime: liczba wzorców wywołań narzędzi wstrzykiwanych do kontekstu agenta.
# A1 (2026-09-22, pomiar na kanonicznej bramce): few-shot z pamięci ZASZKODZIŁ i spowolnił
# (v5: fs0 = 8/8 tools, fs1 ≈ 4/8 i timeout) — dlatego domyślnie 0. Przed ponownym włączeniem
# popraw retrieval/format wzorców i zmierz `e6_gate --few-shot 0/1/2`.
FEWSHOT = int(_env("ASTRO_FEWSHOT", "0"))
# Próg podobieństwa retrieval trajektorii do few-shot (embedding kosinus). Podniesiony z 0.55:
# mierzone 2026-09-24 — słabe trafienia mylą model i gaszą wywołania narzędzi.
FEWSHOT_MIN_SCORE = float(_env("ASTRO_FEWSHOT_MIN_SCORE", "0.75"))
# Pamięć robocza rozmowy (P1, 2026-09-26): krótka historia tur wstrzykiwana WYŁĄCZNIE do
# czatu (tury bez wyboru narzędzi), by ASTRO nie gubił wątku („a jak bardzo?”). Tool-calling
# pozostaje bez historii — ochrona LoRA v7 przed regresem. GAP = po ilu sekundach ciszy
# sesja startuje od nowa; MAX_CHARS = budżet tekstu historii (najnowsza para zawsze zostaje).
SESSION_ENABLED = _flag("ASTRO_SESSION_MEMORY", "1")
SESSION_TURNS = int(_env("ASTRO_SESSION_TURNS", "6"))
SESSION_GAP_S = float(_env("ASTRO_SESSION_GAP", "900"))
SESSION_MAX_CHARS = int(_env("ASTRO_SESSION_MAX_CHARS", "1600"))
# P2: budżet znaków zwiniętego wątku (najstarsze tury streszczane bez modelu).
SESSION_SUMMARY_MAX_CHARS = int(_env("ASTRO_SESSION_SUMMARY_MAX_CHARS", "400"))
# P3: streszczanie zwijanego wątku MODELEM LOKALNYM (0 = heurystyczne, tanie). Model lokalny
# (cpu/npu, `local_only`) bywa wolny, ale daje lepsze streszczenie niż sklejanie urwanych tur.
SESSION_SUMMARY_MODEL = _flag("ASTRO_SESSION_SUMMARY_MODEL", "0")
# P4 (2026-09-27): KONTEKST TRWAŁY. Surowa historia NIE może trafiać inline — prefill na CPU
# Pi 5 to ~7 tok/s (7 dni ~2,4 h). Dlatego: dzienne skróty (digesty) + archiwum `.md`, a na
# starcie wstrzykiwany jest ZWIĘZŁY, STAŁY blok (prefiks cache'owany przez Ollamę — koszt
# prefillu raz, nie co turę). CONTEXT_DAYS = ile dni wstecz; CONTEXT_MAX_CHARS = budżet bloku.
CONTEXT_ENABLED = _flag("ASTRO_CONTEXT_MEMORY", "1")
CONTEXT_DAYS = int(_env("ASTRO_CONTEXT_DAYS", "7"))
CONTEXT_MAX_CHARS = int(_env("ASTRO_CONTEXT_MAX_CHARS", "700"))
CONTEXT_DIR = RUNTIME_DIR / "context"
# Ile surowych tur trzymać w `session_turns` (źródło digestów/archiwum). Wcześniej 50 —
# za mało na dzienny/tygodniowy skrót; digesty i tak przeżywają prune (osobna tabela).
SESSION_RAW_KEEP = int(_env("ASTRO_SESSION_RAW_KEEP", "1000"))
METRICS_FILE = LOGS_DIR / "metrics.jsonl"
NPU_TELEMETRY_FILE = LOGS_DIR / "npu.jsonl"

# Tryby pracy (2026-09-26): głosowy przełącznik profilu routingu backendów.
#   offline  = lokalnie najpierw (CPU/NPU), awaryjnie PC-Kali i remote_ai (stan dotychczasowy)
#   komputer = PC-Kali (bielik) jako runtime brain (NIE trening), lokalny fallback
#   premium  = OpenCode Go / DeepSeek w runtime (z lokalnym fallbackiem, gdy brak sieci)
# Stan trwały w pliku `MODE_FILE` (przeżywa restart); `MODE_DEFAULT` tylko dla braku pliku.
MODE_DEFAULT = _env("ASTRO_MODE", "offline")
MODE_FILE = RUNTIME_DIR / "mode.json"
# Opcjonalny dzienny limit kosztów trybu premium (OpenCode Go). 0 = bez limitu.
# Po przekroczeniu rejestr CICHO pomija backend `premium` i schodzi na pc/cpu — chroni rachunek,
# a tryb nadal działa lokalnie (auto-degradacja). Liczone z `logs/remote_usage.jsonl`.
PREMIUM_DAILY_TOKENS = int(_env("ASTRO_PREMIUM_DAILY_TOKENS", "0"))
PREMIUM_DAILY_REQUESTS = int(_env("ASTRO_PREMIUM_DAILY_REQUESTS", "0"))

# Fraza wake (może być wielowyrazowa). Domyślnie „hej astro" — eksperyment odporności
# na szum tła (2026-09-20); pełna identyfikacja/branding po potwierdzeniu w praktyce.
WAKE_WORD = _env("ASTRO_WAKE_WORD", "hej astro")
AUDIO_DEVICE = _env("ASTRO_AUDIO_DEVICE", "plughw:CARD=wm8960,DEV=0")
SAMPLE_RATE = int(_env("ASTRO_SAMPLE_RATE", "16000"))
RECORDER = _env("ASTRO_RECORDER", "arecord")
PLAYER = _env("ASTRO_PLAYER", "aplay")
VOICE_SESSION_S = float(_env("ASTRO_VOICE_SESSION", "6"))
VOICE_LISTEN_S = float(_env("ASTRO_VOICE_LISTEN", "4"))
VOICE_VAD_SILENCE_S = float(_env("ASTRO_VAD_SILENCE", "0.8"))
VOICE_VAD_MIN_SPEECH_S = float(_env("ASTRO_VAD_MIN_SPEECH", "0.3"))
# Próg VAD (RMS). Uwaga: zmierzony szum tła WM8960 ~0.013 RMS — przy 0.01 VAD startował na
# szumie i Whisper "słyszał" polecenia w tle. Dodatkowo VAD sam dostraja próg do szumu
# (patrz `capture.speech_from_chunks`).
VOICE_VAD_THRESHOLD = float(_env("ASTRO_VAD_THRESHOLD", "0.02"))
VOICE_VAD_WARMUP_S = float(_env("ASTRO_VAD_WARMUP", "0.4"))
# (c) Trwale otwarty strumień mikrofonu (jeden arecord na sesję) — usuwa narzut otwarcia karty
# i warmup przy KAŻDEJ turze. Domyślnie 0: wymaga weryfikacji live (barge-in otwiera własny
# strumień, więc przy 1 barge-in jest wyłączony).
MIC_PERSISTENT = _flag("ASTRO_MIC_PERSISTENT", "0")

# Barge-in („speak-to-interrupt"): ASTRO przestaje mówić, gdy użytkownik zaczyna mówić.
# DOMYŚLNIE WYŁĄCZONE: na WM8960 (pół-duplex, głośnik przesłuchuje mikrofon) włączenie
# powodowało przerwanie własnej wypowiedzi ASTRO („nie melduje się", dziwny beeper).
# Włącz świadomie: ASTRO_BARGE_IN=1 (eksperymentalne).
BARGE_IN = _flag("ASTRO_BARGE_IN", "0")
BARGE_THRESHOLD = float(_env("ASTRO_BARGE_THRESHOLD", "0.06"))
BARGE_WARMUP_S = float(_env("ASTRO_BARGE_WARMUP", "0.5"))

# MCP (Model Context Protocol): klient zdalnych serwerów narzędzi (stdio JSON-RPC).
# Włączone jawnie albo automatycznie, gdy istnieje plik konfiguracyjny serwerów.
MCP_ENABLED = _flag("ASTRO_MCP")
MCP_CONFIG = _env("ASTRO_MCP_CONFIG", str(Path.home() / ".astro-mcp.json"))
MCP_TIMEOUT = int(_env("ASTRO_MCP_TIMEOUT", "30"))

# Home Assistant / MQTT (whitelist encji + potwierdzenia dla mutacji).
HA_CONFIG = _env("ASTRO_HA_CONFIG", str(Path.home() / ".astro-ha.json"))
HA_TIMEOUT = int(_env("ASTRO_HA_TIMEOUT", "15"))

# Wizja (kamera + VLM na Hailo) — sprzęt opcjonalny; bez niego narzędzie mówi wprost.
VISION_ENABLED = _flag("ASTRO_VISION")
VLM_HEF = _env("ASTRO_VLM_HEF", "")

# Kamera sieciowa (ONVIF/RTSP) = „oczy" ASTRO. Podłączona na stałe 2026-09-28 (192.168.0.1):
# ONVIF 8899 (PTZ, bez auth), RTSP `live/ch0` (H.264, 3 MP). `ASTRO_CAMERA=0` wyłącza;
# brak sieci/kamery daje czytelny komunikat zamiast halucynacji.
CAMERA_ENABLED = _flag("ASTRO_CAMERA", "1")
CAMERA_HOST = _env("ASTRO_CAMERA_HOST", "192.168.0.1")
CAMERA_NAME = _env("ASTRO_CAMERA_NAME", "kamera ASTRO")
CAMERA_RTSP = _env("ASTRO_CAMERA_RTSP", f"rtsp://{CAMERA_HOST}:554/live/ch0")
CAMERA_ONVIF = _env("ASTRO_CAMERA_ONVIF", f"http://{CAMERA_HOST}:8899/onvif/device_service")
CAMERA_PTZ_URL = _env("ASTRO_CAMERA_PTZ_URL", f"http://{CAMERA_HOST}:8899/onvif/Ptz")
CAMERA_MEDIA_URL = _env("ASTRO_CAMERA_MEDIA_URL", f"http://{CAMERA_HOST}:8899/onvif/Media")
CAMERA_PROFILE = _env("ASTRO_CAMERA_PROFILE", "profile_0")
CAMERA_USER = _env("ASTRO_CAMERA_USER", "")
CAMERA_PASS = _env("ASTRO_CAMERA_PASS", "")
CAMERA_SPEED = float(_env("ASTRO_CAMERA_SPEED", "0.6"))
CAMERA_MOVE_MS = int(_env("ASTRO_CAMERA_MOVE_MS", "600"))
CAMERA_TIMEOUT = float(_env("ASTRO_CAMERA_TIMEOUT", "6"))
# Obrót obrazu (kamera bywa montowana „do góry nogami"): "180" (domyślnie), "none", "hflip", "vflip".
CAMERA_FLIP = _env("ASTRO_CAMERA_FLIP", "180")
CAMERA_SNAPSHOT = _env("ASTRO_CAMERA_SNAPSHOT",
                       str(RUNTIME_DIR / "camera" / "last.jpg"))
# Wielokamera (Faza 3): dodatkowe źródła poza główną `CAMERA_*` (indeks 0). Rozdzielana
# przecinkami lista „nazwa=rtsp|ptz|profil" (ptz/profil opcjonalne; profil domyślnie profile_0).
CAMERA_SOURCES = _env("ASTRO_CAMERA_SOURCES", "")

# Wizja AI („oczy"): ocena otoczenia (osoby/przedmioty/emocje) + rozpoznawanie osób (twarze).
# Modele ONNX (opencv_zoo) w `models/vision/`; działają lokalnie na CPU (bez chmury).
VISION_AI_ENABLED = _flag("ASTRO_VISION_AI", "1")
VISION_MODELS_DIR = Path(_env("ASTRO_VISION_MODELS", str(REPO / "models" / "vision")))
# Detekcja obiektów na Hailo NPU („oczy na NPU"): YOLOv8 HEF w `models/hailo/` — odciąża CPU.
# Gdy NPU niedostępny/zajęty przez inny proces — automatyczny fallback na CPU (NanoDet/ONNX).
VISION_NPU = _flag("ASTRO_VISION_NPU", "1")
VISION_HAILO_DIR = Path(_env("ASTRO_VISION_HAILO", str(REPO / "models" / "hailo")))
VISION_HEF = _env("ASTRO_VISION_HEF", "")
VISION_OBJECT_HEF = _env("ASTRO_VISION_OBJECT_HEF", "yolov8s.hef")
VISION_NPU_SCORE = float(_env("ASTRO_VISION_NPU_SCORE", "0.45"))
# Zdarzenia zmiany kadru w nasłuchu (Faza 2): ruch / wejście-wyjście / nowe obiekty.
WATCH_CHANGE = _flag("ASTRO_WATCH_CHANGE", "1")
# OCR (Faza 5): Tesseract offline. Języki i binarka konfigurowalne.
TESSERACT_BIN = _env("ASTRO_TESSERACT", "")
OCR_LANG = _env("ASTRO_OCR_LANG", "pol+eng")
# Twarze na NPU (SCRFD): HEF w `models/hailo/`; landmarki pozwalają wyrównać do SFace bez YuNet.
VISION_FACE_HEF = _env("ASTRO_VISION_FACE_HEF", "scrfd_2.5g.hef")
VISION_FACE_SCORE = float(_env("ASTRO_VISION_FACE_SCORE", "0.5"))
VISION_FACE_NMS = float(_env("ASTRO_VISION_FACE_NMS", "0.4"))
FACE_ENABLED = _flag("ASTRO_FACE", "1")
FACE_MATCH_THRESHOLD = float(_env("ASTRO_FACE_MATCH", "0.35"))
FACE_LOG = _flag("ASTRO_FACE_LOG", "1")
# Wiek/płeć (Faza 3): GoogleNet ONNX (Levi & Hassner, Adience) dla najbliższej twarzy.
AGEGENDER_ENABLED = _flag("ASTRO_AGEGENDER", "1")
# Emocja z kamery -> stan afektywny ASTRO (PAD): wyrazy twarzy podbijają/studzą nastrój.
AFFECT_VISION = _flag("ASTRO_AFFECT_VISION", "1")
# Rozpoznawanie sylwetki (person re-ID) — gdy twarzy nie widać (osoba odwrócona/oddalona).
BODY_ENABLED = _flag("ASTRO_BODY", "1")
BODY_MATCH_THRESHOLD = float(_env("ASTRO_BODY_MATCH", "0.55"))
# Ochrona biometrii (Faza 6): szyfrowanie embeddingów twarzy/sylwetek w spoczynku (AES-GCM).
BIO_ENCRYPT = _flag("ASTRO_BIO_ENCRYPT", "1")
BIO_KEY_FILE = _env("ASTRO_BIO_KEY", str(RUNTIME_DIR / "bio.key"))
# Retencja zobaczeń (dni) — starsze czyszczone; 0 = bez limitu.
SIGHTINGS_RETENTION_DAYS = int(_env("ASTRO_SIGHTINGS_RETENTION", "90"))
# Opcjonalny opis sceny przez VLM (Ollama, model z obsługą obrazu, np. moondream/qwen2.5vl).
VLM_MODEL = _env("ASTRO_VLM_MODEL", "")
VLM_URL = _env("ASTRO_VLM_URL", LLM_URL)
VLM_TIMEOUT = int(_env("ASTRO_VLM_TIMEOUT", "120"))
# Rozmiar klatki dla VLM (mniej = mniej tokenów wizji, szybciej) i kontekst modelu.
VLM_IMAGE_PX = int(_env("ASTRO_VLM_IMAGE_PX", "896"))
VLM_NUM_CTX = int(_env("ASTRO_VLM_NUM_CTX", "8192"))
# VLM na NPU Hailo (Faza 4, offline): HEF Qwen2-VL-2B (`ASTRO_VLM_HEF`) + przełącznik.
# `VLM_HAILO` włącza ścieżkę NPU w BIEŻĄCYM procesie (jedno VDevice dzielone ze STT/LLM) —
# ustawia się go tylko tam, gdzie ASTRO jest właścicielem NPU (astro.service), nie w API.
VLM_HAILO = _flag("ASTRO_VLM_HAILO")
VLM_HAILO_IMAGE_PX = int(_env("ASTRO_VLM_HAILO_IMAGE_PX", "336"))
VLM_MAX_TOKENS = int(_env("ASTRO_VLM_MAX_TOKENS", "96"))
# Dekodowanie VLM na NPU (mniej zapętleń PL): jądro próbkowania + kara za powtórzenia.
# `do_sample=0` = greedy (deterministycznie); top_p/top_k/frequency_penalty jak w hailo-apps.
VLM_TEMPERATURE = float(_env("ASTRO_VLM_TEMPERATURE", "0.1"))
VLM_TOP_P = float(_env("ASTRO_VLM_TOP_P", "0.8"))
VLM_TOP_K = int(_env("ASTRO_VLM_TOP_K", "20"))
VLM_REPEAT_PENALTY = float(_env("ASTRO_VLM_REPEAT_PENALTY", "1.15"))
VLM_DO_SAMPLE = _flag("ASTRO_VLM_DO_SAMPLE", "0")
# Preferowany backend opisu: "ollama" (Kali/PC — lepsza jakość 3B) albo "hailo" (NPU, offline).
# Drugi jest fallbackiem, więc offline nadal działa (Hailo-first gdy prefer=hailo).
VLM_PREFER = _env("ASTRO_VLM_PREFER", "ollama")

TTS_ENGINE = _env("ASTRO_TTS_ENGINE", "piper")
PIPER = (_env("ASTRO_PIPER", "")
         or next((p for p in (str(REPO / "venv" / "bin" / "piper"),
                              str(Path.home() / "voice-assistant" / "venv" / "bin" / "piper"))
                  if Path(p).exists()), "piper"))
TTS_MODEL = (_env("ASTRO_TTS_MODEL", "")
             or next((p for p in (
                 # Preferuj głos żeński/dziewczęcy (decyzja użytkownika 2026-09-29: „dziewczynka");
                 # kolejność: gosia (repo) → gosia (legacy) → darkman → mc_speech (fallback męski).
                 str(REPO / "models" / "piper" / "pl_PL-gosia-medium.onnx"),
                 str(Path.home() / "voice-assistant" / "models" / "piper" / "pl_PL-gosia-medium.onnx"),
                 str(REPO / "models" / "piper" / "pl_PL-darkman-medium.onnx"),
                 str(REPO / "models" / "piper" / "pl_PL-mc_speech-medium.onnx"))
                 if Path(p).exists()), ""))
# Profile brzmienia (sox). „subtle" = lekka robotyzacja bez nakładających się efektów
# (lepsza zrozumiałość — patrz scripts/tts_bench.py). „classic" = dawny, cięższy profil.
# „none" = czysty głos Piper. Nadpisywalne bezpośrednio przez ASTRO_TTS_FX.
TTS_FX_PRESETS = {
    "classic": ("pitch 200 chorus 0.6 0.9 50 0.4 0.25 2 -t tremolo 8 25 "
                "echo 0.8 0.88 50 0.3 reverb 20 50 100"),
    "subtle": "pitch 120 chorus 0.5 0.8 45 0.3 0.15 2 -t reverb 10 30 60",
    "none": "",
}
TTS_FX_PROFILE = _env("ASTRO_TTS_FX_PROFILE", "none")
TTS_FX = _env("ASTRO_TTS_FX", TTS_FX_PRESETS.get(TTS_FX_PROFILE, TTS_FX_PRESETS["subtle"]))
# Bazowa warstwa barwy doklejana do KAŻDEGO nastroju (spójny ton niezależnie od emocji).
# Domyślnie „dziewczynka" (podniesiony ton) — decyzja użytkownika 2026-09-29. Pusty = dorosły głos.
TTS_PITCH = _env("ASTRO_TTS_PITCH", "pitch 350 tempo 1.06")
# Ścieżka leksykonu wymowy (skróty/nazwy własne -> zapis fonetyczny). Pusty = wbudowany.
TTS_LEXICON = _env("ASTRO_TTS_LEXICON", "")
# Ekspresja (E8.2): skala pauz po wypowiedzi oraz opcjonalne głosy per nastrój
# (ASTRO_TTS_VOICE_<NASTRÓJ>, np. ASTRO_TTS_VOICE_ZMARTWIONA=/path/pl_voice.onnx).
TTS_PAUSE_SCALE = float(_env("ASTRO_TTS_PAUSE_SCALE", "1.0"))
STT_ENGINE = _env("ASTRO_STT", "npu")
# Normalizacja głośności przed ASR (cicha mowa). ASTRO_STT_NORMALIZE=0 wyłącza.
STT_NORMALIZE = _flag("ASTRO_STT_NORMALIZE", "1")
# Próg pewności (Vosk conf 0..1): poniżej traktujemy transkrypcję jako niepewną (M3.3).
STT_CONF_MIN = float(_env("ASTRO_STT_CONF_MIN", "0.6"))
# Próg dopasowania zniekształconej mowy do znanej komendy must-have (0..1; 0 = wyłączone).
STT_COMMAND_MATCH_MIN = float(_env("ASTRO_STT_COMMAND_MATCH_MIN", "0.80"))
# Dokładny ASR CPU (faster-whisper) jako fallback dla niepewnych komend. Poniżej progu FAST
# (0..1) szybkie silniki uznajemy za niepewne i próbujemy dokładniejszego modelu CPU.
STT_WHISPER_ENABLED = _flag("ASTRO_STT_WHISPER", "1")
STT_WHISPER_MODEL = _env("ASTRO_STT_WHISPER_MODEL", "small")
STT_WHISPER_THREADS = int(_env("ASTRO_STT_WHISPER_THREADS", "4"))
STT_COMMAND_FAST = float(_env("ASTRO_STT_COMMAND_FAST", "0.92"))
# (d) Komenda rozpoznana z WŁASNEJ transkrypcji z fuzzy >= tego progu jest pewna — nie pytamy
# o potwierdzenie (mniej tarcia). NIE dotyczy ratunku gramatyką (wymuszona fraza) — ten nadal
# wymaga potwierdzenia, bo gramatyka potrafi wymusić komendę na szumie tła.
STT_CONFIRM_MIN = float(_env("ASTRO_STT_CONFIRM_MIN", "0.95"))
# Rozpoznawanie mowy: lista must-have (bias gramatyki Voska + dopasowanie komend) + frazy z env.
# Źródłem runtime jest WERSJA WBUDOWANA W REPO (trwała, wersjonowana) — plik w /etc/astro-secrets
# jest tylko narzędziem kontrolnym użytkownika. Kolejność: env > repo > /srv (dla zgodności).
_MUSTHAVE_REPO = REPO / "data" / "commands" / "komendy_must-have.txt"
_MUSTHAVE_SHARE = "/etc/astro-secrets/komendy_must-have"
MUSTHAVE_FILE = (_env("ASTRO_MUSTHAVE_FILE", "")
                 or next((str(p) for p in (_MUSTHAVE_REPO,)
                          if Path(p).is_file()),
                         next((p for p in (_MUSTHAVE_SHARE, _MUSTHAVE_SHARE + ".txt")
                               if Path(p).is_file()), str(_MUSTHAVE_REPO))))
MUSTHAVE_SHARE_FILE = next((p for p in (_MUSTHAVE_SHARE, _MUSTHAVE_SHARE + ".txt")
                            if Path(p).is_file()), "")
COMMAND_EXTRA = _env("ASTRO_COMMAND_EXTRA", "")
VOSK_MODEL = (_env("ASTRO_VOSK_MODEL", "")
              or next((p for p in (str(REPO / "models" / "vosk" / "vosk-model-small-pl-0.22"),
                                   str(Path.home() / "voice-assistant" / "models" / "vosk"
                                       / "vosk-model-small-pl-0.22"))
                       if Path(p).is_dir()), ""))
KNOWLEDGE_DB = _env("ASTRO_KNOWLEDGE_DB",
                    str(Path.home() / "voice-assistant" / "knowledge.db"))

# Retrieval `learned` (hybryda semantyka + leksyka). Sam embedding myli pokrewne pytania
# („odmówić zaproszenia" vs „elementy zaproszenia", „commit" vs „O(n)"), więc wymagamy też
# wsparcia leksykalnego (rdzenie słów pytania) — chyba że trafienie jest bardzo bliskie semantycznie.
# Przypadek: sem >= STRONG; albo sem >= MID i lex >= LEX_MID; albo sem >= WEAK i lex >= LEX_WEAK.
LEARNED_SEM_STRONG = float(_env("ASTRO_LEARNED_SEM_STRONG", "0.86"))
LEARNED_SEM_MID = float(_env("ASTRO_LEARNED_SEM_MID", "0.72"))
LEARNED_LEX_MID = float(_env("ASTRO_LEARNED_LEX_MID", "0.5"))
LEARNED_SEM_WEAK = float(_env("ASTRO_LEARNED_SEM_WEAK", "0.78"))
LEARNED_LEX_WEAK = float(_env("ASTRO_LEARNED_LEX_WEAK", "0.25"))
LEARNED_FLOOR = float(_env("ASTRO_LEARNED_FLOOR", "0.60"))
# Waga leksyki w rankingu kandydatów (hybryda = sem + LEX_W * lex).
LEARNED_LEX_W = float(_env("ASTRO_LEARNED_LEX_W", "0.16"))

# Osobowość (E7): plik temperamentu ASTRO (poza repo, 600) + stałe czasowe zaniku nastroju.
PERSONA_FILE = _env("ASTRO_PERSONA_FILE", str(RUNTIME_DIR / "persona.json"))
AFFECT_EMOTION_HALF_LIFE = float(_env("ASTRO_AFFECT_EMOTION_HALF_LIFE", "180"))
AFFECT_MOOD_HALF_LIFE = float(_env("ASTRO_AFFECT_MOOD_HALF_LIFE", "10800"))
# Pamięć afektywna (E8): rozmiar, próg podobieństwa i siła reminiscencji.
AFFECT_MEMORY_MAX = int(_env("ASTRO_AFFECT_MEMORY_MAX", "500"))
AFFECT_RECALL_MIN_SCORE = float(_env("ASTRO_AFFECT_RECALL_MIN_SCORE", "0.34"))
AFFECT_RECALL_WEIGHT = float(_env("ASTRO_AFFECT_RECALL_WEIGHT", "0.2"))
# Humor (E7.6): minimalny odstęp między spontanicznymi żartami (sekundy).
HUMOR_COOLDOWN = float(_env("ASTRO_HUMOR_COOLDOWN", "180"))
# E9: liczba wzorców polszczyzny wstrzykiwanych do kontekstu modelu (0 = brak).
POLISH_FEWSHOT = int(_env("ASTRO_POLISH_FEWSHOT", "2"))

# Proaktywność (M4): inicjatywa ASTRO — powitanie, spontaniczny humor, tryb cichy.
INITIATIVE_ENABLED = _flag("ASTRO_INITIATIVE", "1")
INITIATIVE_HUMOR = _flag("ASTRO_INITIATIVE_HUMOR", "1")
# Spontaniczne zbieranie kontekstu: przy powitaniu dopytaj JEDNO krótkie, brakujące pole profilu
# (zamiast długiego wywiadu). Respektuje ciszę nocną i cooldown powitań.
INITIATIVE_PROFILE_ASK = _flag("ASTRO_INITIATIVE_PROFILE", "1")
INITIATIVE_COOLDOWN = float(_env("ASTRO_INITIATIVE_COOLDOWN", "600"))
INITIATIVE_GREETING_COOLDOWN = float(_env("ASTRO_INITIATIVE_GREETING_COOLDOWN", "21600"))
INITIATIVE_MAX_PER_HOUR = int(_env("ASTRO_INITIATIVE_MAX_PER_HOUR", "6"))
INITIATIVE_QUIET_START = int(_env("ASTRO_INITIATIVE_QUIET_START", "22"))
INITIATIVE_QUIET_END = int(_env("ASTRO_INITIATIVE_QUIET_END", "7"))
INITIATIVE_STATE_FILE = _env("ASTRO_INITIATIVE_STATE",
                             str(RUNTIME_DIR / "initiative.json"))
# Zaczep „idle" w trakcie sesji (0 = wyłączony): po ilu sekundach ciszy ASTRO może się odezwać.
INITIATIVE_IDLE_S = float(_env("ASTRO_INITIATIVE_IDLE", "0"))

# Zapowiedź startowa (D2): powitanie po starcie usługi. Domyślnie wyłączone.
ANNOUNCE_BOOT = _flag("ASTRO_ANNOUNCE_BOOT", "0")
# Obecność (M5): kamera/detekcja twarzy jako trigger inicjatywy. Domyślnie wyłączone.
PRESENCE_ENABLED = _flag("ASTRO_PRESENCE", "0")
PRESENCE_POLL_S = float(_env("ASTRO_PRESENCE_POLL", "2"))


def ensure_dirs():
    for path in (RUNTIME_DIR, LOGS_DIR, WORKSPACE):
        Path(path).mkdir(parents=True, exist_ok=True)
    return RUNTIME_DIR
