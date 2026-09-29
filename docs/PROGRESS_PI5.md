# ASTRO — progres modelu na Raspberry Pi 5

> Wygenerowano: **2026-09-22 11:50:11**. Model runtime: `astro-qwen3-lora-v5` (Qwen3-1.7B LoRA), serwowany przez Ollamę na Pi (11434).

## 1. Przyrost danych treningowych (trajektorie + dataset)

| etap | opis | trajektorie agenta | train | val |
|---|---|--:|--:|--:|
| 2026-09-19/20 | baza przed sesją | **107** | 165 | 12 |
| 2026-09-21 ~16:00 | wersja B (równolegle PC-MAX∥PC) | **152** | 165 | 12 |
| 2026-09-21 ~18:00 | po sesji B (+45) | **153** | 221 | 17 |
| 2026-09-21 ~21:00 | cykl samodoskonalenia (iter 1) | **254** | 302 | 28 |
| teraz | cykl samodoskonalenia | **697** | 627 | 64 |

### Trajektorie agenta (wykres)

```
2026-09-19/20    ██████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ 107
2026-09-21 ~16:00 █████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ 152
2026-09-21 ~18:00 █████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ 153
2026-09-21 ~21:00 ███████████████░░░░░░░░░░░░░░░░░░░░░░░░░ 254
teraz            ████████████████████████████████████████ 697
```

### Dataset treningowy (wykres)

```
2026-09-19/20    ███████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ 165
2026-09-21 ~16:00 ███████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ 165
2026-09-21 ~18:00 ██████████████░░░░░░░░░░░░░░░░░░░░░░░░░░ 221
2026-09-21 ~21:00 ███████████████████░░░░░░░░░░░░░░░░░░░░░ 302
teraz            ████████████████████████████████████████ 627
```

## 2. Wersje LoRA na Pi5

| wersja | status |
|---|---|
| `astro-qwen3-lora-v6:latest` | w Ollama |
| `astro-qwen3-lora-v5:latest` | w Ollama ← AKTYWNA |
| `astro-qwen3-lora-v4:latest` | w Ollama |
| `astro-qwen3-lora-v3:latest` | w Ollama |
| `astro-qwen3-lora:latest` | w Ollama |
| `astro-qwen3-lora-v2:latest` | w Ollama |

## 3. Bramka E6 (runtime, held-out few-shot) — kolejne iteracje

| log | tools | chain | chat | wynik |
|---|:--:|:--:|:--:|:--:|
| gate_iter1.log | 1/8 | 0/2 | 2/2 | FAIL |
| gate_iter10.log | 1/8 | 0/2 | 2/2 | FAIL |
| gate_iter11.log | 1/8 | 0/2 | 2/2 | FAIL |
| gate_iter12.log | 1/8 | 0/2 | 2/2 | FAIL |
| gate_iter13.log | -/- | -/- | -/- | ? |
| gate_iter2.log | 1/8 | 0/2 | 2/2 | FAIL |
| gate_iter3.log | 1/8 | 0/2 | 2/2 | FAIL |
| gate_iter4.log | 1/8 | 0/2 | 2/2 | FAIL |
| gate_iter5.log | 1/8 | 0/2 | 2/2 | FAIL |
| gate_iter6.log | 1/8 | 0/2 | 2/2 | FAIL |
| gate_iter7.log | 1/8 | 0/2 | 2/2 | FAIL |
| gate_iter8.log | 1/8 | 0/2 | 2/2 | FAIL |
| gate_iter9.log | 1/8 | 0/2 | 2/2 | FAIL |

## 4. Maszyny-nauczyciele (tool-calling / polszczyzna)

- **PC-MAX** (RTX 5070 Ti 16 GB): `qwen3:30b-a3b` — tool-calling + łańcuchy.
- **PC / Kali** (RTX 4060 8 GB): `bielik-11b-v3.0` — polszczyzna/teoria (chat).
- **PC-2** (`LAPTOP-ACKVECNP`, RTX 4060 Laptop 8 GB): `bielik-11b-v3.0` — chat.

## 5. Diagram (SVG)

Diagram słupkowy: `astro/runtime/logs/progress_pi5.svg`.

