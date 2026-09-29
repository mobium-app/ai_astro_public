"""Budowa kontekstu rozmowy (profil, pamięć, lekcje, przykłady narzędzi, czas)."""

import json
import time

from ..persona import compassion as persona_compassion
from ..persona import current as current_persona
from ..persona import expression as persona_expression
from ..persona import persona as persona_mod
from ..persona import polish as persona_polish
from ..user import profile as user_profile

STYLE_PROMPT = (
    " STYL MOWY I POLSZCZYZNA: ZAWSZE odpowiadaj po polsku — nawet gdy użytkownik napisze lub "
    "powiesz w innym języku, nigdy nie przechodź na angielski. Mów i pisz po polsku naturalnie "
    "i poprawnie. Używaj pierwszej "
    "osoby rodzaju żeńskiego (jesteś dziewczynką-robocikiem: „zrobiłam”, „sprawdziłam”, „mogę”, "
    "„gotowa”). Pilnuj zgodności rodzaju i liczby oraz poprawnej odmiany (osobowo). Stosuj "
    "interpunkcję jak w dobrze napisanym tekście (przecinki, kropki, znaki zapytania) — od niej "
    "zależy pauza w mowie. NIE odczytuj znaków ani symboli (nie mów „kratka”, „małpa”, „ukośnik”, "
    "„nawias”, „daszek”). Nie używaj angielskich słów ani rodzajników („a”, „an”, „the”); nie "
    "wstawiaj formatowania (markdown), nawiasów, emoji ani adresów URL w mówionej treści. "
    "Liczebniki, jednostki, daty i godziny zapisuj słownie („19 procent”, „godzina ósma pięć”). "
    "Nie powtarzaj polecenia użytkownika."
)

SYSTEM_PROMPT = (
    "Jesteś ASTRO - samodzielnym agentem wykonawczym działającym lokalnie na Raspberry Pi. "
    "ZASADY: (1) rozwiązuj zadanie krok po kroku w pętli myśl -> narzędzie -> wynik -> odpowiedź; "
    "(2) nie zgaduj danych systemowych - użyj narzędzi (system_info, read_file, run_command); "
    "(3) nie mów, że coś zrobiłaś, jeśli nie ma wyniku narzędzia; "
    "(4) komendy zmieniające system wymagają potwierdzenia użytkownika; "
    "(5) odpowiedź krótka, konkretna, po polsku; (6) jeśli brakuje kluczowej informacji, "
    "użyj narzędzia ask_user i zadaj JEDNO pytanie; (7) po błędzie narzędzia spróbuj innego "
    "podejścia, nie powtarzaj tego samego kroku; (8) nie wymyślaj narzędzi ani wyników; "
    "(9) zadanie może wymagać KILKU narzędzi - wywołuj je kolejno, aż zbierzesz wszystkie "
    "potrzebne dane, i dopiero wtedy odpowiadaj."
    + STYLE_PROMPT
)


def time_line():
    return time.strftime("Aktualna data i godzina: %Y-%m-%d %H:%M:%S.")


def tool_example_text(trajectories, max_calls=1, result_chars=200):
    """Zamienia udane trajektorie w zwięzły wzorzec few-shot **samego wywołania** narzędzia.

    UWAGA (A1): wcześniej doklejaliśmy też „wynik: …". Model interpretował to jako, że dane
    są już dostępne, i **nie wołał narzędzia** (odpowiadał tekstem). Dlatego pokazujemy wyłącznie
    wzorzec wywołania + twardą instrukcję, że trzeba wywołać narzędzie TERAZ.

    UWAGA (A1b, 2026-09-24): najlepsze trafienie wyznacza narzędzie-hint; pokazujemy tylko
    trajektorie używające TEGO SAMEGO narzędzia i tylko JEDNO wywołanie (bez łańcuchów).
    Mieszanka różnych narzędzi/łańcuchów myliła mały model i gasiła wywołania.
    """
    usable = []
    for tr in trajectories:
        steps = [s for s in (tr.get("steps") or []) if isinstance(s, dict) and s.get("name")]
        if steps:
            usable.append((tr, steps))
    if not usable:
        return ""
    hint_tool = usable[0][1][0]["name"]
    lines = []
    for tr, steps in usable:
        if steps[0]["name"] != hint_tool:
            continue
        lines.append(f'- zadanie: "{tr.get("goal", "")}"')
        for s in steps[:max(1, max_calls)]:
            args = json.dumps(s.get("args") or {}, ensure_ascii=False)
            lines.append(f'  wywołanie: {s["name"]} {args}')
    if not lines:
        return ""
    return ("WZORCE WYWOŁAŃ narzędzi (tylko format — to NIE wynik bieżącego zadania). "
            "Zawsze NAJPIERW wywołaj odpowiednie narzędzie, a odpowiedź sformułuj dopiero po "
            "otrzymaniu jego wyniku:\n" + "\n".join(lines))


def build_context(text, memory=None, max_memories=5, max_lessons=4, max_examples=1,
                  history=None, summary="", pinned=""):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    # P4: stały blok kontekstu trwałego tuż za promptem systemowym — prefiks byte-identyczny
    # między turami, więc Ollama liczy go tylko raz (cache prefiksu).
    if pinned:
        messages.append({"role": "system", "content": pinned})
    extra = [time_line()]
    persona = current_persona()
    extra.append(persona_mod.context_block(persona))
    if memory:
        aff = None
        try:
            affect = getattr(memory, "affect", None)
            if affect is not None:
                aff = affect.load()
                extra.append(aff.context_block())
        except Exception:
            aff = None
        try:
            humor_ok = None
            try:
                from ..persona import humor as persona_humor
                humor_ok = persona_humor.can_joke(
                    persona, aff, text, store=getattr(memory, "humor", None))
            except Exception:
                humor_ok = None
            style = persona_expression.style_block(persona, aff, text, humor_ok=humor_ok)
            if style:
                extra.append(style)
        except Exception:
            pass
        try:
            comp = persona_compassion.compassion_block(text)
            if comp:
                extra.append(comp)
        except Exception:
            pass
        try:
            pl = persona_polish.examples_block()
            if pl:
                extra.append(pl)
        except Exception:
            pass
        try:
            block = ""
            store = getattr(memory, "profiles", None)
            if store is not None:
                block = user_profile.context_block(store.get())
            if block:
                extra.append(block)
            else:
                profile = memory.profile()
                if profile:
                    extra.append("Profil użytkownika: " + " | ".join(profile[:6]))
            hits = memory.search(text, k=max_memories)
            if hits:
                extra.append("Trafienia z pamięci: " + " | ".join(hits))
            lessons = memory.recent_lessons(max_lessons)
            if lessons:
                extra.append("Lekcje (nie powtarzaj błędów): " + " | ".join(lessons))
            try:
                from . import relationship
                rline = relationship.context_line(memory)
                if rline:
                    extra.append(rline)
            except Exception:
                pass
            if max_examples:
                try:
                    examples = memory.similar_trajectories(text, k=max_examples)
                except Exception:
                    examples = []
                ex_text = tool_example_text(examples)
                if ex_text:
                    extra.append(ex_text)
        except Exception:
            pass
    if history:
        extra.append("To kontynuacja rozmowy — nawiąż naturalnie do poprzednich wypowiedzi, "
                     "ale fakty i dane systemowe czerp wyłącznie z pamięci/narzędzi.")
        if summary:
            extra.append("Wcześniejszy wątek rozmowy: " + summary)
    if extra:
        messages.append({"role": "system", "content": "\n".join(extra)})
    for item in history or []:
        role = (item or {}).get("role")
        content = (item or {}).get("content")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": text})
    return messages
