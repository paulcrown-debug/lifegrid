import json
import sqlite3
import uuid
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import streamlit as st
import requests

from database import get_connection

# Document storage directory for previews
BASE_DIR = Path(__file__).resolve().parent.parent
DOCUMENT_DIR = BASE_DIR / "data" / "kyc_documents"

# Optional Flutterwave service helper integration
try:
    from services.flutterwave import (
        is_flutterwave_configured,
        _get_secret_key,
        _get_base_url,
        DEFAULT_NG_BANKS,
        get_supported_banks,
    )
except ImportError:
    is_flutterwave_configured = None
    _get_secret_key = None
    _get_base_url = None
    DEFAULT_NG_BANKS = []
    get_supported_banks = None


# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="Withdrawal Administration | LifeGrid",
    page_icon="🛡️",
    layout="wide",
)

st.title("🛡️ Creator Withdrawal Administration")
st.caption(
    "Review, approve, and disburse LifeGrid multi-currency creator withdrawal requests."
)


# ============================================================
# AUTHENTICATION & ADMIN VERIFICATION
# ============================================================

current_user = st.session_state.get("user")

if not current_user:
    st.warning("Please log in to access Withdrawal Administration.")
    st.stop()


def get_user_id(user):
    if isinstance(user, dict):
        return user.get("id") or user.get("user_id")
    if hasattr(user, "id"):
        return user.id
    if hasattr(user, "user_id"):
        return user.user_id
    return None


def get_username(user):
    if isinstance(user, dict):
        return (
            user.get("username")
            or user.get("name")
            or user.get("full_name")
            or user.get("email")
            or "User"
        )
    if hasattr(user, "username"):
        return user.username
    return "User"


user_id = get_user_id(current_user)
username = get_username(current_user)

if not user_id:
    st.error("Unable to identify the current user.")
    st.stop()


# ============================================================
# DATABASE HELPERS & SCHEMA COMPATIBILITY
# ============================================================

def get_columns(connection, table_name):
    cursor = connection.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    return [row[1] for row in cursor.fetchall()]


def ensure_column(connection, table_name, column_name, column_type):
    columns = get_columns(connection, table_name)
    if column_name not in columns:
        try:
            cursor = connection.cursor()
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
            connection.commit()
        except Exception:
            pass


def ensure_kyc_table(connection):
    cursor = connection.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS lifegrid_kyc_verifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            full_legal_name TEXT NOT NULL,
            date_of_birth TEXT,
            country_of_residence TEXT NOT NULL,
            residential_address TEXT NOT NULL,
            city TEXT NOT NULL,
            state_province TEXT NOT NULL,
            postal_code TEXT,
            id_type TEXT NOT NULL,
            id_number TEXT NOT NULL,
            id_expiry_date TEXT,
            id_document_filename TEXT,
            facial_selfie_filename TEXT,
            proof_of_address_type TEXT,
            proof_of_address_filename TEXT,
            verification_status TEXT NOT NULL DEFAULT 'Pending',
            aml_risk_level TEXT DEFAULT 'Low',
            rejection_reason TEXT,
            submitted_at TIMESTAMP NOT NULL,
            reviewed_at TIMESTAMP
        )
        """
    )
    connection.commit()


def update_kyc_status(connection, uid, new_status, reason=None):
    cursor = connection.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        """
        UPDATE lifegrid_kyc_verifications
        SET verification_status = ?, rejection_reason = ?, reviewed_at = ?
        WHERE user_id = ?
        """,
        (new_status, reason, now_str, uid),
    )
    for tbl in ("creator_profiles", "users"):
        cols = set(get_columns(connection, tbl))
        if "is_verified" in cols:
            val = 1 if new_status == "Verified" else 0
            id_col = "user_id" if "user_id" in cols else "id"
            try:
                cursor.execute(f"UPDATE {tbl} SET is_verified = ? WHERE {id_col} = ?", (val, uid))
            except Exception:
                pass
        if "kyc_status" in cols:
            id_col = "user_id" if "user_id" in cols else "id"
            try:
                cursor.execute(f"UPDATE {tbl} SET kyc_status = ? WHERE {id_col} = ?", (new_status, uid))
            except Exception:
                pass
    connection.commit()


def ensure_admin_table(connection):
    ensure_kyc_table(connection)
    cursor = connection.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS lifegrid_admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            username TEXT,
            admin_status TEXT NOT NULL DEFAULT 'Active',
            created_at TEXT NOT NULL
        )
        """
    )
    connection.commit()


def is_admin(connection, user_id_val):
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT id
        FROM lifegrid_admins
        WHERE user_id = ?
          AND admin_status = 'Active'
        LIMIT 1
        """,
        (user_id_val,),
    )
    return cursor.fetchone() is not None


def get_admin_count(connection):
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM lifegrid_admins
        WHERE admin_status = 'Active'
        """
    )
    row = cursor.fetchone()
    return int(row[0] or 0)


def activate_development_admin(connection, user_id_val, username_val):
    cursor = connection.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        """
        INSERT OR IGNORE INTO lifegrid_admins (
            user_id,
            username,
            admin_status,
            created_at
        )
        VALUES (?, ?, 'Active', ?)
        """,
        (user_id_val, username_val, now_str),
    )
    connection.commit()


def get_creator_info(connection, user_id_val):
    cursor = connection.cursor()
    creator_name = None

    if "creator_profiles" in [t[0] for t in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]:
        cols = get_columns(connection, "creator_profiles")
        user_col = "user_id" if "user_id" in cols else ("id" if "id" in cols else None)
        if user_col and "display_name" in cols:
            cursor.execute(
                f"SELECT display_name FROM creator_profiles WHERE {user_col} = ? LIMIT 1",
                (user_id_val,),
            )
            row = cursor.fetchone()
            if row and row[0]:
                creator_name = str(row[0]).strip()

    if not creator_name and "users" in [t[0] for t in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]:
        cols = get_columns(connection, "users")
        name_col = "username" if "username" in cols else ("name" if "name" in cols else "email")
        if "id" in cols:
            cursor.execute(
                f"SELECT {name_col} FROM users WHERE id = ? LIMIT 1",
                (user_id_val,),
            )
            row = cursor.fetchone()
            if row and row[0]:
                creator_name = str(row[0]).strip()

    return creator_name or f"User #{user_id_val}"


def update_withdrawal(
    connection,
    withdrawal_reference,
    new_status,
    admin_note="",
    transaction_ref="",
):
    cursor = connection.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute(
        "SELECT notes FROM creator_withdrawals WHERE withdrawal_reference = ? LIMIT 1",
        (withdrawal_reference,),
    )
    row = cursor.fetchone()
    existing_notes = str(row[0] or "") if row else ""

    combined_notes = existing_notes
    if admin_note.strip():
        stamp = f"[{now_str} Admin: {admin_note.strip()}]"
        combined_notes = f"{existing_notes}\n{stamp}".strip() if existing_notes else stamp

    cols = set(get_columns(connection, "creator_withdrawals"))

    updates = ["status = ?"]
    params = [new_status]

    if "processed_at" in cols:
        updates.append("processed_at = ?")
        params.append(now_str if new_status in ("Processing", "Completed", "Rejected") else None)

    if "notes" in cols:
        updates.append("notes = ?")
        params.append(combined_notes)

    if "transaction_reference" in cols and transaction_ref.strip():
        updates.append("transaction_reference = ?")
        params.append(transaction_ref.strip())

    params.append(withdrawal_reference)

    sql = f"UPDATE creator_withdrawals SET {', '.join(updates)} WHERE withdrawal_reference = ?"
    cursor.execute(sql, params)
    connection.commit()


# ============================================================
# FLUTTERWAVE PAYOUT API HELPER
# ============================================================

def execute_flutterwave_transfer(
    account_number: str,
    bank_code: str,
    amount: float,
    currency: str = "NGN",
    reference: str = "",
    narration: str = "LifeGrid Creator Payout",
) -> dict:
    is_conf = False
    if is_flutterwave_configured:
        try:
            is_conf = is_flutterwave_configured()
        except Exception:
            is_conf = False

    if not is_conf:
        simulated_tx_ref = f"FLW-DEMO-{uuid.uuid4().hex[:8].upper()}"
        return {
            "success": True,
            "status": "Completed",
            "message": "Demo Mode: Transfer simulated successfully (no real funds debited).",
            "transaction_reference": simulated_tx_ref,
            "is_simulated": True,
        }

    secret_key = _get_secret_key() if _get_secret_key else ""
    base_url = _get_base_url() if _get_base_url else "https://api.flutterwave.com/v3"

    headers = {
        "Authorization": f"Bearer {secret_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "account_bank": str(bank_code).strip(),
        "account_number": str(account_number).strip(),
        "amount": float(amount),
        "narration": narration[:50],
        "currency": currency.upper(),
        "reference": reference or f"LG-TX-{uuid.uuid4().hex[:10].upper()}",
    }

    try:
        response = requests.post(
            f"{base_url}/transfers",
            json=payload,
            headers=headers,
            timeout=12,
        )
        try:
            data = response.json()
        except Exception:
            data = {}

        if response.status_code in (200, 201) and data.get("status") == "success":
            transfer_data = data.get("data") or {}
            tx_id = str(transfer_data.get("id") or transfer_data.get("reference") or payload["reference"])
            fw_status = str(transfer_data.get("status") or "SUCCESSFUL").upper()
            return {
                "success": True,
                "status": "Completed" if fw_status in ("SUCCESSFUL", "SUCCESS") else "Processing",
                "message": data.get("message") or "Flutterwave transfer initiated successfully.",
                "transaction_reference": f"FLW-TX-{tx_id}",
                "is_simulated": False,
            }
        else:
            api_msg = data.get("message") or f"Flutterwave API error HTTP {response.status_code}"
            return {
                "success": False,
                "status": "Failed",
                "message": api_msg,
                "transaction_reference": "",
                "is_simulated": False,
            }
    except requests.exceptions.Timeout:
        return {
            "success": False,
            "status": "Timeout",
            "message": "Flutterwave transfer request timed out. Please verify status on your Flutterwave dashboard.",
            "transaction_reference": "",
            "is_simulated": False,
        }
    except Exception as exc:
        return {
            "success": False,
            "status": "Error",
            "message": f"Connection error: {str(exc)}",
            "transaction_reference": "",
            "is_simulated": False,
        }


def parse_destination(destination_str: str):
    raw = str(destination_str or "").strip()
    parts = [p.strip() for p in raw.split("|") if p.strip()]

    parsed = {
        "raw": raw,
        "bank_name": parts[0] if len(parts) > 0 else "",
        "account_number": parts[1] if len(parts) > 1 else "",
        "account_name": parts[2] if len(parts) > 2 else "",
        "extra": " | ".join(parts[3:]) if len(parts) > 3 else "",
    }
    return parsed


# ============================================================
# MAIN APPLICATION LOGIC
# ============================================================

connection = get_connection()

try:
    ensure_admin_table(connection)

    ensure_column(connection, "creator_withdrawals", "processed_at", "TIMESTAMP")
    ensure_column(connection, "creator_withdrawals", "transaction_reference", "TEXT")
    ensure_column(connection, "creator_withdrawals", "asset_type", "TEXT DEFAULT 'FIAT'")
    ensure_column(connection, "creator_withdrawals", "asset_code", "TEXT")
    ensure_column(connection, "creator_withdrawals", "destination", "TEXT DEFAULT ''")
    ensure_column(connection, "creator_withdrawals", "payout_details", "TEXT DEFAULT ''")
    ensure_column(connection, "creator_withdrawals", "notes", "TEXT DEFAULT ''")

    # 1. Admin Bootstrap
    admin_count = get_admin_count(connection)

    if admin_count == 0:
        st.info("🛠️ Development Mode: no administrator has been configured yet.")
        st.write(f"Current logged-in user: **{username}** (ID: {user_id})")
        st.warning(
            "The first administrator is being activated for development testing. "
            "You can click the button below to assign admin privileges to your account."
        )
        if st.button("Activate My Development Admin Access", use_container_width=True):
            activate_development_admin(connection, user_id, username)
            st.success("Development Admin access activated!")
            st.rerun()
        st.stop()

    # 2. Admin Access Check
    if not is_admin(connection, user_id):
        st.error("Access denied. This page is restricted to LifeGrid administrators.")
        st.info("Please contact an existing administrator to grant you access.")
        st.stop()

    # Top Admin Status Banner
    admin_col1, admin_col2 = st.columns([3, 1])
    with admin_col1:
        st.success(f"🛡️ Admin Access Active: **{username}** (User ID: {user_id})")
    with admin_col2:
        st.caption("Environment: **Development / Sandbox**")

    tab_payouts, tab_kyc = st.tabs(["💸 Payout & Withdrawal Requests", "🛡️ Creator KYC & AML Verifications"])

    # --------------------------------------------------------
    # TAB 1: Payout Requests
    # --------------------------------------------------------
    with tab_payouts:
        cols = set(get_columns(connection, "creator_withdrawals"))

        time_col = (
            "requested_at"
            if "requested_at" in cols
            else ("created_at" if "created_at" in cols else "''")
        )
        asset_col = (
            "COALESCE(asset_code, currency, 'USD')"
            if "asset_code" in cols
            else "COALESCE(currency, 'USD')"
        )
        type_col = (
            "COALESCE(asset_type, 'FIAT')"
            if "asset_type" in cols
            else "'FIAT'"
        )
        dest_col = (
            "COALESCE(destination, payout_details, '')"
            if "destination" in cols
            else "COALESCE(payout_details, '')"
        )
        ref_col = (
            "transaction_reference"
            if "transaction_reference" in cols
            else "''"
        )
        proc_col = (
            "processed_at"
            if "processed_at" in cols
            else "''"
        )
        fee_col = (
            "COALESCE(fee_amount, platform_fee, 0.0)"
            if ("fee_amount" in cols or "platform_fee" in cols)
            else "0.0"
        )
        net_col = (
            "COALESCE(net_amount, amount, 0.0)"
            if "net_amount" in cols
            else "amount"
        )

        query = f"""
            SELECT
                id,
                withdrawal_reference,
                user_id,
                amount,
                currency,
                {asset_col} AS effective_currency,
                {type_col} AS effective_asset_type,
                payout_method,
                {dest_col} AS payout_destination,
                status,
                notes,
                {time_col} AS request_time,
                {proc_col} AS processed_time,
                {ref_col} AS tx_reference,
                {fee_col} AS fee_collected,
                {net_col} AS net_disbursed
            FROM creator_withdrawals
            ORDER BY id DESC
        """

        cursor = connection.cursor()
        cursor.execute(query)
        withdrawals = cursor.fetchall()

        currency_totals = {}
        status_counts = {"Pending": 0, "Processing": 0, "Completed": 0, "Rejected": 0}

        for row in withdrawals:
            amt = float(row[3] or 0.0)
            curr = str(row[5] or row[4] or "USD").upper()
            st_val = str(row[9] or "Pending")

            f_amt = float(row[14] or 0.0) if len(row) > 14 else 0.0
            n_amt = float(row[15] or row[3] or 0.0) if len(row) > 15 else amt

            if curr not in currency_totals:
                currency_totals[curr] = {
                    "Pending": 0.0,
                    "Processing": 0.0,
                    "Completed": 0.0,
                    "Rejected": 0.0,
                    "Completed_Fees": 0.0,
                    "Completed_Net": 0.0,
                }

            if st_val in currency_totals[curr]:
                currency_totals[curr][st_val] += amt

            if st_val == "Completed":
                currency_totals[curr]["Completed_Fees"] += f_amt
                currency_totals[curr]["Completed_Net"] += n_amt

            if st_val in status_counts:
                status_counts[st_val] += 1
            else:
                status_counts[st_val] = 1

        st.divider()
        st.subheader("📊 Multi-Currency Overview")

        if not currency_totals:
            st.info("No withdrawals found in the system yet.")
        else:
            currencies = sorted(list(currency_totals.keys()))
            curr_tabs = st.tabs([f"💰 {c}" for c in currencies])

            for idx, curr in enumerate(currencies):
                with curr_tabs[idx]:
                    col1, col2, col3, col4, col5 = st.columns(5)
                    sym = "₦" if curr == "NGN" else ("$" if curr == "USD" else f"{curr} ")

                    with col1:
                        pending_amt = currency_totals[curr]["Pending"]
                        st.metric("Pending Requests", f"{sym}{pending_amt:,.2f}")
                    with col2:
                        proc_amt = currency_totals[curr]["Processing"]
                        st.metric("Processing", f"{sym}{proc_amt:,.2f}")
                    with col3:
                        comp_amt = currency_totals[curr]["Completed"]
                        st.metric("Completed (Gross)", f"{sym}{comp_amt:,.2f}")
                    with col4:
                        fees_amt = currency_totals[curr].get("Completed_Fees", 0.0)
                        st.metric("LifeGrid Revenue", f"{sym}{fees_amt:,.2f}")
                    with col5:
                        rej_amt = currency_totals[curr]["Rejected"]
                        st.metric("Rejected / Returned", f"{sym}{rej_amt:,.2f}")

        st.divider()
        st.subheader("🔎 Manage Withdrawal Requests")

        filter_col1, filter_col2, filter_col3, filter_col4 = st.columns([2, 2, 2, 3])

        with filter_col1:
            status_options = ["All", "Pending", "Processing", "Completed", "Rejected"]
            status_filter = st.selectbox("Status Filter", status_options)

        with filter_col2:
            available_currencies = ["All"] + sorted(list(currency_totals.keys()))
            curr_filter = st.selectbox("Currency Filter", available_currencies)

        with filter_col3:
            methods = ["All"] + sorted(list({str(w[7]) for w in withdrawals if w[7]}))
            method_filter = st.selectbox("Method Filter", methods)

        with filter_col4:
            search_query = st.text_input(
                "Search",
                placeholder="Reference (LG-WD-...), Creator, Account, or ID",
            ).strip().lower()

        filtered_withdrawals = []
        for w in withdrawals:
            w_id = w[0]
            w_ref = str(w[1] or "")
            w_user_id = w[2]
            w_curr = str(w[5] or w[4] or "USD").upper()
            w_method = str(w[7] or "")
            w_dest = str(w[8] or "")
            w_status = str(w[9] or "Pending")
            creator_name = get_creator_info(connection, w_user_id)

            if status_filter != "All" and w_status != status_filter:
                continue
            if curr_filter != "All" and w_curr != curr_filter:
                continue
            if method_filter != "All" and w_method != method_filter:
                continue
            if search_query:
                searchable_str = f"{w_ref} {creator_name} {w_user_id} {w_dest} {w_curr}".lower()
                if search_query not in searchable_str:
                    continue

            filtered_withdrawals.append((w, creator_name))

        st.write(f"Showing **{len(filtered_withdrawals)}** matching withdrawal request(s)")

        if not filtered_withdrawals:
            st.info("No withdrawal requests match your search and filter criteria.")
        else:
            bank_code_lookup = {}
            if DEFAULT_NG_BANKS:
                bank_code_lookup = {b["name"].lower(): b["code"] for b in DEFAULT_NG_BANKS}

            for item in filtered_withdrawals:
                w, creator_name = item
                w_id = w[0]
                w_ref = w[1]
                w_user_id = w[2]
                amount = w[3]
                orig_curr = w[4]
                effective_curr = w[5]
                asset_type = w[6]
                method = w[7]
                destination_raw = w[8]
                status = w[9]
                notes = w[10]
                req_time = w[11]
                proc_time = w[12]
                tx_ref = w[13]
                fee_collected = float(w[14] or 0.0) if len(w) > 14 else 0.0
                net_disbursed = float(w[15] or amount or 0.0) if len(w) > 15 else float(amount or 0.0)

                amt_val = float(amount or 0.0)
                curr_str = str(effective_curr or orig_curr).upper()
                sym = "₦" if curr_str == "NGN" else ("$" if curr_str == "USD" else f"{curr_str} ")
                dest_info = parse_destination(destination_raw)

                with st.container(border=True):
                    head_col1, head_col2 = st.columns([3, 1])

                    with head_col1:
                        st.markdown(f"### 💸 `{w_ref}`")
                        st.caption(f"Requested on **{req_time or 'Unknown Date'}**")

                    with head_col2:
                        if status == "Pending":
                            st.warning("⏳ Status: **Pending**")
                        elif status == "Processing":
                            st.info("⚙️ Status: **Processing**")
                        elif status == "Completed":
                            st.success("✅ Status: **Completed**")
                        elif status == "Rejected":
                            st.error("❌ Status: **Rejected**")
                        else:
                            st.write(f"Status: **{status}**")

                    info1, info2, info3 = st.columns(3)

                    with info1:
                        st.markdown("**Creator Details**")
                        st.write(f"👤 **{creator_name}**")
                        st.caption(f"User ID: `{w_user_id}`")

                    with info2:
                        st.markdown("**Payout Amount**")
                        st.write(f"Gross: **{sym}{amt_val:,.2f} {curr_str}**")
                        if fee_collected > 0:
                            st.caption(f"Platform Fee: **-{sym}{fee_collected:,.2f}** | **Net:** **{sym}{net_disbursed:,.2f}**")
                        else:
                            st.caption(f"Net Disbursal: **{sym}{net_disbursed:,.2f}**")
                        st.caption(f"Asset Type: {asset_type} | Method: {method}")

                    with info3:
                        st.markdown("**Audit Details**")
                        if proc_time:
                            st.write(f"⏱️ Processed: `{proc_time}`")
                        if tx_ref:
                            st.write(f"🔗 Tx Ref: `{tx_ref}`")
                        if not proc_time and not tx_ref:
                            st.caption("Awaiting administrative action.")

                    st.markdown("**Destination & Banking Information**")
                    if curr_str == "NGN" and method == "Bank Account":
                        bank_display = dest_info["bank_name"] or "Nigerian Commercial Bank"
                        acc_display = dest_info["account_number"] or "N/A"
                        name_display = dest_info["account_name"] or creator_name

                        dest_col1, dest_col2, dest_col3 = st.columns(3)
                        with dest_col1:
                            st.write(f"🏦 **Bank:** {bank_display}")
                        with dest_col2:
                            st.write(f"🔢 **Account Number:** `{acc_display}`")
                        with dest_col3:
                            st.write(f"✅ **Account Holder:** {name_display}")
                    elif curr_str == "USD" and method == "Bank Account":
                        st.code(destination_raw or "USD Wire / Domiciliary details not provided", language=None)
                    else:
                        st.code(destination_raw or "No destination specified", language=None)

                    if notes:
                        st.caption(f"📝 **Notes / Audit History:**\n{notes}")

                    if status in ("Pending", "Processing"):
                        st.markdown("---")
                        st.markdown("#### ⚡ Administrative Actions")
                        act_col1, act_col2 = st.columns(2)

                        with act_col1:
                            if status == "Pending":
                                st.write("**Workflow Step 1:** Accept for processing")
                                if st.button(
                                    "▶️ Move to Processing",
                                    key=f"btn_proc_{w_id}",
                                    use_container_width=True,
                                ):
                                    update_withdrawal(
                                        connection,
                                        w_ref,
                                        "Processing",
                                        admin_note="Moved to processing by admin",
                                    )
                                    st.success(f"Request {w_ref} moved to Processing.")
                                    st.rerun()

                            elif status == "Processing":
                                st.write("**Workflow Step 2:** Complete Disbursal")
                                if curr_str == "NGN" and method == "Bank Account":
                                    matched_code = "044"
                                    b_name_clean = dest_info["bank_name"].lower()
                                    for known_name, code in bank_code_lookup.items():
                                        if known_name in b_name_clean or b_name_clean in known_name:
                                            matched_code = code
                                            break

                                    with st.expander("⚡ Disburse via Flutterwave Transfer", expanded=True):
                                        payout_transfer_amount = net_disbursed if net_disbursed > 0 else amt_val
                                        st.write(
                                            f"Transfer Net **₦{payout_transfer_amount:,.2f}** to **{dest_info['account_number']}** "
                                            f"({dest_info['bank_name']})"
                                        )
                                        if fee_collected > 0:
                                            st.caption(f"💡 LifeGrid retains **₦{fee_collected:,.2f}** as platform & processing fee in company wallet.")
                                        if st.button(
                                            f"🚀 Send Net Payout (₦{payout_transfer_amount:,.2f}) via Flutterwave",
                                            key=f"flw_send_{w_id}",
                                            use_container_width=True,
                                            type="primary",
                                        ):
                                            with st.spinner("Dispatching transfer via Flutterwave..."):
                                                fw_res = execute_flutterwave_transfer(
                                                    account_number=dest_info["account_number"],
                                                    bank_code=matched_code,
                                                    amount=payout_transfer_amount,
                                                    currency="NGN",
                                                    reference=w_ref,
                                                    narration=f"LifeGrid Payout {w_ref}",
                                                )

                                                if fw_res.get("success"):
                                                    update_withdrawal(
                                                        connection,
                                                        w_ref,
                                                        "Completed",
                                                        admin_note=f"Disbursed via Flutterwave: {fw_res.get('message')}",
                                                        transaction_ref=fw_res.get("transaction_reference"),
                                                    )
                                                    st.success("Transfer completed successfully!")
                                                    st.rerun()
                                                else:
                                                    st.error(f"Transfer failed: {fw_res.get('message')}")

                                with st.expander("📝 Manual Disbursal / Mark as Completed", expanded=(curr_str != "NGN")):
                                    manual_tx = st.text_input(
                                        "Bank Reference / Transaction ID (Optional)",
                                        placeholder="e.g. NIBSS-001239912 or Bank Slip Ref",
                                        key=f"tx_in_{w_id}",
                                    )
                                    manual_note = st.text_input(
                                        "Completion Note (Optional)",
                                        placeholder="e.g. Sent via corporate internet banking",
                                        key=f"note_in_{w_id}",
                                    )
                                    manual_disbursed_amt = net_disbursed if net_disbursed > 0 else amt_val
                                    if fee_collected > 0:
                                        st.caption(f"Disbursing Net **{curr_str} {manual_disbursed_amt:,.2f}** (Platform charge **{curr_str} {fee_collected:,.2f}** retained).")
                                    if st.button(
                                        f"✅ Mark as Completed ({curr_str} {manual_disbursed_amt:,.2f})",
                                        key=f"btn_comp_{w_id}",
                                        use_container_width=True,
                                    ):
                                        update_withdrawal(
                                            connection,
                                            w_ref,
                                            "Completed",
                                            admin_note=manual_note or "Marked completed manually",
                                            transaction_ref=manual_tx,
                                        )
                                        st.success(f"Withdrawal {w_ref} marked as Completed.")
                                        st.rerun()

                        with act_col2:
                            st.write("**Rejection / Refund:**")
                            st.caption(
                                "Rejecting immediately unblocks the creator's reserved balance "
                                "so they can re-submit with corrected banking details."
                            )

                            with st.expander("❌ Reject Withdrawal Request"):
                                reject_reason = st.text_area(
                                    "Reason for Rejection (Required)",
                                    placeholder="e.g. Account name mismatch with creator profile, or invalid IBAN / SWIFT code.",
                                    key=f"rej_reason_{w_id}",
                                )

                                if st.button(
                                    "Confirm Rejection",
                                    key=f"btn_rej_{w_id}",
                                    type="secondary",
                                    use_container_width=True,
                                ):
                                    if not reject_reason.strip():
                                        st.error("Please provide a rejection reason so the creator knows what to correct.")
                                    else:
                                        update_withdrawal(
                                            connection,
                                            w_ref,
                                            "Rejected",
                                            admin_note=f"Rejection Reason: {reject_reason.strip()}",
                                        )
                                        st.warning(f"Withdrawal {w_ref} rejected and balance restored.")
                                        st.rerun()

                    else:
                        st.markdown("---")
                        if status == "Completed":
                            st.caption(
                                f"🎉 **Payout Finalized:** This transaction was successfully paid out on {proc_time or 'N/A'}. "
                                f"Reference: `{tx_ref or 'Manual Disbursal'}`."
                            )
                        elif status == "Rejected":
                            st.caption(
                                f"🛑 **Request Rejected:** This request was rejected on {proc_time or 'N/A'}. "
                                f"The reserved funds have been returned to the creator's available balance."
                            )

    # --------------------------------------------------------
    # TAB 2: Creator KYC & AML Review (With Direct Image Inspection)
    # --------------------------------------------------------
    with tab_kyc:
        st.subheader("🛡️ Creator AML & Identity Verifications")
        st.caption("Inspect submitted identity documents, live facial selfies, and address documentation before issuing Level 2 high-tier status.")

        k_cursor = connection.cursor()
        k_cursor.execute(
            """
            SELECT
                id,
                user_id,
                full_legal_name,
                date_of_birth,
                country_of_residence,
                residential_address,
                city,
                state_province,
                postal_code,
                id_type,
                id_number,
                id_expiry_date,
                id_document_filename,
                facial_selfie_filename,
                proof_of_address_type,
                proof_of_address_filename,
                verification_status,
                aml_risk_level,
                rejection_reason,
                submitted_at,
                reviewed_at
            FROM lifegrid_kyc_verifications
            ORDER BY id DESC
            """
        )
        kyc_list = k_cursor.fetchall()

        k_pending = sum(1 for r in kyc_list if r[16] == "Pending")
        k_verified = sum(1 for r in kyc_list if r[16] == "Verified")
        k_rejected = sum(1 for r in kyc_list if r[16] == "Rejected")

        kc1, kc2, kc3, kc4 = st.columns(4)
        with kc1:
            st.metric("Total Submissions", len(kyc_list))
        with kc2:
            st.metric("Pending Review", k_pending)
        with kc3:
            st.metric("Verified (Level 2)", k_verified)
        with kc4:
            st.metric("Rejected", k_rejected)

        st.divider()

        kyc_status_filter = st.selectbox(
            "Filter KYC by Status",
            ["All", "Pending", "Verified", "Rejected"],
            key="kyc_filter_status",
        )

        filtered_kyc = [
            r for r in kyc_list
            if (kyc_status_filter == "All" or r[16] == kyc_status_filter)
        ]

        if not filtered_kyc:
            st.info("No KYC submissions match the selected filter.")
        else:
            for k in filtered_kyc:
                (
                    k_id,
                    k_uid,
                    k_name,
                    k_dob,
                    k_country,
                    k_addr,
                    k_city,
                    k_state,
                    k_post,
                    k_id_type,
                    k_id_num,
                    k_id_exp,
                    k_id_file,
                    k_selfie_file,
                    k_poa_type,
                    k_poa_file,
                    k_status,
                    k_risk,
                    k_rej_reason,
                    k_sub_at,
                    k_rev_at,
                ) = k

                with st.container(border=True):
                    kh1, kh2 = st.columns([3, 1])
                    with kh1:
                        st.markdown(f"#### 👤 {k_name} (User ID: `{k_uid}`)")
                        st.caption(f"Submitted on: **{k_sub_at}** | Country: **{k_country}**")
                    with kh2:
                        if k_status == "Verified":
                            st.success("✅ **Verified (Level 2)**")
                        elif k_status == "Pending":
                            st.warning("⏳ **Pending Review**")
                        elif k_status == "Rejected":
                            st.error("❌ **Rejected**")

                    kd1, kd2, kd3 = st.columns([2, 2, 3])

                    # 1. Government ID Display
                    with kd1:
                        st.markdown("**1. Uploaded Government ID**")
                        id_path = (DOCUMENT_DIR / k_id_file) if k_id_file else None
                        if id_path and id_path.exists() and id_path.suffix.lower() in [".jpg", ".jpeg", ".png"]:
                            st.image(str(id_path), caption=f"{k_id_type} ({k_id_file})", use_container_width=True)
                        elif id_path and id_path.exists() and id_path.suffix.lower() == ".pdf":
                            st.info(f"📄 PDF Document: `{k_id_file}`")
                            with open(id_path, "rb") as f_pdf:
                                st.download_button("📥 Download ID PDF", f_pdf.read(), file_name=k_id_file, key=f"dl_id_{k_id}")
                        else:
                            st.caption(f"File: `{k_id_file or 'None'}`")

                        st.write(f"- **Type:** {k_id_type}")
                        st.write(f"- **Number:** `{k_id_num}`")
                        st.write(f"- **Expiry:** `{k_id_exp or 'N/A'}`")

                    # 2. Biometric Facial Photo Display
                    with kd2:
                        st.markdown("**2. Biometric Facial Selfie**")
                        selfie_path = (DOCUMENT_DIR / k_selfie_file) if k_selfie_file else None
                        if selfie_path and selfie_path.exists() and selfie_path.suffix.lower() in [".jpg", ".jpeg", ".png"]:
                            st.image(str(selfie_path), caption=f"Selfie ({k_selfie_file})", use_container_width=True)
                        else:
                            st.caption(f"Selfie File: `{k_selfie_file or 'None'}`")

                    # 3. Residential Details & Proof of Address
                    with kd3:
                        st.markdown("**3. Residential Address & Records**")
                        st.write(f"- **Street:** {k_addr}")
                        st.write(f"- **City / State:** {k_city}, {k_state} {k_post or ''}")
                        st.write(f"- **Country:** {k_country}")
                        st.write(f"- **POA Type:** {k_poa_type or 'None'}")

                        poa_path = (DOCUMENT_DIR / k_poa_file) if k_poa_file else None
                        if poa_path and poa_path.exists():
                            if poa_path.suffix.lower() in [".jpg", ".jpeg", ".png"]:
                                st.image(str(poa_path), caption=f"Address Proof: {k_poa_type}", use_container_width=True)
                            elif poa_path.suffix.lower() == ".pdf":
                                with open(poa_path, "rb") as f_poa:
                                    st.download_button("📥 Download Address Proof (PDF)", f_poa.read(), file_name=k_poa_file, key=f"dl_poa_{k_id}")
                        else:
                            st.caption(f"POA File: `{k_poa_file or 'None'}`")

                    # Compliance Decision Action Controls
                    if k_status == "Pending":
                        st.markdown("---")
                        ka_col1, ka_col2 = st.columns([1, 2])
                        with ka_col1:
                            st.write("**Approval:**")
                            if st.button("✅ Approve Level 2 Status", key=f"btn_appr_kyc_{k_id}", use_container_width=True, type="primary"):
                                update_kyc_status(connection, k_uid, "Verified")
                                st.success(f"KYC approved for {k_name}! Level 2 high limits active.")
                                st.rerun()

                        with ka_col2:
                            st.write("**Rejection with Feedback:**")
                            preset_reasons = [
                                "Expired government identification document",
                                "Blurry or illegible document text / photo",
                                "Suspected altered, cropped, or false document",
                                "Live facial selfie does not match government ID photo",
                                "Proof of address is older than 3 months",
                                "Name on identity document does not match LifeGrid account"
                            ]
                            selected_preset = st.selectbox("Compliance Reason Preset", preset_reasons, key=f"preset_{k_id}")
                            custom_note = st.text_input("Additional Compliance Notes (Optional)", key=f"note_kyc_{k_id}")

                            if st.button("❌ Reject KYC Submission", key=f"btn_rej_kyc_{k_id}", use_container_width=True):
                                final_reason = f"{selected_preset}. {custom_note}".strip()
                                update_kyc_status(connection, k_uid, "Rejected", reason=final_reason)
                                st.warning(f"KYC rejected for {k_name}. Reason: '{final_reason}'")
                                st.rerun()

                    elif k_status == "Rejected" and k_rej_reason:
                        st.caption(f"Rejection Reason: {k_rej_reason}")

finally:
    connection.close()