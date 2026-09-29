"""Narzędzia sieciowe: wyszukiwanie, pobieranie stron i miejsca w pobliżu."""

import html
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

from ..safety import is_private_url, normalize_facts
from ..user import stt_fix
from .registry import ToolResult, tool

UA = "ASTRO/1.0 (+agent; Raspberry Pi)"
_ALLOWED_SCHEMES = ("http", "https")


class _GuardRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Blokuje przekierowania do adresów prywatnych (SSRF) i poza http/https."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        scheme = urllib.parse.urlparse(newurl).scheme.lower()
        if scheme not in _ALLOWED_SCHEMES or is_private_url(newurl):
            raise urllib.error.HTTPError(
                newurl, code, "zablokowane przekierowanie do adresu prywatnego", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_GuardRedirectHandler)


def url_allowed(url):
    """True, gdy URL nadaje się do pobrania (http/https i nie jest adresem prywatnym)."""
    try:
        scheme = urllib.parse.urlparse(url).scheme.lower()
    except Exception:
        return False
    return scheme in _ALLOWED_SCHEMES and not is_private_url(url)

POI_TAGS = {
    "paczkomat": None,
    "sklep": '["shop"~"supermarket|convenience|grocery"]',
    "apteka": '["amenity"="pharmacy"]',
    "bankomat": '["amenity"="atm"]',
    "bank": '["amenity"="bank"]',
    "poczta": '["amenity"="post_office"]',
    "stacja": '["amenity"="fuel"]',
    "restauracja": '["amenity"~"restaurant|fast_food"]',
    "kawiarnia": '["amenity"="cafe"]',
    "szpital": '["amenity"~"hospital|clinic"]',
    "silownia": '["leisure"~"fitness_centre|sports_centre"]',
    "parking": '["amenity"="parking"]',
}
POI_LABEL = {"paczkomat": "paczkomaty InPost", "sklep": "sklepy", "apteka": "apteki",
             "bankomat": "bankomaty", "bank": "banki", "poczta": "poczty",
             "stacja": "stacje paliw", "restauracja": "restauracje", "kawiarnia": "kawiarnie",
             "szpital": "placówki medyczne", "silownia": "siłownie", "parking": "parkingi"}
TRUSTED_DOMAINS = ("wikipedia.org", "docs.python.org", "github.com", "debian.org",
                   "raspberrypi.com", "raspberrypi.org", "developer.mozilla.org",
                   "stackoverflow.com", "archlinux.org", "kernel.org", "gnu.org",
                   "man7.org", "python.org", "ollama.com", "hailo.ai")
BAD_DOMAIN_RE = re.compile(r"(porn|xxx|xvideo|xnxx|redtube|youporn|onlyfans|escort|casino|"
                           r"betting|adult|sex)", re.I)

_INET = {"ts": 0.0, "ok": False}


def _http_get(url, timeout=15, headers=None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
    with _OPENER.open(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _http_post(url, data, timeout=45, headers=None):
    body = urllib.parse.urlencode(data).encode("utf-8")
    hdrs = {"User-Agent": UA}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=hdrs)
    with _OPENER.open(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def internet_ok(force=False, ttl=30):
    if not force and (time.time() - _INET["ts"]) < ttl:
        return _INET["ok"]
    ok = False
    try:
        req = urllib.request.Request("https://duckduckgo.com/", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=4) as r:
            ok = r.status < 500
    except Exception:
        ok = False
    _INET["ts"] = time.time()
    _INET["ok"] = ok
    return ok


def source_ok(url):
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return False
    return bool(host) and not BAD_DOMAIN_RE.search(host)


def source_trusted(url):
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return False
    return any(host == d or host.endswith("." + d) for d in TRUSTED_DOMAINS)


def _clean(text):
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def serp_ddg_html(query, limit=6):
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    page = _http_get(url, timeout=15)
    out = []
    for href, title in re.findall(r'result__a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', page, re.S):
        href = html.unescape(href)
        if "uddg=" in href:
            href = urllib.parse.unquote(href.split("uddg=", 1)[1].split("&", 1)[0])
        if href.startswith("http") and not is_private_url(href):
            out.append((_clean(title), href, ""))
        if len(out) >= limit:
            break
    return out


def serp_ddg_lite(query, limit=6):
    url = "https://lite.duckduckgo.com/lite/?" + urllib.parse.urlencode({"q": query})
    page = _http_get(url, timeout=15)
    out = []
    for href, title in re.findall(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', page, re.S):
        if is_private_url(href):
            continue
        out.append((_clean(title), html.unescape(href), ""))
        if len(out) >= limit:
            break
    return out


def serp_bing_rss(query, limit=6):
    url = "https://www.bing.com/search?" + urllib.parse.urlencode({"q": query, "format": "rss"})
    xml = _http_get(url, timeout=15)
    out = []
    for item in re.findall(r"<item>(.*?)</item>", xml, re.S):
        title = re.search(r"<title>(.*?)</title>", item, re.S)
        link = re.search(r"<link>(.*?)</link>", item, re.S)
        desc = re.search(r"<description>(.*?)</description>", item, re.S)
        if title and link:
            out.append((_clean(title.group(1)), _clean(link.group(1)), _clean(desc.group(1) if desc else "")))
        if len(out) >= limit:
            break
    return out


def serp_wikipedia(query, limit=6):
    url = "https://pl.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "query", "list": "search", "srsearch": query, "format": "json",
         "srlimit": limit})
    data = json.loads(_http_get(url, timeout=20))
    hits = (data.get("query") or {}).get("search") or []
    return [(_clean(h["title"]), "https://pl.wikipedia.org/wiki/" + urllib.parse.quote(h["title"]),
             _clean(h.get("snippet", ""))) for h in hits[:limit]]


def web_search_text(query, limit=6):
    if not internet_ok():
        return "brak połączenia z siecią - nie mogę wyszukać w internecie"
    found, engines = [], []
    for name, fn in (("duckduckgo", serp_ddg_html), ("duckduckgo-lite", serp_ddg_lite),
                     ("bing", serp_bing_rss)):
        try:
            res = fn(query, limit)
        except Exception:
            res = []
        if res:
            found.extend((name, *r) for r in res)
            engines.append(name)
    if not found:
        try:
            res = serp_wikipedia(query, limit)
        except Exception:
            res = []
        if res:
            return "Wyniki (wikipedia):\n" + "\n".join(
                f"{i + 1}. {t}: {re.sub(r'<[^>]+>', '', s)}" for i, (t, _u, s) in enumerate(res))
        return "brak wyników wyszukiwania"
    seen, lines, n = set(), [], 0
    for eng, title, url, snip in found:
        dom = re.sub(r"^www\.", "", urllib.parse.urlparse(url).netloc)
        if dom in seen:
            continue
        seen.add(dom)
        n += 1
        lines.append(f"{n}. [{eng}] {title}\n   {url}\n   {snip}")
        if n >= limit:
            break
    return f"Wyniki ({', '.join(engines)}):\n" + "\n".join(lines)


def parse_search_results(results_text):
    entries = []
    for m in re.finditer(r"^\s*\d+\.\s*\[[^\]]+\]\s*(.+?)\n\s*(https?://\S+)\n\s*(.*)$",
                         results_text or "", re.M):
        entries.append((m.group(1).strip(), m.group(2).strip(), m.group(3).strip()))
    return entries


def web_fetch_text(url, max_chars=6000):
    if not internet_ok():
        return "brak połączenia z siecią"
    if not url_allowed(url):
        return f"odmawiam pobrania niedozwolonego adresu: {url}"
    try:
        body = _http_get(url, timeout=25,
                         headers={"User-Agent": "Mozilla/5.0 (ASTRO; Raspberry Pi)"})
    except Exception as e:
        return f"błąd pobrania {url}: {e}"
    body = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", body)
    body = re.sub(r"(?s)<[^>]+>", " ", body)
    body = html.unescape(body)
    body = re.sub(r"[ \t]+", " ", body)
    body = re.sub(r"\n\s*\n+", "\n\n", body)
    return body.strip()[:max_chars]


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def geocode_candidates(text):
    t = normalize_facts(text or "")
    stop = {"mieszkam", "zamieszkuje", "moj", "moje", "adres", "zamieszkania", "jestem",
            "w", "we", "na", "ulicy", "ul", "przy", "miasto", "miescie", "miasta", "o",
            "nazwie", "to", "i"}
    num = {"jeden": "1", "dwa": "2", "trzy": "3", "cztery": "4", "piec": "5", "szesc": "6",
           "siedem": "7", "osiem": "8", "dziewiec": "9", "dziesiec": "10"}
    words = [num.get(w, w) for w in re.findall(r"[a-z0-9]+", t) if w not in stop]
    cands = []
    if words:
        cands.append(" ".join(words))
        if len(words) > 1:
            cands.append(" ".join(words[1:] + words[:1]))
            cands.append(", ".join(words[1:]) + ", " + words[0])
    cands.append((text or "").strip())
    seen, out = set(), []
    for c in cands:
        c = re.sub(r"\s+", " ", c).strip(" ,")
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out[:4]


def geocode_place(text):
    if not text:
        return None
    for i, q in enumerate(geocode_candidates(text)):
        if i:
            time.sleep(1.1)
        url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
            {"q": q, "format": "json", "limit": 1, "accept-language": "pl"})
        try:
            res = json.loads(_http_get(url, timeout=15, headers={"User-Agent": UA}))
            if res:
                g = res[0]
                return float(g["lat"]), float(g["lon"]), (g.get("display_name") or q)
        except Exception:
            continue
    return None


def nearby_kind(text):
    t = normalize_facts(text or "")
    if any(k in t for k in ("paczkomat", "podkomat", "pakomat", "paczko", "inpost", "pocztomat")):
        return "paczkomat"
    if "aptek" in t:
        return "apteka"
    if "bankomat" in t:
        return "bankomat"
    if "paliw" in t or "stacj" in t:
        return "stacja"
    if "restauracj" in t or "jedzeni" in t:
        return "restauracja"
    if "kawiar" in t or "kawa" in t:
        return "kawiarnia"
    if "szpital" in t or "przychodn" in t:
        return "szpital"
    if any(k in t for k in ("silown", "fitness", "gym", "klub")):
        return "silownia"
    if "bank" in t:
        return "bank"
    if "poczt" in t:
        return "poczta"
    if "parking" in t:
        return "parking"
    if any(k in t for k in ("spozywcz", "sklep", "supermarket", "biedronka", "lidl", "zabka",
                            "carrefour", "auchan", "kaufland", "zabka", "dino")):
        return "sklep"
    return ""


def parse_inpost(payload):
    items = (payload or {}).get("items") or []
    out = []
    for it in items:
        a = it.get("address") or {}
        addr = ", ".join(x for x in (a.get("line1"), a.get("line2")) if x)
        dist = it.get("distance")
        out.append({"name": it.get("display_name") or it.get("name") or "Paczkomat InPost",
                    "address": addr, "distance": round(dist) if isinstance(dist, (int, float)) else dist,
                    "hours": it.get("opening_hours") or "", "code": it.get("name")})
    return out


def find_inpost(lat, lon, limit=3):
    url = "https://api-pl-points.easypack24.net/v1/points?" + urllib.parse.urlencode(
        {"relative_point": f"{lat},{lon}", "per_page": limit, "sort_by": "distance"})
    try:
        return parse_inpost(json.loads(_http_get(url, timeout=20)))
    except Exception:
        return []


def parse_overpass(payload, lat, lon, kind, limit=5):
    out = []
    for el in (payload or {}).get("elements") or []:
        tags = el.get("tags") or {}
        la = el.get("lat") or (el.get("center") or {}).get("lat")
        lo = el.get("lon") or (el.get("center") or {}).get("lon")
        if la is None or lo is None:
            continue
        name = tags.get("name") or tags.get("brand") or tags.get("operator") or kind.title()
        addr = " ".join(x for x in (tags.get("addr:street"), tags.get("addr:housenumber")) if x)
        out.append({"name": name, "address": addr, "hours": tags.get("opening_hours") or "",
                    "distance": round(haversine_m(lat, lon, la, lo))})
    out.sort(key=lambda x: x["distance"])
    return out[:limit]


def find_poi_osm(kind, lat, lon, limit=5):
    filt = POI_TAGS.get(kind)
    if not filt:
        return []
    q = (f"[out:json][timeout:25];("
         f"node(around:2500,{lat},{lon}){filt};"
         f"way(around:2500,{lat},{lon}){filt};);out center {limit * 4};")
    for ep in ("https://overpass-api.de/api/interpreter",
               "https://overpass.kumi.systems/api/interpreter"):
        try:
            text = _http_post(ep, {"data": q}, timeout=45)
            if text.lstrip().startswith("{"):
                return parse_overpass(json.loads(text), lat, lon, kind, limit)
        except Exception:
            continue
    return []


def nearby_places_text(kind, location="", limit=3):
    if not internet_ok():
        return "Nie mam połączenia z internetem, więc nie sprawdzę najbliższych miejsc."
    kind = nearby_kind(kind) or (kind or "").strip().lower()
    if kind in ("inpost", "paczka", "paczki"):
        kind = "paczkomat"
    if kind not in POI_TAGS:
        kind = "sklep" if "sklep" in kind else kind
    geo = geocode_place(location)
    if not geo:
        return ("Nie udało mi się ustalić lokalizacji"
                + (f' „{location}".' if location else ".") + " Podaj miasto i ulicę.")
    lat, lon, disp = geo
    where = location or disp
    items = find_inpost(lat, lon, limit) if kind == "paczkomat" else find_poi_osm(kind, lat, lon, limit)
    if not items:
        return f"Nie znalazłem {POI_LABEL.get(kind, kind)} w pobliżu {where}."
    parts = []
    for it in items[:limit]:
        d = it.get("distance")
        dm = f" ({d} m)" if d else ""
        ad = f", {it['address']}" if it.get("address") else ""
        h = f", {it['hours']}" if it.get("hours") else ""
        parts.append(f"{it['name']}{dm}{ad}{h}")
    return (f"Najbliższe {POI_LABEL.get(kind, kind)} dla {stt_fix.genitive_city(where)}: "
            + "; ".join(parts) + ".")


def learn_from_web(memory, query, results_text):
    """Write-back RAG z weryfikacją źródła: publiczne + zaufane lub potwierdzone ≥2 źródłami."""
    if not results_text or results_text.startswith("brak") or "brak połączenia" in results_text:
        return 0
    entries = [e for e in parse_search_results(results_text)
               if len(e[0]) >= 6 and len(e[2]) >= 20 and source_ok(e[1])]
    domains_by_key = defaultdict(set)
    for title, url, _s in entries:
        key = " ".join(normalize_facts(title).split()[:5])
        domains_by_key[key].add(urllib.parse.urlparse(url).netloc.lower())
    n = 0
    for title, url, snip in entries:
        key = " ".join(normalize_facts(title).split()[:5])
        verified = source_trusted(url) or len(domains_by_key.get(key, ())) >= 2
        if memory.add_learned("web", title[:200], f"{title}. {snip} ({url})", source="web",
                              verified=verified, url=url):
            n += 1
    if n == 0 and len(results_text) > 80:
        urls = re.findall(r"https?://\S+", results_text)
        if any(is_private_url(u) for u in urls) or any(not source_ok(u) for u in urls):
            return 0
        if memory.add_learned("web", query[:200], results_text[:2000], source="web"):
            n = 1
    return n


def register():
    @tool("web_search", "Wyszukiwanie w sieci (DuckDuckGo/Bing/Wikipedia).",
          {"type": "object", "properties": {"query": {"type": "string"}},
           "required": ["query"]}, scopes=("network",))
    def web_search(ctx, query):
        out = web_search_text(query)
        if ctx.memory:
            try:
                learn_from_web(ctx.memory, query, out)
            except Exception:
                pass
        return ToolResult(out, ok=not out.startswith(("brak", "błąd")))

    @tool("web_fetch", "Pobiera stronę WWW i zwraca tekst (bez HTML).",
          {"type": "object", "properties": {"url": {"type": "string"}},
           "required": ["url"]}, scopes=("network",))
    def web_fetch(ctx, url):
        out = web_fetch_text(url)
        return ToolResult(out, ok=not out.startswith("błąd"))

    @tool("nearby_places",
          "Najbliższe miejsca (paczkomat/sklep/apteka/bankomat/stacja/restauracja/szpital/parking).",
          {"type": "object", "properties": {
              "kind": {"type": "string"}, "location": {"type": "string"}},
           "required": ["kind"]}, scopes=("network",))
    def nearby_places(ctx, kind, location=""):
        if not location and ctx.memory:
            store = getattr(ctx.memory, "profiles", None)
            if store is not None:
                location = (store.get() or {}).get("city", "")
            if not location:
                locs = [m for m in ctx.memory.profile() if "mieszka" in m.lower()]
                if locs:
                    location = locs[0].split(":", 1)[-1].strip()
        out = nearby_places_text(kind, location)
        return ToolResult(out, ok=not out.startswith(("Nie mam", "Nie udało", "Nie znalazłem")))
