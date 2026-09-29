# ASTRO — Architektura (kontrakty modułów)

## Zasady
- 1 moduł = 1 odpowiedzialność; brak cyklicznych zależności.
- Model-first: decyzję o narzędziu podejmuje model; determinizm tylko dla bezpieczeństwa/cache.
- Wszystkie wywołania LLM przez jeden interfejs `backends.run(kind, messages, tools=…)`.
- Wszystko testowalne bez sprzętu (audio/LLM za interfejsami, mockowalne).

## Warstwy
```
config/   -> wczytuje env/dropy, brak logiki
safety/   -> decyzje "wolno/nie" + potwierdzenia (nie zna modeli)
tools/    -> rejestr narzędzi: schemat + wykonanie (sandbox/gated)
backends/ -> npu | cpu | pc(opt-in) | remote; run() + capabilities
memory/   -> storage epizodyczny + RAG + profil (SQLite/wektory)
core/     -> pętla agenta, planner, verifier, sesje, dispatch
audio/    -> STT/TTS/VAD/wake (sprzęt za interfejsem)
```

## Kontrakty (interfejsy)
### `backends`
```
class Backend:
    name: str
    capabilities: set[str]      # {"chat","tools","json","plan","fresh"}
    def ready() -> bool
    def run(messages, *, tools=None, fmt=None, max_tokens=..., temperature=...) -> (text, tool_calls)
choose(kind, text) -> backend     # polityka: NPU-first, CPU fallback, PC/remote opt-in
run(kind, messages, **kw)        # kaskada z fallbackiem; loguje metryki
```

### `tools`
```
@tool(name, schema, scopes={"read"|"sandbox"|"gated"|"network"})
def fn(ctx, **args) -> ToolResult(text, ok)
registry.schemas(only=None) -> [schema]   # selekcja podzbioru (mniejszy prompt)
execute(name, args) -> ToolResult          # przez safety gate
```
- `read`: tylko odczyt; `sandbox`: zapis w `~/astro-agent`; `gated`: wymaga potwierdzenia;
  `network`: web (sanitize + `is_private_url`).

### `safety`
```
classify(text) -> "command"|"question"|"chat"
check_request(text) -> ("ok"|"warn"|"refuse", note)
require_confirm(announce, kind, payload) -> bool
is_safe_command/ is_sensitive_path/ is_private_url / validate_plan
```

### `memory`
```
remember(text) / search(query,k) / profile()
add_episode(user, assistant, tools, ok)      # nauka
add_lesson(text) / recent_lessons(n)
trajectories(kind) -> ...                    # dane do treningu
```

### `core`
```
Agent.run(text) -> reply
  build_context() -> [messages]      # profil, pamięć, lekcje, czas, kompakcja
  loop(max_steps): observe -> tool -> verify -> answer
  planner.goal_to_steps(goal)        # gdy trzeba planu
  verifier.check(answer, tool_results)
dispatch(text): fast_tools/router -> Agent (fallback) -> plan (system_task)
```

### `audio`
```
STT.transcribe(pcm) -> text     (NPU Whisper; bez fallbacku poza sprzętem)   [✔]
TTS.speak(text)                 (Piper + profil "słodki robocik" przez sox)  [✔]
VAD + wake                      (wake "Astro" ✔; VAD jeszcze nieprzeniesiony)  [~]
VoiceLoop                       (pół-duplex: nasłuch -> wake -> agent -> głos)[✔]
```

## Przepływ (runtime)
```
audio.wake -> STT -> core.dispatch
  -> fast_tools (godzina/skill/fakt)  [deterministyczne, bezpieczne]
  -> core.Agent.loop (model-first, tools/verify)   [domyślna ścieżka]
  -> system_task (plan + potwierdzenie)            [zmiany systemu]
-> memory.add_episode + kosmetyka -> TTS
```
Backendy: `chat`→NPU (jeśli gotowy) → CPU; `tools/json/plan`→CPU (póki NPU nie ma
function-calling); `pc`/`remote` **tylko** gdy jawnie włączone.

## Ścieżki runtime
- Kod: `/home/user/astro`
- Dane: `~/astro/runtime/` (memory.db, knowledge, datasets, logs)
- Usługa: `astro.service` (`Restart=on-failure`, log `~/astro/runtime/logs/astro.log`)
- Piaskownica agenta: `~/astro-agent`
