"""Wsparcie zdalne ASTRO: łańcuch dostawców OpenAI-compatible (ostatnia deska ratunku).

Kolejność (decyzja użytkownika, 2026-09-23; OpenCode zostaje awaryjnie na KOŃCU):
    0) PC-Kali (bielik-11b, przez tunel) - PIERWSZY: lokalny nauczyciel bez limitów, uczy od razu
    1) Gemini (3 konta) - dzienny limit
    2) Groq (3 konta) - TPM/RPD; model gpt-oss-120b (Groq NIE hostuje DeepSeek)
    3) OpenRouter - model = **DeepSeek v4.1 Flash** (promocja x4)
    4) HuggingFace - model = **DeepSeek v4.1 Flash**
    5) DeepSeek (direct) - obecnie saldo 0 (402)
    6) Grok - obecnie 403 (brak uprawnień)
    7) OpenCode - ostateczne, płatne źródło awaryjne

Gdy PC-Kali jest offline (`_pc_online`), jest szybko pomijany i łańcuch idzie do darmowych chmur.

Model wybieramy u dostawcy tam, gdzie to możliwe (`SPEC`): DeepSeek v4.1 Flash na OpenRouter
i HuggingFace; nadpisywalne `ASTRO_OPENROUTER_MODEL` / `ASTRO_HF_MODEL`.

Zasady:
  * remote wolno użyć **tylko w ostateczności** i tylko do pytań o logikę/wiedzę —
    NIGDY do zleceń komend (model zdalny halucynuje wykonanie);
  * odpowiedź zdalna jest od razu zapisywana do `learned` (`learn_from_remote`), więc kolejne
    pytanie ASTRO obsłuży offline (`Memory.best_learned`);
  * klucze czytamy z pliku `ASTRO_API_FILE` (domyślnie `/etc/astro-secrets/API`), NIE z konfiguracji
    Ateny. Kluczy nie logujemy; zużycie tokenów trafia do `logs/remote_usage.jsonl`.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass

from . import config

UA = "ASTRO/1.0 (+agent; Raspberry Pi)"


@dataclass
class Provider:
    label: str
    url: str
    model: str
    key: str = ""
    timeout: int = 120
    headers: dict = None
    account: str = ""

    def endpoint(self):
        return self.url.rstrip("/") + "/chat/completions"

    def ready(self):
        return bool(self.url and self.model)

    def name(self):
        return self.account or self.label


# Źródła zdalne używane PRZED PC (kolejność tokenów).
SPEC = {
    "deepseek": ("https://api.deepseek.com/v1",
                 os.environ.get("ASTRO_DEEPSEEK_MODEL", "deepseek-chat")),
    "grok": ("https://api.x.ai/v1",
             os.environ.get("ASTRO_GROK_MODEL", "grok-4")),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai",
               os.environ.get("ASTRO_GEMINI_MODEL", "gemini-3.6-flash")),
    # Groq (przez „q") = szybki inference dla modeli otwartych (OpenAI-compatible). Nazwa myląca
    # z Grok (xAI) — to INNY dostawca. Klucz: gsk_...
    # Groq NIE hostuje DeepSeek — zostaje najlepszy dostępny (gpt-oss-120b).
    "groq": ("https://api.groq.com/openai/v1",
             os.environ.get("ASTRO_GROQ_MODEL", "openai/gpt-oss-120b")),
    # OpenRouter: DeepSeek v4.1 Flash (promocja x4) — model wybieramy u dostawcy.
    "openrouter": ("https://openrouter.ai/api/v1",
                   os.environ.get("ASTRO_OPENROUTER_MODEL", "deepseek/deepseek-v4.1-flash")),
    # Hugging Face („happyface") Router = OpenAI-compatible proxy do wielu providerów. Token: hf_...
    "huggingface": ("https://router.huggingface.co/v1",
                    os.environ.get("ASTRO_HF_MODEL", "deepseek-ai/DeepSeek-V4.1-Flash")),
}
PRIMARY_ORDER = ["deepseek", "grok", "gemini", "groq", "openrouter", "huggingface"]
# Dostawcy CHWILOWO nieczynni (deepseek: saldo 0 → 402; grok: 403). Przeniesieni na koniec,
# ZA PC, by nie tracić ~1 s na odrzucenie przed aktywnymi źródłami. Po naprawie — do ACTIVE.
DORMANT_ORDER = ["deepseek", "grok"]
ACTIVE_ORDER = [name for name in PRIMARY_ORDER if name not in DORMANT_ORDER]
OPENCODE = ("https://opencode.ai/zen/go/v1",
            os.environ.get("ASTRO_OPENCODE_MODEL", "deepseek-v4.1-flash"))
# Modele DARMOWE OC Go dla trybu „premium" (eksperyment small-talk 2026-10-03), w kolejności
# od najlepszego: space-bunny-free → longcat-2.5-preview-free → mimo-v2.6-flash-free (zapas).
# Nadpisywalne `ASTRO_OPENCODE_MODELS="m1,m2,m3"`. Gdy model niedostępny, chain idzie dalej.
OPENCODE_FREE_MODELS = [m.strip() for m in os.environ.get(
    "ASTRO_OPENCODE_MODELS",
    "space-bunny-free,longcat-2.5-preview-free,mimo-v2.6-flash-free",
).split(",") if m.strip()]

# Cennik modeli OC Go (USD za 1M tokenów; źródło: docs opencode.ai/go, 2026-10-03).
# Modele free = 0. Wartości płatnych: konserwatywnie (DeepSeek peak); cache pomijany (mały wpływ).
GO_PRICES = {
    "deepseek-v4.1-flash": (0.30, 1.20), "deepseek-v4-flash": (0.30, 1.20),
    "deepseek-v4-pro": (1.32, 3.96), "deepseek-v4-flash-vision-exp": (0.30, 1.20),
    "mimo-v2.6-flash": (0.14, 0.28), "mimo-v2.6-pro": (0.435, 0.87),
    "mimo-v2.5": (0.14, 0.28), "mimo-v2.5-pro": (0.435, 0.87),
    "glm-5.3": (1.40, 4.40), "glm-5.3-flash": (0.15, 0.50), "glm-5.2": (1.40, 4.40),
    "kimi-k3": (3.00, 15.00), "kimi-k2.7-code": (0.95, 4.00), "kimi-k2.6": (0.95, 4.00),
    "longcat-2.0": (0.30, 1.20), "minimax-m3": (0.30, 1.20), "minimax-m2.7": (0.30, 1.20),
    "qwen3.8-max": (2.00, 6.00), "qwen3.8-flash": (0.15, 0.47), "qwen3.7-plus": (0.40, 1.60),
    "grok-4.7": (2.00, 6.00), "grok-4.6": (2.00, 6.00),
    "gpt-6-luna": (0.10, 0.50), "gpt-5.6-luna": (0.20, 1.20),
    "hy3": (0.14, 0.58), "hy4-preview": (0.834, 2.501),
    "muse-spark-1.3-contributor": (0.10, 0.20), "muse-spark-1.2-contributor": (0.10, 0.20),
}
# Modele darmowe OC Go (unlimited, limited-time) — koszt 0.
FREE_MODELS = set(OPENCODE_FREE_MODELS) | {"space-bunny-free", "longcat-2.5-preview-free"}


def is_free_model(model):
    return (model in FREE_MODELS) or ("-free" in (model or ""))


def estimate_usd(model, prompt_tokens, completion_tokens):
    """Szacunkowy koszt USD (0 dla free/nieznanych jako free-nie; patrz GO_PRICES)."""
    if is_free_model(model):
        return 0.0
    pin, pout = GO_PRICES.get(model, (0.0, 0.0))
    return round(pin * prompt_tokens / 1e6 + pout * completion_tokens / 1e6, 6)


def opencode_session_id():
    """Stały identyfikator sesji OpenCode (utrwalony) — kontekst bez zrywania między turami.

    Bramka OC Go wymaga `x-opencode-session` (bez niego 400 MissingSessionID); stała wartość
    daje ciągłość routingu i cache'u prefiksu między turami i restartami usługi
    (do wyłączenia urządzenia). Plik: `runtime/opencode_session.json`.
    """
    path = config.RUNTIME_DIR / "opencode_session.json"
    sid = ""
    try:
        with open(path, encoding="utf-8") as fh:
            sid = (json.load(fh) or {}).get("session", "")
    except Exception:
        sid = ""
    if not sid:
        sid = str(uuid.uuid4())
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"session": sid, "created": time.time()}, fh)
        except Exception:
            pass
    return sid

_ALIASES = {
    "opencode": "opencode", "open code": "opencode", "astro": "opencode",
    "deepseek": "deepseek", "gemini": "gemini", "grok": "grok",
    "groq": "groq", "openrouter": "openrouter",
    "huggingface": "huggingface", "hugging face": "huggingface", "happyface": "huggingface",
    "hugging_face": "huggingface", "hf": "huggingface",
}


def parse_api_file(path):
    """`/etc/astro-secrets/API` -> {provider: [klucze w kolejności kont]} (bez logowania)."""
    keys = {name: [] for name in PRIMARY_ORDER + ["opencode"]}
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        return keys
    current = None
    for line in lines:
        m = re.search(r"Key:\s*(\S+)", line, re.I)
        if m:
            value = m.group(1).strip()
            if current and value and not value.startswith(("-", "[", "$")):
                keys.setdefault(current, []).append(value)
            continue
        low = line.lower()
        for alias, name in _ALIASES.items():
            if alias in low:
                current = name
                break
    return {k: v for k, v in keys.items() if v}


def _env_keys():
    out = {}
    for label, env in (("opencode", "ASTRO_OPENCODE_KEY"), ("deepseek", "ASTRO_DEEPSEEK_KEY"),
                       ("grok", "ASTRO_GROK_KEY"), ("gemini", "ASTRO_GEMINI_KEY"),
                       ("groq", "ASTRO_GROQ_KEY"), ("openrouter", "ASTRO_OPENROUTER_KEY"),
                       ("huggingface", "ASTRO_HF_KEY")):
        value = os.environ.get(env, "").strip()
        if value:
            out.setdefault(label, []).append(value)
    return out


def load_keys(path=None):
    path = path or config.API_FILE
    keys = parse_api_file(path)
    for label, values in _env_keys().items():
        keys.setdefault(label, [])
        for value in values:
            if value not in keys[label]:
                keys[label].insert(0, value)
    return keys


def _providers(names, keys):
    out = []
    for name in names:
        url, model = SPEC[name]
        for i, key in enumerate(keys.get(name, []), 1):
            out.append(Provider(name, url, model, key, timeout=config.REMOTE_TIMEOUT,
                                account=f"{name}#{i}"))
    return out


def provider_chain(path=None, include_pc=True):
    """PC-Kali -> Gemini -> Groq -> OpenRouter -> HuggingFace -> [DeepSeek, Grok] -> OpenCode.

    PC-Kali (bielik-11b przez tunel) jest PIERWSZY (decyzja użytkownika, 2026-09-23): lokalny
    nauczyciel bez limitów odpowiada i uczy od razu; gdy offline, `_pc_online` szybko go pomija
    i łańcuch idzie do darmowych chmur. Nieczynne DeepSeek (saldo 0) i Grok (403) tuż przed
    OpenCode (płatne, zawsze ostatni). DeepSeek v4.1 Flash jako MODEL u OpenRouter i HuggingFace.
    """
    keys = load_keys(path)
    chain = []
    if include_pc and config.PC_URL:
        chain.append(Provider("pc", config.PC_URL.rstrip("/") + "/v1", config.PC_MODEL,
                              timeout=config.REMOTE_TIMEOUT, account="pc"))
    chain += _providers(ACTIVE_ORDER, keys)
    chain += _providers(DORMANT_ORDER, keys)          # nieczynne tuż przed OpenCode
    url, model = OPENCODE
    for i, key in enumerate(keys.get("opencode", []), 1):
        chain.append(Provider("opencode", url, model, key, timeout=config.REMOTE_TIMEOUT,
                              headers={"x-opencode-session": opencode_session_id()},
                              account=f"opencode#{i}"))
    return chain


def opencode_chain(path=None):
    """Łańcuch WYŁĄCZNIE OpenCode Go (tryb „premium") — darmowe modele small-talk w kolejności.

    Kolejność modeli: `OPENCODE_FREE_MODELS` (space-bunny → longcat → mimo-zapas), każdy model
    × wszystkie konta z API.txt. Wszystkie wpisy niosą STAŁY `x-opencode-session`
    (`opencode_session_id`) — kontekst i cache prefiksu nie zrywają się między turami.
    Lokalny fallback (PC/CPU) dokłada rejestr backendów, więc ten łańcuch nie zawiera PC
    ani darmowych chmur. Gdy model chwilowo niedostępny (400), `RemoteChainBackend` schodzi niżej."""
    keys = load_keys(path)
    url, _legacy = OPENCODE
    sid = opencode_session_id()
    models = OPENCODE_FREE_MODELS or [_legacy]
    return [Provider("opencode", url, model, key, timeout=config.REMOTE_TIMEOUT,
                     headers={"x-opencode-session": sid}, account=f"opencode#{i}")
            for model in models
            for i, key in enumerate(keys.get("opencode", []), 1)]


def available():
    return bool(provider_chain(include_pc=False)) and config.REMOTE_ENABLED


_PC_CACHE = {"ts": 0.0, "ok": False}


def _pc_base(url):
    """Baza Ollamy na PC: zdejmuje końcowe `/v1` (API OpenAI-compatible dokleja je samo)."""
    base = (url or "").rstrip("/")
    return base[:-3] if base.endswith("/v1") else base


def _pc_online(url, ttl=30):
    """Szybki test, czy PC (Ollama przez tunel) odpowiada - by pominąć je offline."""
    now = time.time()
    if now - _PC_CACHE["ts"] < ttl:
        return _PC_CACHE["ok"]
    ok = False
    try:
        req = urllib.request.Request(_pc_base(url) + "/api/tags", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=3) as r:
            ok = r.status == 200
    except Exception:
        ok = False
    _PC_CACHE.update(ts=now, ok=ok)
    return ok


def warm_pc(model=None, keep_alive=None, timeout=180):
    """Ładuje model nauczyciela na PC-Kali (Ollama) i trzyma go w RAM (`keep_alive`).

    `/api/generate` z pustym promptem tylko wczytuje model, więc pierwsze pytanie nie płaci
    zimnego startu (11B = kilka-kilkanaście s). Zwraca True, gdy PC odpowiedziało."""
    if not config.PC_URL:
        return False
    payload = {"model": model or config.PC_MODEL,
               "keep_alive": keep_alive or getattr(config, "PC_KEEP_ALIVE", "30m"),
               "prompt": ""}
    req = urllib.request.Request(
        _pc_base(config.PC_URL) + "/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": UA},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _post_full(provider, payload, path=None):
    """Jak `_post`, ale zwraca (data, headers) — nagłówki niosą limity rate-limit."""
    url = (provider.url.rstrip("/") + (path or "/chat/completions"))
    headers = {"Content-Type": "application/json", "User-Agent": UA}
    if provider.key:
        headers["Authorization"] = f"Bearer {provider.key}"
    if provider.headers:
        headers.update(provider.headers)
    if "openrouter" in provider.url:
        headers["HTTP-Referer"] = "https://opencode.ai"
        headers["X-Title"] = "ASTRO"
    # OpenCode Go wymaga nagłówka `x-opencode-session` — bez niego zwraca 400 (MissingSessionID).
    # Uzupełniamy OBROBNIE, gdyby provider powstał poza `opencode_chain`/`provider_chain`
    # (np. z JSON/CLI), żeby żadna ścieżka nie generowała „Bad Request".
    _ensure_opencode_session(provider, headers)
    data = json.dumps(payload).encode("utf-8")

    def _send(hdrs):
        req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
        with urllib.request.urlopen(req, timeout=provider.timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace")), dict(r.headers)

    try:
        return _send(headers)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300].replace("\n", " ")
        # Serwer odrzucił brak/nieświeżą sesję OpenCode — ustaw nagłówek i ponów RAZ.
        if e.code == 400 and "session" in body.lower() and "opencode" in provider.url.lower():
            headers["x-opencode-session"] = str(uuid.uuid4())
            try:
                return _send(headers)
            except urllib.error.HTTPError as e2:
                body = e2.read().decode("utf-8", "replace")[:300].replace("\n", " ")
                raise RuntimeError(f"HTTP {e2.code}: {body}")
        raise RuntimeError(f"HTTP {e.code}: {body}")
    except Exception as e:
        raise RuntimeError(str(e))


def _ensure_opencode_session(provider, headers):
    """Gwarantuje `x-opencode-session` dla OpenCode, jeśli provider go nie niesie."""
    if "opencode" not in (provider.url or "").lower():
        return
    low = {k.lower() for k in headers}
    if "x-opencode-session" not in low:
        headers["x-opencode-session"] = opencode_session_id()


def _post(provider, payload, path=None):
    return _post_full(provider, payload, path)[0]


# Nagłówki rate-limit (nazwy są różne u dostawców); zwracamy tylko te obecne.
_RATE_KEYS = (
    "x-ratelimit-limit-requests", "x-ratelimit-remaining-requests",
    "x-ratelimit-limit-tokens", "x-ratelimit-remaining-tokens",
    "x-ratelimit-reset-requests", "x-ratelimit-reset-tokens",
    "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset",
    "retry-after", "x-request-id",
)


def probe_limits(provider):
    """Minimalne wywołanie (1 token) -> słownik nagłówków rate-limit (albo {})."""
    payload = {"model": provider.model,
               "messages": [{"role": "user", "content": "ok"}],
               "max_tokens": 1, "stream": False}
    try:
        _data, headers = _post_full(provider, payload)
    except Exception:
        return {}
    low = {k.lower(): v for k, v in headers.items()}
    return {k: low[k] for k in _RATE_KEYS if k in low}


def _get(url, key="", timeout=10):
    headers = {"User-Agent": UA}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:150].replace("\n", " ")
        raise RuntimeError(f"HTTP {e.code}: {body}")
    except Exception as e:
        raise RuntimeError(str(e))


def _log_usage(provider, usage, kind=""):
    """Zapis zużycia (rozszerzony 2026-10-03): kind/free/est_usd dla raportów premium."""
    try:
        config.ensure_dirs()
        prompt = int((usage or {}).get("prompt_tokens") or 0)
        completion = int((usage or {}).get("completion_tokens") or 0)
        entry = {"ts": time.time(), "provider": provider.label, "account": provider.name(),
                 "model": provider.model, "prompt": prompt, "completion": completion,
                 "total": int((usage or {}).get("total_tokens") or 0),
                 "kind": kind or "", "free": is_free_model(provider.model),
                 "est_usd": estimate_usd(provider.model, prompt, completion)}
        with open(config.LOGS_DIR / "remote_usage.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def ask(messages, *, tools=None, fmt=None, temperature=0.2, max_tokens=600, timeout=None,
        chain=None, errors_out=None, kind=""):
    """Próbuje dostawców po kolei. Zwraca (text, label, usage) albo None gdy nikt nie odpowie.

    `errors_out` (opcjonalna lista) zbiera komunikaty błędów dostawców — do wykrywania
    wyczerpania limitów (429/402/quota) bez logowania kluczy. `kind` trafia do logu zużycia.
    """
    res = ask_full(messages, tools=tools, fmt=fmt, temperature=temperature, max_tokens=max_tokens,
                   timeout=timeout, chain=chain, errors_out=errors_out, kind=kind)
    if res is None:
        return None
    text, label, usage, _calls = res
    return text, label, usage


def ask_full(messages, *, tools=None, fmt=None, temperature=0.2, max_tokens=600, timeout=None,
             chain=None, errors_out=None, kind=""):
    """Jak `ask`, ale zwraca też `tool_calls`: (text, label, usage, tool_calls) albo None.

    Sukcesem jest również odpowiedź z samymi wywołaniami narzędzi (puste `content`) — bez tego
    backend zdalny (tryb premium/remote) gubiłby wywołania i „przeskakiwał" do kolejnego dostawcy.
    """
    errors = []
    for provider in (chain if chain is not None else provider_chain()):
        if not provider.ready():
            continue
        if provider.label == "pc" and not _pc_online(provider.url):
            errors.append("pc: offline")
            continue
        # Modele „thinking" (OpenCode, OpenRouter/DeepSeek v4.1 Flash, Gemini) zużywają tokeny
        # na reasoning — bez zapasu zwracają pustą treść. Daj bufor.
        budget = max_tokens
        if provider.label in ("opencode", "openrouter"):
            budget = max(max_tokens, 1600)
        elif provider.label in ("gemini", "grok", "groq", "huggingface"):
            budget = max(max_tokens, 1000)
        payload = {"model": provider.model, "messages": messages, "temperature": temperature,
                   "max_tokens": budget, "stream": False}
        if provider.label == "pc":
            # Ollama (przez tunel): trzymaj model w RAM, by kolejne pytania nie płaciły zimnego startu.
            payload["keep_alive"] = getattr(config, "PC_KEEP_ALIVE", "30m")
        if tools:
            payload["tools"] = tools
        if fmt == "json":
            payload["response_format"] = {"type": "json_object"}
        old_timeout = provider.timeout
        if timeout:
            provider.timeout = timeout
        try:
            data = _post(provider, payload)
        except RuntimeError as e:
            errors.append(f"{provider.name()}:{e}")
            continue
        finally:
            provider.timeout = old_timeout
        choices = data.get("choices") or []
        msg = (choices[0].get("message") if choices else {}) or {}
        text = (msg.get("content") or "").strip()
        calls = msg.get("tool_calls") or []
        if text or calls:
            _log_usage(provider, data.get("usage"), kind=kind)
            return text, provider.label, data.get("usage") or {}, calls
        errors.append(f"{provider.name()}: pusta odpowiedź")
    if errors_out is not None:
        errors_out.extend(errors)
    return None


def learn_from_remote(memory, question, answer, source="remote", confidence=0.6):
    """Zapisuje odpowiedź zdalną do `learned` (offline na przyszłość)."""
    if not memory or not (answer or "").strip():
        return None
    try:
        return memory.add_learned(topic="remote", title=(question or "")[:200], text=answer,
                                  source=source, verified=False, confidence=confidence)
    except Exception:
        return None


def probe(question="Odpowiedz jednym zdaniem po polsku: dlaczego niebo jest niebieskie?",
          path=None, include_pc=False):
    """Diagnostyka: który dostawca/konto odpowiada treścią (bez logowania kluczy)."""
    results = []
    for provider in provider_chain(path=path, include_pc=include_pc):
        if not provider.ready():
            continue
        if provider.label == "pc" and not _pc_online(provider.url):
            results.append((provider.name(), provider.model, "offline", 0.0, ""))
            continue
        start = time.time()
        budget = 1200 if provider.label in ("gemini", "opencode", "openrouter") else (
            800 if provider.label == "groq" else 64)
        try:
            data = _post(provider, {"model": provider.model,
                                    "messages": [{"role": "user", "content": question}],
                                    "max_tokens": budget, "stream": False})
            choices = data.get("choices") or []
            text = ((choices[0].get("message") or {}).get("content") or "").strip() if choices else ""
            results.append((provider.name(), provider.model, "OK" if text else "PUSTE",
                            round(time.time() - start, 2), text[:40]))
        except RuntimeError as e:
            results.append((provider.name(), provider.model, f"BŁĄD {str(e)[:60]}",
                            round(time.time() - start, 2), ""))
    return results


def account_info(provider):
    """Saldo/limity, gdy API udostępnia (DeepSeek, OpenRouter); inaczej None."""
    try:
        if provider.label == "deepseek":
            data = _get("https://api.deepseek.com/user/balance", provider.key)
            infos = data.get("balance_infos") or []
            if infos:
                b = infos[0]
                return f"saldo {b.get('total_balance')} {b.get('currency', '')}"
            return f"is_available={data.get('is_available')}"
        if provider.label == "openrouter":
            data = _get("https://openrouter.ai/api/v1/auth/key", provider.key)
            d = data.get("data") or {}
            limit = d.get("limit")
            usage = d.get("usage")
            if limit is None:
                return f"usage={usage} (bez limitu)"
            try:
                remaining = float(limit) - float(usage or 0)
                return f"limit={limit} usage={usage} zostało={remaining:.4f}"
            except Exception:
                return f"limit={limit} usage={usage}"
        if provider.label == "gemini":
            data = _get("https://generativelanguage.googleapis.com/v1beta/openai/models",
                        provider.key)
            return f"modeli={len(data.get('data') or [])}"
        if provider.label == "grok":
            data = _get("https://api.x.ai/v1/models", provider.key)
            return f"modeli={len(data.get('data') or [])}"
        if provider.label == "groq":
            data = _get("https://api.groq.com/openai/v1/models", provider.key)
            return f"modeli={len(data.get('data') or [])}"
        if provider.label == "huggingface":
            data = _get("https://router.huggingface.co/v1/models", provider.key)
            return f"modeli={len(data.get('data') or [])}"
        if provider.label == "opencode":
            data = _get("https://opencode.ai/zen/go/v1/models", provider.key)
            return f"modeli={len(data.get('data') or [])}"
    except RuntimeError as e:
        return f"limit? {str(e)[:70]}"
    except Exception as e:
        return f"limit? {e}"
    return None
