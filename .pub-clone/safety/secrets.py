"""Ochrona sekretów i adresów prywatnych (przeniesione z Ateny, zachowanie 1:1)."""

import ipaddress
import os
import urllib.parse

SECRET_PATHS = tuple(os.path.realpath(os.path.expanduser(p)) for p in (
    "~/.atena-google.json", "~/.atena-github-token", "~/.git-credentials",
    "~/.atena-targets.json", "~/.netrc", "~/.ssh", "~/.config/atena",
    "/etc/atena-remote-ai.env",
    "~/.astro-google.json", "~/.astro-github-token", "~/.config/astro", "/etc/astro-remote.env",
))
SECRET_HINTS = (".atena-google", "atena-github-token", ".git-credentials",
                ".atena-targets", "atena-remote-ai.env", ".netrc",
                "id_rsa", "id_ed25519", "atena_pc", "/.ssh/",
                ".astro-google", "astro-github-token", "astro-remote.env")


def is_sensitive_path(path):
    try:
        p = os.path.realpath(os.path.expanduser(str(path).strip()))
    except Exception:
        return False
    return any(p == s or p.startswith(s + os.sep) for s in SECRET_PATHS)


def command_touches_secret(cmd):
    c = (cmd or "").lower()
    return any(h in c for h in SECRET_HINTS)


def is_private_url(url):
    """True dla adresów lokalnych/prywatnych (ochrona przed SSRF)."""
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower().strip("[]")
    except Exception:
        return True
    if not host or host == "localhost" or host.endswith((".local", ".internal", ".lan")):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
            or ip.is_multicast or ip.is_unspecified)
