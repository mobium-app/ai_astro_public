"""Rejestr skili (receptur): deterministyczne komendy dopasowywane do wypowiedzi.

Skill = mały, sprawdzony przepis: wzorce -> parametry -> komendy -> komunikat. Działa
BEZ modelu (szybko i pewnie), a dzięki temu, że jest też wystawiony jako narzędzie
(`run_skill`/`list_skills`), wzmacnia tool-calling. Skille zmieniające system mają
`confirm: always` i wymagają potwierdzenia; tylko do-odczytu (`confirm: never`) model
może uruchamiać samodzielnie.

Parametry zapisuje się w komendach jako `{{nazwa}}` (wymagany, z grup nazwanych regexu)
lub `{{nazwa|domyślna}}` (z wartością domyślną) - bez zagnieżdżonych map w YAML.
"""

import glob
import json
import os
import re
import shlex
import subprocess
import time
import unicodedata
from dataclasses import dataclass, field

from .. import config
from ..safety import is_blocked_command

RECIPES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recipes")
SKILLS_LOG = os.path.join(str(config.LOGS_DIR), "skills.jsonl")

_CACHE = {"skills": None}
PARAM_RE = re.compile(r"\{\{\s*(\w+)\s*(?:\|\s*([^}]*?))?\s*\}\}")


@dataclass
class Skill:
    name: str
    description: str = ""
    order: int = 100
    patterns: list = field(default_factory=list)
    commands: list = field(default_factory=list)
    confirm: str = "always"
    root: bool = False
    timeout: int = 120
    expect: str = ""
    check: str = ""
    done: str = ""


def _match_text(text):
    """Usuwa diakrytyki (ł→l) ale ZACHOWUJE wielkość liter - ścieżki/argumenty muszą
    zostać w oryginalnej postaci, więc NIE używamy `normalize_facts` (ono lowercaseduje)."""
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return t.replace("ł", "l").replace("Ł", "L")


def _compile(skill):
    skill.patterns = [re.compile(p, re.I) for p in skill.patterns if p]
    return skill


def load_skills(reload=False):
    """Wczytuje receptury z `recipes/*.yaml` (cache). Bez PyYAML - prosty parser schematu."""
    if not reload and _CACHE["skills"] is not None:
        return _CACHE["skills"]
    skills = []
    for path in sorted(glob.glob(os.path.join(RECIPES_DIR, "*.yaml"))):
        try:
            with open(path, encoding="utf-8") as fh:
                data = _parse_yaml(fh.read())
        except Exception:
            continue
        if not data or "name" not in data:
            continue
        cmds = []
        if data.get("command"):
            cmds.append({"command": data["command"], "say": data.get("say", "")})
        for c in data.get("commands") or []:
            if isinstance(c, str):
                cmds.append({"command": c, "say": ""})
            elif isinstance(c, dict) and c.get("command"):
                cmds.append({"command": c["command"], "say": c.get("say", "")})
        skills.append(_compile(Skill(
            name=data["name"], description=data.get("description", ""),
            order=int(data.get("order", 100)), patterns=list(data.get("patterns") or []),
            commands=cmds, confirm=str(data.get("confirm", "always")),
            root=bool(data.get("root")), timeout=int(data.get("timeout", 120)),
            expect=str(data.get("expect", "")), check=str(data.get("check", "")),
            done=str(data.get("done", "")))))
    skills.sort(key=lambda s: s.order)
    _CACHE["skills"] = skills
    return skills


def _parse_yaml(text):
    """Minimalny parser YAML dla schematu receptur (skalary, listy, listy map)."""
    def scalar(v):
        v = v.strip()
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            return v[1:-1]
        if v in ("true", "True"):
            return True
        if v in ("false", "False"):
            return False
        try:
            return int(v)
        except ValueError:
            return v

    data, cur_list, cur_item = {}, None, None
    for raw in (text or "").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        line = raw.strip()
        if line.startswith("- "):
            content = line[2:].strip()
            if cur_list is None:
                cur_list = []
            if ":" in content and not content.startswith(("'", '"')):
                k, _, v = content.partition(":")
                cur_item = {k.strip(): scalar(v)}
                cur_list.append(cur_item)
            else:
                cur_list.append(scalar(content))
                cur_item = None
            continue
        if indent >= 2 and cur_item is not None and ":" in line:
            k, _, v = line.partition(":")
            cur_item[k.strip()] = scalar(v)
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            if val.strip() == "":
                cur_list = []
                data[key] = cur_list
            else:
                data[key] = scalar(val)
                cur_list = None
            cur_item = None
    return data


def _template_params(skill):
    """Buduje domyślne/obowiązkowe parametry na podstawie szablonów komend."""
    defaults, required = {}, set()
    for c in skill.commands:
        for name, default in PARAM_RE.findall(c.get("command", "")):
            if default is None or default == "":
                required.add(name)
            else:
                defaults[name] = default
    if skill.check:
        for name, default in PARAM_RE.findall(skill.check):
            (defaults.setdefault(name, default) if default else required.add(name))
    return defaults, required


def _resolve(value):
    if value == "@project":
        return str(config.REPO)
    if value == "@home":
        return os.path.expanduser("~")
    return value


def match_skill(text, skills=None):
    """Zwraca (skill, params) dla najlepszego dopasowania albo None. Wzorce bez diakrytyków."""
    if not text:
        return None
    norm = _match_text(text)
    for skill in (skills if skills is not None else load_skills()):
        defaults, required = _template_params(skill)
        for rx in skill.patterns:
            m = rx.search(norm)
            if not m:
                continue
            params = dict(defaults)
            for key, val in (m.groupdict() or {}).items():
                if val:
                    params[key] = _resolve(val.strip())
            if any(name not in params for name in required):
                continue
            return skill, params
    return None


def _subst(template, params, quote=False):
    def repl(m):
        name = m.group(1)
        if name == "output":
            return m.group(0)
        if name in params and params[name] != "":
            value = params[name]
        else:
            value = m.group(2) or ""
        value = str(_resolve(value))
        if value.startswith("~"):
            value = os.path.expanduser(value)
        return shlex.quote(value) if quote else value
    return PARAM_RE.sub(repl, template or "")


def render(template, params):
    """Podstawia `{{param}}`/`{{param|default}}` z quotingiem powłokowym (anty-injection)."""
    return _subst(template, params, quote=True)


def _announce(skill, params):
    return f"Wykonać przepis „{skill.name}\"? " + "; ".join(
        render(c["command"], params) for c in skill.commands)


def run_skill(ctx, skill, params=None, allow_readonly=True):
    """Wykonuje skill. Zmieniające (`confirm: always`) wymagają zgody; read-only (`never`) mogą
    iść od razu (gdy `allow_readonly`). Zwraca (text, ok, pending)."""
    if isinstance(skill, str):
        skill = next((s for s in load_skills() if s.name == skill), None)
    if skill is None:
        return "nieznany przepis", False, None
    defaults, _ = _template_params(skill)
    params = {**defaults, **(params or {})}
    cmds = [render(c["command"], params) for c in skill.commands]
    if not cmds:
        return "przepis bez komendy", False, None
    for cmd in cmds:
        if is_blocked_command(cmd):
            return f"odmowa: komenda zablokowana ({cmd})", False, None
    if skill.confirm != "never" and not getattr(ctx, "assume_confirmed", False):
        confirmer = getattr(ctx, "confirmer", None)
        announce = _announce(skill, params)
        confirmed = bool(confirmer and confirmer.require_confirm(
            announce, "skill", {"skill": skill.name, "params": params, "commands": cmds}))
        if not confirmed:
            return (f"Wymaga potwierdzenia: {announce}", False,
                    {"pending": True, "kind": "skill", "skill": skill.name,
                     "params": params, "commands": cmds})
    outputs, ok = [], True
    for cmd, spec in zip(cmds, skill.commands):
        full = ("sudo -n " + cmd) if skill.root else cmd
        try:
            p = subprocess.run(["bash", "-lc", full], capture_output=True, text=True,
                               errors="replace", timeout=skill.timeout)
            out, code = (p.stdout + p.stderr).strip(), p.returncode
        except subprocess.TimeoutExpired:
            out, code = f"przekroczono limit {skill.timeout}s", 124
        except Exception as e:
            out, code = str(e), 1
        if spec.get("say"):
            outputs.append(spec["say"])
        if out:
            outputs.append(out[:1500])
        if code != 0:
            ok = False
    result = "\n".join(outputs) or "(brak wyjścia)"
    if skill.check:
        try:
            chk = subprocess.run(["bash", "-lc", render(skill.check, params)],
                                 capture_output=True, text=True, timeout=skill.timeout)
            chk_out = (chk.stdout + chk.stderr).strip()
            if chk_out:
                result = chk_out
        except Exception:
            pass
    if skill.done:
        result = _subst(skill.done, params).replace("{{output}}", result) + "\n" + result
    _log(skill, params, ok)
    return result, ok, None


def _log(skill, params, ok):
    try:
        os.makedirs(os.path.dirname(SKILLS_LOG), exist_ok=True)
        with open(SKILLS_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": time.time(), "skill": skill.name, "params": params,
                                 "ok": bool(ok)}, ensure_ascii=False) + "\n")
    except Exception:
        pass


def list_skills_text():
    lines = ["Dostępne przepisy (skille):"]
    for s in load_skills():
        mark = "read-only" if s.confirm == "never" else "wymaga potwierdzenia"
        lines.append(f"- {s.name} [{mark}]: {s.description}")
    return "\n".join(lines)
