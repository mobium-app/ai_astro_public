# Egzamin + bramka E6 (PC-MAX ∥ PC) — raport (2026-09-21)

> Bramka: `astro/scripts/e6_gate.py`. Progi promocji: **tools ≥80% (≥17/21), chain ≥60% (≥2/3),
> chat ≥80% (≥3/3)**. Pomiary deterministyczne: `--temp 0 --seed 42`, `--tool-first`,
> `--num-ctx 8192 --num-predict 1024`.

## 1. Kluczowa poprawka bramki (kalibracja)
- **Objaw**: `qwen3:30b-a3b` (i inne) wypadały na „brak wywołań narzędzia" oraz pusty czat.
- **Przyczyna**: `e6_gate.py` **nie ustawiał `num_ctx`** → Ollama używała domyślnego (4096), a prompt
  z **32 schematami narzędzi** sięga kilku tys. tokenów → był obcinany i model nie widział narzędzi.
  Dodatkowo `num_predict=256` nie mieścił „thinking" Qwen3 → czat pusty.
- **Poprawka**: `e6_gate.py` ma teraz `--num-ctx` (domyślnie **8192**) i `--num-predict`
  (domyślnie **1024**); rozmiary w `_chat` ujednolicone.
- **Skalibrowana konfiguracja `qwen3:30b-a3b`**: `--tool-first --no-think` + ctx 8192 + predict 1024
  → **PASS** (19/21, 3/3, 3/3).

## 2. Wyniki (po kalibracji)

| Maszyna | Model | tools | chain | chat | WYNIK |
|---|---|:--:|:--:|:--:|:--:|
| PC-MAX | **qwen3:30b-a3b** | 19/21 (90%) | **3/3** | 3/3 | ✅ PASS |
| PC-MAX | **qwen3:14b** | 18/21 (86%) | **3/3** | 3/3 | ✅ PASS |
| PC-MAX | **qwen2.5:32b** | 19/21 (90%) | **3/3** | 3/3 | ✅ PASS |
| PC-MAX | gpt-oss:20b | 18/21 (86%) | 1/3 | 0/3 | ❌ FAIL |
| PC (Kali) | **bielik-11b-v3.0** | 17/21 (81%) | **3/3** | 3/3 | ✅ PASS |
| PC (Kali) | **qwen3:8b** | 18/21 (86%) | **3/3** | 3/3 | ✅ PASS |
| PC (Kali) | **qwen2.5:7b** | 17/21 (81%) | 2/3 (67%) | 3/3 | ✅ PASS |
| PC (Kali) | qwen2.5:3b | 18/21 (86%) | 0/3 | 3/3 | ❌ FAIL |

Czasy (pełny zestaw 27 testów): qwen3:14b 24 s, qwen3:8b 28 s, gpt-oss:20b 38 s, qwen2.5:7b 43 s,
bielik-11b 154 s, qwen3:30b-a3b 181 s, qwen2.5:32b 275 s.

## 3. Wnioski
- Po poprawce `num_ctx` **wiele modeli przechodzi bramkę**: `qwen3:30b-a3b`, `qwen3:14b`,
  `qwen2.5:32b` (PC-MAX) oraz `bielik-11b`, `qwen3:8b`, `qwen2.5:7b` (PC).
- **`qwen3:30b-a3b` = najlepszy kompromis** (30B jakość, PASS, ~180 s) → dobry nauczyciel
  tool-calling/łańcuchów i kandydat runtime.
- **`qwen3:14b`** = najszybszy pełny PASS (24 s) — świetny do runtime/nauczyciela przy dużej skali.
- **`qwen2.5:32b`** = najwyższy tools (19/21), ale wolny (275 s).
- **`gpt-oss:20b`**: nie nadaje się na runtime bez obsługi formatu „harmony" (chain/chat puste).
- Dwie „porażki" narzędzi `qwen3:30b-a3b` to sensowne alternatywy (`run_command` zamiast
  `system_task`/`run_skill`) — do ewentualnego złagodzenia w bramce.

## 4. Pliki
- `astro/scripts/e6_gate.py` (dodane `--num-ctx`, `--num-predict`; domyślne 8192/1024),
- raporty runów: `/tmp/opencode/exam_pcmax.log`, `/tmp/opencode/exam_pc.log`.

---

# Bramka zunifikowana z runtime + fałszywe negatywy `--no-think` (2026-09-22)

> Kontekst: po serii nieudanych promocji (r7/pc2/kali-full/kali-full3 = FAIL) zbadano **konfigurację
> samej bramki**. Odkryto, że wyniki były zafałszowane.

## 1. `--no-think` fałszywie oblewa adaptery ASTRO (P0)
- **Objaw**: `astro-qwen3-lora-v5` (aktywny, promowany) i `astro-qwen3-lora-kali-full3` dostawały
  **0/8 tools** z flagą `--no-think`, mimo że działają.
- **Dowód (bezpośrednie wywołanie Ollamy)**: ten sam prompt i narzędzia, `think=False` →
  model **halucynuje odpowiedź** („Oto dane: temperatura CPU to 72.5°C…") i **nie woła narzędzia**;
  `think` nieustawiony (domyślnie) → poprawne `tool_call` (`system_info`).
- **Po usunięciu `--no-think`** (tools-only, `--quick`):

  | model | `--tool-first` | `--runtime-prompt` |
  |---|---|:--:|
  | astro-qwen3-lora-v5 | **8/8 PASS** | **8/8 PASS** |
  | astro-qwen3-lora-kali-full3 | **8/8 PASS** | — |
  | astro-qwen3-lora-pc2 | 5/8 FAIL | — |

- **Wniosek**: runtime **nie ustawia** `think` (patrz `backends/cpu.py`), więc `--no-think` był
  rozjazdem bramki i produkcji. **Kanoniczna bramka NIE używa `--no-think`.**

## 2. Błąd doboru narzędzi w runtime (`registry.select`) — naprawiony
- **Objaw**: „Wykonaj polecenie df -h" → wybór `[system_info, ask_user, web_search, web_fetch]`
  **bez `run_command`** → model nie mógł wykonać polecenia.
- **Przyczyna**: hint `...|kurs|cen|...` łapał podsłowo „cen" w „polec**en**ie" → `web_search`,
  a `run_command` wypadał z budżetu `MAX_TOOLS`.
- **Fix**: nowy hint wykonawczy (`wykonaj|uruchom|polecen|komend|df|ls|cat|du|ps|whoami|uname`)
  → `run_command`, oraz `cen` → `\bcen\w*`. Testy regresyjne w `tests/test_tools.py`.

## 3. Kanoniczna bramka (definicja)
```
python3 scripts/e6_gate.py --model <tag> --url http://127.0.0.1:11434 \
  --runtime-prompt --max-tools 6 --few-shot 2 --temp 0 --seed 42 --no-baseline --quick
```
- `--runtime-prompt` = `core/context.SYSTEM_PROMPT` (dokładnie jak runtime),
- `--max-tools 6` + `--few-shot 2` = jak runtime (`registry.select` + `config.FEWSHOT`),
- **bez `--no-think`**.
- Zaktualizowane: `finish_all.sh`, `train_cycle.sh`, `docs/NEXT_SESSION.md`.

## 4. Pełna kanoniczna bramka (tools+chain+chat, `--quick`)
| model | tools | chain | chat | WYNIK |
|---|:--:|:--:|:--:|:--:|
| astro-qwen3-lora-kali-full3 | 5/8 (62%) | 1/2 (50%) | 2/2 | ❌ FAIL |
| astro-qwen3-lora-v5 (aktywny) | 4/8 (50%) | 2/2 (100%) | 2/2 | ❌ FAIL |

- **Nikt nie zostaje promowany**; aktywny pozostaje `astro-qwen3-lora-v5`.
- Uwaga: przy tej konfiguracji spada też v5 — prawdopodobnie **szum few-shot** (`--few-shot 2`
  wstrzykuje trajektorie z pamięci, czasem nietrafne) i/lub dobór narzędzi. Do zbadania:
  porównać `--few-shot 0/1/2` oraz `--max-tools 6/10` na stałym zestawie; ewentualnie poprawić
  `similar_trajectories`/próg. To **nie** jest problem samego modelu (tools-only bez few-shot: 8/8).

## 4a. A1 — pomiar few-shot (2026-09-22, v5, tools-only `--quick`, runtime-prompt, bez `--no-think`)
| konfiguracja | tools | czas |
|---|:--:|:--:|
| `--max-tools 0` (32 schematy), fs=0 | **8/8** | 249 s |
| `--max-tools 6`, fs=0 | **8/8** | 102 s |
| `--max-tools 6`, fs=1 | ~4/8, wolno/timeout | >500 s |
| `--max-tools 6`, fs=2 | wolno/timeout | >500 s |

- **Wniosek**: few-shot z pamięci (`similar_trajectories`) **szkodzi i spowalnia** (nawet gdy zwraca
  niemal dokładne trafienia). Poprawiono format wzorców (bez „wynik: …", mocna instrukcja
  „wywołaj TERAZ") — bez efektu. **Domyślnie `FEWSHOT=0`** (`ASTRO_FEWSHOT`).
- **Kanoniczna bramka**: `--runtime-prompt --max-tools 6` **bez `--few-shot`**. Zaktualizowane
  `finish_all.sh`, `train_cycle.sh`, `NEXT_SESSION.md`.
- Do zrobienia przed ponownym włączeniem few-shot: naprawić retrieval (próg/trafność) i zmierzyć.

## 5. Wnioski
1. Wcześniejsze „FAIL" adapterów były **częściowo artefaktem bramki** (`--no-think`) — realnie
   `kali-full3` i `v5` wołają narzędzia poprawnie (8/8 tools-only).
2. **Bramka musi być 1:1 z runtime** (prompt, liczba narzędzi, few-shot, bez `think`).
3. Otwarte: **few-shot z pamięci** może szkodzić — zmierzyć i ewentualnie wyłączyć/uszczelnić
   w runtime i bramce.
