#!/bin/bash
# Pobiera modele wizji AI ASTRO do `models/vision/`. Uruchom po klonie repo
# (katalog `models/` jest poza gitem — duże pliki ONNX).
#
#   bash astro/scripts/fetch_vision_models.sh
#
# Modele: YuNet (twarze), SFace (rozpoznawanie), NanoDet (obiekty COCO), MobileFaceNet (emocje),
# GoogleNet wiek/płeć (Levi & Hassner, Adience — ONNX z onnxmodelzoo), YouTuReID (sylwetka).
set -euo pipefail
A="$(cd "$(dirname "$0")/.." && pwd)"
D="$A/models/vision"
BASE="${ASTRO_VISION_MODEL_BASE:-https://github.com/opencv/opencv_zoo/raw/main/models}"
HF="https://huggingface.co/onnxmodelzoo"
mkdir -p "$D"

FILES=(
  "face_detection_yunet/face_detection_yunet_2023mar.onnx"
  "face_recognition_sface/face_recognition_sface_2021dec.onnx"
  "object_detection_nanodet/object_detection_nanodet_2022nov.onnx"
  "facial_expression_recognition/facial_expression_recognition_mobilefacenet_2022july.onnx"
  "person_reid_youtureid/person_reid_youtu_2021nov.onnx"
)

for f in "${FILES[@]}"; do
  out="$D/$(basename "$f")"
  if [ -s "$out" ]; then
    echo "[vision] już jest: $(basename "$out") ($(stat -c%s "$out") B)"
    continue
  fi
  echo "[vision] pobieram $(basename "$f") …"
  curl -fL --retry 3 -o "$out" "$BASE/$f"
  echo "[vision] ok: $(basename "$out") ($(stat -c%s "$out") B)"
done

# Wiek/płeć (Faza 3): GoogleNet ONNX, ~23 MB każdy — walidacja rozmiaru jak przy VLM.
AG_FILES=(
  "age_googlenet/age_googlenet.onnx"
  "gender_googlenet/gender_googlenet.onnx"
)
for f in "${AG_FILES[@]}"; do
  out="$D/$(basename "$f")"
  if [ -s "$out" ] && [ "$(stat -c%s "$out")" -gt 10000000 ]; then
    echo "[vision] już jest: $(basename "$out") ($(stat -c%s "$out") B)"
    continue
  fi
  echo "[vision] pobieram $(basename "$f") …"
  curl -fL --retry 3 -o "$out.tmp" "$HF/$f?download=true"
  size="$(stat -c%s "$out.tmp")"
  if [ "$size" -lt 10000000 ]; then
    echo "[vision] BŁĄD: $(basename "$out") za mały ($size B) — usuwam." >&2
    rm -f "$out.tmp"
    exit 1
  fi
  mv "$out.tmp" "$out"
  echo "[vision] ok: $(basename "$out") ($size B)"
done
echo "[vision] modele w: $D"
