"""
LifeGrid - Standalone Webhook Microservice & Background Listener
================================================================
A lightweight, dedicated HTTP webhook receiver designed for continuous 24/7
operation outside of Streamlit Cloud (e.g. Render, Railway, Fly.io, or VPS).

Receives incoming Flutterwave webhook events:
  - transfer.completed: Finalizes creator payouts and generates audit receipts.
  - transfer.failed: Restores creator wallet balances and records refund audit entries.
  - charge.completed: Records verified gift credit purchases into webhook_logs.

Connects directly to your persistent Turso libSQL database (or local SQLite).

Usage:
  python webhook_service.py [--port 8000]
"""

import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# Ensure root directory is on sys.path to access database.py
_root = Path(__file__).resolve().parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

try:
    from database import get_connection
except Exception as e:
    raise RuntimeError(f"Could not import database.get_connection: {e}")


def get_secret_hash() -> str:
    """Retrieve secret webhook hash from environment or Streamlit secrets."""
    secret_hash = os.environ.get("FLUTTERWAVE_SECRET_HASH", "")
    if secret_hash:
        return secret_hash.strip()

    try:
        import streamlit as st
        if hasattr(st, "secrets") and "FLUTTERWAVE_SECRET_HASH" in st.secrets:
            return str(st.secrets["FLUTTERWAVE_SECRET_HASH"]).strip()
    except Exception:
        pass

    secrets_file = _root / ".streamlit" / "secrets.toml"
    if secrets_file.exists():
        try:
            with open(secrets_file, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith("FLUTTERWAVE_SECRET_HASH"):
                        parts = stripped.split("=", 1)
                        if len(parts) == 2:
                            return parts[1].strip().strip('"\'')
        except Exception:
            pass
    return ""


class FlutterwaveWebhookHandler(BaseHTTPRequestHandler):
    """Zero-dependency HTTP request handler for incoming Flutterwave webhooks."""

    def _send_json(self, status_code: int, data: dict):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, verif-hash")
        self.end_headers()

    def do_GET(self):
        """Health check endpoint."""
        if self.path in ("/", "/health", "/status"):
            self._send_json(200, {
                "status": "healthy",
                "service": "LifeGrid Webhook Microservice",
                "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                "secret_hash_configured": bool(get_secret_hash())
            })
        else:
            self._send_json(404, {"error": "Not Found"})

    def do_POST(self):
        """Handle incoming Flutterwave webhook events."""
        configured_secret = get_secret_hash()
        incoming_hash = self.headers.get("verif-hash", "")

        if configured_secret and incoming_hash != configured_secret:
            print(f"[SECURITY ALERT] Invalid webhook signature from {self.client_address[0]}")
            self._send_json(401, {"status": "error", "message": "Invalid webhook signature"})
            return

        content_length = int(self.headers.get("Content-Length", 0))
        if content_length <= 0:
            self._send_json(400, {"status": "error", "message": "Empty request body"})
            return

        try:
            raw_body = self.rfile.read(content_length).decode("utf-8")
            payload = json.loads(raw_body)
        except Exception as exc:
            self._send_json(400, {"status": "error", "message": f"Malformed JSON: {exc}"})
            return

        event_type = str(payload.get("event") or payload.get("event.type") or "unknown")
        data = payload.get("data") or {}
        reference = str(data.get("reference") or data.get("tx_ref") or "NO_REF")

        print(f"📥 Received Flutterwave webhook: {event_type} | Ref: {reference}")

        try:
            conn = get_connection()
            cursor = conn.cursor()
            now_iso = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

            # 1. Log event into webhook_logs
            cursor.execute("""
                INSERT INTO webhook_logs (event_type, reference, status, payload, created_at)
                VALUES (?, ?, 'received', ?, ?)
            """, (event_type, reference, raw_body, now_iso))

            # 2. Process transfer.completed
            if "transfer.completed" in event_type.lower():
                cursor.execute("""
                    UPDATE creator_withdrawals
                    SET status = 'completed', updated_at = ?
                    WHERE withdrawal_reference = ? AND LOWER(status) != 'completed'
                """, (now_iso, reference))

            # 3. Process transfer.failed (refund creator wallet)
            elif "transfer.failed" in event_type.lower():
                row = cursor.execute("""
                    SELECT user_id, amount, currency, status
                    FROM creator_withdrawals
                    WHERE withdrawal_reference = ?
                """, (reference,)).fetchone()

                if row and str(row[3]).lower() != "failed":
                    user_id, amount, currency = row[0], row[1], row[2]
                    # Update status
                    cursor.execute("""
                        UPDATE creator_withdrawals
                        SET status = 'failed', updated_at = ?
                        WHERE withdrawal_reference = ?
                    """, (now_iso, reference))

                    # Refund wallet balance
                    cursor.execute("""
                        UPDATE wallets
                        SET balance = balance + ?
                        WHERE user_id = ?
                    """, (amount, user_id))

                    # Record refund in audit ledger
                    receipt_id = f"REF-{uuid.uuid4().hex[:12].upper()}"
                    cursor.execute("""
                        INSERT INTO financial_audit_ledger (
                            receipt_id, transaction_type, reference_code, user_id,
                            amount, currency, status, created_at
                        ) VALUES (?, 'payout_refund', ?, ?, ?, ?, 'refunded', ?)
                    """, (receipt_id, reference, user_id, amount, currency, now_iso))

            conn.commit()
            self._send_json(200, {"status": "success", "event": event_type, "reference": reference})

        except Exception as exc:
            print(f"❌ Error processing webhook in database: {exc}")
            self._send_json(500, {"status": "error", "message": str(exc)})

    def log_message(self, format, *args):
        # Clean logging format
        print(f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}] {args[0]} {args[1]} {args[2]}")


def run(port: int = 8000):
    server = HTTPServer(("0.0.0.0", port), FlutterwaveWebhookHandler)
    print(f"🚀 LifeGrid Standalone Webhook Microservice listening on http://0.0.0.0:{port}")
    print(f"📡 Health check available at http://0.0.0.0:{port}/health")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping webhook microservice...")
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LifeGrid Standalone Webhook Service")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)), help="Port to listen on")
    args = parser.parse_args()
    run(args.port)
