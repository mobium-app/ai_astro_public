#!/usr/bin/env bash
# =============================================================================
# ASTRO — setup.sh — PEŁNY instalator dla obcej maszyny (np. świeżego Pi 5).
#
# JEDNO polecenie na obcym Pi:
#   curl -fsSL https://raw.githubusercontent.com/mobium-app/ai_astro_public/main/setup.sh | bash
# albo po sklonowaniu repo:  bash setup.sh
#
# Co obejmuje (całość):
#   [1] zależności systemowe (apt, za zgodą)      [2] klon repo (jeśli poza repo)
#   [3] diagnoza sprzętu                          [4] konfiguracja + klucze API (opcjonalne)
#   [5] modele: Ollama (+pull), Vosk STT, Piper TTS
#   [6] venv + zależności Python                  [7] usługa systemd (za zgodą)
#   [8] self-test i następne kroki
#
# Tryby:
#   bash setup.sh            # interaktywny (zalecany)
#   bash setup.sh --check    # tylko diagnoza — nic nie zapisuje/instaluje
#   bash setup.sh --yes      # domyślne bez pytań (klucze API pomijane)
#   bash setup.sh --update   # SYNCHRO: git pull + zależności + modele + restart usługi
#
# Skrypt niczego nie nadpisuje bez kopii .bak-<data>.
# =============================================================================
set -uo pipefail

MODE="interactive"
case "${1:-}" in
  --check)  MODE="check" ;;
  --yes)    MODE="auto" ;;
  --update) MODE="update" ;;
  --help|-h) sed -n '2,26p' "$0"; exit 0 ;;
esac

PUB_REPO="${ASTRO_REPO_URL:-https://github.com/mobium-app/ai_astro_public.git}"
SECRETS_DIR="${HOME}/.astro-secrets"
STAMP="$(date +%Y%m%d-%H%M%S)"

# --- kolory ---
if [ -t 1 ]; then C_B="\033[1m"; C_G="\033[32m"; C_Y="\033[33m"; C_R="\033[31m"; C_0="\033[0m"
else C_B=""; C_G=""; C_Y=""; C_R=""; C_0=""; fi
info() { printf "%b\n" "${C_B}[setup]${C_0} $*"; }
ok()   { printf "%b\n" "${C_G}[ OK ]${C_0} $*"; }
warn() { printf "%b\n" "${C_Y}[uwaga]${C_0} $*" >&2; }
err()  { printf "%b\n" "${C_R}[błąd]${C_0} $*" >&2; }

# --- pytania ---
ask() { # $1=zmienna $2=pytanie $3=domyślna
  local __v="$1" __q="$2" __d="${3:-}" __a=""
  if [ "$MODE" = "auto" ]; then printf -v "$__v" '%s' "$__d"; return 0; fi
  if [ -n "$__d" ]; then read -r -p "$__q [$__d]: " __a || true; else read -r -p "$__q: " __a || true; fi
  printf -v "$__v" '%s' "${__a:-$__d}"
}
ask_yes() { # $1=pytanie $2=domyślna t/n
  local __q="$1" __d="${2:-n}" __a=""
  if [ "$MODE" = "auto" ]; then [ "$__d" = "t" ]; return $?; fi
  read -r -p "$__q [${__d}]: " __a || true
  __a="${__a:-$__d}"
  [[ "$__a" =~ ^[tTyY] ]]
}
ask_secret() { # $1=zmienna $2=pytanie (bez echa; Enter = pomiń)
  local __v="$1" __q="$2" __a=""
  if [ "$MODE" = "auto" ]; then printf -v "$__v" '%s' ""; return 0; fi
  read -rs -p "$__q (Enter = pomiń): " __a || true
  echo
  printf -v "$__v" '%s' "$__a"
}
run_sudo() { # wykonuje komendę z sudo tylko gdy trzeba
  if [ "$(id -u)" = "0" ]; then "$@"; else sudo "$@"; fi
}
clean_key() { # waliduje klucz API: ≥8 znaków, bez spacji; inaczej "" + ostrzeżenie
  local k="$1"
  [ -z "$k" ] && { printf ''; return 0; }
  if [ "${#k}" -lt 8 ] || printf '%s' "$k" | grep -q '[[:space:]]'; then
    warn "Klucz o podejrzanej wartości (za krótki/spacja) — pomijam."
    printf ''; return 0
  fi
  printf '%s' "$k"
}

# ================================ KONTEKST ======================================
# Czy jesteśmy wewnątrz repo ASTRO? (bootstrap gdy nie)
REPO="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo "")"
IN_REPO="0"
[ -n "$REPO" ] && [ -f "$REPO/config/settings.py" ] && IN_REPO="1"

echo
info "ASTRO setup — tryb: $MODE$([ "$IN_REPO" = "1" ] && echo "  (repo: $REPO)" || echo "  (bootstrap — repo zostanie sklonowane)")"
echo

# ================================ UPDATE ========================================
if [ "$MODE" = "update" ]; then
  if [ "$IN_REPO" != "1" ]; then err "Tryb --update wymaga uruchomienia z katalogu repo (np. ~/astro)."; exit 1; fi
  cd "$REPO"
  info "[1/4] git pull…"
  if [ -d .git ]; then git pull --ff-only 2>&1 | tail -2 || warn "git pull nie powiódł się (lokalne zmiany?)"; else warn "brak .git — pomijam"; fi
  info "[2/4] zależności Pythona…"
  [ -x venv/bin/pip ] && venv/bin/pip install -q -r requirements.txt && ok "pip OK" || warn "venv brak — uruchom pełny setup"
  info "[3/4] modele Ollama…"
  if command -v ollama >/dev/null 2>&1; then
    ollama pull qwen2.5:7b 2>&1 | tail -1
    ollama pull nomic-embed-text 2>&1 | tail -1
  else warn "brak ollama — pomijam"; fi
  info "[4/4] restart usługi (jeśli działa)…"
  if systemctl is-active --quiet astro 2>/dev/null; then run_sudo systemctl restart astro && ok "usługa astro zrestartowana"; else info "usługa astro nieaktywna — pomijam"; fi
  ok "SYNCHRO zakończone."
  exit 0
fi

# ============================ BOOTSTRAP: KLON REPO ==============================
if [ "$IN_REPO" != "1" ]; then
  if [ "$MODE" = "check" ]; then
    info "Poza repo ASTRO (tryb --check) — w trybie pełnym setup sklonuje:"
    info "  $PUB_REPO → ~/astro"
    PYV="brak"; command -v python3 >/dev/null 2>&1 && PYV="$(python3 -V 2>&1)"
    printf "  %-18s %s\n" "Python 3.11+:" "$PYV"
    printf "  %-18s %s\n" "git:" "$(command -v git >/dev/null 2>&1 && echo tak || echo nie)"
    printf "  %-18s %s\n" "ffmpeg:" "$(command -v ffmpeg >/dev/null 2>&1 && echo tak || echo nie)"
    printf "  %-18s %s\n" "audio (arecord -l):" "$(arecord -l 2>/dev/null | grep -q '^card' && echo tak || echo nie)"
    exit 0
  fi
  info "Bootstrap: nie jestem w repo ASTRO — sklonuję je."
  TARGET="${HOME}/astro"
  ask TARGET "Katalog instalacji" "$TARGET"
  if [ -d "$TARGET/config" ] && [ -f "$TARGET/config/settings.py" ]; then
    ok "Repo już istnieje: $TARGET"
  else
    if ! command -v git >/dev/null 2>&1; then
      err "Brak gita. Zainstaluj: sudo apt install -y git   (albo uruchom z gotowego klonu)"
      exit 1
    fi
    info "git clone $PUB_REPO → $TARGET"
    git clone --depth 1 "$PUB_REPO" "$TARGET" || { err "Klonowanie nie udało się."; exit 1; }
    ok "Repo sklonowane."
  fi
  REPO="$TARGET"
  cd "$REPO" || exit 1
fi
[ -f "$REPO/config/settings.py" ] || { err "To nadal nie wygląda na repo ASTRO."; exit 1; }

# ============================== 1) APT (za zgodą) ===============================
APT_PKGS="python3 python3-venv python3-pip git ffmpeg alsa-utils unzip curl wget"
if [ "$MODE" = "check" ]; then
  info "--check: pomijam instalacje (apt/ollama/pip)."
elif ask_yes "Zainstalować zależności systemowe (apt: $APT_PKGS)?" "t"; then
  info "apt-get install…"
  run_sudo apt-get update -qq 2>&1 | tail -1
  run_sudo apt-get install -y -qq $APT_PKGS 2>&1 | tail -2
  ok "zależności systemowe zainstalowane"
else
  warn "Pomijam apt — upewnij się, że masz: $APT_PKGS"
fi

# ============================== 2) DIAGNOZA =====================================
ARCH="$(uname -m)"
IS_PI="nie"
if [ "$ARCH" = "aarch64" ] && grep -qi raspberry /proc/device-tree/model 2>/dev/null; then IS_PI="tak"; fi
HAILO="nie"; compgen -G "/dev/hailo*" >/dev/null 2>&1 && HAILO="tak"
AUDIO="nie"; if command -v arecord >/dev/null 2>&1 && arecord -l 2>/dev/null | grep -q '^card'; then AUDIO="tak"; fi
FFMPEG="nie"; command -v ffmpeg >/dev/null 2>&1 && FFMPEG="tak"
PY_OK="nie"; command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; sys.exit(0 if sys.version_info>=(3,11) else 1)' 2>/dev/null && PY_OK="tak"
VENV="nie"; [ -x "$REPO/venv/bin/python" ] && VENV="tak"
OLLAMA="nie"; curl -sf -m 2 http://127.0.0.1:11434/api/version >/dev/null 2>&1 && OLLAMA="tak"
VOSK="nie"; compgen -G "$REPO/models/vosk/*" >/dev/null 2>&1 && VOSK="tak"
PIPER="nie"; compgen -G "$REPO/models/piper/*.onnx" >/dev/null 2>&1 && PIPER="tak"

echo
printf "  %-18s %s\n" "System:" "$(uname -sm)  (Raspberry Pi: $IS_PI)"
printf "  %-18s %s\n" "Hailo NPU:" "$HAILO"
printf "  %-18s %s\n" "Audio (ALSA):" "$AUDIO"
printf "  %-18s %s\n" "ffmpeg:" "$FFMPEG"
printf "  %-18s %s\n" "Python 3.11+:" "$PY_OK"
printf "  %-18s %s\n" "venv:" "$VENV"
printf "  %-18s %s\n" "Ollama (lokalna):" "$OLLAMA"
printf "  %-18s %s\n" "Model Vosk (STT):" "$VOSK"
printf "  %-18s %s\n" "Model Piper (TTS):" "$PIPER"
echo
if [ "$PY_OK" != "tak" ]; then err "Wymagany Python 3.11+ (sudo apt install python3 python3-venv python3-pip)."; fi
[ "$AUDIO" = "nie" ] && warn "Brak karty dźwiękowej — zadziała tryb tekstowy (astro_repl.py)."
[ "$HAILO" = "nie" ] && info "Bez Hailo — CPU + Vosk. To wspierany tryb."

if [ "$MODE" = "check" ]; then
  echo
  info "Tryb --check: diagnoza zakończona. Nic nie zapisano/nie zainstalowano."
  exit 0
fi

# ============================== 3) USTAWIENIA ===================================
info "Konfiguracja (Enter = domyślna)"
echo
ask OLLAMA_URL "Adres lokalnej Ollamy" "http://127.0.0.1:11434"
ask OLLAMA_MODEL "Model czatu Ollamy" "qwen2.5:7b"
ask EMBED_MODEL "Model embeddingów (pamięć)" "nomic-embed-text"

NPU="0"; if [ "$HAILO" = "tak" ]; then ask_yes "Wykryto Hailo NPU — włączyć?" "t" && NPU="1"; fi
STT_ENGINE="vosk"
if [ "$NPU" = "1" ]; then ask_yes "STT na NPU (Whisper HEF) zamiast Vosk?" "t" && STT_ENGINE="npu"; fi

TTS_MODEL=""
compgen -G "$REPO/models/piper/*.onnx" >/dev/null 2>&1 && TTS_MODEL="$(ls "$REPO"/models/piper/*.onnx 2>/dev/null | head -1)"
[ -z "$TTS_MODEL" ] && ask TTS_MODEL "Ścieżka modelu Piper .onnx (puste = TTS wyłączony)" ""

PC_URL=""; PC_MODEL=""
if ask_yes "Masz drugi komputer z Ollamą (nauczyciel przez sieć/tunel)?" "n"; then
  ask PC_URL "Adres Ollamy komputera (URL)" ""
  [ -n "$PC_URL" ] && ask PC_MODEL "Model na komputerze" "SpeakLeash/bielik-11b-v3.0-instruct:Q4_K_M"
fi

CAMERA_ENABLED="0"; CAMERA_HOST=""; CAMERA_RTSP=""; CAMERA_USER=""; CAMERA_PASS=""; CAMERA_FLIP="180"
if ask_yes "Skonfigurować kamerę sieciową ONVIF/RTSP?" "n"; then
  CAMERA_ENABLED="1"
  ask CAMERA_HOST "Adres kamery (IP)" "192.168.1.100"
  ask CAMERA_RTSP "URL RTSP" "rtsp://${CAMERA_HOST}:554/live/ch0"
  ask CAMERA_USER "Użytkownik kamery (puste = bez logowania)" ""
  [ -n "$CAMERA_USER" ] && ask_secret CAMERA_PASS "Hasło kamery"
  ask CAMERA_FLIP "Obrót obrazu (180/none/hflip/vflip)" "180"
fi

echo
info "Klucze API (opcjonalne) — bez echa, zapis 600 w $SECRETS_DIR/API.txt. Pomiń Enterem."
K_OPENCODE=""; K_GEMINI=""; K_GROQ=""; K_OPENROUTER=""; K_HF=""; K_DEEPSEEK=""; K_GROK=""
ask_secret K_OPENCODE   "OpenCode Go (tryb premium — darmowe modele)"
ask_secret K_GEMINI     "Google Gemini"
ask_secret K_GROQ       "Groq"
ask_secret K_OPENROUTER "OpenRouter"
ask_secret K_HF         "HuggingFace"
ask_secret K_DEEPSEEK   "DeepSeek"
ask_secret K_GROK       "Grok (xAI)"

# Walidacja kluczy (2026-10-03): odrzucamy śmieci (za krótkie/spacje) — m.in. gdy ktoś
# odpowie „n"/ENTER nie w tym miejscu.
for __k in K_OPENCODE K_GEMINI K_GROQ K_OPENROUTER K_HF K_DEEPSEEK K_GROK; do
  eval "$__k=\"\$(clean_key \"\${$__k}\")\""
done

# Walidacja TTS: ścieżka musi wskazywać plik .onnx (albo być pusta).
if [ -n "$TTS_MODEL" ] && [ "${TTS_MODEL##*.}" != "onnx" ]; then
  warn "TTS: „$TTS_MODEL” nie wygląda na model .onnx — pomijam (uzupełnisz w config/astro.env)."
  TTS_MODEL=""
fi

# ============================== 4) ZAPIS ========================================
echo
info "Zapisuję konfigurację…"
HAVE_KEYS="0"
if [ -n "$K_OPENCODE$K_GEMINI$K_GROQ$K_OPENROUTER$K_HF$K_DEEPSEEK$K_GROK" ]; then
  mkdir -p "$SECRETS_DIR"; chmod 700 "$SECRETS_DIR"
  API_TMP="$(mktemp)"
  {
    echo "# ASTRO — klucze API (setup.sh $(date +%F)) — format: sekcja + 'Key: ...'"
    [ -n "$K_OPENCODE" ]   && { echo; echo "OpenCode";   printf '    Key: %s\n' "$K_OPENCODE"; }
    [ -n "$K_GEMINI" ]     && { echo; echo "Gemini";     printf '    Key: %s\n' "$K_GEMINI"; }
    [ -n "$K_GROQ" ]       && { echo; echo "Groq";       printf '    Key: %s\n' "$K_GROQ"; }
    [ -n "$K_OPENROUTER" ] && { echo; echo "OpenRouter"; printf '    Key: %s\n' "$K_OPENROUTER"; }
    [ -n "$K_HF" ]         && { echo; echo "HuggingFace";printf '    Key: %s\n' "$K_HF"; }
    [ -n "$K_DEEPSEEK" ]   && { echo; echo "DeepSeek";   printf '    Key: %s\n' "$K_DEEPSEEK"; }
    [ -n "$K_GROK" ]       && { echo; echo "Grok";       printf '    Key: %s\n' "$K_GROK"; }
  } > "$API_TMP"
  [ -f "$SECRETS_DIR/API.txt" ] && cp "$SECRETS_DIR/API.txt" "$SECRETS_DIR/API.txt.bak-$STAMP"
  mv "$API_TMP" "$SECRETS_DIR/API.txt"; chmod 600 "$SECRETS_DIR/API.txt"
  HAVE_KEYS="1"; ok "klucze API: $SECRETS_DIR/API.txt (600)"
else
  warn "Bez kluczy API — praca lokalna (offline); warstwy zdalne pomijane."
fi

ENV_FILE="$REPO/config/astro.env"
{
  echo "# ASTRO — wygenerowane przez setup.sh $(date +%F\ %T)"
  echo "ASTRO_LLM_URL=$OLLAMA_URL"
  echo "ASTRO_LLM=$OLLAMA_MODEL"
  echo "ASTRO_EMBED=$EMBED_MODEL"
  echo "ASTRO_NPU=$NPU"
  echo "ASTRO_STT=$STT_ENGINE"
  [ -n "$TTS_MODEL" ] && echo "ASTRO_TTS_MODEL=$TTS_MODEL"
  [ "$HAVE_KEYS" = "1" ] && echo "ASTRO_API_FILE=$SECRETS_DIR/API.txt"
  [ -n "$PC_URL" ] && { echo "ASTRO_PC_URL=$PC_URL"; [ -n "$PC_MODEL" ] && echo "ASTRO_PC_MODEL=$PC_MODEL"; }
  if [ "$CAMERA_ENABLED" = "1" ]; then
    echo "ASTRO_CAMERA_HOST=$CAMERA_HOST"
    echo "ASTRO_CAMERA_RTSP=$CAMERA_RTSP"
    echo "ASTRO_CAMERA_FLIP=$CAMERA_FLIP"
    [ -n "$CAMERA_USER" ] && echo "ASTRO_CAMERA_USER=$CAMERA_USER"
    [ -n "$CAMERA_PASS" ] && echo "ASTRO_CAMERA_PASS=$CAMERA_PASS"
  fi
  echo "ASTRO_REMOTE=1"
  echo "ASTRO_REMOTE_TIMEOUT=120"
} > "$ENV_FILE.new"
[ -f "$ENV_FILE" ] && { cp "$ENV_FILE" "$ENV_FILE.bak-$STAMP"; warn "astro.env → kopia .bak-$STAMP"; }
mv "$ENV_FILE.new" "$ENV_FILE"; chmod 600 "$ENV_FILE"
ok "config/astro.env"

UNIT_FILE="$REPO/astro.service"
{
  echo "[Unit]"
  echo "Description=ASTRO - samodzielny agent (wake \"Hej Astro\", glos robocika)"
  echo "After=sound.target network-online.target"
  echo "Wants=network-online.target"
  echo
  echo "[Service]"
  echo "Type=simple"
  echo "User=$USER"
  echo "Group=$(id -gn)"
  echo "WorkingDirectory=$REPO"
  echo "Environment=PYTHONUNBUFFERED=1"
  echo "EnvironmentFile=$ENV_FILE"
  echo "ExecStart=$REPO/venv/bin/python $REPO/scripts/astro_voice.py"
  echo "Restart=on-failure"
  echo "RestartSec=5"
  echo "StandardOutput=append:$REPO/runtime/logs/astro.log"
  echo "StandardError=append:$REPO/runtime/logs/astro.log"
  echo
  echo "[Install]"
  echo "WantedBy=multi-user.target"
} > "$UNIT_FILE"
mkdir -p "$REPO/runtime/logs"
ok "astro.service"

# ============================== 5) MODELE =======================================
# 5a) Ollama (instalacja + modele)
if ! command -v ollama >/dev/null 2>&1; then
  if ask_yes "Zainstalować Ollamę (lokalny serwer modeli)?" "t"; then
    curl -fsSL https://ollama.com/install.sh | sh 2>&1 | tail -2
    ok "Ollama zainstalowana"
  fi
fi
if command -v ollama >/dev/null 2>&1; then
  if ask_yes "Pobrać modele Ollama: $OLLAMA_MODEL, $EMBED_MODEL (kilka GB)?" "t"; then
    info "ollama pull $OLLAMA_MODEL…"; ollama pull "$OLLAMA_MODEL" 2>&1 | tail -1
    info "ollama pull $EMBED_MODEL…";   ollama pull "$EMBED_MODEL" 2>&1 | tail -1
    ok "modele Ollama gotowe"
  fi
fi

# 5b) Vosk (STT) + Piper (TTS) — pobranie, gdy brak
mkdir -p "$REPO/models/vosk" "$REPO/models/piper"
if ! compgen -G "$REPO/models/vosk/*" >/dev/null 2>&1; then
  if ask_yes "Pobrać model STT Vosk (polski, ~50 MB)?" "t"; then
    info "Vosk: pobieram…"
    curl -fsSL https://alphacephei.com/vosk/models/vosk-model-small-pl-0.22.zip -o /tmp/vosk.zip \
      && unzip -q -o /tmp/vosk.zip -d "$REPO/models/vosk/" && rm -f /tmp/vosk.zip \
      && ok "Vosk gotowy" || warn "Vosk: pobieranie nie powiodło się (pobierz ręcznie — INSTALL.md §6)"
  fi
fi
if ! compgen -G "$REPO/models/piper/*.onnx" >/dev/null 2>&1; then
  if ask_yes "Pobrać model TTS Piper (polski żeński, ~60 MB)?" "t"; then
    info "Piper: pobieram…"
    BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/pl/pl_PL/gosia/medium"
    curl -fsSL "$BASE/pl_PL-gosia-medium.onnx" -o "$REPO/models/piper/pl_PL-gosia-medium.onnx" \
      && curl -fsSL "$BASE/pl_PL-gosia-medium.onnx.json" -o "$REPO/models/piper/pl_PL-gosia-medium.onnx.json" \
      && ok "Piper gotowy" || warn "Piper: nie powiodło się (INSTALL.md §6)"
    [ -z "$TTS_MODEL" ] && TTS_MODEL="$REPO/models/piper/pl_PL-gosia-medium.onnx"
    grep -q '^ASTRO_TTS_MODEL=' "$ENV_FILE" 2>/dev/null || echo "ASTRO_TTS_MODEL=$TTS_MODEL" >> "$ENV_FILE"
  fi
fi

# ============================== 6) VENV =========================================
if [ "$VENV" = "nie" ] && [ "${SETUP_SKIP_VENV:-0}" = "1" ]; then
  warn "SETUP_SKIP_VENV=1 — venv pominięty (ręcznie: python3 -m venv venv && venv/bin/pip install -r requirements.txt)"
elif [ "$VENV" = "nie" ]; then
  if ask_yes "Utworzyć venv i zainstalować zależności Pythona?" "t"; then
    python3 -m venv "$REPO/venv" && ok "venv utworzony"
    "$REPO/venv/bin/pip" install -q -U pip 2>&1 | tail -1
    info "pip install -r requirements.txt (kilka minut)…"
    "$REPO/venv/bin/pip" install -q -r "$REPO/requirements.txt" && ok "zależności Pythona OK" \
      || err "pip błąd — uruchom ręcznie: $REPO/venv/bin/pip install -r requirements.txt"
  fi
else
  ok "venv już jest"
fi

# ============================== 7) USŁUGA =======================================
if [ "$VENV" = "tak" ] || [ -x "$REPO/venv/bin/python" ]; then
  if ask_yes "Zainstalować i uruchomić usługę systemd (autostart ASTRO)?" "n"; then
    run_sudo cp "$UNIT_FILE" /etc/systemd/system/astro.service \
      && run_sudo systemctl daemon-reload \
      && run_sudo systemctl enable --now astro \
      && ok "usługa astro włączona (logi: journalctl -fu astro)" \
      || warn "nie udało się włączyć usługi — sprawdź ręcznie (INSTALL.md §3 krok 8)"
  fi
fi

# ============================== 8) SELF-TEST ====================================
echo
info "Self-test:"
curl -sf -m 2 "$OLLAMA_URL/api/version" >/dev/null 2>&1 && ok "Ollama odpowiada ($OLLAMA_URL)" \
  || warn "Ollama nie odpowiada — uruchom: ollama serve (albo sprawdź URL w config/astro.env)"
if [ -x "$REPO/venv/bin/python" ]; then
  if (cd "$(dirname "$REPO")" && "$REPO/venv/bin/python" -c "import astro.core.agent" 2>/dev/null); then
    ok "import astro działa"
  else
    warn "import astro nie zadziałał — sprawdź: venv/bin/pip install -r requirements.txt"
  fi
fi
compgen -G "$REPO/models/vosk/*" >/dev/null 2>&1 && ok "STT Vosk obecny" || warn "STT Vosk: brak (tryb tekstowy działa)"
compgen -G "$REPO/models/piper/*.onnx" >/dev/null 2>&1 && ok "TTS Piper obecny" || warn "TTS Piper: brak"

# ============================== 9) NASTĘPNE KROKI ===============================
cat <<EOF

${C_B}== GOTOWE — następne kroki ==${C_0}

1) Test tekstowy:
     cd $(dirname "$REPO") && source "$ENV_FILE" && $REPO/venv/bin/python -m astro.scripts.astro_repl "czat Cześć, kim jesteś?"

2) Tryb głosowy (mikrofon/głośnik):
     cd $REPO && source config/astro.env && venv/bin/python scripts/astro_voice.py

3) Aktualizacja (synchro repo + modele + restart):
     bash $REPO/setup.sh --update

4) Pełna instrukcja: $REPO/docs/INSTALL.md
EOF
