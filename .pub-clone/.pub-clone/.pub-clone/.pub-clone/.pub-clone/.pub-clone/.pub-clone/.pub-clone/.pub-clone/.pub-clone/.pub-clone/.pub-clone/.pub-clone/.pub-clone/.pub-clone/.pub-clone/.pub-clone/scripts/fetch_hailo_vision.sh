#!/usr/bin/env bash
# Pobiera model detekcji obiektów (YOLO) dla Hailo-10H do `models/hailo/` (Faza „oczy na NPU").
# Weryfikuje rozmiar po Content-Length — chroni przed częściowym plikiem.
#
#   bash astro/scripts/fetch_hailo_vision.sh [model, np. yolov8s|yolov8n|yolov8m]
#
# Źródło: Hailo Model Zoo (Compiled), wersja = firmware HailoRT z urządzenia (u nas 5.3.0),
# architektura = hailo10h. Domyślny model: yolov8s (kompromis jakość/tempo/VRAM NPU).
set -euo pipefail
A="$(cd "$(dirname "$0")/.." && pwd)"
D="$A/models/hailo"
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
BASE="https://hailo-model-zoo.s3.eu-west-2.amazonaws.com/ModelZoo/Compiled"
ARCH="hailo10h"
mkdir -p "$D"

model="${1:-yolov8s}"
name="${model%.hef}.hef"

fw="$(hailortcli fw-control identify 2>/dev/null | awk -F': ' '/Firmware Version:/{print $2}' | awk '{print $1}')"
ver="v${fw:-5.3.0}"
url="$BASE/$ver/$ARCH/$name"
out="$D/$name"

want="$(curl -fsIL -A "$UA" "$url" 2>/dev/null | awk -F': ' 'tolower($1)=="content-length"{print $2}' | tr -d '\r' | tail -1)"
[ -n "$want" ] || { echo "[vision] nie mogę ustalić rozmiaru: $url"; exit 1; }
have="$(stat -c%s "$out" 2>/dev/null || echo 0)"
if [ "$have" = "$want" ]; then
  echo "[vision] już jest: $name ($have B, $ver/$ARCH)"
  exit 0
fi
echo "[vision] pobieram $name ($ver/$ARCH), $want B"
curl -fL --retry 3 -A "$UA" -C - -o "$out" "$url"
got="$(stat -c%s "$out")"
if [ "$got" != "$want" ]; then
  echo "[vision] BŁĄD: rozmiar $got != $want (plik niekompletny) — powtórz skrypt"
  exit 1
fi
echo "[vision] ok: $out ($got B)"
