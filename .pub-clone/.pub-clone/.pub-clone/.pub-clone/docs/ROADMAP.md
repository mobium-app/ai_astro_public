# ASTRO — ROADMAP realizacji (kolejność zatwierdzona 2026-09-22)

> **Kolejność:** **B** (mowa, bez M5) → **C** (jakość/efektywność) → **D** (pomysły/UX) →
> **A** (tool-calling/trening — **tylko po potwierdzeniu użytkownika**).
> Promocja modelu jest poza tym roadmapem. Statusy aktualizować po każdym etapie + wpis do
> `LOG_ASTRO.md`. Szczegóły: `PLAN_DOSKONALENIA.md` (B), `ANALIZA_JAKOSCI.md` (C), ten plik (D/A).

## B. Mowa (bez M5)
- [~] **B1 = M3.1** większy STT: **rekonesans zrobiony** — lokalnie tylko `Whisper-Base.hef`; brak
      HEF small/medium dla Hailo-10H, kompilacja wymaga DFC/x86 + ryzyko (upgrade HailoRT). **Plan B**:
      CPU (whisper.cpp / szybki model PL) — odłożone, wymaga instalacji. API Hailo `Speech2Text` nie
      przyjmuje `initial_prompt` (bias Whispera niemożliwy przez ten interfejs).
- [x] **B2 = M3.2** bias: dynamiczna gramatyka Voska = wbudowane frazy + **must-have z pliku**
      (`_must_have_phrases`) + `ASTRO_COMMAND_EXTRA` (`audio/wake.py::build_command_grammar`).
- [x] **B3 = M3.3** próg pewności: `WakeDetector.transcribe_conf` (Vosk `conf`) → niepewna
      transkrypcja w `VoiceLoop.transcribe_ex` (`ASTRO_STT_CONF_MIN`, domyślnie 0.6).
- [x] **B4 = M2.3** pauzy: przecinek przed spójnikiem (ale/jednak/natomiast/zatem) i po okrzyku
      (Uwaga/Słuchaj) — `audio/text.py::_ensure_pauses`.
- [x] **B5 = M2.4** rozbicie monolitu: leksykon w `audio/lexicon.py`, kosmetyka w
      `audio/text_clean.py`, a `audio/text.py` → pakiet `audio/text/` (**numbers/units/dates/lex**;
      fasada `__init__` z `speakable`/`prepare_speech`). Zachowanie **1:1** (złoty snapshot +
      testy 740/740).
- [ ] **B6** odsłuch na żywo (wymaga mikrofonu/głośnika — użytkownik): czysty profil głosu + powitanie.

## C. Jakość/efektywność
- [x] **C1 = P0.3** walidacja metaznaków (`; && || $() \``) w `validate_plan` — plan nie łączy
      poleceń (`safety/plans.py::PLAN_CHAIN_RE`).
- [x] **C2 = P1.3** LRU `_traj_cache` (`ASTRO_TRAJ_CACHE_MAX`, domyślnie 512); pełny indeks/ANN
      (P1.2) nadal odłożony (O(N) skany).
- [~] **C3 = P1.5** NPU reuse KV: **odłożone** — brak możliwości testu na sprzęcie; `clear_context()`
      co turę zostaje (bezpieczne).
- [x] **C4 = P1.6** streaming: backend (`_run_stream`, delty `tool_calls` składane z chunków) +
      REPL + **tor głosowy** (`audio/stream_speech.py`, opt-in `ASTRO_STREAM=1`) — pierwszy
      fragment TTS w trakcie generacji; kroki z narzędziami pomijane, krótkie odpowiedzi nie
      startują, przy niezgodności (remote) TTS przerywany i czytana pełna odpowiedź.
- [x] **C5 = P1.7** throttling `mirror`: dedup identycznych zapisów (`ASTRO_MIRROR_DEDUP_S`) + limit VT
      (`ASTRO_MIRROR_VT_MAX`).
- [x] **C6 = P2.1/P2.2** infrastruktura `logging` (`astro/log.py`, plik `runtime/logs/astro.log`),
      wpięta w `core/agent.py`; stopniowa konwersja `print`/`except pass` w toku.
- [~] **C7 = P2.4–P2.6** dedup definicji: **odłożone** (refaktor ryzykowny; wymaga pomiaru bramką).
- [x] **C8 = P2.8** testy: `verifier`, `usage`, `remote_chain` (`tests/test_core_extra.py`).

## D. Pomysły / UX
- [x] **D1** Voice-ID: `user/voiceid.py` — profile mówcy (enroll/identify, kosinus do centroidu,
      trwałość `runtime/voiceid.json`), opcjonalny embedder Vosk spk (`vosk-model-spk-0.4`).
- [x] **D2** zapowiedź startowa: `scripts/astro_announce.py` (+ `ASTRO_ANNOUNCE_BOOT`, domyślnie 0),
      respektuje tryb cichy; `--force` do testów.
- [~] **D3** wpięcie `presence` w pętlę: **odłożone** do dołożenia kamery (pół-duplex WM8960).
- [x] **D4** Home Assistant/MQTT: **już zaimplementowane** (`tools/home.py`, whitelist encji, `gated`,
      REST + opcjonalny MQTT). Wymaga tylko `~/.astro-ha.json` po stronie użytkownika.

## A. Tool-calling / trening — **potwierdzone przez użytkownika 2026-09-22**
- [x] **A1** few-shot: fs=0 → 8/8, fs=1/2 → ~4/8 i wolno → **`FEWSHOT=0` domyślnie**; bramka bez
      `--few-shot`. (Format wzorców poprawiony, bez efektu.)
- [x] **A2** dane: darmowe **remote_ai nie nadają się do tool-calling**; dobite na PC-Kali
      (`cloud_teacher --parallel`, bielik) → trajektorie z krokami **372 → 436**, dataset
      **train 627 → 744**, val **64 → 77**. Wiedza/polszczyzna z remote: +~1k `learned`.
- [x] **A3** trening z walidacją (`--eval` + early-stop) — **PASS i promocja `astro-qwen3-lora-v7`**
      (2026-09-23). Ścieżka: `--eval`+early-stop (1.7B) → v1 FAIL (chain 1/2) → retrening z ważeniem
      łańcuchów (`make_shards --chain-weight 3`) → **tools 8/8, chain 2/2, chat 2/2 → PASS**.
      Rollback: `astro-qwen3-lora-kali-full3`. Qwen3-4B niepotrzebne.
- [x] **A4** promocja `astro-qwen3-lora-kali-full3` (PASS kanonicznej bramki; rollback = v5).

## Wymaga decyzji/sprzętu
- Kamera (M5), odsłuch TTS/STT, PC-MAX przez WSL2 (admin), dostępność HEF większego STT,
  czyszczenie logów pod „czysty" GitHub (etap E4 — tylko za zgodą).
