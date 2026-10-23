"""
21 - Webhook & Monitor
LifeGrid Automated Payout Webhook Handler & Financial Operations Monitor

Production Streamlit dashboard + background HTTP listener for Flutterwave webhook events.
Handles:
  1. Automated Payout Reconciliation (transfer.completed and transfer.failed)
  2. Automatic Wallet Balance Restoration & Creator Profiles Sync on Failed Transfers
  3. Double-Spend & Idempotent Webhook Guardrails
  4. Unified Notifications Sync (05 - Notifications + withdrawal_notifications)
  5. Cryptographic Financial Audit Ledger & Digital Receipt Generation
  6. Live Operations & Manual Reconciler
"""

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

try:
    import streamlit as st
    HAS_STREAMLIT = True
except ImportError:
    HAS_STREAMLIT = False


# =========================================================
# CONFIGURATION & DATABASE ACCESS
# =========================================================
def get_secret_hash():
    """Retrieve secret webhook hash from environment or Streamlit secrets."""
    secret_hash = os.environ.get("FLUTTERWAVE_SECRET_HASH", "")
    if secret_hash:
        return secret_hash

    if HAS_STREAMLIT:
        try:
            if hasattr(st, "secrets") and "FLUTTERWAVE_SECRET_HASH" in st.secrets:
                return str(st.secrets["FLUTTERWAVE_SECRET_HASH"]).strip()
        except Exception:
            pass

    secrets_file = os.path.join(os.getcwd(), ".streamlit", "secrets.toml")
    if os.path.exists(secrets_file):
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


def get_db():
    """Connect to SQLite database with robust concurrency settings."""
    try:
        from database import get_connection
        return get_connection()
    except Exception:
        db_path = os.environ.get("LIFEGRID_DB_PATH", "lifegrid.db")
        return sqlite3.connect(db_path, check_same_thread=False)


def get_table_columns(conn, table_name):
    """Retrieve list of column names for a given SQLite table."""
    try:
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({table_name})")
        return [row[1] for row in cursor.fetchall()]
    except Exception:
        return []


def ensure_financial_and_webhook_tables(conn):
    """Ensure all required tables exist and migrate missing columns."""
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS webhook_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            reference TEXT,
            status TEXT NOT NULL,
            payload TEXT NOT NULL,
            received_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS withdrawal_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            withdrawal_reference TEXT NOT NULL,
            notification_type TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            currency TEXT DEFAULT 'USD',
            amount REAL DEFAULT 0.0,
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            notification_type TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            reference_type TEXT,
            reference_id TEXT,
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS creator_withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            currency TEXT NOT NULL DEFAULT 'NGN',
            fee REAL DEFAULT 0.0,
            net_amount REAL,
            status TEXT NOT NULL DEFAULT 'Pending',
            withdrawal_reference TEXT UNIQUE,
            transaction_reference TEXT,
            payout_method TEXT DEFAULT 'Bank Account',
            payment_method TEXT DEFAULT 'bank_transfer',
            bank_name TEXT,
            account_number TEXT,
            account_name TEXT,
            bank_code TEXT,
            notes TEXT,
            created_at TEXT,
            processed_at TEXT
        )
    """)

    existing_w_cols = get_table_columns(conn, "creator_withdrawals")
    w_migrations = {
        "currency": "TEXT NOT NULL DEFAULT 'NGN'",
        "fee": "REAL DEFAULT 0.0",
        "net_amount": "REAL DEFAULT 0.0",
        "transaction_reference": "TEXT",
        "payout_method": "TEXT DEFAULT 'Bank Account'",
        "payment_method": "TEXT DEFAULT 'bank_transfer'",
        "bank_name": "TEXT",
        "account_number": "TEXT",
        "account_name": "TEXT",
        "bank_code": "TEXT",
        "notes": "TEXT",
        "created_at": "TEXT",
        "processed_at": "TEXT"
    }
    for col, col_def in w_migrations.items():
        if col not in existing_w_cols:
            try:
                cursor.execute(f"ALTER TABLE creator_withdrawals ADD COLUMN {col} {col_def}")
            except Exception:
                pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wallets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            currency TEXT NOT NULL DEFAULT 'USD',
            balance REAL NOT NULL DEFAULT 0.0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, currency)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wallet_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            transaction_type TEXT NOT NULL,
            amount REAL NOT NULL,
            currency TEXT NOT NULL DEFAULT 'USD',
            description TEXT,
            reference TEXT UNIQUE NOT NULL,
            status TEXT NOT NULL DEFAULT 'Completed',
            counterparty_user_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS creator_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            display_name TEXT,
            total_earnings REAL DEFAULT 0.0,
            pending_balance REAL DEFAULT 0.0,
            kyc_tier INTEGER DEFAULT 1
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS idempotency_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            idempotency_key TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL,
            request_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PROCESSING',
            response_payload TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS financial_audit_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ledger_entry_id TEXT UNIQUE NOT NULL,
            transaction_ref TEXT NOT NULL,
            event_type TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            debit REAL DEFAULT 0.0,
            credit REAL DEFAULT 0.0,
            fee REAL DEFAULT 0.0,
            balance_after REAL NOT NULL,
            currency TEXT NOT NULL,
            prev_hash TEXT NOT NULL,
            entry_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()


# =========================================================
# AUDIT LEDGER & RECEIPT HELPERS
# =========================================================
def get_latest_audit_hash(cursor):
    """Retrieve hash of latest audit record to maintain tamper-evident blockchain."""
    try:
        cursor.execute("SELECT entry_hash FROM financial_audit_ledger ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        return row[0] if row else "GENESIS_BLOCK_0000000000000000"
    except Exception:
        return "GENESIS_BLOCK_0000000000000000"


def record_audit_entry(cursor, tx_ref, event_type, user_id, debit, credit, fee, balance_after, currency):
    """Append a cryptographically sealed SHA-256 audit entry."""
    prev_hash = get_latest_audit_hash(cursor)
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    ledger_id = f"LEDGER-{uuid.uuid4().hex[:12].upper()}"

    payload = f"{prev_hash}|{tx_ref}|{event_type}|{user_id}|{debit:.4f}|{credit:.4f}|{fee:.4f}|{balance_after:.4f}|{currency}|{now_str}"
    entry_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    try:
        cursor.execute("""
            INSERT INTO financial_audit_ledger (
                ledger_entry_id, transaction_ref, event_type, user_id,
                debit, credit, fee, balance_after, currency, prev_hash, entry_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (ledger_id, tx_ref, event_type, user_id, debit, credit, fee, balance_after, currency, prev_hash, entry_hash, now_str))
    except Exception:
        pass
    return ledger_id, entry_hash


def generate_receipt_text(tx_data):
    """Generate official LifeGrid ASCII receipt."""
    ref = tx_data.get("reference", "UNKNOWN")
    amt = tx_data.get("amount", 0.0)
    fee = tx_data.get("fee", 0.0)
    net = tx_data.get("net_amount", amt)
    curr = tx_data.get("currency", "NGN")
    status = tx_data.get("status", "Completed")
    ts = tx_data.get("timestamp", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"))
    bank = tx_data.get("bank_name", "N/A")
    acct = tx_data.get("account_number", "N/A")
    flw_ref = tx_data.get("flw_ref", "N/A")

    return f"""==================================================
           LIFEGRID OFFICIAL PAYOUT RECEIPT       
==================================================
Payout Reference     : {ref}
Date / Time (UTC)    : {ts}
Status               : {status.upper()}
--------------------------------------------------
Recipient User ID    : #{tx_data.get('user_id', 'N/A')}
Destination Bank     : {bank}
Account Number       : {acct}
--------------------------------------------------
Gross Payout Amount  : {curr} {amt:,.2f}
Platform / Bank Fee  : {curr} {fee:,.2f}
Net Disbursed Amount : {curr} {net:,.2f}
--------------------------------------------------
Gateway Reference    : {flw_ref}
Verification Hash    : {hashlib.sha256(f"{ref}:{amt}:{curr}:{ts}".encode()).hexdigest()[:32]}
Security Standard    : Atomic Payout Engine v2.5 (LifeGrid)
==================================================
Funds disbursed via Flutterwave Secure Transfer.
"""


# =========================================================
# WEBHOOK EVENT PROCESSORS
# =========================================================
def process_transfer_completed(payload):
    data = payload.get("data", {})
    transfer_ref = data.get("reference") or data.get("tx_ref") or ""
    flw_ref = str(data.get("id") or data.get("flw_ref") or "FLW-PAYOUT-AUTO")
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db()
    ensure_financial_and_webhook_tables(conn)
    cursor = conn.cursor()

    cols = get_table_columns(conn, "creator_withdrawals")
    user_col = "user_id" if "user_id" in cols else ("creator_id" if "creator_id" in cols else "user_id")

    cursor.execute(f"""
        SELECT id, {user_col}, amount, currency, status, notes, fee, net_amount, bank_name, account_number
        FROM creator_withdrawals
        WHERE withdrawal_reference = ? OR transaction_reference = ?
        LIMIT 1
    """, (transfer_ref, transfer_ref))
    record = cursor.fetchone()

    if not record:
        conn.close()
        return {"status": "not_found", "message": f"Withdrawal ref '{transfer_ref}' not found."}

    w_id, user_id, orig_amount, orig_currency, cur_status, existing_notes, fee, net_amount, bank_name, acct_num = record
    fee = fee or 0.0
    net_amount = net_amount or orig_amount

    if str(cur_status or "").lower() == "completed":
        conn.close()
        return {"status": "already_completed", "message": "Withdrawal was already completed."}

    try:
        cursor.execute("BEGIN IMMEDIATE")
        updated_notes = f"{existing_notes or ''}\n[{now_str} Webhook: Transfer confirmed via Flutterwave ref {flw_ref}]".strip()
        cursor.execute("""
            UPDATE creator_withdrawals
            SET status = 'Completed', processed_at = ?, transaction_reference = ?, notes = ?
            WHERE id = ?
        """, (now_str, flw_ref, updated_notes, w_id))

        cursor.execute("""
            INSERT OR REPLACE INTO wallet_transactions (
                user_id, transaction_type, amount, currency, description, reference, status
            ) VALUES (?, 'PAYOUT_COMPLETED', ?, ?, ?, ?, 'Completed')
        """, (user_id, orig_amount, orig_currency, f"Payout of {orig_currency} {orig_amount:,.2f} disbursed to {bank_name or 'Bank'}", f"WD-{transfer_ref}"))

        notif_msg = f"Your withdrawal of {orig_currency} {orig_amount:,.2f} has been successfully disbursed by Flutterwave (Ref: {flw_ref})."

        cursor.execute("""
            INSERT INTO notifications (user_id, notification_type, title, message, reference_type, reference_id, is_read, created_at)
            VALUES (?, 'Wallet', 'Withdrawal Successful', ?, 'creator_withdrawals', ?, 0, ?)
        """, (user_id, notif_msg, transfer_ref, now_str))

        cursor.execute("""
            INSERT INTO withdrawal_notifications
            (user_id, withdrawal_reference, notification_type, title, message, currency, amount, is_read, created_at)
            VALUES (?, ?, 'completed', 'Withdrawal Successful', ?, ?, ?, 0, ?)
        """, (user_id, transfer_ref, notif_msg, orig_currency, orig_amount, now_str))

        cursor.execute("SELECT balance FROM wallets WHERE user_id = ? AND currency = ?", (user_id, orig_currency))
        w_bal_row = cursor.fetchone()
        cur_bal = w_bal_row[0] if w_bal_row else 0.0
        record_audit_entry(cursor, transfer_ref, "PAYOUT_COMPLETED", user_id, 0.0, 0.0, fee, cur_bal, orig_currency)

        conn.commit()
        conn.close()
        return {"status": "success", "message": f"Withdrawal '{transfer_ref}' marked as Completed."}
    except Exception as e:
        cursor.execute("ROLLBACK")
        conn.close()
        return {"status": "error", "message": str(e)}


def process_transfer_failed(payload):
    data = payload.get("data", {})
    transfer_ref = data.get("reference") or data.get("tx_ref") or ""
    failure_reason = data.get("complete_message") or data.get("reason") or "Transfer declined by bank"
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db()
    ensure_financial_and_webhook_tables(conn)
    cursor = conn.cursor()

    cols = get_table_columns(conn, "creator_withdrawals")
    user_col = "user_id" if "user_id" in cols else ("creator_id" if "creator_id" in cols else "user_id")

    cursor.execute(f"""
        SELECT id, {user_col}, amount, currency, status, notes
        FROM creator_withdrawals
        WHERE withdrawal_reference = ? OR transaction_reference = ?
        LIMIT 1
    """, (transfer_ref, transfer_ref))
    record = cursor.fetchone()

    if not record:
        conn.close()
        return {"status": "not_found", "message": f"Withdrawal ref '{transfer_ref}' not found."}

    w_id, user_id, orig_amount, orig_currency, cur_status, existing_notes = record

    if str(cur_status or "").lower() == "completed":
        conn.close()
        return {"status": "ignored", "message": "Cannot fail an already completed withdrawal."}
    if str(cur_status or "").lower() in ("rejected", "failed", "refunded"):
        conn.close()
        return {"status": "already_refunded", "message": "Withdrawal was already marked Failed/Rejected."}

    try:
        cursor.execute("BEGIN IMMEDIATE")
        updated_notes = f"{existing_notes or ''}\n[{now_str} Webhook: Transfer failed - {failure_reason}. Balance restored.]".strip()
        cursor.execute("""
            UPDATE creator_withdrawals
            SET status = 'Rejected', processed_at = ?, notes = ?
            WHERE id = ?
        """, (now_str, updated_notes, w_id))

        cursor.execute("SELECT balance FROM wallets WHERE user_id = ? AND currency = ?", (user_id, orig_currency))
        w_bal_row = cursor.fetchone()
        old_bal = float(w_bal_row[0]) if w_bal_row else 0.0
        new_bal = round(old_bal + orig_amount, 2)

        if w_bal_row:
            cursor.execute("UPDATE wallets SET balance = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ? AND currency = ?",
                           (new_bal, user_id, orig_currency))
        else:
            cursor.execute("INSERT INTO wallets (user_id, currency, balance) VALUES (?, ?, ?)",
                           (user_id, orig_currency, new_bal))

        p_cols = get_table_columns(conn, "creator_profiles")
        p_user_col = "user_id" if "user_id" in p_cols else ("creator_id" if "creator_id" in p_cols else "user_id")
        earn_col = "total_earnings" if "total_earnings" in p_cols else ("earnings" if "earnings" in p_cols else "total_earnings")
        try:
            cursor.execute(f"UPDATE creator_profiles SET {earn_col} = {earn_col} + ? WHERE {p_user_col} = ?", (orig_amount, user_id))
        except Exception:
            pass

        try:
            rec_cols = get_table_columns(conn, "creator_receiving_accounts")
            if "available_balance" in rec_cols:
                cursor.execute(f"UPDATE creator_receiving_accounts SET available_balance = available_balance + ? WHERE user_id = ? AND currency = ?", (orig_amount, user_id, orig_currency))
            elif "balance" in rec_cols:
                cursor.execute(f"UPDATE creator_receiving_accounts SET balance = balance + ? WHERE user_id = ? AND currency = ?", (orig_amount, user_id, orig_currency))
        except Exception:
            pass

        cursor.execute("""
            INSERT INTO wallet_transactions (
                user_id, transaction_type, amount, currency, description, reference, status
            ) VALUES (?, 'PAYOUT_REFUNDED', ?, ?, ?, ?, 'Completed')
        """, (user_id, orig_amount, orig_currency, f"Refund for failed payout: {failure_reason}", f"REFUND-{transfer_ref}"))

        notif_msg = f"Your withdrawal of {orig_currency} {orig_amount:,.2f} could not be delivered ({failure_reason}). Funds refunded to your wallet."
        cursor.execute("""
            INSERT INTO notifications (user_id, notification_type, title, message, reference_type, reference_id, is_read, created_at)
            VALUES (?, 'Wallet', 'Withdrawal Failed & Refunded', ?, 'creator_withdrawals', ?, 0, ?)
        """, (user_id, notif_msg, transfer_ref, now_str))

        cursor.execute("""
            INSERT INTO withdrawal_notifications
            (user_id, withdrawal_reference, notification_type, title, message, currency, amount, is_read, created_at)
            VALUES (?, ?, 'rejected', 'Withdrawal Failed & Refunded', ?, ?, ?, 0, ?)
        """, (user_id, transfer_ref, notif_msg, orig_currency, orig_amount, now_str))

        record_audit_entry(cursor, transfer_ref, "PAYOUT_REFUND_RESTORED", user_id, 0.0, orig_amount, 0.0, new_bal, orig_currency)

        conn.commit()
        conn.close()
        return {"status": "refunded", "message": f"Withdrawal '{transfer_ref}' refunded to user #{user_id}."}
    except Exception as e:
        cursor.execute("ROLLBACK")
        conn.close()
        return {"status": "error", "message": str(e)}


# =========================================================
# HTTP REQUEST HANDLER
# =========================================================
class FlutterwaveWebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        configured_secret = get_secret_hash()
        provided_hash = self.headers.get("verif-hash")

        if configured_secret and provided_hash != configured_secret:
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Invalid verif-hash signature"}).encode())
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception as e:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": f"Invalid JSON payload: {str(e)}"}).encode())
            return

        event_type = payload.get("event") or payload.get("event.type") or "unknown"
        ref = payload.get("data", {}).get("reference", "")

        conn = get_db()
        ensure_financial_and_webhook_tables(conn)
        conn.execute("""
            INSERT INTO webhook_logs (event_type, reference, status, payload, received_at)
            VALUES (?, ?, 'received', ?, ?)
        """, (event_type, ref, json.dumps(payload), datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()

        if event_type in ["transfer.completed", "transfer_completed"]:
            result = process_transfer_completed(payload)
        elif event_type in ["transfer.failed", "transfer_failed"]:
            result = process_transfer_failed(payload)
        else:
            result = {"status": "acknowledged", "message": f"Event '{event_type}' received and logged."}

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "status": "healthy",
            "service": "LifeGrid Flutterwave Webhook Listener & Payout Reconciler",
            "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        }).encode())

    def log_message(self, format, *args):
        pass


def run_server(port=8000):
    server = HTTPServer(("0.0.0.0", port), FlutterwaveWebhookHandler)
    print(f"🚀 LifeGrid Webhook Server running on http://0.0.0.0:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping webhook server...")
        server.server_close()


# =========================================================
# STREAMLIT USER INTERFACE
# =========================================================
def render_streamlit_ui():
    st.set_page_config(
        page_title="21 - Webhook & Monitor | LifeGrid",
        page_icon="⚡",
        layout="wide"
    )

    st.title("⚡ 21 - Webhook & Payout Monitor")
    st.caption("Live Flutterwave transfer webhook listener, automated payout reconciliation, and audit security.")

    conn = get_db()
    ensure_financial_and_webhook_tables(conn)

    secret_hash = get_secret_hash()
    c = conn.cursor()
    total_logs = c.execute("SELECT COUNT(*) FROM webhook_logs").fetchone()[0]
    pending_w = c.execute("SELECT COUNT(*) FROM creator_withdrawals WHERE LOWER(status) IN ('pending', 'processing')").fetchone()[0]
    total_ledger = c.execute("SELECT COUNT(*) FROM financial_audit_ledger").fetchone()[0]

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if secret_hash:
            st.success(f"🔐 **Secret Hash**: `{secret_hash[:4]}••••{secret_hash[-4:] if len(secret_hash) > 8 else ''}`")
        else:
            st.warning("⚠️ **Secret Hash**: Unset\nSet `FLUTTERWAVE_SECRET_HASH` in `.streamlit/secrets.toml`")

    with col2:
        st.info(f"📥 **Logged Events**: {total_logs} webhook calls")

    with col3:
        st.metric("⏳ Pending / Processing", pending_w)

    with col4:
        st.metric("🛡️ Immutable Audit Entries", total_ledger)

    tabs = st.tabs([
        "⚡ Live Operations & Reconciler",
        "📊 Withdrawal Statuses",
        "📜 Webhook Logs",
        "🔔 Dispatched Notifications",
        "🧾 Digital Receipts",
        "⚙️ Setup & Deployment Guide"
    ])

    # ---------------- TAB 1: LIVE OPERATIONS & RECONCILER ----------------
    with tabs[0]:
        st.subheader("Live Payout Operations & Manual Reconciler")
        st.caption("Manage real incoming webhooks, verify pending creator withdrawals, and resolve status with Flutterwave.")

        col_left, col_right = st.columns([1, 1])

        with col_left:
            st.markdown("### 📡 Live Webhook Listener Status")
            st.write(
                "In production, Flutterwave sends real-time POST notifications to your server when transfers complete or fail. "
                "The endpoint validates the `verif-hash` header and automatically updates creator balances."
            )
            if secret_hash:
                st.success("✅ Webhook security signature (`verif-hash`) is configured and active.")
            else:
                st.warning("⚠️ Webhook security signature is not yet configured. Please set `FLUTTERWAVE_SECRET_HASH`.")

            st.info("""
            **Command to run the standalone background listener on your production server:**
            ```bash
            python pages/21-webhook&monitor.py --serve --port 8000
            ```
            """)

        with col_right:
            st.markdown("### 🔄 Reconcile Pending Withdrawals")
            c = conn.cursor()
            cols = get_table_columns(conn, "creator_withdrawals")
            user_col = "user_id" if "user_id" in cols else ("creator_id" if "creator_id" in cols else "user_id")

            pending_rows = c.execute(f"""
                SELECT id, {user_col}, amount, currency, status, withdrawal_reference, bank_name, account_number
                FROM creator_withdrawals
                WHERE LOWER(status) IN ('pending', 'processing')
                ORDER BY id DESC
            """).fetchall()

            if not pending_rows:
                st.success("✅ All clear! There are currently no pending or processing withdrawal requests awaiting reconciliation.")
            else:
                p_options = {
                    f"Ref: {r[5]} | User #{r[1]} | {r[3]} {r[2]:,.2f} | {r[6] or 'Bank'}: {r[7] or 'N/A'}": r
                    for r in pending_rows
                }
                selected_label = st.selectbox("Select Pending Request to Reconcile:", list(p_options.keys()))
                sel_row = p_options[selected_label]

                manual_ref = st.text_input("Flutterwave Transaction Reference (FLW-Ref)", value=f"FLW-MANUAL-{sel_row[5]}")
                rec_action = st.radio("Resolution Action", ["Confirm & Complete Transfer", "Decline & Refund Creator Wallet"], horizontal=True)

                if st.button("Apply Resolution", type="primary", use_container_width=True):
                    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                    if "Confirm" in rec_action:
                        payload = {
                            "event": "transfer.completed",
                            "data": {
                                "reference": sel_row[5],
                                "id": manual_ref,
                                "amount": sel_row[2],
                                "currency": sel_row[3]
                            }
                        }
                        res = process_transfer_completed(payload)
                        st.success(f"Result: {res.get('message')}")
                    else:
                        payload = {
                            "event": "transfer.failed",
                            "data": {
                                "reference": sel_row[5],
                                "reason": "Manually declined or bank returned transfer",
                                "amount": sel_row[2],
                                "currency": sel_row[3]
                            }
                        }
                        res = process_transfer_failed(payload)
                        st.warning(f"Result: {res.get('message')}")
                    st.rerun()

    # ---------------- TAB 2: WITHDRAWAL STATUSES ----------------
    with tabs[1]:
        st.subheader("Creator Withdrawals Database")
        c = conn.cursor()
        cols = get_table_columns(conn, "creator_withdrawals")
        user_col = "user_id" if "user_id" in cols else ("creator_id" if "creator_id" in cols else "user_id")

        records = c.execute(f"""
            SELECT id, {user_col}, amount, currency, status, withdrawal_reference, transaction_reference, notes, processed_at
            FROM creator_withdrawals
            ORDER BY id DESC LIMIT 50
        """).fetchall()

        if records:
            display_data = []
            for r in records:
                display_data.append({
                    "ID": r[0],
                    "User ID": r[1],
                    "Amount": f"{r[3]} {r[2]:,.2f}",
                    "Status": r[4],
                    "Withdrawal Ref": r[5] or "N/A",
                    "FLW Ref": r[6] or "N/A",
                    "Processed At": r[8] or "Pending",
                    "Notes": (r[7] or "")[:70] + ("..." if len(r[7] or "") > 70 else "")
                })
            st.dataframe(display_data, use_container_width=True)
        else:
            st.info("No withdrawal records found in database.")

    # ---------------- TAB 3: WEBHOOK LOGS ----------------
    with tabs[2]:
        st.subheader("Incoming Webhook Activity Logs")
        c = conn.cursor()
        logs = c.execute("""
            SELECT id, event_type, reference, status, received_at, payload
            FROM webhook_logs
            ORDER BY id DESC LIMIT 50
        """).fetchall()

        if logs:
            col_a, col_b = st.columns([3, 2])
            with col_a:
                table_items = [
                    {
                        "ID": l[0],
                        "Event": l[1],
                        "Reference": l[2],
                        "Status": l[3],
                        "Received At": l[4]
                    } for l in logs
                ]
                st.dataframe(table_items, use_container_width=True)

            with col_b:
                st.write("**Inspect Raw JSON Payload**")
                log_options = {f"Log #{l[0]} - {l[1]} ({l[4]})": l[5] for l in logs}
                chosen_log = st.selectbox("Select Log Entry:", list(log_options.keys()))
                if chosen_log:
                    try:
                        parsed = json.loads(log_options[chosen_log])
                        st.json(parsed)
                    except Exception:
                        st.code(log_options[chosen_log])
        else:
            st.info("No webhook activity recorded yet.")

    # ---------------- TAB 4: NOTIFICATIONS ----------------
    with tabs[3]:
        st.subheader("Dispatched Payout Notifications (Synced with 05 - Notifications)")
        c = conn.cursor()
        notifs = c.execute("""
            SELECT id, user_id, notification_type, title, message, reference_type, reference_id, is_read, created_at
            FROM notifications
            WHERE notification_type IN ('Wallet', 'creator_withdrawals', 'PAYOUT')
            ORDER BY id DESC LIMIT 50
        """).fetchall()

        if notifs:
            for n in notifs:
                icon = "💰" if "Successful" in n[3] else "⚠️"
                with st.expander(f"{icon} {n[3]} (User #{n[1]}) - {n[8]}"):
                    st.write(f"**Reference:** `{n[6]}`")
                    st.write(f"**Message:** {n[4]}")
        else:
            st.info("No financial notifications created yet.")

    # ---------------- TAB 5: DIGITAL RECEIPTS ----------------
    with tabs[4]:
        st.subheader("Official LifeGrid Digital Receipts")
        c = conn.cursor()
        cols = get_table_columns(conn, "creator_withdrawals")

        fee_col = "fee" if "fee" in cols else "0.0 AS fee"
        net_col = "net_amount" if "net_amount" in cols else "amount AS net_amount"
        user_col = "user_id" if "user_id" in cols else ("creator_id" if "creator_id" in cols else "1 AS user_id")
        bank_col = "bank_name" if "bank_name" in cols else "'' AS bank_name"
        acct_col = "account_number" if "account_number" in cols else "'' AS account_number"
        proc_col = "processed_at" if "processed_at" in cols else "created_at AS processed_at"
        tx_ref_col = "transaction_reference" if "transaction_reference" in cols else "'' AS transaction_reference"

        completed_w = c.execute(f"""
            SELECT withdrawal_reference, {user_col}, amount, currency, {fee_col}, {net_col}, status, {bank_col}, {acct_col}, {proc_col}, {tx_ref_col}
            FROM creator_withdrawals
            ORDER BY id DESC LIMIT 20
        """).fetchall()

        if completed_w:
            w_choices = {f"{w[0]} | User #{w[1]} | {w[3]} {w[2]:,.2f} ({w[6]})": w for w in completed_w}
            selected_w_key = st.selectbox("Select Transaction for Receipt:", list(w_choices.keys()))
            selected_w_data = w_choices[selected_w_key]

            receipt_payload = {
                "reference": selected_w_data[0],
                "user_id": selected_w_data[1],
                "amount": selected_w_data[2],
                "currency": selected_w_data[3],
                "fee": selected_w_data[4] or 0.0,
                "net_amount": selected_w_data[5] or selected_w_data[2],
                "status": selected_w_data[6],
                "bank_name": selected_w_data[7] or "N/A",
                "account_number": selected_w_data[8] or "N/A",
                "timestamp": selected_w_data[9] or datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                "flw_ref": selected_w_data[10] or "N/A"
            }

            receipt_text = generate_receipt_text(receipt_payload)
            st.code(receipt_text, language="text")
            st.download_button(
                "📥 Download Official Receipt (.txt)",
                receipt_text,
                file_name=f"LifeGrid_Receipt_{selected_w_data[0]}.txt",
                mime="text/plain"
            )
        else:
            st.info("No withdrawals available to generate receipts.")

    # ---------------- TAB 6: PRODUCTION SETUP GUIDE ----------------
    with tabs[5]:
        st.subheader("Flutterwave Live Webhook Setup")
        st.markdown("""
        ### Connecting Live Flutterwave Webhooks:

        1. **Log in to Flutterwave Dashboard**:
           - Navigate to **Settings > Webhooks**.
        2. **Enter Webhook URL**:
           - Set your endpoint, e.g. `https://your-domain.com/webhook`.
           - In development/testing, forward traffic using ngrok: `ngrok http 8000`.
        3. **Set Secret Hash**:
           - Enter a secret key in Flutterwave (e.g. `lifegrid_webhook_secret_2026`).
           - Add it to `.streamlit/secrets.toml`:
           ```toml
           FLUTTERWAVE_SECRET_HASH = "lifegrid_webhook_secret_2026"
           ```
        4. **Running as a Standalone Server in Production**:
           ```bash
           python pages/21-webhook&monitor.py --serve --port 8000
           ```
        """)


# =========================================================
# SCRIPT EXECUTION (CLI / STREAMLIT)
# =========================================================
is_cli_command = any(arg in sys.argv for arg in ["--serve", "-h", "--help"])

if is_cli_command:
    parser = argparse.ArgumentParser(description="LifeGrid Flutterwave Webhook Listener")
    parser.add_argument("--serve", action="store_true", help="Start the webhook HTTP server listener")
    parser.add_argument("--port", type=int, default=8000, help="Port to run server on (default: 8000)")
    args = parser.parse_args()

    if args.serve:
        run_server(args.port)
else:
    if HAS_STREAMLIT:
        render_streamlit_ui()
    else:
        print("LifeGrid Webhook Utility.")
        print("To run the interactive UI: streamlit run pages/21-webhook&monitor.py")
        print("To run the HTTP listener:   python pages/21-webhook&monitor.py --serve --port 8000")
