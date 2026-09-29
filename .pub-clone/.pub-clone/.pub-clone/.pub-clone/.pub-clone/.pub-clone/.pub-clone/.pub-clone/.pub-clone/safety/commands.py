"""Reguły poleceń i potwierdzeń (przeniesione z Ateny, zachowanie 1:1)."""

import os
import re

from .secrets import command_touches_secret

BLOCKED_COMMANDS = (
    "rm -rf /", "mkfs", "dd if=", "dd of=", ":(){", "shutdown", "reboot", "poweroff",
    "passwd", "sudo ", "chmod 777 /", "chown -r /", "> /dev/sd", "init 0", "init 6",
)
BLOCKED_WRITE_PREFIXES = (
    "/etc", "/boot", "/usr", "/bin", "/sbin", "/lib", "/lib64", "/proc", "/sys", "/dev",
    "/root", "/var/lib", "/var/run", "/var/lock",
)
DANGEROUS_CMD = (
    "rm -rf /", "rm -fr /", "mkfs", "wipefs", "dd if=/dev/", "dd of=/dev/", "> /dev/sd",
    "chmod -r 777 /", "chown -r /", ":(){", "shutdown", "reboot", "poweroff", "halt ",
    "userdel", "passwd ", "visudo", "fdisk /dev/sd", "parted /dev/sd", "mv / ",
    "> /etc/sudoers", "> /etc/passwd", "rm -rf /etc", "rm -rf /boot",
)

SAFE_CMD_RE = re.compile(
    r"^\s*(sudo\s+)?(ls|cat|head|tail|less|grep|egrep|zgrep|find|stat|file|du|df|free|uptime|date|"
    r"hostname|uname|whoami|id|ps|pgrep|pidof|top|dmesg|journalctl|systemctl\s+(status|show|list|"
    r"is-active|is-enabled)|lsusb|lspci|lsblk|lscpu|blkid|mount|ip\s+(a|addr|route|link)|ss|netstat|"
    r"ping|vcgencmd|cat|i2cdetect|aplay|arecord|amixer|python3\s+--version|pip\s+list|apt-cache\s+"
    r"(search|show|policy)|dpkg\s+-l|apt\s+list|git\s+(status|log|diff)|modinfo|tree)\b",
    re.I)
SHELL_META_RE = re.compile(r"[;&|`$<>(){}\\\n\r]")

CONFIRM_RE = re.compile(r"\b(?:potwierdz\w*|zatwierdz\w*|autoryzuj\w*|tak potwierdzam)\b")
# Krótkie potwierdzenie = CAŁA wypowiedź („tak", „ok", „no"). Osobno od CONFIRM_RE, bo „tak"
# w środku zdania nie może zatwierdzać. Uwzględnia częsty błąd ASR „tad" (Whisper gubi końcowe k).
CONFIRM_SHORT_RE = re.compile(
    r"^\s*(?:tak|ta|tad|taj|no|nom|ok|okay|okej|okey|jasne|pewnie|dobrze|zgoda|"
    r"potwierdzam|zatwierdzam|autoryzuj[ęe]|autoryzuj|tak potwierdzam)\s*[.!]?\s*$", re.I)
CONFIRM_ONLY_RE = re.compile(
    r"^\s*(?:tak,?\s+|no\s+)?(?:potwierdzam|zatwierdzam|autoryzuj[ęe]|autoryzuj|"
    r"tak potwierdzam)\s*[.!]?\s*$", re.I)
CONFIRM_WORDS = ("potwierdzam", "zatwierdzam", "autoryzuje", "autoryzuję", "tak potwierdzam")
CANCEL_WORDS = ("anuluj", "nie", "stop", "przerwij", "rezygnuje", "rezygnuję", "wstrzymaj")
CANCEL_RE = re.compile(r"\b(?:nie|anuluj\w*|przerwij\w*|stop|rezygnuj\w*|wstrzymaj\w*)\b")

AGENT_UNSAFE_OPS = re.compile(r"[;&`$<>(){}\\\n\r]")
AGENT_READONLY_CMD = re.compile(
    r"^(?:sudo\s+)?(?:ls|cat|head|tail|wc|grep|egrep|rg|find|findmnt|stat|file|du|df|free|"
    r"uptime|date|hostname|uname|whoami|id|ps|pgrep|pidof|top|htop|dmesg|journalctl|"
    r"systemctl|lsusb|lspci|lsblk|lscpu|blkid|mountpoints|mount|lsns|ip|ss|netstat|ping|"
    r"traceroute|dig|nslookup|vcgencmd|i2cdetect|aplay|arecord|amixer|dpkg-query|apt-cache|"
    r"tree|sort|uniq|cut|tr|jq|zcat|zgrep|which|type|printenv|locale|timedatectl|sensors|"
    r"git|nproc|arch|lscpu)\b")
AGENT_BAD_FLAGS = re.compile(r"(?:-delete|-exec|-execdir|-ok\b|-i\b|--delete|--write|--output|"
                             r"-f\s*$|rm\s)")


def is_safe_command(cmd):
    return (bool(SAFE_CMD_RE.match(cmd)) and not SHELL_META_RE.search(cmd)
            and not command_touches_secret(cmd))


def is_blocked_command(cmd):
    low = " " + (cmd or "").lower()
    return any(b in low for b in BLOCKED_COMMANDS)


def safe_write_path(path):
    p = os.path.realpath(os.path.expanduser(str(path).strip()))
    for pref in BLOCKED_WRITE_PREFIXES:
        if p == pref or p.startswith(pref + "/"):
            return None
    return p


def agent_readonly_ok(cmd):
    """Czy polecenie jest bezpieczne do automatycznego wykonania (tylko odczyt)."""
    cmd = (cmd or "").strip()
    if not cmd or AGENT_UNSAFE_OPS.search(cmd):
        return False
    if command_touches_secret(cmd) or AGENT_BAD_FLAGS.search(cmd):
        return False
    for seg in cmd.split("|"):
        seg = seg.strip()
        if not seg or not bool(AGENT_READONLY_CMD.match(seg)):
            return False
        if seg.startswith(("git ", "systemctl ")):
            if not re.match(r"^(git\s+(status|log|diff|show|branch|remote|config\s+--get)|"
                            r"systemctl\s+(status|show|list|is-active|is-enabled|cat))", seg):
                return False
    return True
