"""
22 - Settlement, Tax & Audit Ledger
LifeGrid Financial Operations & Compliance Suite

Production Streamlit dashboard for:
  1. Treasury & Wallet Liability Reconciliation
  2. Periodic Payout Settlement Batches
  3. Cryptographic Audit Ledger Verification (SHA-256 Chain Integrity)
  4. Creator Tax, Withholding & 1099/W-8BEN Compliance Tracking
  5. Accounting CSV & Financial Ledger Exports
"""

import hashlib
import io
import os
import sqlite3
import uuid
from datetime import datetime

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

try:
    import streamlit as st
    HAS_STREAMLIT = True
except ImportError:
    HAS_STREAMLIT = False


# =========================================================
# DATABASE ACCESS & HELPERS
# =========================================================
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


def ensure_settlement_tables(conn):
    """Ensure all settlement, audit, and tax tables exist."""
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settlement_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_reference TEXT UNIQUE NOT NULL,
            period_label TEXT NOT NULL,
            currency TEXT NOT NULL DEFAULT 'USD',
            total_transactions INTEGER NOT NULL DEFAULT 0,
            gross_amount REAL NOT NULL DEFAULT 0.0,
            fee_amount REAL NOT NULL DEFAULT 0.0,
            net_amount REAL NOT NULL DEFAULT 0.0,
            status TEXT NOT NULL DEFAULT 'Closed',
            reconciled_by TEXT DEFAULT 'System',
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
            notes TEXT,
            created_at TEXT,
            processed_at TEXT
        )
    """)

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

    conn.commit()


# =========================================================
# AUDIT CHAIN VERIFICATION ENGINE
# =========================================================
def verify_audit_ledger_integrity(conn):
    """
    Scans every entry in financial_audit_ledger and validates the SHA-256 chain.
    Returns: (is_valid, total_checked, broken_entry)
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, ledger_entry_id, transaction_ref, event_type, user_id,
               debit, credit, fee, balance_after, currency, prev_hash, entry_hash, created_at
        FROM financial_audit_ledger
        ORDER BY id ASC
    """)
    rows = cursor.fetchall()

    if not rows:
        return True, 0, None

    expected_prev = "GENESIS_BLOCK_0000000000000000"

    for r in rows:
        (row_id, ledger_id, tx_ref, event_type, u_id,
         debit, credit, fee, bal_after, curr, prev_hash, entry_hash, created_at) = r

        if prev_hash != expected_prev:
            return False, row_id, {
                "error": "Previous hash link mismatch",
                "id": row_id,
                "ledger_id": ledger_id,
                "expected": expected_prev,
                "found": prev_hash
            }

        payload = f"{prev_hash}|{tx_ref}|{event_type}|{u_id}|{debit:.4f}|{credit:.4f}|{fee:.4f}|{bal_after:.4f}|{curr}|{created_at}"
        computed_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

        if computed_hash != entry_hash:
            return False, row_id, {
                "error": "Tampered record payload or invalid signature",
                "id": row_id,
                "ledger_id": ledger_id,
                "computed": computed_hash,
                "stored": entry_hash
            }

        expected_prev = entry_hash

    return True, len(rows), None


# =========================================================
# STREAMLIT UI IMPLEMENTATION
# =========================================================
def render_settlement_and_audit_ui():
    st.set_page_config(
        page_title="22 - Settlement & Audit Ledger | LifeGrid",
        page_icon="⚖️",
        layout="wide"
    )

    st.title("⚖️ 22 - Financial Settlement, Tax & Audit Ledger")
    st.caption("Treasury balances, net creator settlement batches, regulatory tax reporting, and cryptographic ledger verification.")

    conn = get_db()
    ensure_settlement_tables(conn)
    cursor = conn.cursor()

    # High-level Metrics
    w_cols = get_table_columns(conn, "creator_withdrawals")
    fee_col = "fee" if "fee" in w_cols else "0.0"
    net_col = "net_amount" if "net_amount" in w_cols else "amount"

    cursor.execute(f"""
        SELECT 
            COALESCE(SUM(amount), 0.0),
            COALESCE(SUM({fee_col}), 0.0),
            COALESCE(SUM({net_col}), 0.0),
            COUNT(*)
        FROM creator_withdrawals
        WHERE LOWER(status) = 'completed'
    """)
    completed_gross, total_fees, completed_net, completed_count = cursor.fetchone()

    cursor.execute("SELECT COALESCE(SUM(balance), 0.0), COUNT(DISTINCT user_id) FROM wallets")
    total_wallet_liabilities, active_wallet_users = cursor.fetchone()

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("💰 Net Payouts Disbursed", f"${completed_net:,.2f}", f"{completed_count} transactions")
    with m2:
        st.metric("🏦 Platform Fees Collected", f"${total_fees:,.2f}")
    with m3:
        st.metric("🛡️ Wallet Liability Reserve", f"${total_wallet_liabilities:,.2f}", f"{active_wallet_users} creators")
    with m4:
        is_valid, count_audited, _ = verify_audit_ledger_integrity(conn)
        if is_valid:
            st.metric("🔒 Ledger Integrity", "100% Sealed", f"{count_audited} SHA-256 blocks")
        else:
            st.metric("⚠️ Ledger Integrity", "Tamper Detected!", delta_color="inverse")

    tabs = st.tabs([
        "📊 Treasury & Liability Overview",
        "📑 Settlement Batches",
        "🔒 Cryptographic Audit Chain",
        "📋 Tax & 1099/Withholding",
        "📥 Accounting Exports"
    ])

    # ---------------- TAB 1: TREASURY & LIABILITY OVERVIEW ----------------
    with tabs[0]:
        st.subheader("Treasury Health & Creator Liabilities")
        st.write("Cross-checks available creator wallet funds against completed and pending gateway obligations.")

        col_a, col_b = st.columns([1, 1])

        with col_a:
            st.markdown("### 💼 Liabilities by Currency")
            cursor.execute("SELECT currency, SUM(balance), COUNT(user_id) FROM wallets GROUP BY currency")
            w_rows = cursor.fetchall()
            if w_rows:
                liability_data = [{"Currency": r[0], "Total Balance": f"{r[0]} {r[1]:,.2f}", "Holders": r[2]} for r in w_rows]
                st.table(liability_data)
            else:
                st.info("No active wallet balances found.")

        with col_b:
            st.markdown("### 🏦 Payouts by Currency & Channel")
            cursor.execute(f"""
                SELECT currency, COUNT(*), SUM(amount), SUM({fee_col})
                FROM creator_withdrawals
                WHERE LOWER(status) = 'completed'
                GROUP BY currency
            """)
            p_rows = cursor.fetchall()
            if p_rows:
                p_data = [{
                    "Currency": r[0],
                    "Disbursed Count": r[1],
                    "Gross Volume": f"{r[0]} {r[2]:,.2f}",
                    "Fees": f"{r[0]} {r[3]:,.2f}"
                } for r in p_rows]
                st.table(p_data)
            else:
                st.info("No completed payouts recorded yet.")

    # ---------------- TAB 2: SETTLEMENT BATCHES ----------------
    with tabs[1]:
        st.subheader("Periodic Settlement Batches")
        st.caption("Reconcile grouped batches of completed payouts for banking matching and general ledger posting.")

        b_left, b_right = st.columns([2, 1])

        with b_left:
            st.markdown("### 📜 Past Settlement Batches")
            cursor.execute("""
                SELECT batch_reference, period_label, currency, total_transactions, gross_amount, fee_amount, net_amount, status, created_at
                FROM settlement_batches
                ORDER BY id DESC LIMIT 50
            """)
            batches = cursor.fetchall()

            if batches:
                b_display = [{
                    "Batch Ref": b[0],
                    "Period": b[1],
                    "Currency": b[2],
                    "Transactions": b[3],
                    "Gross": f"{b[4]:,.2f}",
                    "Fees": f"{b[5]:,.2f}",
                    "Net Disbursed": f"{b[6]:,.2f}",
                    "Status": b[7],
                    "Closed At": b[8]
                } for b in batches]
                st.dataframe(b_display, use_container_width=True)
            else:
                st.info("No formal settlement batches generated yet. You can close a settlement batch below.")

        with b_right:
            st.markdown("### ➕ Close New Settlement Batch")
            period_label = st.text_input("Period Label", value=datetime.utcnow().strftime("BATCH-%Y-%m-%d"))
            batch_curr = st.selectbox("Currency", ["USD", "NGN", "KES", "GHS", "EUR", "GBP"])

            cursor.execute(f"""
                SELECT COUNT(*), COALESCE(SUM(amount), 0.0), COALESCE(SUM({fee_col}), 0.0), COALESCE(SUM({net_col}), 0.0)
                FROM creator_withdrawals
                WHERE LOWER(status) = 'completed' AND currency = ?
            """, (batch_curr,))
            c_tx, g_amt, f_amt, n_amt = cursor.fetchone()

            st.write(f"**Unbatched Completed Items:** {c_tx}")
            st.write(f"**Total Net Disbursed:** `{batch_curr} {n_amt:,.2f}`")

            if st.button("Generate & Seal Settlement Batch", type="primary", use_container_width=True):
                if c_tx == 0:
                    st.warning(f"No completed payouts found in {batch_curr} to batch.")
                else:
                    new_ref = f"STL-{uuid.uuid4().hex[:10].upper()}"
                    now_ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                    cursor.execute("""
                        INSERT INTO settlement_batches 
                        (batch_reference, period_label, currency, total_transactions, gross_amount, fee_amount, net_amount, status, reconciled_by, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 'Closed', 'Admin', ?)
                    """, (new_ref, period_label, batch_curr, c_tx, g_amt, f_amt, n_amt, now_ts))
                    conn.commit()
                    st.success(f"Settlement Batch `{new_ref}` successfully created and sealed.")
                    st.rerun()

    # ---------------- TAB 3: CRYPTOGRAPHIC AUDIT CHAIN ----------------
    with tabs[2]:
        st.subheader("Cryptographic Financial Audit Ledger (Tamper-Evident Chain)")
        st.write(
            "Every withdrawal and refund recorded by Page 21 appends a cryptographically linked SHA-256 audit entry. "
            "Any manual database alteration breaks this hash chain."
        )

        valid, total_checked, err = verify_audit_ledger_integrity(conn)

        if valid:
            st.success(f"✅ Cryptographic Integrity Verified: All {total_checked} entries in the ledger form a valid, unbroken SHA-256 chain.")
        else:
            st.error(f"❌ TAMPER WARNING: Integrity broken at Record #{err.get('id')} ({err.get('ledger_id')}). Reason: {err.get('error')}")

        cursor.execute("""
            SELECT id, ledger_entry_id, transaction_ref, event_type, user_id, debit, credit, fee, balance_after, currency, prev_hash, entry_hash, created_at
            FROM financial_audit_ledger
            ORDER BY id DESC LIMIT 50
        """)
        ledger_rows = cursor.fetchall()

        if ledger_rows:
            l_data = [{
                "ID": r[0],
                "Ledger Ref": r[1],
                "Tx Ref": r[2],
                "Event": r[3],
                "User": f"#{r[4]}",
                "Debit": f"{r[5]:,.2f}",
                "Credit": f"{r[6]:,.2f}",
                "Balance After": f"{r[9]} {r[8]:,.2f}",
                "Entry Hash": f"{r[11][:16]}...",
                "Timestamp": r[12]
            } for r in ledger_rows]
            st.dataframe(l_data, use_container_width=True)
        else:
            st.info("No audit ledger entries recorded yet. Webhook completions and refunds automatically append to this ledger.")

    # ---------------- TAB 4: TAX & 1099/WITHHOLDING ----------------
    with tabs[3]:
        st.subheader("Creator Tax & Earnings Compliance")
        st.caption("Tracks aggregate gross creator disbursements for 1099-NEC / 1099-K / statutory tax reporting thresholds.")

        tax_year = st.selectbox("Select Calendar Year", [2026, 2025, 2024], index=0)
        threshold = st.number_input("Reporting Threshold (e.g., $600 for IRS Form 1099-NEC)", min_value=0.0, value=600.0, step=50.0)

        cols = get_table_columns(conn, "creator_withdrawals")
        user_col = "user_id" if "user_id" in cols else ("creator_id" if "creator_id" in cols else "user_id")

        cursor.execute(f"""
            SELECT 
                {user_col},
                COUNT(*) as payout_count,
                SUM(amount) as gross_earnings,
                SUM({fee_col}) as total_fees,
                currency
            FROM creator_withdrawals
            WHERE LOWER(status) = 'completed' AND (created_at LIKE '{tax_year}%' OR processed_at LIKE '{tax_year}%')
            GROUP BY {user_col}, currency
            HAVING gross_earnings >= ?
            ORDER BY gross_earnings DESC
        """, (threshold,))
        tax_records = cursor.fetchall()

        if tax_records:
            st.markdown(f"### Creators Exceeding Threshold (${threshold:,.2f}) for Tax Year {tax_year}")
            tax_table = [{
                "User ID": f"#{t[0]}",
                "Payout Count": t[1],
                "Gross Disbursed": f"{t[4]} {t[2]:,.2f}",
                "Platform Fees Deducted": f"{t[4]} {t[3]:,.2f}",
                "Estimated 10% Withholding": f"{t[4]} {(t[2] * 0.10):,.2f}",
                "Filing Status": "Action Required" if t[2] >= 600 else "Exempt"
            } for t in tax_records]
            st.dataframe(tax_table, use_container_width=True)
        else:
            st.info(f"No creators have exceeded the ${threshold:,.2f} threshold for calendar year {tax_year}.")

    # ---------------- TAB 5: ACCOUNTING EXPORTS ----------------
    with tabs[4]:
        st.subheader("Financial Ledger & Accounting Exports")
        st.write("Generate clean, reconciled CSV and text reports to import into QuickBooks, Xero, or send to your accounting team.")

        export_choice = st.radio(
            "Select Dataset to Export",
            ["Completed Creator Disbursements", "Full Audit Ledger Chain", "Settlement Batches"],
            horizontal=True
        )

        csv_buffer = io.StringIO()

        if export_choice == "Completed Creator Disbursements":
            cursor.execute(f"""
                SELECT id, {user_col}, amount, currency, {fee_col}, {net_col}, status, withdrawal_reference, transaction_reference, bank_name, account_number, created_at, processed_at
                FROM creator_withdrawals
                WHERE LOWER(status) = 'completed'
                ORDER BY id ASC
            """)
            rows = cursor.fetchall()
            header = "id,user_id,amount,currency,fee,net_amount,status,withdrawal_reference,transaction_reference,bank_name,account_number,created_at,processed_at\n"
            csv_buffer.write(header)
            for r in rows:
                csv_buffer.write(",".join(f'"{str(val or "")}"' for val in r) + "\n")
            file_name = f"LifeGrid_Disbursements_{datetime.utcnow().strftime('%Y%m%d')}.csv"

        elif export_choice == "Full Audit Ledger Chain":
            cursor.execute("""
                SELECT id, ledger_entry_id, transaction_ref, event_type, user_id, debit, credit, fee, balance_after, currency, prev_hash, entry_hash, created_at
                FROM financial_audit_ledger
                ORDER BY id ASC
            """)
            rows = cursor.fetchall()
            header = "id,ledger_entry_id,transaction_ref,event_type,user_id,debit,credit,fee,balance_after,currency,prev_hash,entry_hash,created_at\n"
            csv_buffer.write(header)
            for r in rows:
                csv_buffer.write(",".join(f'"{str(val or "")}"' for val in r) + "\n")
            file_name = f"LifeGrid_Audit_Ledger_{datetime.utcnow().strftime('%Y%m%d')}.csv"

        else:
            cursor.execute("""
                SELECT id, batch_reference, period_label, currency, total_transactions, gross_amount, fee_amount, net_amount, status, reconciled_by, created_at
                FROM settlement_batches
                ORDER BY id ASC
            """)
            rows = cursor.fetchall()
            header = "id,batch_reference,period_label,currency,total_transactions,gross_amount,fee_amount,net_amount,status,reconciled_by,created_at\n"
            csv_buffer.write(header)
            for r in rows:
                csv_buffer.write(",".join(f'"{str(val or "")}"' for val in r) + "\n")
            file_name = f"LifeGrid_Settlement_Batches_{datetime.utcnow().strftime('%Y%m%d')}.csv"

        st.download_button(
            label=f"📥 Download {export_choice} (.csv)",
            data=csv_buffer.getvalue(),
            file_name=file_name,
            mime="text/csv",
            type="primary"
        )


if __name__ == "__main__":
    if HAS_STREAMLIT:
        render_settlement_and_audit_ui()
    else:
        print("LifeGrid Settlement & Audit Module.")
        print("Run with: streamlit run pages/22-settlement_and_audit.py")
