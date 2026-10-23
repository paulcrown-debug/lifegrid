import sqlite3
import uuid
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime

import streamlit as st

from database import get_connection


# =========================================================
# PAGE CONFIGURATION
# =========================================================

st.set_page_config(
    page_title="Gifts & Contributions | LifeGrid",
    page_icon="🎁",
    layout="wide",
)


# =========================================================
# LOGIN PROTECTION
# =========================================================

if "user" not in st.session_state or not st.session_state["user"]:
    st.warning("Please log in to use Gifts & Contributions.")
    st.stop()


current_user = st.session_state["user"]

if isinstance(current_user, dict):
    user_id = current_user.get("id")
    username = current_user.get("username", "LifeGrid User")
    user_currency = current_user.get("currency", "USD")
else:
    user_id = current_user
    username = "LifeGrid User"
    user_currency = "USD"


if not user_id:
    st.error("Unable to identify your LifeGrid account.")
    st.stop()


# =========================================================
# DEVELOPMENT PLATFORM FEE
# =========================================================

# Development testing fee.
# This can be changed later.
PLATFORM_FEE_PERCENT = Decimal("1.00")


# =========================================================
# DATABASE
# =========================================================

connection = get_connection()


# =========================================================
# DATABASE HELPERS
# =========================================================

def table_exists(conn, table_name):
    row = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
        AND name = ?
        """,
        (table_name,),
    ).fetchone()

    return row is not None


def column_exists(conn, table_name, column_name):
    rows = conn.execute(
        f"PRAGMA table_info({table_name})"
    ).fetchall()

    return any(row[1] == column_name for row in rows)


def ensure_column(conn, table_name, column_name, definition):
    if not column_exists(conn, table_name, column_name):
        conn.execute(
            f"""
            ALTER TABLE {table_name}
            ADD COLUMN {column_name} {definition}
            """
        )


# =========================================================
# CREATE GIFTS TABLE
# =========================================================

connection.execute(
    """
    CREATE TABLE IF NOT EXISTS gifts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gift_reference TEXT UNIQUE NOT NULL,
        sender_id INTEGER NOT NULL,
        recipient_id INTEGER NOT NULL,
        gift_type TEXT NOT NULL,
        amount REAL NOT NULL,
        platform_fee REAL NOT NULL DEFAULT 0,
        sender_total REAL NOT NULL,
        recipient_amount REAL NOT NULL,
        currency TEXT NOT NULL,
        message TEXT,
        wallet_reference TEXT,
        status TEXT NOT NULL DEFAULT 'Completed',
        created_at TEXT NOT NULL
    )
    """
)

connection.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_gifts_sender
    ON gifts(sender_id)
    """
)

connection.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_gifts_recipient
    ON gifts(recipient_id)
    """
)

connection.execute(
    """
    CREATE TABLE IF NOT EXISTS platform_revenue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        revenue_reference TEXT UNIQUE NOT NULL,
        source_type TEXT NOT NULL,
        source_reference TEXT,
        payer_id INTEGER,
        amount REAL NOT NULL,
        currency TEXT NOT NULL,
        description TEXT,
        created_at TEXT NOT NULL
    )
    """
)

connection.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_platform_revenue_created
    ON platform_revenue(created_at)
    """
)

connection.commit()


# =========================================================
# NOTIFICATION HELPER
# =========================================================

def create_notification(
    conn,
    recipient_id,
    title,
    message,
    notification_type="gift",
    reference_type="gift",
    reference_id=None,
):
    if not table_exists(conn, "notifications"):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                notification_type TEXT,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                reference_type TEXT,
                reference_id INTEGER,
                is_read INTEGER DEFAULT 0,
                created_at TEXT
            )
            """
        )

    ensure_column(
        conn,
        "notifications",
        "notification_type",
        "TEXT",
    )

    ensure_column(
        conn,
        "notifications",
        "reference_type",
        "TEXT",
    )

    ensure_column(
        conn,
        "notifications",
        "reference_id",
        "INTEGER",
    )

    ensure_column(
        conn,
        "notifications",
        "is_read",
        "INTEGER DEFAULT 0",
    )

    ensure_column(
        conn,
        "notifications",
        "created_at",
        "TEXT",
    )

    conn.execute(
        """
        INSERT INTO notifications (
            user_id,
            notification_type,
            title,
            message,
            reference_type,
            reference_id,
            is_read,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, 0, ?)
        """,
        (
            recipient_id,
            notification_type,
            title,
            message,
            reference_type,
            reference_id,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )


# =========================================================
# WALLET HELPERS
# =========================================================

def get_wallet(conn, account_user_id):
    return conn.execute(
        """
        SELECT
            id,
            user_id,
            currency,
            balance,
            available_balance,
            pending_balance,
            wallet_status
        FROM wallets
        WHERE user_id = ?
        LIMIT 1
        """,
        (account_user_id,),
    ).fetchone()


def find_user_by_receiving_id(conn, receiving_id):
    receiving_id = receiving_id.strip().upper()

    if not receiving_id:
        return None

    return conn.execute(
        """
        SELECT
            ra.user_id,
            ra.receiving_id,
            ra.currency,
            ra.account_status,
            u.username
        FROM receiving_accounts ra
        JOIN users u
            ON u.id = ra.user_id
        WHERE UPPER(ra.receiving_id) = ?
        LIMIT 1
        """,
        (receiving_id,),
    ).fetchone()


# =========================================================
# MONEY CALCULATION
# =========================================================

def calculate_transaction(amount):
    fee = (
        amount * PLATFORM_FEE_PERCENT / Decimal("100")
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    sender_total = (
        amount + fee
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    recipient_amount = amount.quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    return fee, sender_total, recipient_amount


# =========================================================
# WALLET TRANSACTION
# =========================================================

def create_wallet_transaction(
    conn,
    account_user_id,
    transaction_type,
    amount,
    currency,
    description,
    reference,
    counterparty_user_id=None,
):
    if not table_exists(conn, "wallet_transactions"):
        raise ValueError(
            "The wallet_transactions table does not exist."
        )

    columns = [
        "user_id",
        "transaction_type",
        "amount",
        "currency",
        "description",
        "reference",
        "status",
        "created_at",
    ]

    values = [
        account_user_id,
        transaction_type,
        float(amount),
        currency,
        description,
        reference,
        "Completed",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    ]

    if column_exists(
        conn,
        "wallet_transactions",
        "counterparty_user_id",
    ):
        columns.append("counterparty_user_id")
        values.append(counterparty_user_id)

    placeholders = ", ".join(["?"] * len(values))
    column_names = ", ".join(columns)

    conn.execute(
        f"""
        INSERT INTO wallet_transactions (
            {column_names}
        )
        VALUES ({placeholders})
        """,
        values,
    )


# =========================================================
# PAGE HEADER
# =========================================================

st.title("🎁 Gifts & Contributions")

st.write(
    "Send gifts, contributions, or creator support to another "
    "LifeGrid user using their Receiving ID."
)

st.info(
    f"Development platform charge: "
    f"{PLATFORM_FEE_PERCENT:.2f}%"
)

st.divider()


# =========================================================
# CURRENT WALLET
# =========================================================

wallet = get_wallet(connection, user_id)

if not wallet:
    st.warning(
        "Your LifeGrid wallet has not been created yet. "
        "Please open Wallet first."
    )
    connection.close()
    st.stop()


wallet_id = wallet[0]
wallet_currency = wallet[2] or user_currency or "USD"
wallet_balance = Decimal(str(wallet[3] or 0))
wallet_available = Decimal(str(wallet[4] or 0))
wallet_pending = Decimal(str(wallet[5] or 0))
wallet_status = wallet[6] or "Active"


# =========================================================
# WALLET SUMMARY
# =========================================================

st.subheader("💳 Your Wallet")

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric(
        "Total Balance",
        f"{wallet_currency} {wallet_balance:,.2f}",
    )

with col2:
    st.metric(
        "Available",
        f"{wallet_currency} {wallet_available:,.2f}",
    )

with col3:
    st.metric(
        "Pending",
        f"{wallet_currency} {wallet_pending:,.2f}",
    )

with col4:
    st.metric(
        "Status",
        wallet_status,
    )


st.divider()


# =========================================================
# SEND FORM
# =========================================================

st.subheader("🎁 Send a Gift or Contribution")

gift_type = st.selectbox(
    "Transaction Type",
    [
        "Gift",
        "Contribution",
        "Creator Support",
    ],
)

recipient_id_text = st.text_input(
    "Recipient LifeGrid Receiving ID",
    placeholder="Example: LG-00000002",
)

amount_text = st.text_input(
    f"Gift Amount ({wallet_currency})",
    placeholder="Example: 10.00",
)

message = st.text_area(
    "Message (optional)",
    placeholder="Write a message to the recipient...",
    max_chars=500,
)


# =========================================================
# PREVIEW
# =========================================================

amount = None
fee = Decimal("0.00")
sender_total = Decimal("0.00")
recipient_amount = Decimal("0.00")

if amount_text.strip():

    try:
        amount = Decimal(
            amount_text.replace(",", "").strip()
        )

        if amount > 0:

            amount = amount.quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )

            fee, sender_total, recipient_amount = (
                calculate_transaction(amount)
            )

            st.subheader("💰 Transaction Preview")

            preview1, preview2, preview3 = st.columns(3)

            with preview1:
                st.metric(
                    "Recipient Receives",
                    f"{wallet_currency} "
                    f"{recipient_amount:,.2f}",
                )

            with preview2:
                st.metric(
                    "Platform Charge",
                    f"{wallet_currency} "
                    f"{fee:,.2f}",
                )

            with preview3:
                st.metric(
                    "You Pay",
                    f"{wallet_currency} "
                    f"{sender_total:,.2f}",
                )

        else:
            st.warning("Amount must be greater than zero.")

    except (InvalidOperation, ValueError):
        st.warning("Please enter a valid amount.")


# =========================================================
# CONFIRMATION
# =========================================================

confirmed = st.checkbox(
    "I have reviewed the recipient, gift amount, platform charge, and total payment."
)

send_button = st.button(
    "🎁 Send Gift / Contribution",
    type="primary",
    use_container_width=True,
)


# =========================================================
# PROCESS TRANSACTION
# =========================================================

if send_button:

    # -----------------------------------------------------
    # VALIDATION
    # -----------------------------------------------------

    if not recipient_id_text.strip():
        st.error(
            "Please enter the recipient's LifeGrid Receiving ID."
        )
        connection.close()
        st.stop()

    if amount is None or amount <= 0:
        st.error(
            "Please enter a valid gift amount."
        )
        connection.close()
        st.stop()

    if not confirmed:
        st.error(
            "Please confirm the transaction details before sending."
        )
        connection.close()
        st.stop()

    # -----------------------------------------------------
    # RECALCULATE
    # -----------------------------------------------------

    amount = amount.quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    fee, sender_total, recipient_amount = (
        calculate_transaction(amount)
    )

    # -----------------------------------------------------
    # FIND RECIPIENT
    # -----------------------------------------------------

    recipient = find_user_by_receiving_id(
        connection,
        recipient_id_text,
    )

    if not recipient:
        st.error(
            "No LifeGrid account was found with that Receiving ID."
        )
        connection.close()
        st.stop()

    recipient_user_id = recipient[0]
    recipient_receiving_id = recipient[1]
    recipient_currency = recipient[2] or wallet_currency
    recipient_account_status = recipient[3] or "Active"
    recipient_username = recipient[4] or "LifeGrid User"

    # -----------------------------------------------------
    # SELF TRANSFER
    # -----------------------------------------------------

    if int(recipient_user_id) == int(user_id):
        st.error(
            "You cannot send a gift to yourself."
        )
        connection.close()
        st.stop()

    # -----------------------------------------------------
    # RECIPIENT ACCOUNT STATUS
    # -----------------------------------------------------

    if str(recipient_account_status).lower() not in {
        "active",
        "verified",
        "enabled",
    }:
        st.error(
            "The recipient's Receiving Account is not active."
        )
        connection.close()
        st.stop()

    # -----------------------------------------------------
    # CURRENCY CHECK
    # -----------------------------------------------------

    if (
        str(recipient_currency).upper()
        != str(wallet_currency).upper()
    ):
        st.error(
            f"Currency mismatch. Your wallet uses "
            f"{wallet_currency}, while the recipient uses "
            f"{recipient_currency}."
        )
        connection.close()
        st.stop()

    # -----------------------------------------------------
    # RECIPIENT WALLET
    # -----------------------------------------------------

    recipient_wallet = get_wallet(
        connection,
        recipient_user_id,
    )

    if not recipient_wallet:
        st.error(
            "The recipient does not have a LifeGrid wallet."
        )
        connection.close()
        st.stop()

    recipient_wallet_id = recipient_wallet[0]
    recipient_wallet_balance = Decimal(
        str(recipient_wallet[3] or 0)
    )
    recipient_wallet_available = Decimal(
        str(recipient_wallet[4] or 0)
    )
    recipient_wallet_pending = Decimal(
        str(recipient_wallet[5] or 0)
    )

    # -----------------------------------------------------
    # START DATABASE TRANSACTION
    # -----------------------------------------------------

    try:

        connection.execute("BEGIN")

        # -------------------------------------------------
        # GET THE CURRENT SENDER WALLET
        # -------------------------------------------------

        current_wallet = get_wallet(
            connection,
            user_id,
        )

        if not current_wallet:
            raise ValueError(
                "Your wallet could not be found."
            )

        current_balance = Decimal(
            str(current_wallet[3] or 0)
        )

        # IMPORTANT:
        # Use the wallet's actual available_balance.
        current_available = Decimal(
            str(current_wallet[4] or 0)
        )

        current_pending = Decimal(
            str(current_wallet[5] or 0)
        )

        # -------------------------------------------------
        # BALANCE CHECK
        # -------------------------------------------------

        if sender_total > current_available:
            raise ValueError(
                f"Insufficient available balance. "
                f"You need {wallet_currency} "
                f"{sender_total:,.2f}, but your available "
                f"balance is {wallet_currency} "
                f"{current_available:,.2f}."
            )

        # -------------------------------------------------
        # CALCULATE NEW SENDER BALANCE
        # -------------------------------------------------

        new_sender_balance = (
            current_balance - sender_total
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

        new_sender_available = (
            current_available - sender_total
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

        if new_sender_balance < 0:
            raise ValueError(
                "The transaction would create a negative wallet balance."
            )

        if new_sender_available < 0:
            raise ValueError(
                "The transaction would create a negative available balance."
            )

        # -------------------------------------------------
        # CALCULATE RECIPIENT BALANCE
        # -------------------------------------------------

        new_recipient_balance = (
            recipient_wallet_balance
            + recipient_amount
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

        new_recipient_available = (
            recipient_wallet_available
            + recipient_amount
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

        timestamp = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        # -------------------------------------------------
        # REFERENCES
        # -------------------------------------------------

        gift_reference = (
            "LG-GIFT-"
            + uuid.uuid4().hex[:12].upper()
        )

        wallet_reference = (
            "LG-GIFT-WALLET-"
            + uuid.uuid4().hex[:12].upper()
        )

        revenue_reference = (
            "LG-REV-GIFT-"
            + uuid.uuid4().hex[:12].upper()
        )

        # -------------------------------------------------
        # UPDATE SENDER
        # -------------------------------------------------

        connection.execute(
            """
            UPDATE wallets
            SET balance = ?,
                available_balance = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                float(new_sender_balance),
                float(new_sender_available),
                timestamp,
                wallet_id,
            ),
        )

        # -------------------------------------------------
        # UPDATE RECIPIENT
        # -------------------------------------------------

        connection.execute(
            """
            UPDATE wallets
            SET balance = ?,
                available_balance = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                float(new_recipient_balance),
                float(new_recipient_available),
                timestamp,
                recipient_wallet_id,
            ),
        )

        # -------------------------------------------------
        # SENDER WALLET LEDGER
        # -------------------------------------------------

        create_wallet_transaction(
            conn=connection,
            account_user_id=user_id,
            transaction_type="Gift Sent",
            amount=-sender_total,
            currency=wallet_currency,
            description=(
                f"{gift_type} sent to "
                f"{recipient_username} "
                f"({recipient_receiving_id})"
            ),
            reference=wallet_reference,
            counterparty_user_id=recipient_user_id,
        )

        # -------------------------------------------------
        # RECIPIENT WALLET LEDGER
        # -------------------------------------------------

        create_wallet_transaction(
            conn=connection,
            account_user_id=recipient_user_id,
            transaction_type="Gift Received",
            amount=recipient_amount,
            currency=wallet_currency,
            description=(
                f"{gift_type} received from "
                f"{username}"
            ),
            reference=gift_reference,
            counterparty_user_id=user_id,
        )

        # -------------------------------------------------
        # GIFT RECORD
        # -------------------------------------------------

        gift_cursor = connection.execute(
            """
            INSERT INTO gifts (
                gift_reference,
                sender_id,
                recipient_id,
                gift_type,
                amount,
                platform_fee,
                sender_total,
                recipient_amount,
                currency,
                message,
                wallet_reference,
                status,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                gift_reference,
                user_id,
                recipient_user_id,
                gift_type,
                float(amount),
                float(fee),
                float(sender_total),
                float(recipient_amount),
                wallet_currency,
                message.strip(),
                wallet_reference,
                "Completed",
                timestamp,
            ),
        )

        gift_id = gift_cursor.lastrowid

        # -------------------------------------------------
        # PLATFORM REVENUE
        # -------------------------------------------------

        connection.execute(
            """
            INSERT INTO platform_revenue (
                revenue_reference,
                source_type,
                source_reference,
                payer_id,
                amount,
                currency,
                description,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                revenue_reference,
                "Gift Platform Fee",
                gift_reference,
                user_id,
                float(fee),
                wallet_currency,
                (
                    f"{PLATFORM_FEE_PERCENT:.2f}% "
                    f"platform charge on {gift_type.lower()}"
                ),
                timestamp,
            ),
        )

        # -------------------------------------------------
        # RECIPIENT NOTIFICATION
        # -------------------------------------------------

        recipient_message = (
            f"{username} sent you a "
            f"{gift_type.lower()} of "
            f"{wallet_currency} "
            f"{recipient_amount:,.2f}."
        )

        if message.strip():
            recipient_message += (
                f" Message: {message.strip()}"
            )

        create_notification(
            conn=connection,
            recipient_id=recipient_user_id,
            title=f"🎁 New {gift_type}",
            message=recipient_message,
            notification_type="gift",
            reference_type="gift",
            reference_id=gift_id,
        )

        # -------------------------------------------------
        # SENDER NOTIFICATION
        # -------------------------------------------------

        create_notification(
            conn=connection,
            recipient_id=user_id,
            title=f"✅ {gift_type} Sent",
            message=(
                f"You sent {wallet_currency} "
                f"{recipient_amount:,.2f} to "
                f"{recipient_username}. "
                f"Platform charge: "
                f"{wallet_currency} {fee:,.2f}. "
                f"Total paid: "
                f"{wallet_currency} "
                f"{sender_total:,.2f}."
            ),
            notification_type="gift",
            reference_type="gift",
            reference_id=gift_id,
        )

        # -------------------------------------------------
        # COMMIT
        # -------------------------------------------------

        connection.commit()

        st.success(
            f"🎉 {gift_type} completed successfully!"
        )

        result1, result2, result3 = st.columns(3)

        with result1:
            st.metric(
                "Recipient Receives",
                f"{wallet_currency} "
                f"{recipient_amount:,.2f}",
            )

        with result2:
            st.metric(
                "Platform Charge",
                f"{wallet_currency} "
                f"{fee:,.2f}",
            )

        with result3:
            st.metric(
                "Total You Paid",
                f"{wallet_currency} "
                f"{sender_total:,.2f}",
            )

        st.info(
            f"Gift Reference: {gift_reference}"
        )

        st.rerun()

    except ValueError as error:

        try:
            connection.rollback()
        except Exception:
            pass

        st.error(str(error))

    except sqlite3.IntegrityError as error:

        try:
            connection.rollback()
        except Exception:
            pass

        st.error(
            "The transaction could not be completed because "
            "of a database integrity problem."
        )

        st.caption(str(error))

    except Exception as error:

        try:
            connection.rollback()
        except Exception:
            pass

        st.error(
            "The gift transaction could not be completed."
        )

        st.caption(str(error))


# =========================================================
# HISTORY
# =========================================================

st.divider()

st.subheader("📜 Gift & Contribution History")

sent_tab, received_tab = st.tabs(
    [
        "📤 Sent",
        "📥 Received",
    ]
)


# =========================================================
# SENT HISTORY
# =========================================================

with sent_tab:

    sent_rows = connection.execute(
        """
        SELECT
            g.gift_reference,
            g.gift_type,
            g.amount,
            g.platform_fee,
            g.sender_total,
            g.recipient_amount,
            g.currency,
            g.message,
            g.status,
            g.created_at,
            u.username
        FROM gifts g
        LEFT JOIN users u
            ON u.id = g.recipient_id
        WHERE g.sender_id = ?
        ORDER BY g.created_at DESC
        """,
        (user_id,),
    ).fetchall()

    if not sent_rows:

        st.info(
            "You have not sent any gifts or contributions yet."
        )

    else:

        for row in sent_rows:

            (
                reference,
                gift_type_row,
                gift_amount,
                platform_fee,
                total_paid,
                received_amount,
                currency,
                gift_message,
                status,
                created_at,
                recipient_name,
            ) = row

            with st.container(border=True):

                col1, col2, col3 = st.columns(
                    [2, 2, 1]
                )

                with col1:

                    st.markdown(
                        f"### 🎁 {gift_type_row}"
                    )

                    st.write(
                        f"To: **{recipient_name or 'LifeGrid User'}**"
                    )

                with col2:

                    st.write(
                        f"Recipient receives: "
                        f"**{currency} "
                        f"{Decimal(str(received_amount or 0)):,.2f}**"
                    )

                    st.write(
                        f"Platform charge: "
                        f"**{currency} "
                        f"{Decimal(str(platform_fee or 0)):,.2f}**"
                    )

                    st.write(
                        f"Total paid: "
                        f"**{currency} "
                        f"{Decimal(str(total_paid or 0)):,.2f}**"
                    )

                with col3:

                    st.write(
                        f"**{status}**"
                    )

                    st.caption(
                        created_at
                    )

                if gift_message:

                    st.write(
                        f"💬 {gift_message}"
                    )

                st.caption(
                    f"Reference: {reference}"
                )


# =========================================================
# RECEIVED HISTORY
# =========================================================

with received_tab:

    received_rows = connection.execute(
        """
        SELECT
            g.gift_reference,
            g.gift_type,
            g.amount,
            g.platform_fee,
            g.sender_total,
            g.recipient_amount,
            g.currency,
            g.message,
            g.status,
            g.created_at,
            u.username
        FROM gifts g
        LEFT JOIN users u
            ON u.id = g.sender_id
        WHERE g.recipient_id = ?
        ORDER BY g.created_at DESC
        """,
        (user_id,),
    ).fetchall()

    if not received_rows:

        st.info(
            "You have not received any gifts or contributions yet."
        )

    else:

        for row in received_rows:

            (
                reference,
                gift_type_row,
                gift_amount,
                platform_fee,
                total_paid,
                received_amount,
                currency,
                gift_message,
                status,
                created_at,
                sender_name,
            ) = row

            with st.container(border=True):

                col1, col2, col3 = st.columns(
                    [2, 2, 1]
                )

                with col1:

                    st.markdown(
                        f"### 🎁 {gift_type_row}"
                    )

                    st.write(
                        f"From: **{sender_name or 'LifeGrid User'}**"
                    )

                with col2:

                    st.write(
                        f"You received: "
                        f"**{currency} "
                        f"{Decimal(str(received_amount or 0)):,.2f}**"
                    )

                with col3:

                    st.write(
                        f"**{status}**"
                    )

                    st.caption(
                        created_at
                    )

                if gift_message:

                    st.write(
                        f"💬 {gift_message}"
                    )

                st.caption(
                    f"Reference: {reference}"
                )


# =========================================================
# FEE INFORMATION
# =========================================================

st.divider()

with st.expander(
    "ℹ️ How the LifeGrid platform charge works"
):

    st.write(
        f"""
        The current development platform charge is
        **{PLATFORM_FEE_PERCENT:.2f}%**.

        Example:

        Gift amount: **{wallet_currency} 10.00**

        Platform charge: **{wallet_currency} 0.10**

        Total deducted from sender: **{wallet_currency} 10.10**

        Recipient receives: **{wallet_currency} 10.00**

        If the sender has **{wallet_currency} 19.00 available**,
        the remaining available balance should be:

        **{wallet_currency} 8.90**
        """
    )


# =========================================================
# FOOTER
# =========================================================

st.divider()

st.caption(
    "🌍 LifeGrid • Your life, your growth, your connections."
)

connection.close()