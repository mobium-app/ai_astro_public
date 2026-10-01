"""Serwer Flask mobility (M0) — REST dla apki Astro Mobilne.

Uruchomienie:  python -m mobility.server [--port 8000] [--bind auto]
Wiązanie:      auto = adres Tailscale (100.x), fallback 127.0.0.1.
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from flask import Flask, jsonify, request

from . import chat
from .auth import check_token, load_token
from .store import MobilityStore

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "mobility.db"
APP_VERSION = "0.1.0"


def tailscale_ip() -> str | None:
    try:
        out = subprocess.run(["tailscale", "ip", "-4"], capture_output=True,
                             text=True, timeout=5).stdout.strip()
        return out.splitlines()[0] if out else None
    except Exception:
        return None


def create_app(db_path: Path = DB_PATH, token: str | None = None) -> Flask:
    app = Flask(__name__)
    app.config["STORE"] = MobilityStore(db_path)
    app.config["TOKEN"] = token or load_token()

    def authorized() -> bool:
        return check_token(request.headers.get("Authorization"),
                           app.config["TOKEN"])

    def require_auth():
        if not authorized():
            return jsonify({"error": "unauthorized"}), 401

    @app.before_request
    def _auth():
        if request.method == "OPTIONS":
            return "", 204
        if request.path in ("/health",):
            return None
        return require_auth()

    @app.get("/health")
    def health():
        store: MobilityStore = app.config["STORE"]
        return jsonify({"status": "ok", "version": APP_VERSION,
                        "counts": store.counts(),
                        "server_version": store.server_version()})

    @app.get("/context")
    def context():
        since = request.args.get("since", default=0, type=int)
        limit = min(request.args.get("limit", default=100, type=int), 500)
        store: MobilityStore = app.config["STORE"]
        return jsonify({"records": store.records_since(since, limit),
                        "knowledge_delta": [],
                        "server_version": store.server_version()})

    @app.post("/episodes")
    @app.post("/lessons")
    @app.post("/plans")
    def push_record():
        body = request.get_json(silent=True) or {}
        rec_type = request.path.strip("/")
        if not body.get("id"):
            return jsonify({"error": "id required"}), 400
        store: MobilityStore = app.config["STORE"]
        version = store.upsert_record(
            body["id"], rec_type, body.get("content") or "{}",
            body.get("updated_at") or time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            body.get("source") or "phone")
        return jsonify({"id": body["id"], "version": version})

    @app.post("/remember")
    def push_remember():
        body = request.get_json(silent=True) or {}
        if not body.get("id"):
            return jsonify({"error": "id required"}), 400
        store: MobilityStore = app.config["STORE"]
        content = body.get("content") or "{}"
        try:
            text = _json_get(content, "text", "notatka")
        except Exception:
            text = "notatka"
        when = _json_get(content, "when", "") if isinstance(content, str) else ""
        version = store.add_reminder(body["id"], text, when,
                                     body.get("updated_at") or time.strftime("%Y-%m-%dT%H:%M:%SZ"))
        return jsonify({"id": body["id"], "version": version})

    @app.get("/remember")
    def due_reminders():
        store: MobilityStore = app.config["STORE"]
        return jsonify({"items": store.due_reminders()})

    @app.post("/chat")
    def chat_endpoint():
        body = request.get_json(silent=True) or {}
        messages = body.get("messages")
        if not chat.validate_messages(messages):
            return jsonify({"error": "messages required"}), 400
        try:
            reply = chat.agent_reply(messages, body.get("language", "pl"))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 503
        return jsonify({"reply": reply, "backend": "mobility/0.1"})

    return app


def _json_get(content: str, key: str, default: str) -> str:
    import json
    if isinstance(content, str):
        try:
            data = json.loads(content)
        except Exception:
            return default
    else:
        data = content
    if isinstance(data, dict):
        return str(data.get(key, default))
    return default


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="mobility")
    parser.add_argument("--port", type=int, default=int(os.environ.get("MOBILITY_PORT", 8000)))
    parser.add_argument("--bind", default=os.environ.get("MOBILITY_BIND", "auto"))
    args = parser.parse_args(argv)

    bind = args.bind
    if bind == "auto":
        bind = tailscale_ip() or "127.0.0.1"
        print(f"[mobility] auto-bind → {bind}", file=sys.stderr)

    app = create_app()
    print(f"[mobility] v{APP_VERSION} na http://{bind}:{args.port}", file=sys.stderr)
    app.run(host=bind, port=args.port, threaded=True)


if __name__ == "__main__":
    main()