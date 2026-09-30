"""Raport HTML ASTRO: postęp/nauka, zasoby lokalne, zasoby remote (statystyki, wykresy, drzewka).

Zapis do folderu udostępnionego (`/etc/astro-secrets`). Bez zewnętrznych bibliotek (inline CSS/SVG).
"""

import datetime
import html
import json
import os
import sqlite3

from . import __version__, config
from .core.resources import bar, human, resource_data

SHARE_DIR = os.environ.get("ASTRO_SHARE", "/etc/astro-secrets")


def _db_counts():
    out = {}
    try:
        con = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True, timeout=5)
        con.row_factory = sqlite3.Row
        for table in ("learned", "trajectories", "conversations", "plans", "lessons",
                      "unknowns", "learned_vectors"):
            try:
                out[table] = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            except Exception:
                out[table] = 0
        try:
            out["learned_by_source"] = {r["source"]: r["n"] for r in con.execute(
                "SELECT source, count(*) n FROM learned GROUP BY source")}
        except Exception:
            out["learned_by_source"] = {}
        try:
            out["traj_by_kind"] = {r["kind"]: r["n"] for r in con.execute(
                "SELECT kind, count(*) n FROM trajectories GROUP BY kind")}
        except Exception:
            out["traj_by_kind"] = {}
        con.close()
    except Exception as e:
        out["error"] = str(e)
    return out


def _remote_stats():
    path = os.path.join(str(config.LOGS_DIR), "remote_usage.jsonl")
    stats = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                prov = r.get("provider") or "inne"
                st = stats.setdefault(prov, {"calls": 0, "prompt": 0, "completion": 0,
                                             "total": 0, "accounts": {}})
                st["calls"] += 1
                st["prompt"] += r.get("prompt") or 0
                st["completion"] += r.get("completion") or 0
                st["total"] += r.get("total") or 0
                acc = r.get("account") or prov
                st["accounts"][acc] = st["accounts"].get(acc, 0) + 1
    except OSError:
        pass
    return stats


def _usage_routes():
    path = os.path.join(str(config.LOGS_DIR), "usage.jsonl")
    routes = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                routes[r.get("route") or "?"] = routes.get(r.get("route") or "?", 0) + 1
    except OSError:
        pass
    return routes


def _bar_row(label, pct, detail):
    pct = max(0.0, min(100.0, pct))
    return (f'<div class="row"><div class="lbl">{html.escape(label)}</div>'
            f'<div class="track"><div class="fill" style="width:{pct:.1f}%"></div></div>'
            f'<div class="val">{html.escape(detail)}</div></div>')


def _svg_bars(data, width=560, height=180):
    """Prosty wykres słupkowy SVG (etykiety + wartości)."""
    if not data:
        return "<p>b/d</p>"
    items = sorted(data.items(), key=lambda kv: -kv[1])[:8]
    maxv = max(v for _, v in items) or 1
    bw = width / (len(items) * 1.6)
    parts = [f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">']
    for i, (name, v) in enumerate(items):
        x = 20 + i * (width - 40) / len(items)
        h = (height - 50) * v / maxv
        y = height - 30 - h
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{h:.1f}" '
                     f'fill="#4aa3ff"/>')
        parts.append(f'<text x="{x + bw / 2:.1f}" y="{y - 5:.1f}" font-size="11" '
                     f'text-anchor="middle" fill="#cde">{v}</text>')
        parts.append(f'<text x="{x + bw / 2:.1f}" y="{height - 12}" font-size="10" '
                     f'text-anchor="middle" fill="#8aa">{html.escape(str(name)[:12])}</text>')
    parts.append("</svg>")
    return "".join(parts)


def build_report(out_dir=None):
    out_dir = out_dir or SHARE_DIR
    d = resource_data()
    db = _db_counts()
    remote = _remote_stats()
    routes = _usage_routes()

    mi = d["mem"]
    mem_pct = (mi["used"] / mi["total"] * 100) if mi["total"] else 0
    disk_rows = ""
    for disk in d["disks"]:
        p = (disk["used"] / disk["total"] * 100) if disk["total"] else 0
        disk_rows += _bar_row(disk["mount"],
                              p, f"{human(disk['used'])} / {human(disk['total'])} "
                                 f"({p:.0f}%, wolne {human(disk['free'])})")
    cpu_temp = f"{d['cpu']['temp_c']}°C" if d["cpu"]["temp_c"] is not None else "n/d"

    remote_rows = ""
    remote_totals = {}
    for prov, st in sorted(remote.items(), key=lambda kv: -kv[1]["total"]):
        remote_totals[prov] = st["total"]
        accs = " · ".join(f"{k} ×{v}" for k, v in sorted(st["accounts"].items()))
        remote_rows += (f"<tr><td>{html.escape(prov)}</td><td>{st['calls']}</td>"
                        f"<td>{st['prompt']:,}</td><td>{st['completion']:,}</td>"
                        f"<td>{st['total']:,}</td><td>{html.escape(accs)}</td></tr>"
                        .replace(",", " "))

    route_rows = "".join(f"<tr><td>{html.escape(k)}</td><td>{v}</td></tr>"
                         for k, v in sorted(routes.items(), key=lambda kv: -kv[1]))
    src_rows = "".join(f"<tr><td>{html.escape(str(k))}</td><td>{v}</td></tr>"
                       for k, v in sorted(db.get("learned_by_source", {}).items(),
                                          key=lambda kv: -kv[1]))

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    doc = f"""<!DOCTYPE html>
<html lang="pl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ASTRO — raport {now}</title>
<style>
 body{{background:#0f141b;color:#dbe6f0;font-family:system-ui,Segoe UI,Roboto,sans-serif;margin:0;padding:24px}}
 h1,h2{{color:#7fd1ff}} h1{{margin:0 0 4px}} .muted{{color:#8aa;font-size:13px}}
 .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px;margin-top:16px}}
 .card{{background:#161d27;border:1px solid #24303e;border-radius:10px;padding:16px}}
 .row{{display:flex;align-items:center;gap:10px;margin:6px 0;font-size:13px}}
 .lbl{{width:120px;color:#9fb}} .val{{color:#cde;min-width:150px}}
 .track{{flex:1;height:14px;background:#0c1117;border-radius:7px;overflow:hidden;border:1px solid #223}}
 .fill{{height:100%;background:linear-gradient(90deg,#2b8cff,#59d0ff)}}
 table{{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}}
 th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid #24303e}}
 th{{color:#8aa}} pre{{background:#0c1117;border:1px solid #223;border-radius:8px;padding:12px;overflow:auto;color:#bfe}}
 .kpi{{display:flex;gap:18px;flex-wrap:wrap}} .kpi div{{background:#101823;border:1px solid #223;border-radius:8px;padding:10px 14px}}
 .kpi b{{color:#7fd1ff;font-size:20px}}
</style></head><body>
<h1>ASTRO — raport</h1>
<div class="muted">v{html.escape(__version__)} · {html.escape(d['host'])} · {html.escape(d['arch'])}
 · {now}</div>

<div class="kpi" style="margin-top:14px">
 <div><b>{db.get('learned',0)}</b><br>learned</div>
 <div><b>{db.get('trajectories',0)}</b><br>trajektorie</div>
 <div><b>{db.get('conversations',0)}</b><br>rozmowy</div>
 <div><b>{db.get('plans',0)}</b><br>plany</div>
 <div><b>{sum(remote_totals.values()):.0f}</b><br>tokeny remote</div>
</div>

<div class="grid">
 <div class="card"><h2>Zasoby lokalne</h2>
  {_bar_row('RAM', mem_pct, f"{human(mi['used'])} / {human(mi['total'])}")}
  {disk_rows}
  <p class="muted">CPU: {d['cpu']['cores']} rdzeni · {cpu_temp} · load {d['cpu']['load']}<br>
   NPU: {html.escape(d['npu'][:160])}</p>
 </div>

 <div class="card"><h2>Postęp / nauka</h2>
  <table><tr><th>źródło wiedzy</th><th>wpisy</th></tr>{src_rows}</table>
  <h2 style="margin-top:14px">Trasy zapytań</h2>
  <table><tr><th>trasa</th><th>liczba</th></tr>{route_rows or '<tr><td>b/d</td><td>0</td></tr>'}</table>
 </div>

 <div class="card"><h2>Zasoby remote — tokeny</h2>
  {_svg_bars(remote_totals)}
  <table><tr><th>dostawca</th><th>wywołania</th><th>prompt</th><th>odpowiedź</th><th>razem</th><th>konta</th></tr>
  {remote_rows or '<tr><td>b/d</td><td colspan="5">brak wywołań</td></tr>'}</table>
 </div>

 <div class="card"><h2>Drzewko zasobów (tekst)</h2>
  <pre>{html.escape(_tree_text(d, db, remote_totals))}</pre>
 </div>
</div>
</body></html>"""

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"astro_report_{datetime.datetime.now():%Y%m%d_%H%M%S}.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    return path


def _tree_text(d, db, remote_totals):
    lines = [f"ASTRO v{__version__} — postęp i zasoby", "│",
             f"├─ zasoby: RAM {human(d['mem']['used'])}/{human(d['mem']['total'])} · "
             f"CPU {d['cpu']['temp_c']}°C"]
    for disk in d["disks"]:
        p = disk["used"] / disk["total"] * 100 if disk["total"] else 0
        lines.append(f"├─ dysk {disk['mount']} {p:.0f}%")
    lines += [f"├─ wiedza: learned={db.get('learned',0)} trajektorie={db.get('trajectories',0)}",
              f"└─ remote: " + (", ".join(f"{k}={int(v)}" for k, v in remote_totals.items())
                                or "brak")]
    return "\n".join(lines)


if __name__ == "__main__":
    print(build_report())
