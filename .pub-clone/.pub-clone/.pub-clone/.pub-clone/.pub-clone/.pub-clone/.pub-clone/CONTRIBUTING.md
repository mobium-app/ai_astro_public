# Contributing to ASTRO

Dziękujemy za zainteresowanie ulepszaniem ASTRO! Ten projekt powstał jako
samodzielny, uczący się agent — każda dobra zmiana przyspiesza jego rozwój.

Więcej o projekcie: **[netrunner.edu.pl/projekt-astro](https://netrunner.edu.pl/projekt-astro)**

## Jak zacząć
1. Zforkuj repo i sklonuj swoją kopię.
2. Zainstaluj zależności: `pip install -r requirements.txt`.
3. Uruchom testy: `python3 tests/run_tests.py` (hermetyczne, bez sprzętu —
   testy NPU/kamery automatycznie przechodzą w tryb symulacji przy `ASTRO_CI=1`).
4. Utwórz branch: `git checkout -b feature/cool-thing`.

## Zasady
- **Jakość przed tempem.** Każda zmiana musi mieć testy (stdlib `unittest`).
- **Brak danych prywatnych.** Repo jest publiczne — nie commituj kluczy API,
  haseł, IP sieci lokalnej ani danych osobowych. Wzorce konfiguracji → pliki `*.example`.
- **Hermetyczność testów.** Testy nie mogą wymagać NPU, kamery, mikrofonu ani sieci.
- **Język komentarzy/commitów:** angielski (komunikaty commitów), polski dozwolony
  w treści promptów/głosu (projekt jest dwujęzyczny z naciskiem na PL).

## Co jest mile widziane
- Nowe narzędzia (`tools/`) i komendy must-have (`data/commands/`).
- Poprawki STT/TTS (Vosk/Whisper/Piper) — mowa to ~90% UX.
- Trening/destylacja LoRA (playbook: `scripts/train_book.py`).
- Dokumentacja i przykłady konfiguracji.

## Proces
1. Upewnij się, że `python3 tests/run_tests.py` przechodzi lokalnie.
2. Otwórz PR z opisem: co zmienia, dlaczego, jak przetestowano.
3. Maintainer (AI-assisted) analizuje zmiany, adaptuje do prywatnego rdzenia
   i testuje na realnym sprzęcie przed merge.

## Licencja
MIT — patrz `LICENSE`.