# E0 — AUDYT (fakty, inwentarz, decyzje)

Data: 2026-09-18. Źródło: `../voice-assistant/` (projekt Atena). Cel: ustalić, co przenosimy do
**ASTRO**, a co zostaje; jak czyścimy szum i archiwizujemy stare.

## 1. Stan starego projektu (pomiary)
| Metryka | Wartość | Wniosek |
|---|---|---|
| `voice_assistant.py` | 11 665 linii, 465 funkcji (241 top-level), 8 klas | monolit, brak granic modułów |
| `INTENT_*` / `re.compile` | 78 / 259 | router-first, kruchy |
| Skrypty | 30 `.py` + 19 `.sh` | dużo jednorazowych |
| LOG.md | 3027 linii, **151** sekcji „seria poprawek" | narosłe łatanie, utrata kontroli |
| Dokumentacja | AGENTS 1263 + README 1335 + PLAN 303 + ROADMAP 150 | rozproszona, częściowo historyczna |
| Commity | 178 (głównie auto-LOG) | historia bez wartości projektowej |
| Dispatch | `agent_run` tylko dla `{research, web_search, nearby, knowledge}`; reszta regex | **odwrotność** wizji agent SDK |
| PC backend | `atena.service.d/pc.conf` → Bielik dla chat/tools/plan | narusza założenie „PC tylko trening" + Bielik tools 2/18 |
| Hailo | STT ~0,44 s/~2% CPU; NPU-LLM **bezczynny** | NPU wykorzystany częściowo |
| LoRA | 3 iteracje (7B×2, 3B×1) — **wszystkie FAIL** | ślepy zaułek na 8 GB + 352 epizodach |

## 2. Inwentarz funkcjonalny — co ZACHOWUJEMY („must keep")
### 2.1 Wiedza sprzętowa i integracje (najcenniejsze)
- **Audio WM8960**: kalibracja (numid 50/51 boost, Capture 39, ADC 195, MICB off), `setup_mixer.sh`,
  pół-duplex (`speaking`/`drain`). Źródło: `voice_assistant.py` (`capture_thread`, `Player`),
  `scripts/setup_mixer.sh`, `/etc/asound.conf`, `dtoverlay=wm8960-soundcard`.
- **Hailo-10H**: `NpuEngine` (`genai.Speech2Text` + `genai.LLM` na jednym VDevice), `hailo_check.py`,
  HEF `models/hailo/Whisper-Base.hef`, rollback `ATENA_NPU_HTTP=1`, wyłączony `hailo-ollama`.
- **Ollama tuning**: `--threads` (7B: 3; 3B: 2), `keep_alive=24h`, `MAX_LOADED_MODELS=2`,
  warmup `/etc/ollama-warmup.json`.
- **STT**: Vosk small PL (wake+gramatyka) + Whisper fallback; `initial_prompt`, fuzzy programów.

### 2.2 Bezpieczeństwo (przetestowane — przenieść 1:1)
- `CONFIRM_RE`/`CONFIRM_ONLY_RE`/`CANCEL_*`, `require_confirm`, `run_pending`,
  `is_safe_command` + `SHELL_META_RE`, `BLOCKED_COMMANDS`, `SECRET_PATHS`/`is_sensitive_path`,
  `is_private_url`, `validate_plan`, `assess_user_request`, PROTECTED_SYMBOLS (F7).

### 2.3 Rdzeń agenta (koncept do przepisania, nie kopiowania)
- `agent_run`/`_agent_loop`: observe→act→verify, tool_calls, ask_user, subagenty, kompakcja.
- `AGENT_SYSTEM_PROMPT` (reguły 1–12), `select_agent_tools`, `system_task`.
- Rejestr narzędzi i skille: `skills/*.yaml`, `load_skills`, `match_skill`, `execute_skill`.

### 2.4 Pamięć / wiedza
- `memory.db` (SQLite): `memories`, `conversations`, `lessons`, `plans` (CBR), `trajectories`,
  `learned`, `unknowns`; wektory (numpy→HNSW→sqlite-vec), `nomic-embed-text`.
- `knowledge.db` (FTS5, 130 573 dok.) + `knowledge_self.db` (1155) — **dane do ew. reimportu**.
- `knowledge/facts.txt`, `first_aid.txt`, `factory_topics.txt`.

### 2.5 Dane + bramki (aktywa treningowe)
- `trajectories`: **agent 352** (19/19 narzędzi, zweryfikowane), plan 413, remote 179, chat 6.
- `scripts/toolcall_gen.py` (generator), `scripts/build_dataset.py` (`--toolcalls`, `--full-schema`).
- `scripts/eval_lora.py` (rozszerzona bramka), `eval_atena` 59/59, `roadmap_check` 26/26,
  `tests/run_tests.py` 45/45.
- `scripts/merge_lora_hf.py`, `train_lora.py` (offload_embedding, filtrowanie), build `llama.cpp`
  (llama-quantize) na Kali.

### 2.6 Głos/UX
- `speakable()`/`feminize()` (poprawna polszczyzna/liczby), `mirror_tty`/`wall_write`, wake fallback
  gramatyką, briefing/self-review (koncept proaktywności).

## 3. Co ODRZUCAMY (dług, nie przenosić)
- Monolityczny `voice_assistant.py` jako całość (przenosimy funkcje, nie plik).
- Router-first (78 intencji, 259 regexów) jako bramka decyzyjna — zostaje tylko cache/bezpieczeństwo.
- **PC jako live backend** — usuwamy z runtime; PC tylko offline/trening (opt-in).
- Nagromadzone skrypty jednorazowe i logi/śmieci w rejestrach.
- Branding Ateny (logo/banery) — tymczasowo wyczyszczony.

## 4. Korekta roli PC (kluczowa)
- **Docelowo:** PC = self-play, LoRA, trening, generacja danych, ewaluacja modeli.
- **Nie:** codzienne odpowiedzi/„wiedza" runtime. Jeśli PC używany w runtime, to **jawnie opt-in**
  i tylko dla zadań, których Pi nie potrafi (z etykietą i pomiarem), nigdy domyślnie.

## 5. Hailo — stan i realistyczny plan
- Działa: STT na NPU (~0,44 s, ~2% CPU). NPU-LLM bezczynny (polityka → PC).
- Ograniczenia: brak HEF do embeddingów/VAD/function-calling; HailoRT 5.1.1 = urządzenie na
  wyłączność; brak telemetrii hwmon; `measure-power` wymaga zwolnienia urządzenia.
- Plan (po rdzeniu): HP1 telemetria aplikacyjna (liczniki STT/LLM, czasy), HP2 embeddingi na NPU
  (jeśli zdobędziemy/ skompilujemy HEF), HP3 większy LLM HEF, HP4 NPU-first tam, gdzie potrafi.

## 6. Werdykt
- **Ratujemy wiedzę, dane, bezpieczeństwo i koncept agenta.**
- **Wymieniamy architekturę** (monolit/router-first/PC-live) na czysty rdzeń **ASTRO**.
- Pełny greenfield od zera = strata najdroższych assetów → **nie**. Budujemy nowy rdzeń obok i
  przenosimy moduły selektywnie (patrz `MIGRATION.md`).
