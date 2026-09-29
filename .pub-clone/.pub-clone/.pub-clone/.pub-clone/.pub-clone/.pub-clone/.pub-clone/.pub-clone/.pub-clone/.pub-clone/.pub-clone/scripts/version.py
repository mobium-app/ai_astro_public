#!/usr/bin/env python3
"""Wersjonowanie ASTRO według Semantic Versioning 2.0.0 + Keep a Changelog.

Użycie:
    python3 scripts/version.py --show                 # aktualna wersja + git describe
    python3 scripts/version.py --bump patch           # 0.1.0 -> 0.1.1 (+ commit + tag)
    python3 scripts/version.py --bump minor --no-git   # tylko pliki (bez commit/tag)
    python3 scripts/version.py --tag                   # utwórz tag vX.Y.Z dla VERSION

Zasady:
  * MAJOR — niekompatybilne zmiany API,
  * MINOR — nowe funkcje (wstecznie zgodne),
  * PATCH — poprawki błędów (wstecznie zgodne).
"""

import argparse
import datetime
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_FILE = os.path.join(REPO, "VERSION")
CHANGELOG = os.path.join(REPO, "CHANGELOG.md")
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def read_version():
    with open(VERSION_FILE, encoding="utf-8") as fh:
        return fh.read().strip()


def write_version(version):
    with open(VERSION_FILE, "w", encoding="utf-8") as fh:
        fh.write(version + "\n")


def bump(version, part):
    match = SEMVER.match(version)
    if not match:
        raise SystemExit(f"VERSION nie jest SemVer: {version!r}")
    major, minor, patch = (int(x) for x in match.groups())
    if part == "major":
        major, minor, patch = major + 1, 0, 0
    elif part == "minor":
        minor, patch = minor + 1, 0
    else:
        patch += 1
    return f"{major}.{minor}.{patch}"


def changelog_release(new_version):
    """Przenosi sekcję [Unreleased] do nowej wersji z dzisiejszą datą."""
    if not os.path.exists(CHANGELOG):
        return
    with open(CHANGELOG, encoding="utf-8") as fh:
        text = fh.read()
    today = datetime.date.today().isoformat()
    text = text.replace("## [Unreleased]",
                        f"## [Unreleased]\n\n## [{new_version}] - {today}", 1)
    with open(CHANGELOG, "w", encoding="utf-8") as fh:
        fh.write(text)


def git(*args, check=True):
    return subprocess.run(["git", "-C", REPO, *args], check=check)


def current_tag(version):
    return f"v{version}"


def main():
    ap = argparse.ArgumentParser(description="Wersjonowanie ASTRO (SemVer)")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--bump", choices=["major", "minor", "patch"])
    ap.add_argument("--tag", action="store_true", help="utwórz tag dla bieżącej VERSION")
    ap.add_argument("--no-git", action="store_true", help="bez commit/tag")
    args = ap.parse_args()

    version = read_version()

    if args.show or (not args.bump and not args.tag):
        try:
            desc = subprocess.run(["git", "-C", REPO, "describe", "--tags", "--always"],
                                  capture_output=True, text=True, check=False).stdout.strip()
        except Exception:
            desc = ""
        print(f"ASTRO {version}" + (f"  (git: {desc})" if desc else ""))
        return 0

    if args.bump:
        new = bump(version, args.bump)
        write_version(new)
        changelog_release(new)
        print(f"{version} -> {new}")
        if not args.no_git:
            git("add", "VERSION", "CHANGELOG.md")
            git("commit", "-m", f"astro(release): v{new}")
            git("tag", "-a", current_tag(new), "-m", f"ASTRO v{new}")
            print(f"tag: {current_tag(new)}")
        return 0

    if args.tag:
        tag = current_tag(version)
        existing = subprocess.run(["git", "-C", REPO, "tag", "-l", tag],
                                  capture_output=True, text=True, check=False).stdout.strip()
        if existing:
            print(f"tag już istnieje: {tag}")
        else:
            git("tag", "-a", tag, "-m", f"ASTRO v{version}")
            print(f"tag: {tag}")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
