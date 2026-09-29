# RESEARCH — Qwen3-1.7B na Hailo-10H + baza wiedzy + optymalizacja wydajności

> Analiza **teoretyczna** (bez wdrażania). Data: 2026-09-19. Autor: opencode + Michał.
> Cel: ocenić, czy warto oprzeć „inteligentny" runtime ASTRO na **Qwen3-1.7B-Instruct** na
> Hailo-10H, z bazą wiedzy i optymalizacją pod wydajność (dobór narzędzi, krótsze ścieżki).
> Hipoteza wejściowa: „optymalizacja mądrzejszego modelu bywa łatwiejsza niż uczenie słabszego".

## 0. Werdykt (skrót)
- **Hailo realnie wspiera Qwen3-1.7B** (oficjalny HEF dla Hailo-10H), ale wymaga
  **HailoRT > 5.2.0**; my mamy **5.1.1** → potrzebny upgrade (jest udokumentowany w społeczności).
- **Hipoteza jest częściowo prawdziwa**: Qwen3-1.7B jest w swojej klasie **najlepszym
  tool-callerem** (niezależny benchmark #1), a nowsza baza lepiej „przyjmuje" optymalizację niż
  Qwen2.5. **Ale** wiążące ograniczenia tego toru to **kwantyzacja HEF (A8W4)** i **kontekst 2048**,
  nie sama inteligencja modelu. To nie „magia", tylko inżynieria budżetu tokenów + ryzyko DFC.
- NPU nie jest szybszy niż CPU Pi w surowych tok/s (Geerling 2026) — jego wartością jest
  **odciążenie CPU, 8 GB dedykowanego RAM i ~3 W**. Czyli „wykorzystanie potencjału Hailo" =
  przeniesienie **lekkich decyzji** (routing/1 wywołanie narzędzia), nie ciężkiego rozumowania.

## 1. Czy Hailo naprawdę wspiera Qwen3-1.7B?
- **Oficjalny HEF**: GenAI Model Zoo, Hailo-10H, `Qwen3-1.7B-Instruct` (1.79 GB), wymagalność
  **> 5.2.0**, publikowany w `dev-public.hailo.ai/v5.4.0`.
- **Nasz stan**: HailoRT **5.1.1**, FW `HAILO10H`; lokalnie mamy HEF-y tylko 1.5B + `llama3.2:3b`
  (legacy, **nie w aktualnym zoo**). Qwen3-1.7B **nie uruchomi się na 5.1.1**.
- **Wydajność HEF (Hailo, 2048 ctx, A8W4)**: load 6.75 s, TTFT 0.62 s, **4.78 tok/s**.
  Dla porównania Pi CPU: 3B ≈ 5,3 tok/s, 7B ≈ 2,3 tok/s. Czyli NPU ~między 3B i 7B szybkością,
  ale z jakością 1.7B (mniej niż 7B).
- **Reality check (Jeff Geerling, AI HAT+ 2, 2026-01)**: Hailo-10H ma 8 GB LPDDR4X i ~3 W;
  „Pi CPU bije Hailo w LLM", Hailo wygrywa głównie **efektywnością i odciążeniem**, a TTS/VLM
  i „mixed mode" (wizja + inferencja) to realne zastosowania.
- **Wersje**: HailoRT 5.2.0 (I 2026), 5.3.0 (IV 2026), 5.4.0 (VIII 2026); społeczność ma guide
  „Upgrading to HailoRT 5.2.0 – step by step (Raspberry Pi & Hailo Apps)". Upgrade = realny, ale
  dotyka sterownika (`hailo1x` DKMS), FW i istniejącego STT/HEF → ryzyko regresji.

## 2. Dlaczego Qwen3-1.7B jest „mądrzejszy" — dowody
- **Qwen3**: 119 języków, tryb **thinking / non-thinking** (przełączany `/think`|`/no_think`),
  natywne **tool calling**, „significantly improved over Qwen2.5" w rozumowaniu/kodzie/agentach.
  Benchmarki bazy 1.7B: MMLU 62.63, GSM8K 75.44, EvalPlus (kod) 52.70, MMMLU 63.27,
  RULER (długi kontekst) 85.2 (non-thinking).
- **Niezależny tool-calling benchmark (Apple Silicon, 2026)**: `qwen3:1.7b` **#1** — Agent Score
  **0.960**, Action 0.900, Restraint 1.000, Wrong Tool 0 (średnio ~10,7 s w trybie thinking).
  Dwa istotne wnioski z tego samego źródła:
  - **„Bigger isn't always better": `qwen2.5:1.5b` wygrał z `qwen2.5:3b`** (dane/nowszość > rozmiar),
  - **thinking to broń obosieczna**: dłuższe łańcuchy nie pomagają w decyzjach narzędziowych —
    do głosu trzeba **`/no_think`** (szybciej, podobny wynik).
- Wniosek: w klasie ≤2B Qwen3-1.7B jest **najlepszym dostępnym wyborem pod agentowość**, a jego
  „inteligencja" jest właśnie w poprawnym **wyborze narzędzia i restraint** — czyli dokładnie tam,
  gdzie chcemy optymalizować runtime.

## 3. Symulacja architektury: Qwen3-1.7B + baza wiedzy + wydajność
### 3.1 Twardy budżet kontekstu (najważniejsze ograniczenie)
HEF ma **2048 tokenów**. Musi się w nich zmieścić: system prompt + schematy narzędzi + wzorce
few-shot + kontekst z bazy wiedzy + historia + odpowiedź. To wymusza **dyscyplinę tokenową**:
| Element | Wariant „ciężki" | Wariant „odchudzony" (wymagany) |
|---|---|---|
| System prompt | ~250 tok | **~90–120 tok** (skrócony, bez ozdób) |
| Schematy narzędzi | 23 narzędzia ≈ 2500+ tok | **6 narzędzi ≈ 500–650 tok** (selekcja) |
| Few-shot | 2 wzorce z wynikami ≈ 400–800 tok | **1 wzorzec, wynik ≤120 znaków ≈ 150 tok** |
| RAG / wiedza | 3 fragmenty × 400 znaków | **1–2 fragmenty × ~200 znaków ≈ 150 tok** |
| Historia | 6 tur | **1–2 tury lub brak** |
| Odpowiedź | 600 tok | **≤150 tok** |
- Selekcja narzędzi (`MAX_TOOLS=6`) jest **niezbędna**, nie opcjonalna. Mniej narzędzi = krótszy
  prompt = szybszy prefill na NPU i **mniej pomyłek** (Qwen3 i tak preferuje restraint).
- To realnie tłumaczy hipotezę: „optymalizacja" = redukcja budżetu + lepsze uporządkowanie decyzji.

### 3.2 Skrócenie ścieżek decyzyjnych (zgodne z istniejącym ASTRO)
- **Fast-path deterministyczny** przed modelem: fakty offline, status, zasilanie za zgodą —
  zero tokenów NPU (już mamy).
- **Cache planów (CBR)** i **retrieval trajektorii** (few-shot) — ale na 2048 ctx
  **k=1, nie k=2** (koszt tokenów rośnie liniowo).
- **Jedno wywołanie narzędzia na turę** + zarezerwowany krok na syntezę (jak w ASTRO) — mniej
  „łańcuchów myślowych" = mniej tokenów i mniejsze ryzyko pętli.
- **RAG kompaktowy**: retriever zwraca 1 najlepszy fragment (nie top-3), z twardym limitem znaków.
- **Gra warta świeczki**: przy 2048 ctx każdy zaoszczędzony token to szybszy prefill; NPU jest
  wrażliwy na długość promptu (TTFT rośnie ~liniowo).

### 3.3 Praca na kodzie (wymóg użytkownika)
- Qwen3-1.7B jest dobry w kodzie *jak na 1.7B* (EvalPlus 52.7), ale **2048 ctx = za mało na pliki**.
- Realny podział: **NPU** = decyzje/krótkie fragmenty/edycje punktowe; **CPU 7B lub PC** = czytanie
  i analiza większych plików. Alternatywa „specjalisty": `Qwen2.5-Coder-1.5B` na Hailo (TPS 8.13).
- To argument przeciw stawianiu „wszystkiego na NPU": Hailo nie da kontekstu potrzebnego do kodu.

## 4. Hipoteza: „optymalizować mądrzejszy model łatwiej niż uczyć słabszy"
**Za:**
- Nowsza, lepiej wyrównana baza (Qwen3) daje wyższy sufit i większy zwrot z LoRA/dystylacji niż
  stara 1.5B (Qwen2.5). Benchmark pokazuje, że **restraint/agentowość** Qwen3 są już wysokie —
  zostaje je „dostroić", a nie „wbudowywać od zera".
- Dystylacja z nauczyciela 7B (CPU/PC, dozwolone jako trening) → 1.7B: sensowna krzywa.
- Małe modele „nasycają się" szybciej i mają mniej pojemności; trenowanie słabszego często walczy
  z jego ograniczeniami, a nie z zadaniem.

**Przeciw / ograniczenia:**
- **Kwantyzacja A8W4 na HEF** obniża jakość — zyski z „mądrzejszej" bazy mogą zostać częściowo
  skonsumowane przez HEF. To trzeba zmierzyć, nie założyć.
- **2048 ctx** ucina few-shot i RAG → „optymalizacja" zamienia się w redukcję, nie w bogactwo.
- **Tool-calling na HEF**: nasz `NpuBackend` jest **chat-only**; HEF ma template z `custom_tools`,
  ale musi to obsłużyć runtime (hailo-ollama/genai) — niepotwierdzone.
- Nieznana **jakość polskiego** 1.7B (119 języków tak, ale PL bywa słabszy niż w 7B).

**Werdykt**: hipoteza jest **prawdopodobna i warta sprawdzenia**, ale nie jest uniwersalna —
wiązaniem są HEF/ctx/plumbing, więc „mądrzejszy model" daje przewagę tylko przy **agresywnej
dyscyplinie tokenowej i poprawnym tool-callingu**.

## 5. Zagrożenia
1. **Upgrade HailoRT 5.1.1 → 5.4** może zepsuć działające STT (Whisper-Base) i zmusić do
   przepakowania HEF-ów; dotyka DKMS/FW. Ryzyko downtime/niestabilności.
2. **Wyłączność urządzenia** (5.1.1) vs group-sharing (≥5.2): po upgrade można łączyć STT+LLM,
   ale konfiguracja bywa kapryśna (wątki społeczności o `HAILO_VDMA_LAUNCH_TRANSFER`).
3. **Kompilacja własnego HEF (punkt 4)**: DFC działa na **x86 z AVX**, wymaga konta/Developer
   Zone; LLM-owa ścieżka jest **reverse-engineered/eksperymentalna**. Wątek społeczności:
   skompilowano **Qwen2-1.5B LoRA** (DFC 5.2.0) — HEF zawiera `router/engineer/responder`
   prefill+tbt, ale **`hailo_platform.genai.LLM` zgłasza `HAILO_HEF_FILE_CORRUPTED`**; obejście =
   niskopoziomowe API/orchestracja network-group. Czyli „da się, ale boli".
4. **Ryzyko regresji jakości PL**: 1.7B A8W4 może mówić po polsku gorzej niż CPU 3B/7B.
5. **Koszt utrzymania**: dwa runtime'y (HF + HEF), dwa tokenizatory, wersjonowanie HEF.
6. **Bezpieczeństwo**: więcej ścieżek wykonawczych = więcej miejsc na błąd bramek (nie osłabiać
   `PROTECTED`/potwierdzeń).

## 6. Szanse
1. **Odciążenie CPU i RAM Pi** (8 GB Hailo RAM własne) — CPU wolny dla TTS/STT/agenta.
2. **Najlepszy small-tool-caller** → routing i wybór narzędzi na NPU, krótkie ścieżki, ~3 W.
3. **Offline i prywatnie** — brak chmury; pełna kontrola.
4. **Dystylacja 7B→1.7B** (na PC) → potencjalnie 1.7B bijące dzisiejsze 3B w tool-callingu.
5. **Własny HEF** (badawczo) = unikalna przewaga: polski 1.7B/3B na NPU, gdy inni mają tylko
   generyczne modele. Ścieżka istnieje (community compiler + DFC).
6. **VLM/kamera** w przyszłości (Qwen3-VL-2B) — „mixed mode" wizja+LLM.
7. **TTS na NPU** (community POC) — dalsze odciążenie CPU.

## 7. Rekomendacje (etapowe, bramkowane)
**Zasada nadrzędna: NAJPIERW waliduj model, POTEM ruszaj HailoRT.** Nie odwrotnie.

- **Faza A — „papier/CPU" (0 ryzyka, zalecany start)**: uruchom `qwen3:1.7b` (non-thinking)
  **na CPU/Ollama** i przepuść przez istniejącą bramkę held-out (`e6_gate --holdout`) + próbki PL.
  Zmierz: tools/chain, długość ścieżki, tokeny, czas. **Jeśli 1.7B nie jest sensowny na CPU,
  na HEF będzie tylko gorzej** (A8W4). To de-ryzykuje cały projekt.
- **Faza B — upgrade HailoRT (środowisko)**: 5.1.1 → 5.4 w kontroli (snapshot, test STT,
  test istniejących HEF, rollback plan). Dopiero potem Qwen3-1.7B przez hailo-ollama.
- **Faza C — optymalizacja tokenowa**: skróć system prompt, zejdź do k=1 few-shot, RAG 1 fragment,
  `MAX_TOOLS≈6`, `/no_think`. Zmierz różnicę względem pełnego wariantu.
- **Faza D — dystylacja (punkt 4)**: nauczyciel 7B/PC generuje trajektorie PL tool-calling →
  LoRA na Qwen3-1.7B (PC GPU) → walidacja na CPU → **próba kompilacji HEF** (badawczo, osobne
  ryzyko). Bramka: kandydat ≥ baza w każdej kategorii, inaczej odrzucić.
- **Faza E — decyzja architektoniczna**: czy docelowo (a) NPU-routing + CPU 7B (hybryda),
  (b) PC live opt-in, czy (c) CPU 7B. Rekomendacja bieżąca: **hybryda** (NPU lekkie decyzje,
  CPU/PC ciężkie) — największy zysk bez oddawania jakości.

## 8. Projekt teoretycznego eksperymentu (metryki i bramki)
- **Zbiór**: held-out `e6_gate --holdout` (21 parafraz, nieobecne w pamięci) + zestaw PL
  (10 pytań wiedzowych, 5 krótkich komend, 3 operacje na kodzie) + kilka tur rozmowy.
- **Warianty**: (1) Qwen2.5-1.5B HEF (baseline NPU), (2) Qwen3-1.7B HEF, (3) Qwen3-1.7B CPU,
  (4) Qwen2.5-7B CPU (sufit jakości).
- **Metryki per wariant**: tool acc (%), chain, chat, **średnia liczba kroków**, **tokeny promptu**,
  TTFT, tok/s, **% tur obsłużonych lokalnie bez CPU**, subiektywna ocena PL (1–5).
- **Bramka promocji NPU**: kandydat ≥ baseline NPU i nie więcej niż −1 vs CPU 7B w jakości PL;
  inaczej NPU tylko do routingu.
- **Hipoteza do potwierdzenia/odrzucenia**: Qwen3-1.7B HEF osiąga **≥ Qwen2.5-3B CPU** w tool
  accuracy przy **niższym CPU** i akceptowalnym PL.

## 9. Otwarte pytania (do weryfikacji w fazach)
1. Czy hailo-ollama/genai obsłuży **tool-calling** na HEF Qwen3 (nie tylko chat)?
2. Jak bardzo **A8W4** psuje polski i tool-calling vs Qwen3 na CPU?
3. Czy 2048 ctx wystarczy na sensowny RAG+few-shot po odchudzeniu?
4. Czy `hailo-10h-llm-compiler` (community) pozwoli wgrać **polski LoRA HEF** i czy genai go uniesie?
5. Czy upgrade runtime nie zepsuje STT i obecnych HEF-ów (rollback?).

## 10. Źródła
- Hailo Model Zoo GenAI `docs/MODELS.rst` (Qwen3-1.7B, TPS/TTFT/ctx/kwantyzacja, wymagania wersji).
- Hailo Model Explorer GenAI (lista modeli Hailo-10H).
- Qwen3-1.7B model card (HF): tryby thinking/non-thinking, 119 języków, agentowość, benchmarki.
- lintware/tool-calling-benchmark (2026): `qwen3:1.7b` #1 (0.960); „qwen2.5:1.5b > 3b"; thinking
  nie zawsze pomaga.
- Jeff Geerling, „Raspberry Pi AI HAT+ 2" (2026-01): 8 GB, 40 TOPS, ~3 W; CPU vs NPU; mixed mode.
- Community Hailo: „Upgrading to HailoRT 5.2.0", „Qwen compiled LoRA HEF… genai error",
  `l-nmch/hailo-10h-llm-compiler` (eksperymentalny pipeline DFC), „I compiled an LLM for hailo-10h".
- HailoRT driver releases (5.2.0/5.3.0/5.4.0).

---

## 11. ANEKS — pomysł „wirtualny SWITCH" (model × tryb) — analiza 2026-09-19
### 11.1 Korekta faktu (ważne)
W benchmarku tool-calling (lintware, 2026) **`qwen3:1.7b` był #1 (Agent Score 0.960)**.
Zdanie „1.5B > 3B" dotyczyło **tej samej rodziny Qwen2.5** (`qwen2.5:1.5b` wygrał z `qwen2.5:3b`),
a **nie** porównania Qwen2.5-1.5B z Qwen3-1.7B. Fakty są więc takie:
- **Qwen3-1.7B wygrywa i reasoning, i tool-calling** w klasie ≤2B;
- Qwen2.5-1.5B jest dobry, ale **nie lepszy od Qwen3-1.7B** w narzędziach.

### 11.2 Switch jest już wbudowany w Qwen3 (jeden model, dwa tryby)
Qwen3 to model **hybrydowy**: te same wagi, tryb `thinking` i `non-thinking` przełączane
`/think` | `/no_think`. Zatem „myślenie vs wykonanie" to **nie dwa modele**, tylko dwa tryby
jednego modelu — taniej: jeden HEF, jeden tokenizer, jedno wdrożenie.

### 11.3 Macierz przeznaczeń (proponowany switch w ASTRO)
| Zadanie | Rekomendacja | Uzasadnienie |
|---|---|---|
| Reasoning / składnia / pętle / problem | **CPU 7B** (think opcjonalnie) | HEF 4.78 tok/s + ctx 2048 nie udźwignie długich łańcuchów |
| Tool-calling / wykonanie | **NPU Qwen3-1.7B non-thinking** lub specjalista `Qwen2-1.5B-Function-Calling` HEF | mocna strona, odciąża CPU |
| Czat / polszczyzna | **CPU 7B** | jakość PL |
| Wiedza / fakty | **fast-path offline** (bez modelu) | 0 tokenów, 0 latencji |
| Ciężki kod / duże pliki | **CPU 7B / PC** | ctx 2048 za mały na pliki |

W ASTRO ta macierz **już istnieje** jako `POLICY` po `kind`. Rozszerzenie = z „backend" na
**„backend + model + tryb"**, np. `("npu","qwen3-1.7b","nothink")`, `("cpu","qwen2.5:7b","think")`.
To rozwinięcie obecnej warstwy, nie nowy byt architektoniczny.

### 11.4 Ocena i ryzyka
- **Sens jest** — ale jako **routing po przeznaczeniu**, a nie „1.7B myśli / 1.5B robi".
- **Thinking na CPU/PC**, nie na Hailo (latencja + 2048 ctx).
- Ryzyka: (1) **tool-calling na HEF niepotwierdzony** (nasz `NpuBackend` chat-only);
  (2) niezawodność samego switcha (decyzja routingu musi być tania i pewna — stąd fast-path);
  (3) dwa tryby = dwa zachowania do walidacji; (4) pokusa „przełączania za często" (narzut).
- **Kolejność bez ryzyka**: najpierw zmierzyć switch **na CPU** (Faza A), potem przenosić wybrane
  role na HEF (Faza B/C). Nie odwrotnie.

### 11.5 Status
- Zapisane jako aneks do tego raportu. Bez zmian w runtime. Do wdrożenia w Fazie C/E po Fazy A/B.

---

## 12. WYNIKI FAZY A — Qwen3-1.7B na CPU (2026-09-19, eksperyment)
Środowisko: `qwen3:1.7b` Q4_K_M, Ollama Pi 5 (CPU, 3 wątki), `think:false`, bramka held-out
(21 parafraz nieobecnych w pamięci). Do porównania istniejące wyniki `qwen2.5:3b`.

| Konfiguracja | tools | Uwaga |
|---|---|---|
| Qwen3-1.7B + **ASTRO SYSTEM_PROMPT** | **2/21** (10%) | model „mówi, że sprawdzi", nie woła |
| Qwen3-1.7B + **prompt tool-first** | **14/21** (67%) | sam prompt dał +12 |
| Qwen3-1.7B + tool-first + **few-shot 2** | **15/21** (71%) | +1 |
| (ref) `qwen2.5:3b` baseline | 17/21 (81%) | – |
| (ref) `qwen2.5:3b` few-shot 2 | **20/21** (95%) | – |

### 12.1 Wnioski
1. **Prompt jest decydujący** (2 → 14): „optymalizacja" realnie działa i jest tańsza niż trening.
2. **Ale Qwen3-1.7B nadal przegrywa z `qwen2.5:3b` w tool-callingu** (15 vs 17/20). Wynik #1
   z benchmarku **nie reprodukuje się** na naszym stacku (Ollama 0.34.0 + nasze prompty/narzędzia);
   tam był Apple MLX/llama.cpp i Qwen-Agent.
3. **Artefakt `think:false`**: Ollama dokleja `/no_think` do ostatniej tury użytkownika, a mały model
   wpisuje to do argumentów (np. `check_script {"path": "/no_think"}`). Lepiej: `/no_think`
   w system prompcie i nie ustawiać flagi `think`.
4. **Thinking jest nieużywalny na Pi**: 39–183 s na krótką odpowiedź (a na HEF 4.78 tok/s będzie
   gorzej). Myślenie musi iść na CPU 7B/PC, nie na NPU.
5. Pozostałe błędy to **rozróżnianie narzędzi**: `man_page` vs `cmd_help`, `system_task` vs
   `run_command`, `ask_user` vs `remember`, `run_skill`/`knowledge_stats`/`npu_status` → „brak".

### 12.2 Implikacje dla planu (rewizja hipotezy)
- Hipoteza „lepszy model → optymalizacja" **sprawdza się dla promptu/konfiguracji**, ale **nie**
  dla samego tool-callingu w tym starciu: `qwen2.5:3b` (3B) jest lepszym narzędziowcem niż
  `qwen3:1.7b` (1.7B). Rozmiar tu wygrywa.
- **Wniosek architektoniczny**: „switch po przeznaczeniu" — ale narzędzia zostają na
  `qwen2.5:3b`/`7b`, a Qwen3-1.7B ewentualnie do **rozumowania/planowania** (thinking, CPU/PC).
- **Upgrade HailoRT + HEF Qwen3-1.7B nie jest (na razie) uzasadniony** dla tool-callingu:
  nawet na CPU jest poniżej obecnego 3B, a kwantyzacja A8W4 tylko to pogorszy.
- Hailo ma sens głównie dla **STT** (i ewentualnie odciążenia w przyszłości, jeśli zaakceptujemy
  niższą celność narzędzi).

### 12.3 Następne eksperymenty (jeśli brniemy dalej z Qwen3)
1. `/no_think` w system prompcie zamiast flagi (usuwa artefakt argumentów).
2. Prompt + **per-tool few-shot** (wzorce dla `man_page` vs `cmd_help`, `ask_user`, `run_skill`).
3. `k=3` i/lub obniżony próg retrieval.
4. Ewentualnie **specjalista**: `Qwen2-1.5B-Instruct-Function-Calling` HEF (>5.2.0).
5. Zmierzyć, czy Qwen3-1.7B **thinking** (CPU) bije 7B w planowaniu — bo tam jego wartość.

---

## 13. WYNIKI FAZ C/D/E + DECYZJA ARCHITEKTONICZNA (2026-09-19)
> Zrealizowane: Faza A ✔, **Faza C ✔**, **Faza D ✔** (destylacja+LoRA), **Faza E ✔** (poniżej).
> **Faza B (upgrade HailoRT 5.1.1→5.4) ŚWIADOMIE POMINIĘTA** (decyzja użytkownika) — bez zmian HEF.

### 13.1 Faza C — optymalizacja tokenowa (pomiar, `e6_gate.py --holdout`, CPU, 21 parafraz)
Wariant „lean" = krótki prompt tool-first + `/no_think` **w prompcie** + `--few-shot 1`.

| Wariant (qwen2.5:3b) | tools | czas | Wniosek |
|---|---|---|---|
| pełny: SYSTEM_PROMPT + wszystkie narzędzia + few-shot 0 | **17/21** | 299 s | baseline |
| pełny + few-shot 2 | **20/21** | 1901 s | jakość |
| **lean + wszystkie narzędzia** (`--lean --max-tools 0`) | **20/21** | 1804 s | ✔ krótszy prompt nie szkodzi |
| lean + `--max-tools 6` (narzędzia per pytanie) | **11/21** | 578 s | ✖ selektor gubi narzędzie |
| lean + `--max-tools 6` (qwen3:1.7b) | 9/21 | — | ✖ jw. |

**Kluczowy wniosek:** sprawcą regresji nie jest prompt, tylko **dobór narzędzi**
(`registry.select_names`, `TOOL_HINTS`). Na parafrazach held-out selektor nie wrzuca właściwego
narzędzia do kandydatów (np. „Utwórz plik notatka.txt…" → brak `write_file`; „Zapisz w pamięci…" →
brak `remember`; „Wyślij podręcznik rsync" → brak `man_page`), więc model **nie może** go wywołać.
- Rekomendacja: **podnieść `MAX_TOOLS`** (użyć pełnej/poszerzonej puli) albo **naprawić recall
  selektora** (dodać `TOOL_HINTS` dla `write_file`/`remember`/`man_page`/`check_script`/`run_script`/
  `web_fetch`/`search_knowledge`). Samo skrócenie promptu jest bezpieczne (20/21 przy 0 kosztu).

### 13.2 Faza D — destylacja PL → QLoRA Qwen3-1.7B (na PC, RTX 4060)
- **Nauczyciel**: `Bielik-11B-v3.0-instruct` (Q4_K_M) na PC (GPU) przez tunel Ollama; `cloud_teacher`
  (`--guided`, `--expand 2`), 415 wywołań, ~841k tokenów (0 zł, lokalnie).
- **Dane**: `datasets/astro_{train,val}.jsonl` = **219 / 24** (było 76/8); 195 z `tools`, 82 nowe trajektorie.
- **Trening** (`scripts/train_lora_pc.py`, unsloth): `unsloth/Qwen3-1.7B`, QLoRA 4-bit r=16, 3 epoki,
  84 kroki, ~970 s, `train_loss 0.43` → ~0.17; seq 4096. (`--merge` + `--gguf q4_k_m` ręcznie —
  unsloth przerwał na nadpisaniu read-only `model.safetensors`, dokończone `convert_hf_to_gguf.py` +
  `llama-quantize`.)
- **Model na Pi**: `models/lora/astro-qwen3-q4km.gguf` (1,1 GB) → `ollama create astro-qwen3-lora`.
- **Walidacja held-out (`e6_gate --holdout`, CPU)**:
  | Model / warunek | tools |
  |---|---|
  | `qwen3:1.7b` baza + SYSTEM_PROMPT (Faza A) | 2/21 |
  | `qwen3:1.7b` baza + tool-first (Faza A) | 14/21 |
  | **`astro-qwen3-lora`** + SYSTEM_PROMPT (po destylacji) | **15/21** |
  | `qwen2.5:3b` baseline (runtime) | 17/21 |
- Bramka `chain`/`chat` dla LoRA: nie uruchomiono (kategoria tools poniżej progu) — `--few-shot 2` na
  LoRA przerwano czasowo (zbyt wolne na CPU), co nie zmienia decyzji (tools 15/21 < 17/21).
- **Wniosek**: destylacja działa (+13 vs baza ASTRO-prompt), ale **1.7B LoRA nadal < `qwen2.5:3b`**
  (15 vs 17) i < few-shot 20/21. **NIE promujemy** modelu.

### 13.3 Faza E — DECYZJA ARCHITEKTONICZNA
**Wybór: (a) HYBRYDA — „routing po przeznaczeniu"** (rozszerzenie istniejącego `POLICY`), a nie
PC-live jako domyślny backend ani Qwen3 jako główny model:

| Rola | Backend / model | Uzasadnienie |
|---|---|---|
| Narzędzia / tool-calling | **CPU `qwen2.5:3b`** (+ few-shot 2) | 20/21; LoRA 1.7B 15/21, baza 2/21 |
| Czat / polszczyzna | **CPU `qwen2.5:7b`** | jakość PL; NPU 1.5B słaby |
| Rozumowanie / trudne | **PC `Bielik-11B` opt-in** (`ASTRO_PC=1`) | ~25 tok/s, najlepszy PL |
| STT | **NPU Whisper-Base** | 0,44 s / ~2 % CPU |
| Wiedza prosta | **fast-path offline** | 0 tokenów |

**Uzasadnienie wyboru (a)**: (1) narzędzia na 3B są dziś najlepsze i lokalne; (2) 7B daje jakość
polszczyzny bez PC; (3) NPU jest realnie wartościowy tylko dla STT (A8W4 pogorszyłby tool-calling,
a HEF wymaga upgrade'u HailoRT = Faza B, pominięta); (4) PC/Bielik jako **opt-in** daje najwyższą
jakość, gdy jest dostępny, bez uzależnienia runtime.
**Odrzucone na teraz**: (b) PC-live domyślnie (zależność od dostępności PC + prywatność),
(c) sam CPU 7B do narzędzi (wolny, 2 tok/s) i promocja `astro-qwen3-lora` (poniżej progu bramki).

**Warunki promocji modelu (bramka `e6_gate`)** — bez spełnienia nie promujemy:
`tools ≥ max(qwen2.5:3b, 17/21)` **i** brak regresji `chain`/`chat`; docelowo `≥ 20/21`.
`astro-qwen3-lora` (15/21) **nie przechodzi**.

### 13.4 Następne kroki (po decyzji)
1. **Naprawić recall selektora narzędzi** (Faza C) — to najtańszy zysk w runtime; potem zmierzyć lean.
2. Zwiększyć dane destylacji (więcej parafraz, `--expand`, k=3) i **ponowić trening**; bramka jak wyżej.
3. Ewentualnie większa baza do destylacji (Qwen2.5-3B LoRA) — skoro 3B wygrywa rozmiarem.
4. Faza B (HailoRT) dopiero gdy 1.7B zacznie wygrywać na CPU — inaczej HEF tylko pogorszy (A8W4).

