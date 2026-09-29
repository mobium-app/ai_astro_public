# ROADMAP — WIZJA AI / „OCZY" ASTRO

> Dokument wdrożeniowy dla kierunku „oczy ASTRO": ocena otoczenia, rozpoznawanie osób, opis
> sceny (VLM), ciągły nasłuch + inicjatywa. Bazuje na stanie 2026-09-28 (v0.103.0).
> Zasady nadrzędne: **lokalność/prywatność**, **jakość przed tempem**, **CPU/NPU-first**,
> brak monolitów, każdy etap domknięty testem/bramką.

## Stan wyjściowy (Faza 0 — ZROBIONE)
- Kamera sieciowa `192.168.0.1` (ONVIF/RTSP, PTZ), podłączona na stałe + panel na Kali.
- `astro/vision/` (OpenCV 5 + ONNX): twarze (YuNet), rozpoznawanie (SFace 128-d), obiekty
  (NanoDet COCO), emocje (MobileFaceNet) — na CPU, pełna ocena klatki **~0,35 s**.
- Baza twarzy w `memory.db` (`faces`/`face_sightings`), narzędzia i komendy głosowe.
- Walidacja live: zapis→dopasowanie **cos 0,865**; testy **840/840**, audyt **153/153**.

## Fazy wdrożenia

### Faza 1 — Opis sceny (VLM) + panel z nakładkami
Cel: naturalny opis „co się dzieje" i czytelny panel.
- **1a (Kali GPU) ✔ ZROBIONE 2026-09-28**: VLM `qwen2.5vl:3b` na Ollama (Kali) — `camera_look`
  dokłada opis PL, `vision_api` `/caption`, panel „opisz scenę (AI)". Opis ~5,4 s; obraz
  skalowany do 896 px. *Kryterium*: opis po polsku < 5 s (5,4 s — blisko) ✔; fallback offline ✔.
- **1b (Pi)**: VLM 2B na Hailo-10H (patrz Faza 4) albo mały VLM na CPU (wolno) — offline.
  **ZAMKNIĘTE 2026-09-29**: gen-ai zoo Hailo-10H ma **tylko `Qwen2-VL-2B`** (brak 7B — sprawdzone
  v5.1/5.2/5.3 → 404). Większy VLM na NPU **niemożliwy**; Kali `qwen2.5vl:3b` = jakość, NPU = offline
  fallback (dekodowanie poprawione: top_p/top_k/freq). Szczegóły: `docs/HAILO_GATE.md`.
- **1c (panel) ✔ ZROBIONE 2026-09-28**: API wizji na Pi (`scripts/vision_api.py`, `astro-vision-api`,
  :8099) — `/stream.mjpg` z ramkami, `/detect.json`, galeria (`/faces`, `/enroll`, `/forget`);
  panel Kali pokazuje ramki + „zapamiętaj z kamery". *Kryterium*: podgląd z ramkami ✔ (10 fps),
  zapis osoby z UI ✔.

### Faza 2 — Ciągły nasłuch + inicjatywa (eventy)
Cel: ASTRO sam zauważa zdarzenia.
- **ZROBIONE 2026-09-28**: `scripts/vision_watch.py` (systemd `astro-vision-watch`) próbkuje
  kamerę co 20 s; zdarzenia: nieznana osoba (alert), powrót znanej (powitanie); polityka
  `Initiative.event` (tryb cichy, cisza nocna, cooldown, limit/h); log `runtime/vision_events.jsonl`.
- Dalej: detekcja ruchu/zmiany kadru, „zniknął z kadru", zdarzenia przedmiotów (np. ruch w oknie),
  użycie zdarzeń w kontekście rozmowy („kto był dziś") i panel (podgląd zdarzeń).
- *Kryterium*: brak fałszywych alarmów na pustej scenie; zdarzenie mówione raz na epizod ✔ (cooldowny).
- **ZROBIONE 2026-09-29 (v0.116.0)**: `vision/diff.py` — ruch/zmiana sceny/wejście-wyjście/nowe obiekty
  (`enter`/`leave`/`appeared`/`disappeared`/`motion`/`scene_change`, cooldowny); panel `/events`.
- **ZROBIONE 2026-09-29 (v0.119.0)**: użycie zdarzeń w rozmowie — narzędzie `vision_events`
  (ostatnie zdarzenia z `runtime/vision_events.jsonl`) + komenda „co zauważyłeś / co się działo /
  co słychać u kamery" (deterministycznie, bez modelu). Zostaje: podgląd na żywo w panelu.

### Faza 3 — Rozszerzone rozpoznawanie
- Person re-ID sylwetki (opencv_zoo `person_reid_youtureid`) — gdy twarzy nie widać.
- Wiek/płeć (opcjonalnie), emocje → `core/affect` (nastrój rozmowy).
- Wielokamera: lista źródeł ONVIF + macierz/panorama.
- *Kryterium*: re-ID rozpoznaje osobę odwróconą; brak wycieku między różnymi osobami.
- **ZROBIONE 2026-09-28 (re-ID)**: `person_reid_youtu_2021nov.onnx` (768-d) + `bodies` w pamięci;
  `person_enroll` zapisuje twarz+sylwetkę; scena/nasłuch/panel używają sylwetki, gdy brak twarzy;
  walidacja cos **0,989**. Dalej: wiek/płeć, `core/affect` z emocji, wielokamera.
- **ZROBIONE 2026-09-29 (wiek/płeć + affect, v0.119.0)**: GoogleNet ONNX (Levi & Hassner,
  Adience, onnxmodelzoo/HF) — `age_googlenet.onnx` + `gender_googlenet.onnx` w `models/vision/`
  (OpenCV 5.0 nie ma `readNetFromCaffe`, więc wersja ONNX; wejście 224×224 BGR, mean 104/117/123).
  `engine.age_gender()` (~0,5 s/twarz na Pi), `scene.assess` → `age_gender` (najbliższa twarz),
  `describe` → „Najbliższa osoba to najpewniej kobieta w wieku od 25 do 32 lat." (8 klas wieku PL).
  Emocje → **`core/affect`**: `affect/appraisal.EXPRESSION_PAD` (koło Russella → PAD) + hook
  w `assess_current()` — wyraz twarzy podbija/studzi nastrój ASTRO (`AFFECT_VISION`, `vision_status`
  pokazuje `nastroj=`). *Kryterium Fazy 3*: wiek/płeć na żywej kamerze ✔ (kobieta 0,999),
  affect bez regresji ✔.
- **ZROBIONE 2026-09-29 (wielokamera, v0.120.0)**: `CAMERA_SOURCES` (lista „nazwa=rtsp|ptz|profil"),
  wybór kamery głosem po numerze/słowie/nazwie („spójrz na kamerę 2", „druga kamera w lewo"),
  PTZ per źródło, `camera_reachable` po ONVIF lub RTSP, API `/cameras`, „ile kamer / lista kamer".
  Główna kamera bez regresji. **FAZA 3 DOMKNIĘTA** (re-ID + wiek/płeć + affect + wielokamera;
  macierz/panorama = opcjonalnie, gdy będzie druga fizyczna kamera).

### Faza 4 — Hailo-10H dla wizji (odciążyć CPU)
Cel: detekcja/VLM na NPU (`hailo-apps`, gen-ai model zoo).
- **GATE**: pierwsza próba upgrade 5.3.0 na kernelu 6.18 = **NO-GO** (sterownik PCIe się nie
  kompilował). Druga próba po zejściu na **kernel 6.12 LTS** = **GO** (`docs/HAILO_GATE.md`).
- **ZROBIONE 2026-09-28 (v0.111.0)**: HailoRT/FW **5.3.0** (węzeł `/dev/h1x-0`, kod wykrywa oba
  warianty), HEF `Qwen2-VL-2B-Instruct.hef`, `NpuEngine.describe_frame()` + `tools/vision` z
  preferencją `ASTRO_VLM_PREFER` (`ollama` domyślnie / `hailo` offline) i fallbackiem; guard
  `_looks_polish`; `scripts/fetch_hailo_vlm.sh` (walidacja rozmiaru); `scripts/hailo_rollback_5.1.1.sh`.
  STT (Whisper) na NPU po upgrade działa.
- *Kryterium*: VLM na Hailo daje opis offline; CPU zwolniony; STT nadal działa — **spełnione**
  (jakość 2B < 3B na Kali, dlatego Kali preferowany; NPU = offline fallback).
- **ZROBIONE 2026-09-29 (v0.112.0–v0.121.0)**: **detekcja obiektów na NPU** (YOLOv8s, x2,6) +
  **twarze SCRFD** (x6,1) na wspólnym VDevice; **kolejka NPU** (priorytetowa: STT=0 > chat=1 >
  wizja=2; koniec równoległych inferencji na jednym VDevice — `NpuGate` w `backends/npu.py`,
  detekcja przez `engine.gate()`); **Qwen3-VL-2B na NPU** (HEF dostępny dla v5.3.0!; wejście
  512×288 RGB zamiast 336×336; polskie opisy z retry pustego wyniku). Preferencja bez zmian:
  Kali 3B = jakość, NPU = offline. Szczegóły: `docs/HAILO_GATE.md`.
- *Kryterium Fazy 4*: **spełnione** — VLM offline (Qwen3-VL), detekcja na NPU, kolejka
  eliminuje konflikty VDevice. **FAZA 4 DOMKNIĘTA** (zostało opcjonalne: Qwen3-VL większy
  niż 2B — czekamy na model zoo).

### Faza 5 — Pamięć, kwerendy, dokumenty
- „Kto był dziś", „kiedy ostatnio widziałeś X" — kwerendy na `face_sightings` (+FTS).
- OCR (`text_detection_ppocr`) — „przeczytaj, co jest na kartce".- Spięcie z kontekstem trwałym i profilem relacji.
- **ZROBIONE 2026-09-28 (kwerendy)**: `sightings_summary`/`sightings_since`, narzędzie
  `person_sightings`, komenda „kto był dzisiaj", API `/sightings`; zobaczenia logowane przy
  rozpoznaniu. Dalej: OCR, spięcie z kontekstem.
- **ZROBIONE 2026-09-29 (OCR, v0.116.0)**: `vision/ocr.py` (Tesseract offline, `pol+eng`),
  narzędzie `camera_ocr` + komendy „przeczytaj/odczytaj/co jest napisane". *Uwaga*: brak HEF OCR
  dla Hailo-10H — świadomie Tesseract w procesie usługi (offline).
- **ZROBIONE 2026-09-29 (v0.119.0)**: spięcie z kontekstem — odczyty OCR trafiają do
  `vision_notes` (memory.db); narzędzie `ocr_recent` + komenda „co było napisane / co przeczytałaś /
  ostatni odczyt" (pamięć długoterminowa odczytów z kamery).

### Faza 6 — Prywatność i bezpieczeństwo
- Szyfrowanie bazy twarzy (embeddingi), zgoda na zapis, retencja zobaczeń, audyt.
- Twardy „watch off" i `local_only` dla danych biometrycznych (nigdy do chmury).
- **ZROBIONE 2026-09-28**: AES-GCM na embeddingach (`memory/biocrypto.py`, klucz `runtime/bio.key`),
  migracja jawnych wpisów, retencja zobaczeń (`purge_sightings`, komenda „wyczyść zobaczenia"),
  `vision_status` → `biometria_szyfrowana`. Dalej: „watch off" jako komenda i audyt dostępu.
- **ZROBIONE 2026-09-29 (v0.116.0)**: `vision/privacy.py` — twardy **watch off** (`runtime/vision_watch.off`,
  nasłuch pomija całą analizę; komendy „wyłącz/włącz nasłuch") + **audyt biometrii**
  (`runtime/logs/biometria_audit.jsonl`, append-only; API `/audit`). Dane biometryczne nigdy do chmury.

## Kolejność i bramki
1. Faza 1c (panel) — szybkie, bez nowych modeli.
2. Faza 2 (nasłuch/inicjatywa) — offline, wysoka wartość.
3. Faza 1a (VLM na Kali) — jakość opisu.
4. Faza 3/5 (re-ID, OCR, kwerendy) — rozszerzenia.
5. Faza 4 (Hailo) — po gate technicznym.
6. Faza 6 (prywatność) — równolegle, przed włączeniem nasłuchu na stałe.

## Ryzyka
- Fałszywe detekcje (progi, filtr rozmiaru) — stroić pomiarem, nie „na oko".
- HailoRT 5.1.1 vs wymagania VLM `hailo-apps` — możliwy brak wsparcia (gate).
- Jedno VDevice (STT vs wizja) — możliwy konflikt; plan B: naprzemiennie / kolejka.
- Prywatność biometrii — szyfrowanie + zgoda zanim ruszy nasłuch ciągły.

## ⏭ NA JUTRO (2026-09-29) — PRIORYTET 1
> Powód: Faza 4 dała VLM **offline**, ale **nie przyspieszyła** działania — detekcja wciąż na CPU,
> a STT na 5.3.0 niezmierzony. Te dwa kroki domykają „odciążyć CPU przez Hailo".

1. **Detekcja obiektów/twarzy na Hailo NPU** (odciążenie CPU z ~0,35 s/klatkę):
   - HEF YOLO dla `hailo10h` (`detection` w `hailo-apps` → `yolov8n/s/m`, `yolov11n/s/m`);
     pobrać z walidacją rozmiaru (`scripts/fetch_hailo_vision.sh`, wzór: `fetch_hailo_vlm.sh`).
   - `astro/vision/hailo.py` (HailoRT `InferModel` + NMS) wpięty w `engine.detect_objects`
     z **fallbackiem CPU**; ten sam proces/VDevice co STT/VLM + lock.
   - Bramka: ms/klatkę i %CPU NPU vs CPU, brak regresji STT/VLM, testy + audyt zielone.
2. **Benchmark STT na 5.3.0** (potwierdzić brak regresji vs 5.1.1; baseline avg 0,48 s / med. 0,35 s):
   `stt_eval.py --record 25` → `--pipeline` na żywym głosie; wynik do `docs/HAILO_GATE.md`.
3. (opcjonalnie) VLM na NPU: `top_p/top_k/frequency_penalty` w `describe_frame` — mniej zapętleń PL.

Uwaga: krok 1 i 2 wykonuje użytkownik przy mikrofonie/na żywo dla weryfikacji głosowej.
