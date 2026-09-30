"""Zasoby systemu ASTRO: dane + drzewko terminalowe (jak `resources.py` Ateny)."""

import os
import shutil
import subprocess
import time
from pathlib import Path

from .. import __version__, config


def _read(path, default=""):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return default


def cpu_temp():
    raw = _read("/sys/class/thermal/thermal_zone0/temp")
    try:
        return round(int(raw) / 1000, 1)
    except ValueError:
        return None


def meminfo():
    data = {}
    for line in _read("/proc/meminfo").splitlines():
        parts = line.split()
        if len(parts) >= 2:
            data[parts[0].rstrip(":")] = int(parts[1]) * 1024
    total = data.get("MemTotal", 0)
    avail = data.get("MemAvailable", 0)
    used = max(0, total - avail)
    swap_total = data.get("SwapTotal", 0)
    swap_used = max(0, swap_total - data.get("SwapFree", 0))
    return {"total": total, "used": used, "free": avail,
            "swap_total": swap_total, "swap_used": swap_used}


def disks():
    out = []
    seen = set()
    try:
        mounts = _read("/proc/mounts").splitlines()
    except Exception:
        mounts = []
    for line in mounts:
        parts = line.split()
        if len(parts) < 2:
            continue
        dev, mnt = parts[0], parts[1]
        if not dev.startswith("/dev/") or "loop" in dev or mnt in seen:
            continue
        if any(mnt.startswith(p) for p in ("/boot", "/run", "/sys", "/proc", "/dev")):
            # /boot pokazujemy jako osobny punkt (FAT), resztę pomijamy
            if mnt != "/boot" and mnt != "/boot/firmware":
                continue
        try:
            total, used, free = shutil.disk_usage(mnt)
        except OSError:
            continue
        seen.add(mnt)
        out.append({"mount": mnt, "dev": dev, "total": total, "used": used, "free": free})
    out.sort(key=lambda d: d["mount"])
    return out


def uptime_s():
    try:
        return float(_read("/proc/uptime").split()[0])
    except (ValueError, IndexError):
        return 0.0


def human(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
        n /= 1024


def bar(pct, width=20):
    pct = max(0.0, min(100.0, pct))
    filled = int(round(pct / 100 * width))
    return "█" * filled + "░" * (width - filled)


def npu_line():
    try:
        from ..backends import npu_status_text
        return npu_status_text().splitlines()[0]
    except Exception:
        return "NPU: brak danych"


def resource_data():
    mi = meminfo()
    return {
        "version": __version__,
        "host": os.uname().nodename,
        "kernel": os.uname().release,
        "arch": os.uname().machine,
        "python": os.sys.version.split()[0],
        "cpu": {"cores": os.cpu_count(), "temp_c": cpu_temp(),
                "load": [round(x, 2) for x in os.getloadavg()]},
        "mem": mi,
        "swap": {"total": mi["swap_total"], "used": mi["swap_used"]},
        "disks": disks(),
        "uptime_s": uptime_s(),
        "npu": npu_line(),
    }


def _pct(used, total):
    return (used / total * 100) if total else 0.0


def system_tree():
    d = resource_data()
    mi = d["mem"]
    up = d["uptime_s"]
    lines = [f"ZASOBY ASTRO   (v{d['version']}  ·  {d['host']}  ·  {d['arch']})", "│"]
    # CPU
    load = " ".join(str(x) for x in d["cpu"]["load"])
    temp = f"{d['cpu']['temp_c']}°C" if d["cpu"]["temp_c"] is not None else "n/d"
    lines += ["├─ CPU",
              f"│  ├─ rdzenie: {d['cpu']['cores']}   ·   obciążenie: {load}",
              f"│  ├─ temperatura: {temp}",
              f"│  └─ uptime: {int(up // 86400)}d {int((up % 86400) // 3600)}h "
              f"{int((up % 3600) // 60)}m"]
    # RAM
    mp = _pct(mi["used"], mi["total"])
    lines += ["├─ pamięć RAM",
              f"│  └─ [{bar(mp)}] {mp:4.0f}%   {human(mi['used'])} / {human(mi['total'])}  "
              f"(wolne {human(mi['free'])})"]
    # swap (jeśli jest)
    if mi["swap_total"]:
        sp = _pct(mi["swap_used"], mi["swap_total"])
        lines.append(f"├─ swap  [{bar(sp)}] {sp:4.0f}%   {human(mi['swap_used'])} / "
                     f"{human(mi['swap_total'])}")
    # dyski
    lines.append("├─ dyski")
    for i, disk in enumerate(d["disks"]):
        p = _pct(disk["used"], disk["total"])
        last = i == len(d["disks"]) - 1
        arm = "└─" if last else "├─"
        lines.append(f"│  {arm} {disk['mount']:14} [{bar(p)}] {p:4.0f}%   "
                     f"{human(disk['used'])} / {human(disk['total'])}  (wolne {human(disk['free'])})")
    # NPU
    lines += ["└─ NPU", f"   └─ {d['npu']}"]
    return "\n".join(lines)


if __name__ == "__main__":
    print(system_tree())
