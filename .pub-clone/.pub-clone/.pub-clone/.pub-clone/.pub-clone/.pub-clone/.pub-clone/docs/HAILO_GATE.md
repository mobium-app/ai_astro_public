# Faza 4 — Hailo-10H dla wizji: WYNIK (GO — VLM na NPU, offline)

> Data: 2026-09-28 (aktualizacja po udanym upgrade). Decyzja: **GO** — HailoRT 5.3.0
> działa po zejściu na **kernel 6.12 LTS**; VLM `Qwen2-VL-2B` uruchomiony **na NPU** i wpięty
> w ASTRO. Jakość opisu 2B jest niższa niż `qwen2.5vl:3b` na Kali → **Kali pozostaje
> preferowany**, NPU jest **offline fallbackiem**.

## Historia / dlaczego dwa podejścia
- **2026-09-28 (pierwsza próba)**: upgrade 5.3.0 na kernelu **6.18** = **NO-GO** — sterownik PCIe
  `hailort-pcie-driver` 5.3.0 nie kompiluje się (`vdma/monitor.c`, brak `del_timer_sync`).
  Pełny rollback do 5.1.1. Wniosek: runtime bez zgodnego sterownika pod kernel jest bezużyteczny.
- **2026-09-28 (druga próba, wieczór)**: **zejście na kernel 6.12.75+rpt-rpi-2712** (z 6.18.50;
  backup: `~/astro-backups/kernel-6.12.75/`, `boot-firmware-before-kernel-*.tgz`) → sterownik
  5.3.0 **kompiluje się i działa**.

## Stan po upgrade (zweryfikowany)
- Pakiety: `hailort` 5.3.0, `hailort-pcie-driver` 5.3.0, `hailo-gen-ai-model-zoo` 5.3.0;
  binding `hailo_platform` w venv **5.3.0**.
- `hailortcli fw-control identify` → **Firmware 5.3.0**, arch HAILO10H.
- **Nowy węzeł urządzenia**: `/dev/h1x-0` (w 5.1.1 było `/dev/hailo0`). Kod ASTRO wykrywa oba
  (`backends/npu.py: device_paths()` glob `/dev/hailo*`, `/dev/h1x*`).
- **STT (Whisper-Base)** na NPU działa: `Speech2Text` otwiera się (~1,2–1,7 s), `astro.service`
  active. Jedno VDevice dzielone przez STT/LLM/VLM w procesie usługi.
- **VLM**: `models/hailo/Qwen2-VL-2B-Instruct.hef` (3 255 444 179 B, z `dev-public.hailo.ai/v5.3.0`).
  Load ~8 s, opis ~7–20 s (zależnie od długości). **Uwaga**: pierwszy plik był **ucięty**
  (3 070 230 528 B) i dawał `HAILO_FILE_OPERATION_FAILURE` — pobierać z walidacją rozmiaru
  (`scripts/fetch_hailo_vlm.sh`).

## Integracja w ASTRO
- `backends/npu.py`: `NpuEngine.vlm_ready()/_ensure_vlm()/describe_frame(img_rgb, question)`;
  `resolve_vlm_hef()` (env `ASTRO_VLM_HEF`, domyślnie model w repo); status/HEF-y pokazują VLM.
- `tools/vision.py`: `_vlm_caption` wybiera backend wg `ASTRO_VLM_PREFER` (`ollama` domyślnie,
  `hailo` = NPU-first), z **fallbackiem** w drugą stronę; `_ollama_reachable()` (szybki TCP, bez
  120 s zawieszenia); kadrowanie obrazu 336×336 z zachowaniem proporcji; guard `_looks_polish()`
  odrzuca angielskie odmowy, CJK i zapętlenia małego VLM.
- Konfiguracja (drop-in `astro.service.d/vlm.conf`): `ASTRO_VLM_HEF`, `ASTRO_VLM_HAILO=1`,
  `ASTRO_VLM_MAX_TOKENS=96`; `ASTRO_VLM_PREFER` domyślnie `ollama`. API wizji (`astro-vision-api`)
  **nie** włącza NPU (osobny proces — nie zabiera VDevice usłudze); tam działa Ollama.

## Ograniczenie: brak większego VLM na Hailo-10H (2026-09-29)
- **Weryfikacja**: gen-ai model zoo Hailo (`dev-public.hailo.ai/{v5.1.0,v5.2.0,v5.3.0}/blob/`)
  dla `hailo10h` udostępnia **wyłącznie `Qwen2-VL-2B-Instruct`**. Próby `Qwen2-VL-7B-Instruct`,
  `Qwen2.5-VL-3B/7B` → HTTP 404. Analogicznie LLM na Hailo-10H to tylko ≤1.5B
  (`Qwen2.5-1.5B-Instruct`), mimo że urządzenie ma 15 GB RAM na Pi.
- **Wniosek**: na tym sprzęcie **nie ma** większego VLM do pobrania — „Faza 1b (większy VLM na NPU)"
  jest **niemożliwa do zrealizowania** w obecnym model zoo, nie z powodu konfiguracji.
- **Decyzja**: jakość opisu sceny = **Kali `qwen2.5vl:3b`** (Ollama, tunel 11435, `ASTRO_VLM_PREFER=ollama`),
  a `Qwen2-VL-2B` na NPU pozostaje **offline fallbackiem**. Fazę 1b uznajemy za **zamkniętą**
  (ograniczenie sprzętowo-modelowe, świadome). Poprawa jakości 2B przez dekodowanie
  (top_p/top_k/frequency_penalty) — patrz § „jakość dekodowania" niżej.
- **Przyszłość**: gdy Hailo opublikuje HEF większego VLM (Qwen3-VL itp.) — wrócić do tematu.

## ✅ Qwen3-VL-2B na NPU — ZROBIONE (2026-09-29, v0.121.0)
- **HEF**: `models/hailo/Qwen3-VL-2B-Instruct.hef` (3 185 773 502 B) **dostępny dla v5.3.0**
  (`dev-public.hailo.ai/v5.3.0/blob/` — sprawdzone 2026-09-29; v5.4.0 też ma). Pobieranie:
  `bash scripts/fetch_hailo_vlm.sh [v5.3.0] [Qwen3-VL-2B-Instruct.hef]` (walidacja rozmiaru).
  Qwen2-VL-2B pozostaje jako model alternatywny (ten sam skrypt).
- **Wejście modelu**: `Qwen3-VL-2B` oczekuje klatki **512×288 RGB uint8** (NIE kwadratu 336×336
  jak Qwen2-VL!) — `NpuEngine.vlm_input_shape(ensure=True)` czyta `input_frame_shape()` z modelu;
  `_image_rgb` obsługuje pary (h, w) (wcześniej ucinał do kwadratu — fix). `describe_frame`
  dostaje klatkę dopasowaną do modelu, env `ASTRO_VLM_HAILO_IMAGE_PX` = fallback.
- **Jakość (pomiar na żywej kamerze)**: opisy **po polsku, poprawne** („Na obrazku widoczny jest
  fragment ekranu, który przedstawia informacje o produkcie…"), generacja ~3–7 s (krótkie) /
  ~21 s (pełne 96 tokenów). Zdarza się **pusty wynik** (natychmiast `<|im_end|>`) lub powtórzenia
  pytania → `describe_frame` ma **jedną ponowną próbę z próbkowaniem** (temp 0.4, top_p 0.9,
  top_k 40, do_sample=True, seed 42); guard `_looks_polish`/`_clean_caption` odrzuca resztę.
  Preferencja bez zmian: **Kali `qwen2.5vl:3b` = jakość, NPU Qwen3-VL = offline**.
- **Konfiguracja**: drop-in `astro.service.d/vlm.conf` → `ASTRO_VLM_HEF=…/Qwen3-VL-2B-Instruct.hef`
  (usługa zrestartowana 2026-09-29). `resolve_vlm_hef()` preferuje Qwen3-VL gdy plik istnieje.

## ✅ Kolejka NPU (Faza 4: „kolejka VDevice") — ZROBIONE (2026-09-29, v0.121.0)
- **Problem**: STT/VLM/LLM (NpuEngine) i detekcja YOLO/SCRFD (`vision/hailo.py`) miały OSOBNE
  locki → równoległa inferencja na jednym VDevice (błędy/wydłużenia).
- **Rozwiązanie**: `NpuGate` — priorytetowa kolejka dostępu do NPU w `backends/npu.py`:
  **STT=0 (interaktywny), LLM/chat=1, wizja (VLM/detekcja)=2**, FIFO w obrębie priorytetu.
  Wywołania HailoRT są blokujące — kolejka porządkuje czekających (nie przerywa biegu).
  Implementacja: Condition + „front przechodzi" (atomowe pod condition; sam sort + notify_all
  miał wyścig — 2 wątki mogły przejść naraz).
- **Integracja**: `NpuEngine.gate` (wszystkie operacje + `get_vdevice`), `vision/hailo.py`
  owija inferencję w `engine.gate(PRIO_VISION)` (osobny proces bez NPU → lokalny lock).
  `npu_status()` pokazuje `gate: {acquires, waits}`.
- **Testy**: `TestNpuGate` (FIFO, STT wyprzedza wizję, LLM przed wizją, statystyki) — odporność
  na wyścigi (poll „w kolejce" zamiast sleepów); + `_image_rgb` kształty (336 / 512×288 / 0),
  + `describe_frame` retry pustego wyniku, + `resolve_vlm_hef` preferencja. Testy **989/989**.

## Ocena jakości (pomiar 2026-09-28)
- `qwen2.5vl:3b` (Kali, tunel 11435): opis poprawny po polsku, ~5–12 s. **Preferowany.**
- `Qwen2-VL-2B` (NPU): działa offline, ale język bywa łamany i zdarza się zapętlenie/angielski.
  Dlatego: prefer Ollama, a opis z NPU dopisywany tylko, gdy przejdzie guard.
- **Jakość dekodowania (poprawa 2026-09-29)**: `describe_frame` przekazuje `top_p=0,8`, `top_k=20`,
  `frequency_penalty=1,15`, `temperature=0,1` (`do_sample=0`) + czyszczenie opisu (`_clean_caption`).
  Znika pętla liczbowa na trudnych kadrach; **wymagana kwadratowa klatka 336×336** (inaczej
  `HAILO_INVALID_OPERATION`). Jakość 2B nadal < 3B na Kali → preferencja bez zmian.
- **Kryterium Fazy 4**: „VLM na Hailo daje opis offline; CPU zwolniony; STT nadal działa" —
  **spełnione** (jakość modelu ograniczona, nie infrastruktury).

## Benchmark STT — świeże próbki głosu (2026-09-29)
- **Materiał**: **23 nowe nagrania** użytkownika (`stt_eval.py --record --limit 25 --speak-prompt`:
  ASTRO wypowiada komendę → beep → powtórzenie; 2 komendy pominięte, bo nic nie usłyszano).
  Zakres: system/zasoby/aktualizacje/temperatura/godzina/data.
- **Pełny pipeline NPU na HailoRT 5.3.0**: exact **17/23 (73%)**, „do znanej komendy"
  **22/23 (95%)**, niepewne **3/23 (13%)**.
- **Porównanie z 41 starymi nagraniami (2026-09-23)**: fuzzy identycznie wysokie (95% vs 100%),
  ale **niepewność spadła 24% → 13%** — czyli mniej pytań „Nie jestem pewna…".
- **Pojedynczy błąd**: „wyświetl zasoby zdalne" → `Wyśrede zasoby zdarne` (0,79). Zostają drobne
  pomyłki Whisper-Base na „remote/zdalne" i „podaj godzinę".
- **Wniosek**: na świeżym, aktualnym głosie STT na 5.3.0 działa dobrze; brak regresji potwierdzony
  niezależnie od starego zestawu. Narzędzie: `scripts/stt_eval.py` (`_wait_free` chroni przed wyścigiem).
- **Poprawka 2026-09-29 (po stronie kodu)**: `command_match.restore_diacritics` + `canonicalize`
  (aliasy „remote/remont/zdarne"→„zdalne") i `loop._same_command` (utrata ogonków = pewne trafienie)
  → na tych samych 23 nagraniach: „do znanej komendy" **23/23 (100%)**, niepewne **2/23 (8%)**.
- **Kalibracja progów (2026-09-29)**: dodano wariant prefiksu „za-" (`zainstaluj`≈`instaluj`) oraz
  „potwierdzenie gramatyką, gdy transkrypcja JUŻ słyszała tę komendę" (`_same_command(grammar_from_text)`).
  Pozostałe **2/23 niepewne są ZASADNE**: NPU usłyszał coś obcego (`Instanuj program`,
  `Temperatura 100.1`), a gramatyka WYMUSIŁA komendę z szumu → potwierdzenie chroni przed
  wykonaniem na ślepym trafie. To poprawne działanie bezpieczeństwa, nie regresja.

## Benchmark STT na HailoRT 5.3.0 (2026-09-29)
- **Materiał**: te same **41 realnych nagrań** (`runtime/stt_eval/` + `labels.jsonl`, głos użytkownika):
  `stt_eval.py --eval --npu` (raw NPU) oraz `--pipeline --npu` (pełny tor).
- **Czas (NPU Whisper-Base)**: **avg 0,397 s, med 0,362 s** (min 0,218 s, max 1,537 s, n=41)
  vs dokumentowany baseline 5.1.1 (**avg 0,48 s, med 0,35 s**) → **brak regresji** (avg nieco lepszy).
- **Jakość (pełny pipeline NPU+Vosk+gramatyka+fuzzy+CPU)**: exact **32/41 (78%)**,
  „do znanej komendy" **41/41 (100%)**, niepewne **10/41 (24%)** — **identycznie** jak przed
  upgradem (v0.73.0, 2026-09-24) → **brak regresji**.
- **Raw NPU (samo Whisper, bez Vosk/gramatyki/fuzzy)**: exact 15/41, fuzzy 28/41 — zgodnie
  z naturą Whisper-Base (pipeline decyduje o jakości komend).
- **Wniosek**: upgrade 5.3.0 (kernel 6.12 LTS) **nie pogorszył STT** — zostaje.
- **Narzędzie**: `stt_eval.py` po `stop` usługi **czeka na zwolnienie NPU** (`_wait_free`, grace 2 s)
  — wcześniej przy działającej usłudze bywał wyścig i `HAILO_OUT_OF_PHYSICAL_DEVICES`.
- **Do zrobienia (opcjonalnie)**: `--record 25` na nowych próbkach głosu (potwierdzenie na świeżych
  nagraniach; obecny pomiar używa 41 nagrań z 2026-09-23).

## Rollback (gdy trzeba wrócić na 5.1.1)
```bash
bash astro/scripts/hailo_rollback_5.1.1.sh   # pakiety + binding venv z ~/astro-backups/hailo-5.1.1/
# kernel: przywrócić 6.18 z ~/astro-backups/boot-firmware-before-kernel-*.tgz (gdy potrzebne)
```

## Wnioski
- **Runtime wymaga zgodnego sterownika pod kernel** — bramka = kompilacja `hailort-pcie-driver`.
- 5.3.0 jest stabilne na **6.12 LTS**; zmiana węzła `/dev/hailo0` → `/dev/h1x-0` obsłużona w kodzie.
- VLM 2B na NPU to **offline fallback**, nie zamiennik modelu 3B na Kali (jakość > koszt).
- Kandydat na przyszłość: **Qwen3-VL**/większy VLM na Hailo, gdy pojawi się HEF i więcej RAM/kontekstu.
