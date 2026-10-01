"""Setup/pairing dla kreatora apki (autoimport konfiguracji i głosu).

Endpointy (wymagają klucza parowania):
  GET /setup?key=<pairing>       -> {token_secret, ntfy_topic, name, server_version}
  GET /setup/voice               -> pl_PL-gosia-medium.onnx (bajty)
  GET /setup/voice-config        -> pl_PL-gosia-medium.onnx.json (bajty)

Klucz parowania: secrets/pairing.key (600, poza repo), krótki do przepisania na telefonie.
CLI: python -m astro.mobility.setup [--show|--regenerate]
"""

import secrets as _secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PAIRING_PATH = ROOT / "secrets" / "pairing.key"
VOICE_ONNX = ROOT / "models" / "piper" / "pl_PL-gosia-medium.onnx"
VOICE_JSON = ROOT / "models" / "piper" / "pl_PL-gosia-medium.onnx.json"


def pairing_key(regenerate: bool = False) -> str:
    if regenerate or not PAIRING_PATH.exists():
        PAIRING_PATH.parent.mkdir(parents=True, exist_ok=True)
        # 6 znaków alfanumerycznych bez mylących: łatwe do przepisania
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        key = "".join(_secrets.choice(alphabet) for _ in range(6))
        PAIRING_PATH.write_text(key)
        PAIRING_PATH.chmod(0o600)
        return key
    return PAIRING_PATH.read_text().strip()


def setup_payload(secret: str | None = None, topic: str | None = None,
                  name: str = "s5-astro") -> dict:
    if secret is None:
        secret_path = ROOT / "secrets" / "mobility.secret"
        secret = secret_path.read_text().strip() if secret_path.exists() else ""
    if topic is None:
        topic_path = ROOT / "secrets" / "ntfy_topic"
        topic = topic_path.read_text().strip() if topic_path.exists() else ""
    return {
        "token_secret": secret,
        "ntfy_topic": topic,
        "name": name,
        "server_version": "0.2.0",
        "voice": VOICE_ONNX.name,
        "voice_size": VOICE_ONNX.stat().st_size if VOICE_ONNX.exists() else 0,
    }


def main(argv=None) -> int:
    mode = (argv or sys.argv[1:])
    if "--regenerate" in mode:
        key = pairing_key(regenerate=True)
        print(f"Nowy klucz parowania: {key}  (zapisany w {PAIRING_PATH})")
        return 0
    print(pairing_key())
    return 0


if __name__ == "__main__":
    sys.exit(main())