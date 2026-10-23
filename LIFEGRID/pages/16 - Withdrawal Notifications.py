import sqlite3
from datetime import datetime
from decimal import Decimal

import streamlit as st

from database import get_connection

# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="Withdrawal Notifications | LifeGrid",
    page_icon="🔔",
    layout="wide",
)

st.title("🔔 Withdrawal Notifications")
st.caption(
    "Real-time notifications, status updates, and audit trail for your LifeGrid creator payouts."
)


# ============================================================
# AUTHENTICATION
# ============================================================

current_user = st.session_state.get("user")

if not current_user:
    st.warning("Please log in to view your Withdrawal Notifications.")
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
# DATABASE HELPERS & NOTIFICATIONS SCHEMA
# ============================================================

def get_columns(connection, table_name):
    cursor = connection.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    return [row[1] for row in cursor.fetchall()]


def ensure_notifications_table(connection):
    """
    Ensure the withdrawal_notifications table exists with proper schema and indexing.
    """
    cursor = connection.cursor()
    cursor.execute(
        """
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
            created_at TEXT NOT NULL,
            UNIQUE(user_id, withdrawal_reference, notification_type)
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_withdrawal_notifs_user
        ON withdrawal_notifications(user_id, is_read, created_at)
        """
    )
    connection.commit()


def sync_withdrawal_notifications(connection, uid):
    """
    Inspect creator_withdrawals for this creator and automatically sync
    notification records for any lifecycle state (Requested, Processing, Completed, Rejected).
    Guarantees creators never miss an update, even if status changed offline.
    """
    cursor = connection.cursor()

    # Verify if creator_withdrawals exists
    tables = [t[0] for t in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    if "creator_withdrawals" not in tables:
        return

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
            withdrawal_reference,
            amount,
            {asset_col} AS curr,
            payout_method,
            {dest_col} AS destination,
            status,
            notes,
            {time_col} AS req_time,
            {proc_col} AS proc_time,
            {ref_col} AS tx_ref,
            {fee_col} AS fee_val,
            {net_col} AS net_val
        FROM creator_withdrawals
        WHERE user_id = ?
        ORDER BY id ASC
    """
    cursor.execute(query, (uid,))
    withdrawals = cursor.fetchall()

    for item in withdrawals:
        w_ref = item[0]
        amount = item[1]
        curr = item[2]
        method = item[3]
        dest = item[4]
        status = item[5]
        notes = item[6]
        req_time = item[7]
        proc_time = item[8]
        tx_ref = item[9]
        fee_val = float(item[10] or 0.0) if len(item) > 10 else 0.0
        net_val = float(item[11] or amount or 0.0) if len(item) > 11 else float(amount or 0.0)

        amt_val = float(amount or 0.0)
        curr_str = str(curr or "USD").upper()
        sym = "₦" if curr_str == "NGN" else ("$" if curr_str == "USD" else f"{curr_str} ")

        # 1. Base Event: Request Received
        cursor.execute(
            """
            INSERT OR IGNORE INTO withdrawal_notifications (
                user_id,
                withdrawal_reference,
                notification_type,
                title,
                message,
                currency,
                amount,
                is_read,
                created_at
            )
            VALUES (?, ?, 'REQUESTED', ?, ?, ?, ?, 0, ?)
            """,
            (
                uid,
                w_ref,
                f"Withdrawal Request Submitted: {sym}{amt_val:,.2f} {curr_str}",
                f"Your withdrawal request {w_ref} for {sym}{amt_val:,.2f} ({method}) has been submitted. " + (f"Platform charge: {sym}{fee_val:,.2f}, Net disbursal: {sym}{net_val:,.2f}. " if fee_val > 0 else "") + "Queued for administrative review.",
                curr_str,
                amt_val,
                req_time or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )

        # 2. Event: Processing
        if status in ("Processing", "Completed"):
            cursor.execute(
                """
                INSERT OR IGNORE INTO withdrawal_notifications (
                    user_id,
                    withdrawal_reference,
                    notification_type,
                    title,
                    message,
                    currency,
                    amount,
                    is_read,
                    created_at
                )
                VALUES (?, ?, 'PROCESSING', ?, ?, ?, ?, 0, ?)
                """,
                (
                    uid,
                    w_ref,
                    f"Withdrawal in Processing: {sym}{amt_val:,.2f} {curr_str}",
                    f"Your withdrawal request {w_ref} is now being processed. Banking details are being verified for transfer.",
                    curr_str,
                    amt_val,
                    proc_time or req_time or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )

        # 3. Event: Completed
        if status == "Completed":
            tx_detail = f" Transaction Reference: {tx_ref}." if tx_ref else ""
            cursor.execute(
                """
                INSERT OR IGNORE INTO withdrawal_notifications (
                    user_id,
                    withdrawal_reference,
                    notification_type,
                    title,
                    message,
                    currency,
                    amount,
                    is_read,
                    created_at
                )
                VALUES (?, ?, 'COMPLETED', ?, ?, ?, ?, 0, ?)
                """,
                (
                    uid,
                    w_ref,
                    f"Payout Disbursed Successfully 🎉",
                    f"Your payout {w_ref} of {sym}{amt_val:,.2f} {curr_str} has been completed and sent to your destination: {dest}.{tx_detail}",
                    curr_str,
                    amt_val,
                    proc_time or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )

        # 4. Event: Rejected
        if status == "Rejected":
            reason_str = ""
            if notes and "Rejection Reason:" in notes:
                reason_str = f" Reason: {notes.split('Rejection Reason:')[-1].strip()}"
            elif notes:
                reason_str = f" Note: {notes.strip()}"

            cursor.execute(
                """
                INSERT OR IGNORE INTO withdrawal_notifications (
                    user_id,
                    withdrawal_reference,
                    notification_type,
                    title,
                    message,
                    currency,
                    amount,
                    is_read,
                    created_at
                )
                VALUES (?, ?, 'REJECTED', ?, ?, ?, ?, 0, ?)
                """,
                (
                    uid,
                    w_ref,
                    f"Withdrawal Request Rejected ⚠️",
                    f"Your withdrawal request {w_ref} was not approved.{reason_str} The reserved balance of {sym}{amt_val:,.2f} {curr_str} has been returned to your available creator balance.",
                    curr_str,
                    amt_val,
                    proc_time or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )

    connection.commit()


def mark_notification_read(connection, notif_id, is_read=1):
    cursor = connection.cursor()
    cursor.execute(
        "UPDATE withdrawal_notifications SET is_read = ? WHERE id = ?",
        (is_read, notif_id),
    )
    connection.commit()


def mark_all_notifications_read(connection, uid):
    cursor = connection.cursor()
    cursor.execute(
        "UPDATE withdrawal_notifications SET is_read = 1 WHERE user_id = ?",
        (uid,),
    )
    connection.commit()


def clear_read_notifications(connection, uid):
    cursor = connection.cursor()
    cursor.execute(
        "DELETE FROM withdrawal_notifications WHERE user_id = ? AND is_read = 1",
        (uid,),
    )
    connection.commit()


# ============================================================
# MAIN APPLICATION LOGIC
# ============================================================

connection = get_connection()

try:
    ensure_notifications_table(connection)

    # Sync latest withdrawal events
    sync_withdrawal_notifications(connection, user_id)

    # Fetch all notifications for this creator
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT
            id,
            withdrawal_reference,
            notification_type,
            title,
            message,
            currency,
            amount,
            is_read,
            created_at
        FROM withdrawal_notifications
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (user_id,),
    )
    all_notifs = cursor.fetchall()

    # Overview Metrics Calculations
    total_count = len(all_notifs)
    unread_count = sum(1 for n in all_notifs if n[7] == 0)
    completed_notifs = [n for n in all_notifs if n[2] == "COMPLETED"]
    rejected_notifs = [n for n in all_notifs if n[2] == "REJECTED"]

    # ========================================================
    # 1. SUMMARY METRICS
    # ========================================================
    met1, met2, met3, met4 = st.columns(4)

    with met1:
        st.metric("Total Notifications", total_count)
    with met2:
        st.metric("Unread Alerts", unread_count, delta="Action required" if unread_count > 0 else None)
    with met3:
        st.metric("Completed Payouts", len(completed_notifs))
    with met4:
        st.metric("Rejected / Restored", len(rejected_notifs))

    st.divider()

    # ========================================================
    # 2. FILTER & BULK ACTIONS
    # ========================================================
    st.subheader("📬 Notifications Inbox")

    top_act1, top_act2, top_act3 = st.columns([3, 1, 1])

    with top_act1:
        type_filter = st.selectbox(
            "Filter by Notification Type",
            [
                "All Notifications",
                "Unread Only",
                "Completed / Paid 🎉",
                "In Processing ⚙️",
                "Rejected / Balance Restored ⚠️",
                "Requests Submitted ⏳",
            ],
        )

    with top_act2:
        st.write("")
        st.write("")
        if st.button("Mark All as Read", use_container_width=True, disabled=(unread_count == 0)):
            mark_all_notifications_read(connection, user_id)
            st.success("All notifications marked as read.")
            st.rerun()

    with top_act3:
        st.write("")
        st.write("")
        if st.button("Clear Read", use_container_width=True, disabled=(total_count - unread_count == 0)):
            clear_read_notifications(connection, user_id)
            st.info("Cleared read notifications.")
            st.rerun()

    # Filter application
    filtered_notifs = []
    for n in all_notifs:
        n_id, n_ref, n_type, title, msg, curr, amt, is_read, dt = n

        if type_filter == "Unread Only" and is_read == 1:
            continue
        elif type_filter == "Completed / Paid 🎉" and n_type != "COMPLETED":
            continue
        elif type_filter == "In Processing ⚙️" and n_type != "PROCESSING":
            continue
        elif type_filter == "Rejected / Balance Restored ⚠️" and n_type != "REJECTED":
            continue
        elif type_filter == "Requests Submitted ⏳" and n_type != "REQUESTED":
            continue

        filtered_notifs.append(n)

    # ========================================================
    # 3. NOTIFICATION CARDS
    # ========================================================
    if not filtered_notifs:
        st.info("You have no notifications matching this filter.")
    else:
        for notif in filtered_notifs:
            (
                notif_id,
                w_ref,
                notif_type,
                title,
                message,
                currency,
                amount,
                is_read,
                created_at,
            ) = notif

            amt_val = float(amount or 0.0)
            curr_str = str(currency or "USD").upper()
            sym = "₦" if curr_str == "NGN" else ("$" if curr_str == "USD" else f"{curr_str} ")

            with st.container(border=True):
                c_head1, c_head2 = st.columns([4, 1])

                with c_head1:
                    # Visual status tag
                    if notif_type == "COMPLETED":
                        st.markdown(f"#### ✅ {title}")
                    elif notif_type == "PROCESSING":
                        st.markdown(f"#### ⚙️ {title}")
                    elif notif_type == "REJECTED":
                        st.markdown(f"#### 🛑 {title}")
                    else:
                        st.markdown(f"#### ⏳ {title}")

                    st.caption(f"📅 Received on **{created_at}** • Reference: `{w_ref}`")

                with c_head2:
                    if is_read == 0:
                        st.warning("🔵 Unread")
                    else:
                        st.caption("⚪ Read")

                st.write(message)

                # Context-specific guidance boxes
                if notif_type == "COMPLETED":
                    st.success(
                        f"💰 **Funds Disbursed:** {sym}{amt_val:,.2f} {curr_str} has been transmitted. "
                        "Please allow standard banking clearance times for the funds to reflect."
                    )
                elif notif_type == "REJECTED":
                    st.error(
                        f"💡 **Balance Restored:** The full amount of {sym}{amt_val:,.2f} {curr_str} "
                        "has been automatically returned to your available creator balance. "
                        "You can verify your banking information under **Creator Receiving Account** "
                        "and submit a new withdrawal request whenever you are ready."
                    )
                elif notif_type == "PROCESSING":
                    st.info(
                        "An administrator has verified your request and initiated the transfer. "
                        "You will receive an updated notification once the transfer completes."
                    )

                # Card Actions
                card_col1, card_col2, card_col3 = st.columns([2, 1, 1])
                with card_col1:
                    st.caption(f"Amount: **{sym}{amt_val:,.2f} {curr_str}**")

                with card_col3:
                    if is_read == 0:
                        if st.button("Mark as Read", key=f"read_{notif_id}", use_container_width=True):
                            mark_notification_read(connection, notif_id, 1)
                            st.rerun()
                    else:
                        if st.button("Mark Unread", key=f"unread_{notif_id}", use_container_width=True):
                            mark_notification_read(connection, notif_id, 0)
                            st.rerun()

    # ========================================================
    # 4. QUICK SHORTCUTS & HELP
    # ========================================================
    st.divider()
    st.subheader("🔗 Quick Creator Shortcuts")

    nav_col1, nav_col2 = st.columns(2)
    with nav_col1:
        st.markdown("### 💸 Creator Withdrawal")
        st.write("View your current available balance, reserved funds, or submit a new payout request.")
        st.info("Navigate to **Creator Withdrawal** from the sidebar.")

    with nav_col2:
        st.markdown("### 🏦 Receiving Accounts")
        st.write("Add, inspect, or verify your Nigerian bank accounts or USD domiciliary/wire transfer accounts.")
        st.info("Navigate to **Creator Receiving Account** from the sidebar.")

finally:
    connection.close()