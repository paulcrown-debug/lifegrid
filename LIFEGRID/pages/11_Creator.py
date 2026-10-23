import sqlite3
import uuid
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime

import streamlit as st

from database import get_connection


# =========================================================
# LIFEGRID CREATOR EARNINGS
# =========================================================

st.set_page_config(
    page_title="Creator | LifeGrid",
    page_icon="💰",
    layout="wide",
)


# =========================================================
# LOGIN PROTECTION
# =========================================================

if "user" not in st.session_state or not st.session_state["user"]:
    st.warning("Please log in to access Creator Earnings.")
    st.stop()


# =========================================================
# CURRENT USER
# =========================================================

current_user = st.session_state["user"]

if isinstance(current_user, dict):
    user_id = int(
        current_user.get("id")
        or current_user.get("user_id")
        or 0
    )

    username = str(
        current_user.get("username")
        or current_user.get("name")
        or "User"
    )

    user_currency = str(
        current_user.get("currency")
        or current_user.get("currency_code")
        or "USD"
    ).upper()

else:
    user_id = int(current_user)
    username = "User"
    user_currency = "USD"


if not user_id:
    st.error("Unable to identify your LifeGrid account.")
    st.stop()


# =========================================================
# DEVELOPMENT PLATFORM FEE
# =========================================================

PLATFORM_FEE_PERCENT = Decimal("1.00")


# =========================================================
# DATABASE HELPERS
# =========================================================

def table_columns(connection, table_name):
    rows = connection.execute(
        f"PRAGMA table_info({table_name})"
    ).fetchall()

    return {row[1] for row in rows}


def ensure_column(connection, table_name, column_name, definition):
    columns = table_columns(connection, table_name)

    if column_name not in columns:
        connection.execute(
            f"""
            ALTER TABLE {table_name}
            ADD COLUMN {column_name} {definition}
            """
        )


def create_tables(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS creator_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            description TEXT DEFAULT '',
            creator_status TEXT NOT NULL DEFAULT 'active',
            total_earnings REAL NOT NULL DEFAULT 0,
            currency TEXT NOT NULL DEFAULT 'USD',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS creator_earnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            earning_reference TEXT NOT NULL UNIQUE,
            creator_id INTEGER NOT NULL,
            supporter_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            platform_fee REAL NOT NULL DEFAULT 0,
            supporter_total REAL NOT NULL,
            currency TEXT NOT NULL,
            message TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Completed',
            created_at TEXT NOT NULL
        )
        """
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_revenue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            revenue_reference TEXT NOT NULL UNIQUE,
            source_type TEXT NOT NULL,
            source_reference TEXT NOT NULL,
            payer_id INTEGER,
            amount REAL NOT NULL,
            currency TEXT NOT NULL,
            description TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )

    connection.commit()


def get_wallet(connection, owner_id):
    return connection.execute(
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
        (owner_id,),
    ).fetchone()


def get_creator(connection, owner_id):
    return connection.execute(
        """
        SELECT
            id,
            user_id,
            display_name,
            description,
            creator_status,
            total_earnings,
            currency,
            created_at,
            updated_at
        FROM creator_profiles
        WHERE user_id = ?
        LIMIT 1
        """,
        (owner_id,),
    ).fetchone()


def get_all_active_creators(connection, exclude_user_id):
    return connection.execute(
        """
        SELECT
            cp.id,
            cp.user_id,
            cp.display_name,
            cp.description,
            cp.total_earnings,
            cp.currency,
            u.username
        FROM creator_profiles cp
        LEFT JOIN users u
            ON u.id = cp.user_id
        WHERE cp.creator_status = 'active'
          AND cp.user_id != ?
        ORDER BY cp.display_name COLLATE NOCASE
        """,
        (exclude_user_id,),
    ).fetchall()


def create_notification(connection, recipient_id, title, message):
    columns = table_columns(connection, "notifications")

    fields = []
    values = []

    if "user_id" in columns:
        fields.append("user_id")
        values.append(recipient_id)

    if "notification_type" in columns:
        fields.append("notification_type")
        values.append("creator")

    if "title" in columns:
        fields.append("title")
        values.append(title)

    if "message" in columns:
        fields.append("message")
        values.append(message)

    if "reference_type" in columns:
        fields.append("reference_type")
        values.append("creator_earning")

    if "reference_id" in columns:
        fields.append("reference_id")
        values.append(str(uuid.uuid4()))

    if "is_read" in columns:
        fields.append("is_read")
        values.append(0)

    if "created_at" in columns:
        fields.append("created_at")
        values.append(
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )

    if not fields:
        return

    placeholders = ", ".join(["?"] * len(fields))

    connection.execute(
        f"""
        INSERT INTO notifications
        ({", ".join(fields)})
        VALUES ({placeholders})
        """,
        tuple(values),
    )


def create_wallet_transaction(
    connection,
    owner_id,
    transaction_type,
    amount,
    currency,
    description,
    reference,
    counterparty_user_id=None,
):
    columns = table_columns(
        connection,
        "wallet_transactions",
    )

    fields = [
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
        owner_id,
        transaction_type,
        float(amount),
        currency,
        description,
        reference,
        "Completed",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    ]

    if "counterparty_user_id" in columns:
        fields.append("counterparty_user_id")
        values.append(counterparty_user_id)

    placeholders = ", ".join(["?"] * len(fields))

    connection.execute(
        f"""
        INSERT INTO wallet_transactions
        ({", ".join(fields)})
        VALUES ({placeholders})
        """,
        tuple(values),
    )


def calculate_support(amount):
    fee = (
        amount
        * PLATFORM_FEE_PERCENT
        / Decimal("100")
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    supporter_total = (
        amount + fee
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    return fee, supporter_total


# =========================================================
# DATABASE INITIALIZATION
# =========================================================

connection = get_connection()

try:
    create_tables(connection)

    ensure_column(
        connection,
        "creator_profiles",
        "total_earnings",
        "REAL NOT NULL DEFAULT 0",
    )

    ensure_column(
        connection,
        "creator_profiles",
        "currency",
        "TEXT NOT NULL DEFAULT 'USD'",
    )

    connection.commit()

except Exception as exc:
    try:
        connection.close()
    except Exception:
        pass

    st.error(
        f"Creator database setup failed: {exc}"
    )
    st.stop()


# =========================================================
# PAGE HEADER
# =========================================================

st.title("💰 Creator Earnings")

st.caption(
    "Build your creator profile, receive support, "
    "and earn through LifeGrid."
)


# =========================================================
# CREATOR PROFILE
# =========================================================

creator = get_creator(
    connection,
    user_id,
)

st.subheader("🎨 Your Creator Account")

if creator:
    creator_id = creator[0]
    creator_display_name = creator[2]
    creator_description = creator[3] or ""
    creator_status = creator[4]

    total_earnings = Decimal(
        str(creator[5] or 0)
    )

    creator_currency = str(
        creator[6] or user_currency
    ).upper()

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric(
            "Creator Status",
            (
                "Active"
                if creator_status == "active"
                else creator_status.title()
            ),
        )

    with col2:
        st.metric(
            "Total Earnings",
            f"{creator_currency} {total_earnings:.2f}",
        )

    with col3:
        st.metric(
            "Platform Fee",
            f"{PLATFORM_FEE_PERCENT:.0f}%",
        )

    with st.expander(
        "✏️ Edit Creator Profile"
    ):
        new_display_name = st.text_input(
            "Creator Display Name",
            value=creator_display_name,
            max_chars=100,
        )

        new_description = st.text_area(
            "Creator Description",
            value=creator_description,
            max_chars=500,
            height=120,
        )

        if st.button(
            "Save Creator Profile",
            type="primary",
            use_container_width=True,
        ):
            cleaned_name = (
                new_display_name.strip()
            )

            if not cleaned_name:
                st.error(
                    "Please enter a creator display name."
                )
            else:
                connection.execute(
                    """
                    UPDATE creator_profiles
                    SET
                        display_name = ?,
                        description = ?,
                        updated_at = ?
                    WHERE user_id = ?
                    """,
                    (
                        cleaned_name,
                        new_description.strip(),
                        datetime.now().strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                        user_id,
                    ),
                )

                connection.commit()

                st.success(
                    "Creator profile updated successfully."
                )

                st.rerun()

else:
    st.info(
        "You do not have an active Creator Account yet. "
        "Activate one below to start receiving creator support."
    )

    with st.form(
        "activate_creator_form"
    ):
        display_name = st.text_input(
            "Creator Display Name",
            value=username,
            max_chars=100,
        )

        description = st.text_area(
            "Tell people about your creator account",
            placeholder=(
                "Example: I create educational, construction, "
                "business, or community content on LifeGrid."
            ),
            max_chars=500,
            height=130,
        )

        activate = st.form_submit_button(
            "🚀 Activate Creator Account",
            use_container_width=True,
        )

        if activate:
            cleaned_name = (
                display_name.strip()
            )

            if not cleaned_name:
                st.error(
                    "Please enter a creator display name."
                )
            else:
                now = datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

                connection.execute(
                    """
                    INSERT INTO creator_profiles (
                        user_id,
                        display_name,
                        description,
                        creator_status,
                        total_earnings,
                        currency,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        ?,
                        ?,
                        ?,
                        'active',
                        0,
                        ?,
                        ?,
                        ?
                    )
                    """,
                    (
                        user_id,
                        cleaned_name,
                        description.strip(),
                        user_currency,
                        now,
                        now,
                    ),
                )

                create_notification(
                    connection,
                    user_id,
                    "Creator Account Activated",
                    (
                        f"Welcome to LifeGrid Creator Earnings, "
                        f"{cleaned_name}. Your creator account "
                        "is now active."
                    ),
                )

                connection.commit()

                st.success(
                    "Your Creator Account has been "
                    "activated successfully."
                )

                st.rerun()


# =========================================================
# SUPPORT A CREATOR
# =========================================================

st.divider()

st.subheader("❤️ Support a Creator")

active_creators = get_all_active_creators(
    connection,
    user_id,
)

if not active_creators:
    st.info(
        "There are currently no other active Creator "
        "Accounts available to support."
    )

else:
    creator_options = {}

    for row in active_creators:
        profile_id = row[0]
        creator_owner_id = row[1]
        display_name = row[2]
        description = row[3] or ""
        currency = str(
            row[5] or user_currency
        ).upper()
        creator_username = row[6] or ""

        label = (
            f"{display_name} "
            f"(@{creator_username})"
        )

        creator_options[label] = {
            "profile_id": profile_id,
            "user_id": creator_owner_id,
            "display_name": display_name,
            "description": description,
            "currency": currency,
        }

    selected_label = st.selectbox(
        "Choose a Creator",
        list(creator_options.keys()),
    )

    selected_creator = creator_options[
        selected_label
    ]

    if selected_creator["description"]:
        st.caption(
            selected_creator["description"]
        )

    st.info(
        f"Creator receives the full contribution. "
        f"The current development platform charge is "
        f"{PLATFORM_FEE_PERCENT:.0f}% and is paid by "
        "the supporter."
    )

    with st.form(
        "creator_support_form"
    ):
        amount_input = st.number_input(
            (
                "Support Amount "
                f"({selected_creator['currency']})"
            ),
            min_value=0.01,
            value=10.00,
            step=1.00,
            format="%.2f",
        )

        support_message = st.text_area(
            "Message (optional)",
            max_chars=300,
            placeholder=(
                "Send a message to the creator."
            ),
        )

        confirmation = st.checkbox(
            "I have reviewed the creator, support "
            "amount, platform charge, and total payment."
        )

        send_support = st.form_submit_button(
            "💰 Send Creator Support",
            type="primary",
            use_container_width=True,
        )

        amount = Decimal(
            str(amount_input)
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

        fee, supporter_total = (
            calculate_support(amount)
        )

        st.caption(
            f"Creator receives: "
            f"{selected_creator['currency']} "
            f"{amount:.2f}  |  "
            f"Platform charge: "
            f"{selected_creator['currency']} "
            f"{fee:.2f}  |  "
            f"Total payment: "
            f"{selected_creator['currency']} "
            f"{supporter_total:.2f}"
        )

        if send_support:

            if not confirmation:
                st.error(
                    "Please confirm the support details "
                    "before sending."
                )
                st.stop()

            if amount <= 0:
                st.error(
                    "Support amount must be greater than zero."
                )
                st.stop()

            if selected_creator["user_id"] == user_id:
                st.error(
                    "You cannot send creator support "
                    "to your own account."
                )
                st.stop()

            sender_wallet = get_wallet(
                connection,
                user_id,
            )

            recipient_wallet = get_wallet(
                connection,
                selected_creator["user_id"],
            )

            if not sender_wallet:
                st.error(
                    "Your LifeGrid wallet could not be found."
                )
                st.stop()

            if not recipient_wallet:
                st.error(
                    "The creator does not currently "
                    "have a LifeGrid wallet."
                )
                st.stop()

            sender_currency = str(
                sender_wallet[2]
                or user_currency
            ).upper()

            recipient_currency = str(
                recipient_wallet[2]
                or selected_creator["currency"]
            ).upper()

            if sender_currency != recipient_currency:
                st.error(
                    "The creator's wallet currency does "
                    "not match your wallet currency."
                )
                st.stop()

            if sender_wallet[6] != "Active":
                st.error(
                    "Your wallet is not active."
                )
                st.stop()

            if recipient_wallet[6] != "Active":
                st.error(
                    "The creator's wallet is not active."
                )
                st.stop()

            current_available = Decimal(
                str(sender_wallet[4] or 0)
            )

            current_balance = Decimal(
                str(sender_wallet[3] or 0)
            )

            recipient_balance = Decimal(
                str(recipient_wallet[3] or 0)
            )

            recipient_available = Decimal(
                str(recipient_wallet[4] or 0)
            )

            if supporter_total > current_available:
                st.error(
                    f"Insufficient available balance. "
                    f"You need {sender_currency} "
                    f"{supporter_total:.2f}, but only "
                    f"{sender_currency} "
                    f"{current_available:.2f} is available."
                )
                st.stop()

            # -------------------------------------------------
            # UNIQUE REFERENCES
            # -------------------------------------------------

            earning_reference = (
                f"LG-CREATOR-"
                f"{uuid.uuid4().hex[:12].upper()}"
            )

            sender_wallet_reference = (
                f"LG-CREATOR-SENT-"
                f"{uuid.uuid4().hex[:12].upper()}"
            )

            recipient_wallet_reference = (
                f"LG-CREATOR-RECEIVED-"
                f"{uuid.uuid4().hex[:12].upper()}"
            )

            revenue_reference = (
                f"LG-REVENUE-"
                f"{uuid.uuid4().hex[:12].upper()}"
            )

            now = datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            # -------------------------------------------------
            # CALCULATE NEW BALANCES
            # -------------------------------------------------

            new_sender_balance = (
                current_balance - supporter_total
            ).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )

            new_sender_available = (
                current_available - supporter_total
            ).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )

            new_recipient_balance = (
                recipient_balance + amount
            ).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )

            new_recipient_available = (
                recipient_available + amount
            ).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )

            # -------------------------------------------------
            # ATOMIC TRANSACTION
            # -------------------------------------------------

            try:
                connection.execute("BEGIN")

                # =============================================
                # DEDUCT SUPPORTER
                # =============================================

                connection.execute(
                    """
                    UPDATE wallets
                    SET
                        balance = ?,
                        available_balance = ?,
                        updated_at = ?
                    WHERE user_id = ?
                    """,
                    (
                        float(new_sender_balance),
                        float(new_sender_available),
                        now,
                        user_id,
                    ),
                )

                # =============================================
                # CREDIT CREATOR
                # =============================================

                connection.execute(
                    """
                    UPDATE wallets
                    SET
                        balance = ?,
                        available_balance = ?,
                        updated_at = ?
                    WHERE user_id = ?
                    """,
                    (
                        float(new_recipient_balance),
                        float(new_recipient_available),
                        now,
                        selected_creator["user_id"],
                    ),
                )

                # =============================================
                # SENDER WALLET TRANSACTION
                # =============================================

                create_wallet_transaction(
                    connection,
                    user_id,
                    "Creator Support Sent",
                    -supporter_total,
                    sender_currency,
                    (
                        "Creator support sent to "
                        f"{selected_creator['display_name']}"
                    ),
                    sender_wallet_reference,
                    selected_creator["user_id"],
                )

                # =============================================
                # CREATOR WALLET TRANSACTION
                # =============================================

                create_wallet_transaction(
                    connection,
                    selected_creator["user_id"],
                    "Creator Earnings Received",
                    amount,
                    sender_currency,
                    (
                        "Creator earnings received from "
                        f"{username}"
                    ),
                    recipient_wallet_reference,
                    user_id,
                )

                # =============================================
                # CREATOR EARNING RECORD
                # =============================================

                connection.execute(
                    """
                    INSERT INTO creator_earnings (
                        earning_reference,
                        creator_id,
                        supporter_id,
                        amount,
                        platform_fee,
                        supporter_total,
                        currency,
                        message,
                        status,
                        created_at
                    )
                    VALUES (
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        'Completed',
                        ?
                    )
                    """,
                    (
                        earning_reference,
                        selected_creator["user_id"],
                        user_id,
                        float(amount),
                        float(fee),
                        float(supporter_total),
                        sender_currency,
                        support_message.strip(),
                        now,
                    ),
                )

                # =============================================
                # UPDATE CREATOR TOTAL
                # =============================================

                connection.execute(
                    """
                    UPDATE creator_profiles
                    SET
                        total_earnings =
                            total_earnings + ?,
                        updated_at = ?
                    WHERE user_id = ?
                    """,
                    (
                        float(amount),
                        now,
                        selected_creator["user_id"],
                    ),
                )

                # =============================================
                # PLATFORM REVENUE
                # =============================================

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
                    VALUES (
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        ?
                    )
                    """,
                    (
                        revenue_reference,
                        "creator_support",
                        earning_reference,
                        user_id,
                        float(fee),
                        sender_currency,
                        (
                            "Creator support platform charge "
                            f"from {username}"
                        ),
                        now,
                    ),
                )

                # =============================================
                # CREATOR NOTIFICATION
                # =============================================

                create_notification(
                    connection,
                    selected_creator["user_id"],
                    "Creator Support Received",
                    (
                        f"You received "
                        f"{sender_currency} "
                        f"{amount:.2f} in creator support "
                        f"from {username}."
                    ),
                )

                # =============================================
                # SUPPORTER NOTIFICATION
                # =============================================

                create_notification(
                    connection,
                    user_id,
                    "Creator Support Sent",
                    (
                        f"Your "
                        f"{sender_currency} "
                        f"{amount:.2f} creator support to "
                        f"{selected_creator['display_name']} "
                        "was completed. "
                        f"Platform charge: "
                        f"{sender_currency} "
                        f"{fee:.2f}."
                    ),
                )

                # =============================================
                # COMMIT EVERYTHING
                # =============================================

                connection.commit()

                st.success(
                    "Creator support completed successfully. "
                    f"{sender_currency} {amount:.2f} was sent "
                    f"to {selected_creator['display_name']}."
                )

                st.rerun()

            except Exception as exc:

                try:
                    connection.rollback()
                except Exception:
                    pass

                st.error(
                    "The creator support transaction "
                    "could not be completed."
                )

                st.exception(exc)


# =========================================================
# CREATOR EARNINGS HISTORY
# =========================================================

st.divider()

st.subheader(
    "📜 Your Creator Earnings History"
)

earnings = connection.execute(
    """
    SELECT
        ce.earning_reference,
        ce.amount,
        ce.platform_fee,
        ce.supporter_total,
        ce.currency,
        ce.message,
        ce.status,
        ce.created_at,
        u.username
    FROM creator_earnings ce
    LEFT JOIN users u
        ON u.id = ce.supporter_id
    WHERE ce.creator_id = ?
    ORDER BY ce.id DESC
    """,
    (user_id,),
).fetchall()

if not earnings:
    st.info(
        "You have not received any creator earnings yet."
    )

else:
    total_received = Decimal("0.00")
    total_fees = Decimal("0.00")

    for earning in earnings:

        (
            reference,
            amount,
            fee,
            supporter_total,
            currency,
            message,
            status,
            created_at,
            supporter_username,
        ) = earning

        amount_decimal = Decimal(
            str(amount or 0)
        )

        fee_decimal = Decimal(
            str(fee or 0)
        )

        total_received += amount_decimal
        total_fees += fee_decimal

        with st.container(border=True):

            col1, col2 = st.columns([3, 1])

            with col1:
                st.markdown(
                    "### 💰 Creator Earnings"
                )

                st.write(
                    f"**From:** "
                    f"{supporter_username or 'LifeGrid user'}"
                )

                st.write(
                    f"**Received:** "
                    f"{currency} "
                    f"{amount_decimal:.2f}"
                )

                st.write(
                    f"**Platform charge:** "
                    f"{currency} "
                    f"{fee_decimal:.2f}"
                )

                if message:
                    st.write(
                        f"💬 {message}"
                    )

                st.caption(
                    f"Reference: {reference} • "
                    f"{created_at}"
                )

            with col2:
                st.metric(
                    "Status",
                    status,
                )

    st.divider()

    summary_col1, summary_col2 = st.columns(2)

    with summary_col1:
        st.metric(
            "Total Creator Earnings",
            f"{user_currency} "
            f"{total_received:.2f}",
        )

    with summary_col2:
        st.metric(
            "Platform Fees Generated",
            f"{user_currency} "
            f"{total_fees:.2f}",
        )


# =========================================================
# DEVELOPMENT INFORMATION
# =========================================================

st.divider()

with st.expander(
    "ℹ️ Creator Earnings Development Rules"
):
    st.write(
        "• Creator receives the full support amount."
    )

    st.write(
        "• The supporter pays the platform charge."
    )

    st.write(
        f"• Current development platform charge: "
        f"{PLATFORM_FEE_PERCENT:.0f}%."
    )

    st.write(
        "• Creator earnings are credited directly "
        "to the creator's LifeGrid wallet."
    )

    st.write(
        "• Every completed earning receives a unique "
        "creator reference."
    )

    st.write(
        "• Sender and creator wallet transactions each "
        "receive their own unique wallet reference."
    )

    st.write(
        "• Platform revenue is recorded separately."
    )

    st.write(
        "• The current fee is a development setting, "
        "not a final production pricing decision."
    )


# =========================================================
# FOOTER
# =========================================================

st.divider()

st.caption(
    "LifeGrid Creator Earnings • "
    "Your life, your growth, your connections."
)


# =========================================================
# CLOSE DATABASE
# =========================================================

connection.close()