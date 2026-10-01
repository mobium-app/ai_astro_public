# ASTRO — Mobility M0/M1: REST backend dla apki Astro Mobilne

Moduł `mobility/` w repo ASTRO: lekki backend REST, przez który telefon (apka Flutter,
projekt `astro-mobilne`) gada z Astro i synchronizuje pamięć. Zasada: **Pi = jedyne
źródło prawdy** (pamięć, wiedza, destylacja), telefon = lustro + agent offline-first.

## Endpointy

| Metoda | Ścieżka | Co robi |
|---|---|---|
| GET | `/health` | status, wersja, liczniki, `server_version` (bez autoryzacji — health-check) |
| GET | `/context?since=&limit=&knowledge=&kdelta=` | **delta** rekordów z telefonu + delta wiedzy |
| POST | `/episodes`, `/lessons`, `/plans` | push rekordu pamięci (telefon → Pi) |
| POST | `/remember` | notatka/przypomnienie |
| GET | `/remember?due=1` | przypomnienia due (konsumpcja w apce) |
| GET | `/knowledge?since=&limit=` | paczka wiedzy (ręczne wgranie na telefon) |
| POST | `/chat` | proxy do agenta (backend CPU/NPU/PC/remote) + persona Astro |

`since` = ostatnia znana wersja (delta rekordów). `knowledge=0` wyłącza wiedzę
(domyślnie włączona). `kdelta` = ostatni znany `id` wpisu wiedzy.

## Autoryzacja

Token **sha256** (wzorzec z API v1):

* `secrets/mobility.token` — digest trzymany przez serwer,
* `secrets/mobility.secret` — sekret wysyłany przez klienta jako `Authorization: Bearer <sekret>`,
* porównanie `hmac.compare_digest`, oba pliki `600`, katalog `secrets/` **poza repo** (`.gitignore`).

Generowanie + instalacja usługi:

```bash
bash scripts/install_mobility.sh --with-token   # sekret+digest, unit, enable+restart
```

Serwer wiąże się **wyłącznie na adresie Tailscale** (`tailscale ip -4`, fallback
`127.0.0.1`), więc REST nie wystawia się w LAN. `tailscale up` musi być zrobione
na Pi (wymaga konta właściciela) — bez tego telefon nie połączy się przez VLAN.

## Wersjonowanie i konflikty (LWW)

* `version` — monotoniczny licznik **serwera**; to on napędza deltę `?since=`.
* `client_version` — wersja rekordu **z telefonu** (pole `version` w JSON-ie treści);
  to ona rozstrzyga konflikt: wygrywa wyższa, przy remisie nowszy `updated_at`.
* Rozdzielenie tych dwóch liczników jest celowe — porównywanie ich ze sobą odrzucało
  świeższe pushy z telefonu, gdy licznik serwera zdążył urosnąć.

## Wiedza (`knowledge.py`)

Eksport tabeli `learned` (16 578 wpisów → ~16 577 po odsianiu, ~7,7 MB JSON) jako
`{id, q, a, topic, source}`. Zasady:

* **bez wektorów** — embeddingi zostają na Pi, telefon liczy retrieval lokalnie,
* **odpowiedzi ucięte** (kończące się `…`) pomijane — telefon nie ma narzędzi do czyszczenia,
* `delta(since)` po `id` — koszt rzędu milisekund (indeks po `id`).

## Testy

`tests/test_mobility.py` (16 testów, `unittest` — wliczane przez `tests/run_tests.py`):
autoryzacja, health, push/pull delta, LWW (w tym odrzucenie starszej wersji), remember/due,
walidacja i proxy chatu (mock backendu), eksport wiedzy (mini baza `learned`), brak bazy = pusta.

## Znane ograniczenia

* Flask dev-server (do wystawienia publicznego potrzebny WSGI, ale VLAN + token to wystarczająco),
* `knowledge_delta` nie ma jeszcze kompresji/wersjonowania po stronie klienta poza `id`,
* brak synchronizacji `reminders` z powrotem na Pi (dziś tylko push i odczyt due),
* brak endpointu `POST /token/rotate` (ROADMAP aplikacji).
