#!/usr/bin/env bash
# Pobiera VLM (HEF) dla Hailo-10H do `models/hailo/` (Faza 4 „oczy" offline).
# Weryfikuje rozmiar po Content-Length — chroni przed częściowym plikiem (zdarzyło się 2026-09-28).
#
#   bash astro/scripts/fetch_hailo_vlm.sh [wersja, np. v5.3.0] [model]
#
# Modele: Qwen3-VL-2B-Instruct (domyślny, preferowany — lepszy język PL),
#         Qwen2-VL-2B-Instruct (legacy).
# Źródło: gen-ai model zoo (dev-public.hailo.ai), wersja = firmware HailoRT z urządzenia.
set -euo pipefail
A="$(cd "$(dirname "$0")/.." && pwd)"
D="$A/models/hailo"
NAME="${2:-Qwen3-VL-2B-Instruct.hef}"
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
mkdir -p "$D"

ver="${1:-}"
if [ -z "$ver" ]; then
  fw="$(hailortcli fw-control identify 2>/dev/null | awk -F': ' '/Firmware Version:/{print $2}' | awk '{print $1}')"
  ver="v${fw:-5.3.0}"
fi
url="https://dev-public.hailo.ai/${ver}/blob/${NAME}"
out="$D/$NAME"

want="$(curl -fsIL -A "$UA" "$url" 2>/dev/null | awk -F': ' 'tolower($1)=="content-length"{print $2}' | tr -d '\r' | tail -1)"
[ -n "$want" ] || { echo "[vlm] nie mogę ustalić rozmiaru: $url"; exit 1; }
have="$(stat -c%s "$out" 2>/dev/null || echo 0)"
if [ "$have" = "$want" ]; then
  echo "[vlm] już jest: $NAME ($have B, $ver)"
  exit 0
fi
echo "[vlm] pobieram $NAME ($ver), brakuje $((want - have)) B z $want B"
curl -fL --retry 3 -A "$UA" -C - -o "$out" "$url"
got="$(stat -c%s "$out")"
if [ "$got" != "$want" ]; then
  echo "[vlm] BŁĄD: rozmiar $got != $want (plik niekompletny) — powtórz skrypt"
  exit 1
fi
echo "[vlm] ok: $out ($got B)"
