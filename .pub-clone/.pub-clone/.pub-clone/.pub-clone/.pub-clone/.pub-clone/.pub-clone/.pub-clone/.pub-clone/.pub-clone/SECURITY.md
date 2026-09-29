# Security Policy

## Supported versions
Publiczne snapshoty (`public-*` tagi) wspierane są do następnego snapshotu.
Raporty o lukach przyjmowane dla najnowszej wersji.

## Reporting a vulnerability
Prosimy o **nie zgłaszanie luk w publicznych issue** (repo jest publiczne).

Zgłoś przez:
- **GitHub Security Advisory** („Report a vulnerability" w repo), albo
- prywatny fork z opisem problemu + minimalnym PoC.

W zgłoszeniu podaj:
- wersję/snapshot (`public-*` tag albo commit),
- opis podatności i wpływ,
- kroki reprodukcji (bez danych prywatnych),
- proponowaną poprawkę (opcjonalnie).

## Zasady dla zgłaszających
- Ujawnienie koordynowane: 30 dni na poprawkę przed publicznym opisem.
- Nie eksfiltruj danych: repo publiczne, ale nie zawiera danych prywatnych —
  nie próbuj omijać sanityzacji (zgłoś to jako lukę, nie exploit).

## Czego repo NIE zawiera
- Kluczy API, haseł, tokenów (`runtime/`, `/etc/astro-secrets/` są poza repo).
- Danych biometrycznych, nagrań, bazy wiedzy osobistej.
- IP/konfiguracji sieci prywatnej (zastąpione placeholderami).