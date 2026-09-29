# ASTRO — Migracja, czyszczenie, GitHub

## Zasada
Nie kopiujemy monolitu. **Selektywnie przenosimy sprawdzone funkcje** (z testami) do czystych
modułów ASTRO. Stary projekt zostaje jako referencja (`../voice-assistant/`, nieusuwany).
ASTRO nie trzyma już archiwum dokumentów — własny `docs/` jest jedynym źródłem prawdy.

## Etapy
### E0 — audyt i szkielet ✔ (ten etap)
- Inwentarz i „must keep": `docs/E0_AUDIT.md`.
- Kontrakty modułów: `docs/ARCHITECTURE.md`.
- Szkielet katalogów `core/ tools/ backends/ memory/ safety/ audio/ config/ tests/`.

### E1 — rdzeń agenta (bez głosu) ✔
- `backends/` (interfejs + CPU/NPU stub), `tools/` (rejestr), `safety/` (przeniesione reguły),
  `memory/` (nowy `memory.db` + import tylko kuratorowanej wiedzy), `core/` (pętla agenta).
- Przenieść testy: router/klasyfikacja/bezpieczeństwo/speakable/feminize → `tests/`.
- Kryterium: `pytest`/`run_tests.py` zielone; przykład „zadanie → narzędzia → odpowiedź" działa
  na CPU bez audio.

### E2 — narzędzia i pamięć pełne ✔
- Port `read_file/list_dir/search_files/run_command(read-only)/write/append/run_script(sandbox)/
  web_search/web_fetch/nearby_places/man_page/cmd_help/check_script/system_task/ask_user`.
- Pamięć: epizodyczna + lekcje + CBR + wektory; profil; write-back z weryfikacją.

### E3 — backendy i polityka ✔
- NPU-first dla czatu (gdy gotowy), CPU dla tools/json/plan; **PC/remote tylko opt-in**.
- Metryki backendów (log JSONL) + selekcja podzbioru narzędzi.

### E4 — czyszczenie, archiwizacja, GitHub ✔ (częściowo: GitHub bez zmian na życzenie)
- **Logi**: archiwizuj i wyzeruj `voice-assistant/logs/*`; nowy, czysty `astro/runtime/logs/`.
- **Journal**: `journalctl --vacuum-time=…` / ograniczyć; journald już `persistent` + 200M.
- **Rejestry**: ASTRO startuje z **nowym `memory.db`**; z Ateny importujemy TYLKO: `facts.txt`,
  `first_aid.txt`, wyselekcjonowane `learned` (wysoka pewność), oraz **352 epizody agenta jako
  datasety** (poza żywą pamięcią). Odpady (unknowns, błędne lekcje, nieudane plany, pętle rozmów)
  **nie** są przenoszone.
- **Agent**: katalog roboczy `~/astro-agent` (czysty); stary `~/atena-agent` archiwizowany.
- **GitHub**: patrz sekcja niżej.

### E5 — Hailo-first (po rdzeniu) ✔ (HP1/HP4; HP2/HP3 zablokowane brakiem HEF)
- HP1 telemetria aplikacyjna NPU; HP2 embeddingi (HEF/kompilacja); HP3 większy LLM HEF;
  HP4 polityka NPU-first + pomiar redukcji CPU.

### E6 — trening (tylko PC) + bramka
- Dataset/generator/loRA na PC (Kali) — Pi nie trenuje. Promocja wyłącznie po zdanej bramce.

## GitHub — „czysty" stan
Rekomendacja (najbezpieczniejsza): **nowe repo `astro`** (świeża historia, nowy README), a stare
`mobium-app/atena_bot` **archiwum** (nie kasujemy). 
Alternatywa (jeśli chcesz jedno repo): **orphan branch** + force-push (zmienia wszystkie commity)
— **wymaga Twojej jawnej zgody**, bo niszczy historię.
Procedura E4 (do wykonania po E3):
```
cd ~/astro && git init -b main
git add -A && git commit -m "ASTRO: czysty start (E0-E3)"
# nowe repo:
gh repo create <konto>/astro --private --source=. --push
```
`.gitignore`: `venv/ runtime/ logs/ datasets/ models/ knowledge/local|web/ archive/ *.db *.env`.

## Czyszczenie „szumu" — konkret
- Usunąć z runtime komunikaty/trace, które zaśmiecają (nadmiarowe `log()`); wprowadzić poziomy logu
  (`INFO/WARN/DEBUG`) i jeden kanał (`astro.log`) + opcjonalny `--debug`.
- Wyłączyć/poukładać stare timery Ateny (self-review, knowledge-factory, training-check) — w ASTRO
  zastąpić jednym, świadomym mechanizmem (jeśli w ogóle).
- Rejestry: zero „unknowns/lesson" śmieci; lekcje tylko z realnych, potwierdzonych błędów.

## Kryteria sukcesu ASTRO (bramki)
1. Brak pliku-monolitu; każdy moduł < ~800 linii i testowalny.
2. PC **nie** jest wymagany do runtime; domyślnie OFF jako live backend.
3. Hailo: STT + (docelowo) czat/embeddingi na NPU; telemetria widoczna.
4. Testy zielone; `eval_atena` (przeniesione) i „agent gate" PASS.
5. Dokumentacja aktualna i jednoznaczna (jeden `docs/` + README).
