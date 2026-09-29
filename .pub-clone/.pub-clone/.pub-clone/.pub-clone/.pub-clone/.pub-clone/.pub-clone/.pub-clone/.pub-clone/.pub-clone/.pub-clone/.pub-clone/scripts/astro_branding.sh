#!/usr/bin/env bash
# Branding ASTRO: logo robocika (z PNG, w kolorach) na konsoli i przy logowaniu SSH.
# Tworzy /etc/issue, /etc/issue.net, /etc/update-motd.d/00-astro oraz /usr/local/bin/astro-logo.
# Wymaga sudo (bez hasła). Użycie: bash scripts/astro_branding.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/venv/bin/python"
SHARE="/usr/local/share/astro"
WIDTH="${ASTRO_LOGO_WIDTH:-56}"

echo "[astro] buduję warianty logo (width=$WIDTH)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
"$PY" "$REPO/scripts/astro_logo.py" --width "$WIDTH" --build "$TMP"
sudo -n mkdir -p "$SHARE"
sudo -n cp "$TMP"/astro_logo_*.txt "$SHARE"/

echo "[astro] /usr/local/bin/astro-logo"
sudo -n tee /usr/local/bin/astro-logo >/dev/null <<EOF
#!/usr/bin/env bash
exec "$PY" "$REPO/scripts/astro_logo.py" "\$@"
EOF
sudo -n chmod 755 /usr/local/bin/astro-logo

echo "[astro] /etc/issue (16 kolorów, konsola) i /etc/issue.net (plain, pre-login)"
sudo -n cp "$SHARE/astro_logo_16.txt" /etc/issue
printf '\n   ASTRO agent   ·   terminal \\\\l\n\n' | sudo -n tee -a /etc/issue >/dev/null
sudo -n cp "$SHARE/astro_logo_plain.txt" /etc/issue.net

echo "[astro] /etc/update-motd.d/00-astro (truecolor + info)"
sudo -n rm -f /etc/update-motd.d/00-atena
sudo -n tee /etc/update-motd.d/00-astro >/dev/null <<EOF
#!/usr/bin/env bash
cat "$SHARE/astro_logo_true.txt"
printf '\\n'
printf '  \\033[1;36mASTRO\\033[0m  \\033[0;90m%s\\033[0m  ·  \\033[0;90mup %s\\033[0m\\n' \\
  "\$(hostname)" "\$(uptime -p 2>/dev/null | sed 's/^up //')"
printf '  \\033[0;90mIP\\033[0m %s   \\033[0;90mCPU\\033[0m %s   \\033[0;90mRAM\\033[0m %s\\n\\n' \\
  "\$(hostname -I 2>/dev/null | awk '{print \$1}')" \\
  "\$(nproc)" \\
  "\$(free -h 2>/dev/null | awk '/Mem:/{print \$3"/"\$2}')"
EOF
sudo -n chmod 755 /etc/update-motd.d/00-astro

echo "[astro] gotowe. Podgląd: astro-logo --mode truecolor"
