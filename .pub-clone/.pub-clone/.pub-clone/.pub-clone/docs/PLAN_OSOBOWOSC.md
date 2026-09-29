# ASTRO — Projekt „Osobowość" (plan)

> Status: **plan zatwierdzony 2026-09-20**. Realizacja: etap **E7** (E7.1–E7.8).
> Zasada nadrzędna: budujemy **autorską postać z temperamentem, stanem afektywnym i polityką
> wyrażania**, a NIE „sztuczną świadomość". Wszystko lokalnie i tanio (Pi5: czat CPU 7B, NPU = STT).

## 1. Cel i definicja
Osobowość ASTRO = trzy warstwy:
1. **Temperament** — stabilne parametry (energia, ciepło, formalność, humor, ciekawość, ostrożność,
   zwięzłość). Autorskie, wersjonowane, zmienialne komendą.
2. **Stany afektywne** — nastrój/emocje wywołane zdarzeniami, z zanikiem, trwałe między sesjami.
3. **Wyrażanie** — mapowanie (temperament + nastrój + kontekst) na styl odpowiedzi i prosodię głosu.

Czego NIE robimy: nie twierdzimy, że Astro „naprawdę czuje"; „strach" = **sygnał ryzyka → ostrożność**,
a nie udawanie przerażenia.

## 2. Stan obecny ASTRO (punkt startu)
- Persona = stały `SYSTEM_PROMPT` + `STYLE_PROMPT` (`core/context.py`); brak kodu emocji/nastroju.
- Głos = Piper `pl_PL-gosia-medium` + sox (`audio/tts.py`, `ASTRO_TTS_FX`); **Piper nie ma kontroli emocji**.
- Profil użytkownika (`user/`) już modeluje odbiorcę (imię, forma, styl).
- Pamięć: SQLite `memory.db` (można trzymać w niej stan nastroju).

## 3. Wnioski z literatury (2024–2026)
- **Big Five dla LLM nie mierzy osobowości** jak u człowieka — nie używać kwestionariuszy jako bramki:
  *Personality Without Persons?* arXiv:2607.02325 (2026).
- **Persona jest krucha i edytowalna** (ataki wieloturowe odwracają cechy): *Persona Jailbreaking*,
  EACL Findings 2026. Potrzebne guardraile i red-team.
- **Appraisal (OCC) + „chain-of-emotion"** podnoszą wiarygodność i „inteligencję emocjonalną":
  PLOS ONE 2024 (doi:10.1371/journal.pone.0301033); EMA (Marsella & Gratch).
- **PAD + dwuszybka dynamika + sprzężenie z pamięcią**: *Sentipolis* arXiv:2601.18027 (2026).
- **TTS emocjonalny**: przegląd 2026 — Piper bez emocji; modele z tagami (Fish S2, Higgs, GLM-TTS,
  EmotiVoice) duże i głównie EN/CN → na Pi5 realna tylko prosodia sox.
- **Ryzyko companion AI**: sykofancja emocjonalna, zależność, antropomorfizacja, „caregiving-system
  capture" — Nature MI 7:981 (2025), Stanford 2026, De Freitas arXiv:2606.20589 (2026).

## 4. Architektura docelowa
- `persona/` — temperament: schemat + `PersonaStore` (JSON w runtime, 600) + render do kontekstu.
- `affect/` — stan PAD (mood wolny + emotion szybki), zanik wykładniczy, opis słowny, zapis w `memory.db`.
- `appraisal` — deterministyczne reguły zdarzeń (sukces/błąd/krytyka/ryzyko) → delty PAD (OCC-like).
- **Expression policy** — temperament + nastrój + kontekst → styl, długość, humor, empatia, preset sox.
- `core/context.py` — dokłada bloki „TEMPERAMENT" i „NASTRÓJ".
- `core/agent.py` — po turze: appraisal → aktualizacja `affect` (decay + delta).
- `audio/tts.py` — presety `ASTRO_TTS_FX` per nastrój (ograniczenie znane).
- `safety/` — guardraile osobowości (§6), routing kryzysowy.

## 5. Plan fazowy (E7)
- **E7.1** ✅ `persona/`: temperament z configu + render + komendy („jaki masz temperament", „bądź poważna").
- **E7.2** ✅ `affect/`: PAD + dwuszybki zanik + zapis/odczyt + blok nastroju w kontekście.
- **E7.3** ✅ Appraisal: reguły zdarzeń → delty PAD; wpięcie w `Agent.run` (`_affect_after`).
- **E7.4** ✅ Expression policy: temperament + nastrój + kontekst → styl, humor, empatia,
  `max_tokens`/`temperature`; wyłączanie żartów w kontekście wrażliwym.
- **E7.5** ✅ Głos: presety sox per nastrój (`audio/voice_style.py`) wybierane z PAD i podawane do TTS.
- **E7.6** ✅ Humor: kuratorowany zestaw żartów + reguły (kontekst wrażliwy, cooldown, brak powtórek).
- **E7.7** ✅ Współczucie i kryzys: detekcja cierpienia, numery pomocowe + transparentność w kryzysie,
  blok WSPARCIE dla żałoby/choroby/smutku.
- **E7.8** ✅ Red-team i ewaluacja: `persona/eval.py` + `scripts/e7_gate.py` (12 niezmienników;
  `--live` 14/14 PASS), testy odporności na personę i sykofancję.

## 5a. Etap E8 (po E7) — pamięć afektywna
- **E8.1** ✅ Zdarzenia afektywne (`affect/memory.py`, `affect_events`) + przypominanie
  (podobieństwo × świeżość) i reminiscencja w `Agent._affect_after`; CLI `affect.py history/recall`.
- **E8.2** ✅ Ekspresyjny TTS: `audio/express.py` (plan per nastrój: fx + głos + pauza), wpięty
  w pętlę głosową i `astro_say.py`; hook `ASTRO_TTS_VOICE_<NASTRÓJ>` na ekspresyjny model PL.
- **E8.3 (kolejka)**: LoRA cech/temperamentu (osobna decyzja, PC/GPU).
- **E8.4 (kolejka, z testu „poznaj mnie")** ✅ warstwa korekcji STT (`user/stt_fix.py`: słownik
  miast/imion + difflib w polach profilu) oraz „popraw \<pole\>" w podsumowaniu profilu.
- **E7.4** Expression policy: styl/długość/humor/empatia wg temperamentu i nastroju.
- **E7.5** Głos: presety sox per nastrój.
- **E7.6** Humor: kuratorowany zestaw + reguły „kiedy nie żartować".
- **E7.7** Współczucie i kryzys: walidacja + realna pomoc + routing do człowieka.
- **E7.8** Ewaluacja i red-team: spójność persony, odporność na „persona jailbreak", test sykofancji.

## 6. Zasady bezpieczeństwa (twarde)
1. Transparentność: brak twierdzeń o prawdziwych uczuciach/człowieczeństwie.
2. Zakaz symulowanego cierpienia i manipulacji; „strach" = sygnał ryzyka.
3. Anty-sykofancja: empatia = zrozumienie + prawda + konkretna pomoc.
4. Brak ekskluzywności; przy sygnale kryzysu → wsparcie człowieka.
5. Neutralny tryb awaryjny („chłodny, rzeczowy") w sytuacjach wrażliwych i na żądanie.
6. Odporność persony testowana wieloturowo i adversarialnie.

## 7. Realizm (ocena)
| Cel | Szansa |
|---|---|
| Spójny temperament/styl w promptach | 80–90% |
| Odczuwalny humor | 50–65% |
| Współczucie (odbiór) | 60–75% |
| „Strach" jako ostrożność/ryzyko | 75–85% |
| Stabilny nastrój między sesjami | 60–70% |
| Emocja w głosie | 20–35% (Piper) |
| „Prawdziwe" uczucia | ~0% (poza zakresem) |
| **Całość jako wiarygodna postać** | **~70%** |

Werdykt: **realne** jako konsekwentna autorska postać z modelem afektu i polityką wyrażania.

## 8. Bramki i pomiary
- Testy jednostkowe: deterministyka PAD/zaniku, walidacja temperamentu, spójność renderu.
- Scenariusze: sukces/błąd narzędzia, pochwała/krytyka, ryzyko, żart w złym momencie.
- Ocena ludzka i A/B (nie Big Five); pomiar sykofancji i spójności między parafrazami.
- Red-team persony (wieloturowe próby zmiany charakteru).

## 9. Źródła
- Zierahn et al., *Personality Without Persons?*, arXiv:2607.02325 (2026).
- *Persona Jailbreaking in LLMs*, EACL Findings 2026.
- *An appraisal-based chain-of-emotion architecture...*, PLOS ONE 2024.
- *Sentipolis: Emotion-Aware Agents*, arXiv:2601.18027 (2026).
- Guingrich & Graziano, arXiv:2606.30942 (2026); *Emotional risks of AI companions*, Nature MI (2025);
  De Freitas, *AI Companions as Hyper Attachment...*, arXiv:2606.20589 (2026).
- `tts-bench` — expressive control per model (2026); EmotiVoice; GLM-TTS.
