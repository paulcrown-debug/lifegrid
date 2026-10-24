
import sqlite3
from datetime import datetime
from decimal import Decimal, InvalidOperation

import streamlit as st

from database import get_connection
import uuid
try:
    from services.flutterwave import (
        create_payment_link,
        is_flutterwave_configured,
        verify_transaction,
        verify_transaction_by_reference,
    )
except ImportError:
    def is_flutterwave_configured():
        return False
    def create_payment_link(*args, **kwargs):
        return {"checkout_url": "#"}
    def verify_transaction(*args, **kwargs):
        return {"data": {}}
    def verify_transaction_by_reference(*args, **kwargs):
        return {"data": {}}


# =========================================================
# PAGE CONFIGURATION
# =========================================================

st.set_page_config(
    page_title="Gift Store | LifeGrid",
    page_icon="🎁",
    layout="wide",
)


# =========================================================
# LOGIN
# =========================================================

if "user" not in st.session_state:
    st.warning("Please log in to access the LifeGrid Gift Store.")
    st.stop()

if not st.session_state.get("user"):
    st.warning("Please log in to access the LifeGrid Gift Store.")
    st.stop()


# =========================================================
# USER ID
# =========================================================

session_user = st.session_state.get("user")

if isinstance(session_user, dict):
    USER_ID = (
        session_user.get("id")
        or session_user.get("user_id")
        or session_user.get("uid")
    )
else:
    USER_ID = session_user

if USER_ID is None:
    st.error("Unable to identify the current LifeGrid account.")
    st.stop()


# =========================================================
# DATABASE HELPERS
# =========================================================

def now():
    return datetime.now().isoformat(timespec="seconds")


def get_columns(connection, table_name):
    rows = connection.execute(
        f"PRAGMA table_info({table_name})"
    ).fetchall()

    return {row[1] for row in rows}


def get_table_info(connection, table_name):
    return connection.execute(
        f"PRAGMA table_info({table_name})"
    ).fetchall()


def add_column(
    connection,
    table_name,
    column_name,
    definition,
):
    columns = get_columns(
        connection,
        table_name,
    )

    if column_name not in columns:
        connection.execute(
            f"""
            ALTER TABLE {table_name}
            ADD COLUMN {column_name} {definition}
            """
        )


def make_reference(prefix="LG"):
    return (
        f"{prefix}-"
        f"{datetime.now().strftime('%Y%m%d%H%M%S')}-"
        f"{USER_ID}-"
        f"{datetime.now().microsecond}"
    )


def value_for_required_column(
    column_name,
    transaction_reference,
    timestamp,
    currency,
    amount,
    credits,
    user_id,
):
    name = column_name.lower()

    if name in (
        "reference",
        "transaction_reference",
        "transaction_id",
        "reference_id",
        "ref",
    ):
        return transaction_reference

    if name in (
        "user_id",
        "sender_user_id",
        "customer_id",
        "account_id",
    ):
        return user_id

    if name in (
        "receiver_user_id",
        "recipient_user_id",
        "counterparty_user_id",
    ):
        return None

    if name in (
        "wallet_currency",
        "currency",
        "currency_code",
    ):
        return currency

    if name in (
        "amount",
        "wallet_amount",
        "debit_amount",
        "value",
        "price",
    ):
        return amount

    if name in (
        "credits",
        "credit",
        "gift_credits",
        "credit_amount",
        "total_credits",
    ):
        return credits

    if name in (
        "quantity",
    ):
        return 1

    if name in (
        "status",
        "transaction_status",
    ):
        return "Completed"

    if name in (
        "created_at",
        "updated_at",
        "transaction_date",
        "date",
        "timestamp",
    ):
        return timestamp

    if name in (
        "description",
        "details",
        "note",
    ):
        return "LifeGrid Gift Credit purchase"

    if name in (
        "transaction_type",
        "type",
    ):
        return "Gift Credit Purchase"

    if name in (
        "asset_type",
    ):
        return "FIAT"

    if name in (
        "asset_code",
    ):
        return currency

    if name in (
        "network",
    ):
        return ""

    if name in (
        "creator_value",
    ):
        return credits

    return ""


def insert_compatible(
    connection,
    table_name,
    data,
    transaction_reference,
    timestamp,
    currency,
    amount,
    credits,
    user_id,
):
    """
    Insert into an existing/legacy table while satisfying
    required NOT NULL columns.
    """

    info = get_table_info(
        connection,
        table_name,
    )

    if not info:
        raise sqlite3.OperationalError(
            f"Table {table_name} does not exist."
        )

    fields = []
    values = []

    for row in info:
        column_name = row[1]
        not_null = row[3]
        default_value = row[4]
        primary_key = row[5]

        if primary_key and column_name == "id":
            continue

        if column_name in data:
            value = data[column_name]

        elif not_null and default_value is None:
            value = value_for_required_column(
                column_name,
                transaction_reference,
                timestamp,
                currency,
                amount,
                credits,
                user_id,
            )

        else:
            continue

        fields.append(column_name)
        values.append(value)

    if not fields:
        return

    placeholders = ", ".join(
        ["?"] * len(fields)
    )

    connection.execute(
        f"""
        INSERT INTO {table_name}
        ({", ".join(fields)})
        VALUES ({placeholders})
        """,
        values,
    )


# =========================================================
# DATABASE INITIALIZATION
# =========================================================

connection = get_connection()

try:

    # =====================================================
    # GIFT CATALOG
    # =====================================================

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS gift_catalog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gift_code TEXT,
            gift_icon TEXT,
            gift_name TEXT,
            gift_emoji TEXT,
            credit_price INTEGER DEFAULT 0,
            credit_cost INTEGER DEFAULT 0,
            creator_value INTEGER DEFAULT 0,
            currency_code TEXT DEFAULT 'USD',
            is_active INTEGER DEFAULT 1,
            sort_order INTEGER DEFAULT 0,
            created_at TEXT
        )
        """
    )

    for column, definition in [
        ("gift_code", "TEXT"),
        ("gift_icon", "TEXT"),
        ("gift_name", "TEXT"),
        ("gift_emoji", "TEXT"),
        ("credit_price", "INTEGER DEFAULT 0"),
        ("credit_cost", "INTEGER DEFAULT 0"),
        ("creator_value", "INTEGER DEFAULT 0"),
        ("currency_code", "TEXT DEFAULT 'USD'"),
        ("is_active", "INTEGER DEFAULT 1"),
        ("sort_order", "INTEGER DEFAULT 0"),
        ("created_at", "TEXT"),
    ]:
        add_column(
            connection,
            "gift_catalog",
            column,
            definition,
        )

    # =====================================================
    # GIFT CREDIT BALANCES
    # =====================================================

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS gift_credit_balances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            balance INTEGER DEFAULT 0,
            lifetime_purchased INTEGER DEFAULT 0,
            lifetime_received INTEGER DEFAULT 0,
            lifetime_sent INTEGER DEFAULT 0,
            updated_at TEXT
        )
        """
    )

    for column, definition in [
        ("user_id", "INTEGER"),
        ("balance", "INTEGER DEFAULT 0"),
        ("lifetime_purchased", "INTEGER DEFAULT 0"),
        ("lifetime_received", "INTEGER DEFAULT 0"),
        ("lifetime_sent", "INTEGER DEFAULT 0"),
        ("updated_at", "TEXT"),
    ]:
        add_column(
            connection,
            "gift_credit_balances",
            column,
            definition,
        )

    # =====================================================
    # GIFT CREDIT TRANSACTIONS
    # =====================================================

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS gift_credit_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            transaction_reference TEXT,
            reference TEXT,
            transaction_type TEXT,
            credits INTEGER DEFAULT 0,
            balance_after INTEGER DEFAULT 0,
            wallet_currency TEXT,
            wallet_amount REAL DEFAULT 0,
            status TEXT DEFAULT 'Completed',
            description TEXT,
            created_at TEXT
        )
        """
    )

    for column, definition in [
        ("user_id", "INTEGER"),
        ("transaction_reference", "TEXT"),
        ("reference", "TEXT"),
        ("transaction_type", "TEXT"),
        ("credits", "INTEGER DEFAULT 0"),
        ("balance_after", "INTEGER DEFAULT 0"),
        ("wallet_currency", "TEXT"),
        ("wallet_amount", "REAL DEFAULT 0"),
        ("status", "TEXT DEFAULT 'Completed'"),
        ("description", "TEXT"),
        ("created_at", "TEXT"),
    ]:
        add_column(
            connection,
            "gift_credit_transactions",
            column,
            definition,
        )

    # =====================================================
    # GIFT WALLET DEBITS
    # =====================================================

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS gift_wallet_debits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference TEXT,
            transaction_reference TEXT,
            user_id INTEGER,
            wallet_currency TEXT,
            amount REAL DEFAULT 0,
            credits INTEGER DEFAULT 0,
            status TEXT DEFAULT 'Completed',
            created_at TEXT
        )
        """
    )

    for column, definition in [
        ("reference", "TEXT"),
        ("transaction_reference", "TEXT"),
        ("user_id", "INTEGER"),
        ("wallet_currency", "TEXT"),
        ("amount", "REAL DEFAULT 0"),
        ("credits", "INTEGER DEFAULT 0"),
        ("status", "TEXT DEFAULT 'Completed'"),
        ("created_at", "TEXT"),
    ]:
        add_column(
            connection,
            "gift_wallet_debits",
            column,
            definition,
        )

    # Repair legacy debit rows.

    debit_columns = get_columns(
        connection,
        "gift_wallet_debits",
    )

    if "reference" in debit_columns:
        connection.execute(
            """
            UPDATE gift_wallet_debits
            SET reference =
                'LG-LEGACY-DEBIT-' || id
            WHERE reference IS NULL
               OR TRIM(reference) = ''
            """
        )

    if "transaction_reference" in debit_columns:
        connection.execute(
            """
            UPDATE gift_wallet_debits
            SET transaction_reference = reference
            WHERE (
                transaction_reference IS NULL
                OR TRIM(transaction_reference) = ''
            )
            AND reference IS NOT NULL
            """
        )

    if "wallet_currency" in debit_columns:
        connection.execute(
            """
            UPDATE gift_wallet_debits
            SET wallet_currency = 'USD'
            WHERE wallet_currency IS NULL
               OR TRIM(wallet_currency) = ''
            """
        )

    if "status" in debit_columns:
        connection.execute(
            """
            UPDATE gift_wallet_debits
            SET status = 'Completed'
            WHERE status IS NULL
               OR TRIM(status) = ''
            """
        )

    if "created_at" in debit_columns:
        connection.execute(
            """
            UPDATE gift_wallet_debits
            SET created_at = ?
            WHERE created_at IS NULL
               OR TRIM(created_at) = ''
            """,
            (now(),),
        )

    # =====================================================
    # WALLET TRANSACTIONS
    # =====================================================

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS wallet_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            transaction_type TEXT,
            amount REAL DEFAULT 0,
            currency TEXT,
            description TEXT,
            reference TEXT,
            status TEXT DEFAULT 'Completed',
            asset_type TEXT,
            asset_code TEXT,
            network TEXT,
            counterparty_user_id INTEGER
        )
        """
    )

    for column, definition in [
        ("user_id", "INTEGER"),
        ("transaction_type", "TEXT"),
        ("amount", "REAL DEFAULT 0"),
        ("currency", "TEXT"),
        ("description", "TEXT"),
        ("reference", "TEXT"),
        ("status", "TEXT DEFAULT 'Completed'"),
        ("asset_type", "TEXT"),
        ("asset_code", "TEXT"),
        ("network", "TEXT"),
        ("counterparty_user_id", "INTEGER"),
    ]:
        add_column(
            connection,
            "wallet_transactions",
            column,
            definition,
        )

    # =====================================================
    # GIFTS SENT
    # =====================================================

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS gifts_sent (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_user_id INTEGER,
            receiver_user_id INTEGER,
            recipient_user_id INTEGER,
            gift_id INTEGER,
            gift_code TEXT,
            gift_name TEXT,
            quantity INTEGER DEFAULT 1,
            credits INTEGER DEFAULT 0,
            total_credits INTEGER DEFAULT 0,
            creator_value INTEGER DEFAULT 0,
            transaction_reference TEXT,
            reference TEXT,
            status TEXT DEFAULT 'Completed',
            created_at TEXT
        )
        """
    )

    # IMPORTANT:
    # total_credits is explicitly included here because older
    # versions of the database may already contain this column
    # as NOT NULL.

    for column, definition in [
        ("sender_user_id", "INTEGER"),
        ("receiver_user_id", "INTEGER"),
        ("recipient_user_id", "INTEGER"),
        ("gift_id", "INTEGER"),
        ("gift_code", "TEXT"),
        ("gift_name", "TEXT"),
        ("quantity", "INTEGER DEFAULT 1"),
        ("credits", "INTEGER DEFAULT 0"),
        ("total_credits", "INTEGER DEFAULT 0"),
        ("creator_value", "INTEGER DEFAULT 0"),
        ("transaction_reference", "TEXT"),
        ("reference", "TEXT"),
        ("status", "TEXT DEFAULT 'Completed'"),
        ("created_at", "TEXT"),
    ]:
        add_column(
            connection,
            "gifts_sent",
            column,
            definition,
        )

    # =====================================================
    # REPAIR LEGACY GIFTS SENT
    # =====================================================

    gifts_sent_columns = get_columns(
        connection,
        "gifts_sent",
    )

    if "total_credits" in gifts_sent_columns:

        if "credits" in gifts_sent_columns:

            connection.execute(
                """
                UPDATE gifts_sent
                SET total_credits = COALESCE(credits, 0)
                WHERE total_credits IS NULL
                   OR total_credits = 0
                """
            )

    if "receiver_user_id" in gifts_sent_columns:

        if "recipient_user_id" in gifts_sent_columns:

            connection.execute(
                """
                UPDATE gifts_sent
                SET receiver_user_id = recipient_user_id
                WHERE receiver_user_id IS NULL
                  AND recipient_user_id IS NOT NULL
                """
            )

    if "recipient_user_id" in gifts_sent_columns:

        if "receiver_user_id" in gifts_sent_columns:

            connection.execute(
                """
                UPDATE gifts_sent
                SET recipient_user_id = receiver_user_id
                WHERE recipient_user_id IS NULL
                  AND receiver_user_id IS NOT NULL
                """
            )

    # =====================================================
    # Ensure creator_earnings and creator_profiles exist for seamless ledger integration
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS creator_earnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            earning_reference TEXT UNIQUE,
            creator_id INTEGER NOT NULL,
            supporter_id INTEGER,
            amount REAL DEFAULT 0,
            platform_fee REAL DEFAULT 0,
            currency TEXT DEFAULT "NGN",
            status TEXT DEFAULT "Completed",
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS creator_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            display_name TEXT,
            creator_status TEXT DEFAULT "active",
            total_earnings REAL DEFAULT 0,
            currency TEXT DEFAULT "NGN"
        )
        """
    )
    connection.commit()

    # CREATOR GIFT EARNINGS
    # =====================================================

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS creator_gift_earnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_user_id INTEGER,
            sender_user_id INTEGER,
            gift_id INTEGER,
            gift_code TEXT,
            credits INTEGER DEFAULT 0,
            creator_value INTEGER DEFAULT 0,
            transaction_reference TEXT,
            reference TEXT,
            status TEXT DEFAULT 'Pending',
            created_at TEXT
        )
        """
    )

    for column, definition in [
        ("creator_user_id", "INTEGER"),
        ("sender_user_id", "INTEGER"),
        ("gift_id", "INTEGER"),
        ("gift_code", "TEXT"),
        ("credits", "INTEGER DEFAULT 0"),
        ("creator_value", "INTEGER DEFAULT 0"),
        ("transaction_reference", "TEXT"),
        ("reference", "TEXT"),
        ("status", "TEXT DEFAULT 'Pending'"),
        ("created_at", "TEXT"),
    ]:
        add_column(
            connection,
            "creator_gift_earnings",
            column,
            definition,
        )

    # =====================================================
    # PLATFORM REVENUE
    # =====================================================

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_revenue_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_reference TEXT,
            reference TEXT,
            user_id INTEGER,
            credits INTEGER DEFAULT 0,
            platform_revenue INTEGER DEFAULT 0,
            wallet_currency TEXT,
            wallet_amount REAL DEFAULT 0,
            status TEXT DEFAULT 'Completed',
            created_at TEXT
        )
        """
    )

    for column, definition in [
        ("transaction_reference", "TEXT"),
        ("reference", "TEXT"),
        ("user_id", "INTEGER"),
        ("credits", "INTEGER DEFAULT 0"),
        ("platform_revenue", "INTEGER DEFAULT 0"),
        ("wallet_currency", "TEXT"),
        ("wallet_amount", "REAL DEFAULT 0"),
        ("status", "TEXT DEFAULT 'Completed'"),
        ("created_at", "TEXT"),
    ]:
        add_column(
            connection,
            "platform_revenue_ledger",
            column,
            definition,
        )

    # =====================================================
    # PREMIUM GIFT CATALOG
    # =====================================================

    gifts = [
        ("HEART", "❤️", "Heart", 10, 8, 1),
        ("LIKE", "👍", "Like", 100, 80, 2),
        ("CLAP", "👏", "Clap", 500, 400, 3),
        ("ROSE", "🌹", "Rose", 1000, 800, 4),
        ("DIAMOND", "💎", "Diamond", 10000, 8000, 5),
        ("CROWN", "👑", "Crown", 100000, 80000, 6),
        ("ROYAL_DIAMOND", "💠", "Royal Diamond", 1000000, 800000, 7),
        ("LIFEGRID_CROWN", "🏆", "LifeGrid Crown", 5000000, 4000000, 8),
    ]

    catalog_columns = get_columns(
        connection,
        "gift_catalog",
    )

    for (
        gift_code,
        gift_icon,
        gift_name,
        credit_price,
        creator_value,
        sort_order,
    ) in gifts:

        existing = connection.execute(
            """
            SELECT id
            FROM gift_catalog
            WHERE gift_code = ?
               OR gift_name = ?
            LIMIT 1
            """,
            (
                gift_code,
                gift_name,
            ),
        ).fetchone()

        gift_data = {
            "gift_code": gift_code,
            "gift_icon": gift_icon,
            "gift_name": gift_name,
            "gift_emoji": gift_icon,
            "credit_price": credit_price,
            "credit_cost": credit_price,
            "creator_value": creator_value,
            "currency_code": "USD",
            "is_active": 1,
            "sort_order": sort_order,
            "created_at": now(),
        }

        if existing:

            assignments = []
            values = []

            for column, value in gift_data.items():

                if column in catalog_columns:
                    assignments.append(
                        f"{column} = ?"
                    )
                    values.append(value)

            if assignments:

                values.append(existing[0])

                connection.execute(
                    f"""
                    UPDATE gift_catalog
                    SET {", ".join(assignments)}
                    WHERE id = ?
                    """,
                    values,
                )

        else:

            fields = []
            values = []

            for column, value in gift_data.items():

                if column in catalog_columns:
                    fields.append(column)
                    values.append(value)

            placeholders = ", ".join(
                ["?"] * len(fields)
            )

            connection.execute(
                f"""
                INSERT INTO gift_catalog
                ({", ".join(fields)})
                VALUES ({placeholders})
                """,
                values,
            )

    # =====================================================
    # GIFT CREDIT ACCOUNT
    # =====================================================

    existing_balance = connection.execute(
        """
        SELECT id
        FROM gift_credit_balances
        WHERE user_id = ?
        LIMIT 1
        """,
        (USER_ID,),
    ).fetchone()

    if not existing_balance:

        balance_columns = get_columns(
            connection,
            "gift_credit_balances",
        )

        balance_data = {
            "user_id": USER_ID,
            "balance": 0,
            "lifetime_purchased": 0,
            "lifetime_received": 0,
            "lifetime_sent": 0,
            "updated_at": now(),
        }

        fields = []
        values = []

        for column, value in balance_data.items():

            if column in balance_columns:
                fields.append(column)
                values.append(value)

        placeholders = ", ".join(
            ["?"] * len(fields)
        )

        connection.execute(
            f"""
            INSERT INTO gift_credit_balances
            ({", ".join(fields)})
            VALUES ({placeholders})
            """,
            values,
        )

    connection.commit()

except Exception:
    connection.rollback()
    raise


# =========================================================
# LOAD WALLET (Self-Healing Table Migration)
# =========================================================

try:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS wallets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            balance REAL DEFAULT 0.0,
            available_balance REAL DEFAULT 0.0,
            pending_balance REAL DEFAULT 0.0,
            currency TEXT DEFAULT 'USD',
            wallet_status TEXT DEFAULT 'Active',
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    for _col, _defn in [
        ("balance", "REAL DEFAULT 0.0"),
        ("available_balance", "REAL DEFAULT 0.0"),
        ("pending_balance", "REAL DEFAULT 0.0"),
        ("currency", "TEXT DEFAULT 'USD'"),
        ("wallet_status", "TEXT DEFAULT 'Active'"),
    ]:
        add_column(connection, "wallets", _col, _defn)

    wallet = connection.execute(
        """
        SELECT
            balance,
            available_balance,
            pending_balance,
            currency,
            wallet_status
        FROM wallets
        WHERE user_id = ?
        LIMIT 1
        """,
        (USER_ID,),
    ).fetchone()
except Exception:
    wallet = None


if wallet:

    wallet_balance = float(
        wallet[0] or 0
    )

    wallet_pending = float(
        wallet[2] or 0
    )

    wallet_available = float(
        wallet[1]
        if wallet[1] is not None
        else max(
            0,
            wallet_balance - wallet_pending,
        )
    )

    wallet_currency = (
        wallet[3]
        or "USD"
    )

    wallet_status = (
        wallet[4]
        or "Active"
    )

else:

    wallet_balance = 0.0
    wallet_available = 0.0
    wallet_pending = 0.0
    wallet_currency = "USD"
    wallet_status = "Unavailable"


# =========================================================
# LOAD USER CURRENCY
# =========================================================

user_currency = "NGN"

try:

    user_row = connection.execute(
        """
        SELECT currency
        FROM users
        WHERE id = ?
        LIMIT 1
        """,
        (USER_ID,),
    ).fetchone()

    if user_row and user_row[0]:
        user_currency = user_row[0]

except Exception:
    user_currency = "NGN"


# =========================================================
# LOAD GIFT CREDITS
# =========================================================

credit_row = connection.execute(
    """
    SELECT
        balance,
        lifetime_purchased,
        lifetime_received,
        lifetime_sent
    FROM gift_credit_balances
    WHERE user_id = ?
    LIMIT 1
    """,
    (USER_ID,),
).fetchone()


if credit_row:

    gift_credits = int(
        credit_row[0] or 0
    )

    lifetime_purchased = int(
        credit_row[1] or 0
    )

    lifetime_received = int(
        credit_row[2] or 0
    )

    lifetime_sent = int(
        credit_row[3] or 0
    )

else:

    gift_credits = 0
    lifetime_purchased = 0
    lifetime_received = 0
    lifetime_sent = 0


# =========================================================
# MULTI-CURRENCY SETUP & EXCHANGE CONVERSIONS
# =========================================================
# Supported fiat currencies with live Flutterwave support
SUPPORTED_CURRENCIES = ["NGN", "USD", "GBP", "EUR", "KES", "GHS", "ZAR", "CAD"]

# Baseline conversion rates relative to USD (1.00 USD)
CURRENCY_RATES = {
    "USD": 1.0,
    "NGN": 1600.0,
    "GBP": 0.78,
    "EUR": 0.92,
    "KES": 130.0,
    "GHS": 15.5,
    "ZAR": 18.5,
    "CAD": 1.38,
}

# Resolve active currency from session state, then wallet, then account
active_curr_candidate = (
    st.session_state.get("selected_currency")
    or st.session_state.get("gift_currency")
    or (str(wallet[3]).strip().upper() if wallet and len(wallet) > 3 and wallet[3] else None)
    or str(user_currency or "NGN").strip().upper()
)

if active_curr_candidate not in SUPPORTED_CURRENCIES:
    active_curr_candidate = "NGN"

# =========================================================
# PAGE HEADER WITH CURRENCY SELECTOR
# =========================================================

title_col, curr_select_col = st.columns([3, 2])

with title_col:
    st.title("🎁 LifeGrid Gift Store")
    st.write(
        "Purchase LifeGrid Gift Credits and prepare your "
        "account for Live virtual gifting."
    )

with curr_select_col:
    st.write("") # spacing
    gift_payment_currency = st.selectbox(
        "💱 Active Currency",
        options=SUPPORTED_CURRENCIES,
        index=SUPPORTED_CURRENCIES.index(active_curr_candidate),
        key="gift_store_active_currency",
        help="Select the currency you wish to transact with. Packages, estimates, and checkout adapt automatically.",
    )

# Synchronize across all LifeGrid pages
st.session_state["selected_currency"] = gift_payment_currency
st.session_state["gift_currency"] = gift_payment_currency

curr_rate = CURRENCY_RATES.get(gift_payment_currency, 1.0)
wallet_rate = CURRENCY_RATES.get(wallet_currency, 1.0)

# Calculate converted wallet balance in active currency for user clarity
if wallet_currency == gift_payment_currency:
    wallet_display_str = f"{wallet_currency} {wallet_available:,.2f}"
else:
    # Convert through USD pivot
    usd_equiv = wallet_available / wallet_rate if wallet_rate else wallet_available
    converted_wallet = usd_equiv * curr_rate
    wallet_display_str = f"{gift_payment_currency} {converted_wallet:,.2f}"

# =========================================================
# ACCOUNT SUMMARY
# =========================================================

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric(
        "🎁 Gift Credits",
        f"{gift_credits:,}",
    )

with col2:
    st.metric(
        "💰 Wallet Available",
        wallet_display_str,
        delta=f"Base: {wallet_currency} {wallet_available:,.2f}" if wallet_currency != gift_payment_currency else None,
        delta_color="off",
    )

with col3:
    st.metric(
        "🌍 Selected Currency",
        gift_payment_currency,
        delta=f"Rate: {curr_rate:,.2f}/USD" if gift_payment_currency != "USD" else "Base USD",
        delta_color="off",
    )

with col4:
    st.metric(
        "📦 Lifetime Purchased",
        f"{lifetime_purchased:,}",
    )

if gift_payment_currency != "USD":
    st.caption(
        f"🔄 **Active Currency:** {gift_payment_currency} (1 USD ≈ {curr_rate:,.2f} {gift_payment_currency}). "
        "All Gift Credit packages and Flutterwave checkout amounts are converted automatically."
    )

# =========================================================
# REAL FLUTTERWAVE GIFT CREDIT CHECKOUT
# =========================================================

st.info(
    "💳 Gift Credit purchases use Flutterwave hosted checkout. "
    "LifeGrid adds credits only after directly verifying the transaction "
    "with Flutterwave. The purchase does not debit your internal wallet."
)

# A live-payment ledger records checkouts before a customer is sent to Flutterwave.
connection.execute(
    """
    CREATE TABLE IF NOT EXISTS gift_credit_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        transaction_reference TEXT NOT NULL UNIQUE,
        credits INTEGER NOT NULL,
        amount REAL NOT NULL,
        currency TEXT NOT NULL,
        provider TEXT NOT NULL DEFAULT 'Flutterwave',
        checkout_url TEXT,
        provider_transaction_id TEXT,
        status TEXT NOT NULL DEFAULT 'Pending',
        created_at TEXT NOT NULL,
        verified_at TEXT,
        credited_at TEXT,
        verification_note TEXT
    )
    """
)
connection.commit()

if str(wallet_status or "").strip().lower() != "active":
    st.caption(
        f"Internal wallet status: {wallet_status}. This purchase is an external Flutterwave charge "
        "and will not debit or change the internal wallet balance."
    )

flw_active = is_flutterwave_configured()
if flw_active:
    st.success("🟢 Live Flutterwave Checkout is active.")
else:
    st.info(
        "ℹ️ **Payment Gateway Status:** Live Flutterwave checkout is currently awaiting live merchant activation. "
        "**Sandbox Simulation Mode** is enabled so you can test gift credit packages, gifting creators, and ledger reconciliation without blocking."
    )


def _gift_customer_details():
    """Get the logged-in user's email/name without exposing payment secrets."""
    email = ""
    name = "LifeGrid User"
    try:
        user_columns = get_columns(connection, "users")
        selected = [
            column for column in ("email", "full_name", "username", "name")
            if column in user_columns
        ]
        if selected and "id" in user_columns:
            row = connection.execute(
                f"SELECT {', '.join(selected)} FROM users WHERE id = ? LIMIT 1",
                (USER_ID,),
            ).fetchone()
            if row:
                details = dict(zip(selected, row))
                email = str(details.get("email") or "").strip()
                name = str(
                    details.get("full_name")
                    or details.get("name")
                    or details.get("username")
                    or name
                ).strip()
    except Exception:
        pass

    if isinstance(session_user, dict):
        email = email or str(session_user.get("email") or "").strip()
        name = str(
            session_user.get("full_name")
            or session_user.get("name")
            or name
        ).strip()
    return email, name


def _get_pending_payment(tx_ref):
    row = connection.execute(
        """
        SELECT id, user_id, transaction_reference, credits, amount, currency,
               status, credited_at, provider_transaction_id
        FROM gift_credit_payments
        WHERE transaction_reference = ? AND user_id = ?
        LIMIT 1
        """,
        (tx_ref, USER_ID),
    ).fetchone()
    if not row:
        raise ValueError("That LifeGrid payment reference was not found for your account.")
    return {
        "id": row[0],
        "user_id": row[1],
        "transaction_reference": row[2],
        "credits": row[3],
        "amount": row[4],
        "currency": row[5],
        "status": row[6],
        "credited_at": row[7],
        "provider_transaction_id": row[8],
    }


def _finalize_verified_gift_payment(payment, provider_data):
    """Credit credits exactly once after checking Flutterwave's verified transaction data."""
    tx_ref = str(payment["transaction_reference"])
    expected_user_id = str(payment["user_id"])
    expected_credits = int(payment["credits"])
    expected_currency = str(payment["currency"] or "").upper()
    expected_amount = Decimal(str(payment["amount"])).quantize(Decimal("0.01"))

    provider_status = str(provider_data.get("status") or "").strip().lower()
    provider_reference = str(provider_data.get("tx_ref") or "").strip()
    provider_currency = str(provider_data.get("currency") or "").strip().upper()
    provider_transaction_id = str(provider_data.get("id") or "").strip()

    try:
        provider_amount = Decimal(str(provider_data.get("amount"))).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        provider_amount = Decimal("-1")

    if provider_status != "successful":
        raise ValueError(
            f"Flutterwave's verified status is '{provider_status or 'unknown'}', not 'successful'. "
            "No credits have been added."
        )
    if provider_reference != tx_ref:
        raise ValueError("The verified Flutterwave reference does not match this LifeGrid payment.")
    if provider_currency != expected_currency:
        raise ValueError(
            f"Currency mismatch: expected {expected_currency}, received {provider_currency or 'unknown'}."
        )
    if provider_amount != expected_amount:
        raise ValueError(
            f"Amount mismatch: expected {expected_currency} {expected_amount:,.2f}; "
            f"Flutterwave verified {provider_currency} {provider_amount:,.2f}. No credits have been added."
        )
    if not provider_transaction_id:
        raise ValueError("Flutterwave did not return a transaction ID. No credits have been added.")

    timestamp = now()
    connection.execute("BEGIN IMMEDIATE")
    try:
        fresh = connection.execute(
            """
            SELECT status, credited_at, user_id, credits, amount, currency,
                   provider_transaction_id
            FROM gift_credit_payments
            WHERE transaction_reference = ?
            LIMIT 1
            """,
            (tx_ref,),
        ).fetchone()
        if not fresh:
            raise ValueError("No matching LifeGrid payment record exists.")
        if str(fresh[2]) != expected_user_id or str(fresh[2]) != str(USER_ID):
            raise ValueError("This payment belongs to a different LifeGrid account.")
        if int(fresh[3]) != expected_credits:
            raise ValueError("The stored gift-credit quantity changed. Please contact LifeGrid support.")
        if Decimal(str(fresh[4])).quantize(Decimal("0.01")) != expected_amount:
            raise ValueError("The stored payment amount changed. Please contact LifeGrid support.")
        if str(fresh[5] or "").upper() != expected_currency:
            raise ValueError("The stored payment currency changed. Please contact LifeGrid support.")
        if fresh[1] or str(fresh[0] or "").lower() == "completed":
            connection.commit()
            return False
        if str(fresh[0] or "").lower() not in ("pending", "verification_required"):
            raise ValueError(f"This payment has status '{fresh[0]}' and cannot be credited.")

        # Do not let one Flutterwave transaction ID be used for two different payments.
        reused_id = connection.execute(
            """
            SELECT transaction_reference
            FROM gift_credit_payments
            WHERE provider_transaction_id = ?
              AND transaction_reference <> ?
              AND credited_at IS NOT NULL
            LIMIT 1
            """,
            (provider_transaction_id, tx_ref),
        ).fetchone()
        if reused_id:
            raise ValueError("This Flutterwave transaction ID was already applied to another payment.")

        balance_row = connection.execute(
            """
            SELECT balance, lifetime_purchased
            FROM gift_credit_balances
            WHERE user_id = ?
            LIMIT 1
            """,
            (USER_ID,),
        ).fetchone()

        if not balance_row:
            balance_columns = get_columns(connection, "gift_credit_balances")
            initial_data = {
                "user_id": USER_ID,
                "balance": 0,
                "lifetime_purchased": 0,
                "lifetime_received": 0,
                "lifetime_sent": 0,
                "updated_at": timestamp,
            }
            fields = [key for key in initial_data if key in balance_columns]
            connection.execute(
                f"INSERT INTO gift_credit_balances ({', '.join(fields)}) "
                f"VALUES ({', '.join(['?'] * len(fields))})",
                [initial_data[key] for key in fields],
            )
            old_balance = 0
        else:
            old_balance = int(balance_row[0] or 0)

        new_balance = old_balance + expected_credits
        connection.execute(
            """
            UPDATE gift_credit_balances
            SET balance = ?,
                lifetime_purchased = COALESCE(lifetime_purchased, 0) + ?,
                updated_at = ?
            WHERE user_id = ?
            """,
            (new_balance, expected_credits, timestamp, USER_ID),
        )

        insert_compatible(
            connection=connection,
            table_name="gift_credit_transactions",
            data={
                "user_id": USER_ID,
                "transaction_reference": tx_ref,
                "reference": tx_ref,
                "transaction_type": "Purchase",
                "credits": expected_credits,
                "balance_after": new_balance,
                "wallet_currency": expected_currency,
                "wallet_amount": float(expected_amount),
                "status": "Completed",
                "description": f"Flutterwave-verified purchase of {expected_credits:,} LifeGrid Gift Credits",
                "created_at": timestamp,
            },
            transaction_reference=tx_ref,
            timestamp=timestamp,
            currency=expected_currency,
            amount=float(expected_amount),
            credits=expected_credits,
            user_id=USER_ID,
        )

        insert_compatible(
            connection=connection,
            table_name="wallet_transactions",
            data={
                "user_id": USER_ID,
                "transaction_type": "Gift Credit Purchase",
                "amount": float(expected_amount),
                "currency": expected_currency,
                "description": f"External Flutterwave payment for {expected_credits:,} Gift Credits; internal wallet not debited",
                "reference": tx_ref,
                "status": "Completed",
                "asset_type": "FIAT",
                "asset_code": expected_currency,
                "network": "Flutterwave",
                "counterparty_user_id": None,
            },
            transaction_reference=tx_ref,
            timestamp=timestamp,
            currency=expected_currency,
            amount=float(expected_amount),
            credits=expected_credits,
            user_id=USER_ID,
        )

        insert_compatible(
            connection=connection,
            table_name="platform_revenue_ledger",
            data={
                "transaction_reference": tx_ref,
                "reference": tx_ref,
                "user_id": USER_ID,
                "credits": expected_credits,
                "platform_revenue": int(expected_credits * 0.20),
                "wallet_currency": expected_currency,
                "wallet_amount": float(expected_amount),
                "status": "Completed",
                "created_at": timestamp,
            },
            transaction_reference=tx_ref,
            timestamp=timestamp,
            currency=expected_currency,
            amount=float(expected_amount),
            credits=expected_credits,
            user_id=USER_ID,
        )

        # No gift_wallet_debits row is written: no internal LifeGrid wallet was debited.
        connection.execute(
            """
            UPDATE gift_credit_payments
            SET status = 'Completed',
                provider_transaction_id = ?,
                verified_at = ?,
                credited_at = ?,
                verification_note = ?
            WHERE transaction_reference = ?
              AND credited_at IS NULL
            """,
            (provider_transaction_id, timestamp, timestamp,
             "Verified directly with Flutterwave API", tx_ref),
        )
        if connection.execute("SELECT changes()").fetchone()[0] != 1:
            raise RuntimeError("The payment could not be marked as credited exactly once.")

        connection.commit()
        return True
    except Exception:
        connection.rollback()
        raise


def _verify_pending_payment(tx_ref, transaction_id=None):
    payment = _get_pending_payment(tx_ref)
    if payment["credited_at"] or str(payment["status"] or "").lower() == "completed":
        return False
    if transaction_id:
        result = verify_transaction(transaction_id)
    else:
        result = verify_transaction_by_reference(tx_ref)
    provider_data = result.get("data") or {}
    return _finalize_verified_gift_payment(payment, provider_data)


st.subheader("💳 Buy Gift Credits")

# Base USD cost per credit package (e.g. 100 credits = $2.00, etc.)
# Provides realistic tiered pricing rather than charging 1:1 nominal units
PACKAGE_BASE_USD = {
    100: 2.00,
    500: 10.00,
    1000: 19.50,
    5000: 95.00,
    10000: 185.00,
    50000: 899.00,
    100000: 1750.00,
    500000: 8500.00,
    1000000: 16500.00,
    5000000: 80000.00,
    10000000: 155000.00,
}

packages = list(PACKAGE_BASE_USD.keys())
current_rate = CURRENCY_RATES.get(gift_payment_currency, 1.0)

def calc_pkg_price(credits_count):
    usd_val = PACKAGE_BASE_USD.get(credits_count, float(credits_count) * 0.02)
    converted = usd_val * current_rate
    # Round cleanly to 2 decimal places
    return Decimal(str(round(converted, 2))).quantize(Decimal("0.01"))

package_labels = [
    f"{amount:,} Gift Credits — {gift_payment_currency} {calc_pkg_price(amount):,.2f}"
    for amount in packages
]
selected_label = st.selectbox("Choose a Gift Credit package", package_labels)
selected_credits = packages[package_labels.index(selected_label)]
purchase_amount = calc_pkg_price(selected_credits)
st.write(f"**Selected package:** {selected_credits:,} Gift Credits")
st.write(f"**Payment amount:** {gift_payment_currency} {purchase_amount:,.2f}")
st.caption(
    "The selected amount is charged through Flutterwave hosted checkout. "
    "LifeGrid does not deduct funds from your internal wallet."
)

if is_flutterwave_configured():
    customer_email, customer_name = _gift_customer_details()
    if not customer_email or "@" not in customer_email:
        st.warning(
            "Add a valid email address to your LifeGrid account before starting checkout. "
            "Flutterwave requires a customer email."
        )
    if st.button(
        "🔐 Continue to Live Flutterwave Checkout",
        type="primary",
        use_container_width=True,
        disabled=(not customer_email or "@" not in customer_email),
    ):
        tx_ref = make_reference("LG-GIFT-FLW")
        timestamp = now()
        try:
            # Persist the pending record before requesting checkout.
            connection.execute(
                """
                INSERT INTO gift_credit_payments
                    (user_id, transaction_reference, credits, amount, currency,
                     provider, status, created_at, verification_note)
                VALUES (?, ?, ?, ?, ?, 'Flutterwave', 'Pending', ?, ?)
                """,
                (USER_ID, tx_ref, int(selected_credits), float(purchase_amount),
                 gift_payment_currency, timestamp, "Checkout creation started"),
            )
            connection.commit()

            checkout = create_payment_link(
                tx_ref=tx_ref,
                amount=str(purchase_amount),
                currency=gift_payment_currency,
                customer_email=customer_email,
                customer_name=customer_name,
                title="LifeGrid Gift Credits",
                description=f"Purchase {selected_credits:,} LifeGrid Gift Credits",
                meta={"lifegrid_user_id": str(USER_ID), "gift_credits": int(selected_credits)},
            )
            connection.execute(
                """
                UPDATE gift_credit_payments
                SET checkout_url = ?, verification_note = ?
                WHERE transaction_reference = ? AND user_id = ?
                """,
                (checkout["checkout_url"], "Checkout link created; awaiting payment", tx_ref, USER_ID),
            )
            connection.commit()
            st.session_state["lifegrid_gift_checkout_ref"] = tx_ref
            st.session_state["lifegrid_gift_checkout_url"] = checkout["checkout_url"]
            st.success(
                "Secure checkout is ready. Complete payment on Flutterwave; "
                "LifeGrid will add Gift Credits only after verifying the transaction."
            )
            st.rerun()
        except Exception as exc:
            connection.rollback()
            try:
                connection.execute(
                    """
                    UPDATE gift_credit_payments
                    SET status = 'Checkout_Failed', verification_note = ?
                    WHERE transaction_reference = ? AND credited_at IS NULL
                    """,
                    (f"Checkout creation failed: {str(exc)[:300]}", tx_ref),
                )
                connection.commit()
            except Exception:
                connection.rollback()
            st.error(f"Could not create Flutterwave checkout: {exc}")
else:
    st.info("💡 **Sandbox Mode Active:** Complete this purchase instantly in development mode while awaiting live Flutterwave merchant activation.")
    if st.button(
        f"🧪 Complete Sandbox Test Purchase ({selected_credits:,} Gift Credits)",
        type="primary",
        use_container_width=True,
    ):
        tx_ref = make_reference("LG-GIFT-SANDBOX")
        timestamp = now()
        try:
            connection.execute(
                """
                INSERT INTO gift_credit_payments
                    (user_id, transaction_reference, credits, amount, currency,
                     provider, status, created_at, verification_note)
                VALUES (?, ?, ?, ?, ?, 'Sandbox_Simulator', 'Pending', ?, 'Development test purchase')
                """,
                (USER_ID, tx_ref, int(selected_credits), float(purchase_amount),
                 gift_payment_currency, timestamp),
            )
            connection.commit()

            sim_payment = {
                "transaction_reference": tx_ref,
                "user_id": USER_ID,
                "credits": int(selected_credits),
                "currency": gift_payment_currency,
                "amount": float(purchase_amount),
                "status": "Pending",
                "credited_at": None,
            }
            sim_data = {
                "status": "successful",
                "tx_ref": tx_ref,
                "currency": gift_payment_currency,
                "amount": str(purchase_amount),
                "id": f"SIM-{uuid.uuid4().hex[:8].upper()}",
            }
            _finalize_verified_gift_payment(sim_payment, sim_data)
            st.success(f"🎉 Sandbox payment verified! Added {selected_credits:,} Gift Credits to your balance.")
            st.rerun()
        except Exception as exc:
            connection.rollback()
            st.error(f"Sandbox purchase error: {exc}")

# Display checkout links still awaiting payment so the user can return to the provider page.
checkout_ref = st.session_state.get("lifegrid_gift_checkout_ref")
checkout_url = st.session_state.get("lifegrid_gift_checkout_url")
if checkout_ref and checkout_url:
    st.markdown(f"**Payment reference:** `{checkout_ref}`")
    st.link_button("Open secure Flutterwave checkout", checkout_url, use_container_width=True)

pending_payments = connection.execute(
    """
    SELECT transaction_reference, credits, amount, currency, created_at, checkout_url, status
    FROM gift_credit_payments
    WHERE user_id = ?
      AND status IN ('Pending', 'Verification_Required')
      AND credited_at IS NULL
    ORDER BY id DESC
    LIMIT 10
    """,
    (USER_ID,),
).fetchall()

if pending_payments:
    st.subheader("🧾 Check or verify a Gift Credit payment")
    st.caption(
        "After completing checkout, select the matching reference and let LifeGrid "
        "query Flutterwave directly. A redirect, screenshot, or customer claim alone is not proof of payment."
    )
    pending_labels = [
        f"{row[0]} — {int(row[1]):,} credits — {row[3]} {float(row[2]):,.2f} — {row[6]}"
        for row in pending_payments
    ]
    selected_pending_label = st.selectbox(
        "Choose the checkout you completed",
        pending_labels,
        key="gift_pending_payment_select",
    )
    pending_index = pending_labels.index(selected_pending_label)
    pending_row = pending_payments[pending_index]
    pending_ref = pending_row[0]
    if pending_row[5]:
        st.link_button("Reopen Flutterwave checkout", pending_row[5])
    if st.button(
        "✅ Verify payment with Flutterwave",
        key="verify_gift_payment_by_reference",
        type="primary",
        use_container_width=True,
    ):
        try:
            did_credit = _verify_pending_payment(pending_ref)
            if did_credit:
                st.success("Flutterwave verified the payment. Gift Credits have been added to your account.")
            else:
                st.info("This payment has already been credited. No duplicate credits were added.")
            st.session_state.pop("lifegrid_gift_checkout_ref", None)
            st.session_state.pop("lifegrid_gift_checkout_url", None)
            st.rerun()
        except Exception as exc:
            try:
                connection.execute(
                    "UPDATE gift_credit_payments SET verification_note = ? WHERE transaction_reference = ? AND credited_at IS NULL",
                    (f"Verification attempt: {str(exc)[:300]}", pending_ref),
                )
                connection.commit()
            except Exception:
                connection.rollback()
            st.error(f"Payment not credited: {exc}")

    with st.expander("Have a Flutterwave transaction ID? (optional)"):
        manual_tx_id = st.text_input(
            "Flutterwave transaction ID",
            key="gift_flutterwave_tx_id",
            help="Optional. Use the numeric transaction ID returned by Flutterwave, not the LifeGrid payment reference.",
        ).strip()
        if st.button("Verify using transaction ID", key="verify_gift_payment_by_id"):
            if not manual_tx_id:
                st.error("Enter the Flutterwave transaction ID first.")
            else:
                try:
                    did_credit = _verify_pending_payment(pending_ref, manual_tx_id)
                    if did_credit:
                        st.success("Flutterwave verified the transaction and Gift Credits were added.")
                    else:
                        st.info("This payment was already credited. No duplicate credits were added.")
                    st.session_state.pop("lifegrid_gift_checkout_ref", None)
                    st.session_state.pop("lifegrid_gift_checkout_url", None)
                    st.rerun()
                except Exception as exc:
                    st.error(f"Payment not credited: {exc}")

# Flutterwave can redirect to the public Gift Store URL with transaction_id, tx_ref and status.
try:
    params = st.query_params
    callback_tx_id = str(params.get("transaction_id", "") or "").strip()
    callback_ref = str(params.get("tx_ref", "") or "").strip()
    callback_status = str(params.get("status", "") or "").strip().lower()
except Exception:
    callback_tx_id = callback_ref = callback_status = ""

if callback_tx_id and callback_ref and callback_status in ("successful", "completed"):
    try:
        did_credit = _verify_pending_payment(callback_ref, callback_tx_id)
        if did_credit:
            st.success("Flutterwave payment verified and Gift Credits added.")
        else:
            st.info("This payment has already been credited. No duplicate credits were added.")
        st.session_state.pop("lifegrid_gift_checkout_ref", None)
        st.session_state.pop("lifegrid_gift_checkout_url", None)
        try:
            st.query_params.clear()
        except Exception:
            pass
        st.rerun()
    except Exception as exc:
        st.error(f"Flutterwave returned to LifeGrid, but verification did not pass: {exc}")


# =========================================================
# VIRTUAL GIFT CATALOG
# =========================================================

st.divider()

st.subheader(
    "🎁 LifeGrid Virtual Gift Catalog"
)

st.caption(
    "Send appreciation, support creators, and make your "
    "LifeGrid Live experience more interactive."
)

catalog_columns = get_columns(
    connection,
    "gift_catalog",
)

name_column = (
    "gift_name"
    if "gift_name" in catalog_columns
    else "gift_code"
)

emoji_column = (
    "gift_emoji"
    if "gift_emoji" in catalog_columns
    else "gift_icon"
)

price_column = (
    "credit_cost"
    if "credit_cost" in catalog_columns
    else "credit_price"
)

catalog_rows = connection.execute(
    f"""
    SELECT
        id,
        {name_column},
        {emoji_column},
        {price_column},
        creator_value
    FROM gift_catalog
    WHERE is_active = 1
    ORDER BY sort_order ASC, id ASC
    """
).fetchall()


# =========================================================
# GIFT CARDS
# =========================================================

if catalog_rows:

    columns_per_row = 4

    for start in range(
        0,
        len(catalog_rows),
        columns_per_row,
    ):

        gift_row = catalog_rows[
            start:start + columns_per_row
        ]

        display_columns = st.columns(
            columns_per_row
        )

        for display_column, gift in zip(
            display_columns,
            gift_row,
        ):

            gift_name = (
                gift[1]
                or "Gift"
            )

            gift_emoji = (
                gift[2]
                or "🎁"
            )

            try:
                credit_cost = int(
                    gift[3] or 0
                )
            except (TypeError, ValueError):
                credit_cost = 0

            try:
                creator_value = int(
                    gift[4] or 0
                )
            except (TypeError, ValueError):
                creator_value = 0

            with display_column:

                with st.container(
                    border=True
                ):

                    st.markdown(
                        f"## {gift_emoji}"
                    )

                    st.markdown(
                        f"### {gift_name}"
                    )

                    st.markdown(
                        f"**{credit_cost:,} Gift Credits**"
                    )

                    st.caption(
                        f"Creator value: "
                        f"{creator_value:,} credits"
                    )

else:

    st.info(
        "No virtual gifts are currently available."
    )


# =========================================================
# SEND GIFT SECTION
# =========================================================

st.divider()

st.subheader(
    "🎁 Send a Gift to Someone"
)

st.caption(
    "Use the Gift Credits you have already purchased "
    "to send a virtual gift to another LifeGrid user."
)


# =========================================================
# SESSION STATE
# =========================================================

if "gift_store_selected_gift_id" not in st.session_state:
    st.session_state["gift_store_selected_gift_id"] = None

if "gift_store_selected_gift_name" not in st.session_state:
    st.session_state["gift_store_selected_gift_name"] = ""

if "gift_store_selected_gift_emoji" not in st.session_state:
    st.session_state["gift_store_selected_gift_emoji"] = "🎁"

if "gift_store_selected_gift_price" not in st.session_state:
    st.session_state["gift_store_selected_gift_price"] = 0


# =========================================================
# GIFT NOTIFICATION
# =========================================================

def send_gift_notification(
    connection,
    recipient_user_id,
    sender_user_id,
    gift_name,
    gift_emoji,
    quantity,
    credits,
    reference,
):

    try:
        notification_columns = get_columns(
            connection,
            "notifications",
        )
    except Exception:
        return

    if not notification_columns:
        return

    timestamp = now()

    sender_name = "Another LifeGrid user"

    try:

        sender_columns = get_columns(
            connection,
            "users",
        )

        sender_name_column = (
            "full_name"
            if "full_name" in sender_columns
            else "username"
            if "username" in sender_columns
            else None
        )

        if sender_name_column:

            sender_row = connection.execute(
                f"""
                SELECT {sender_name_column}
                FROM users
                WHERE id = ?
                LIMIT 1
                """,
                (sender_user_id,),
            ).fetchone()

            if sender_row and sender_row[0]:
                sender_name = str(
                    sender_row[0]
                )

    except Exception:
        pass

    data = {
        "user_id": recipient_user_id,
        "notification_type": "gift_received",
        "title": f"{gift_emoji} You received a gift",
        "message": (
            f"{sender_name} sent you "
            f"{quantity} × {gift_emoji} {gift_name} "
            f"worth {credits:,} Gift Credits."
        ),
        "reference_type": "gift",
        "reference_id": reference,
        "is_read": 0,
        "created_at": timestamp,
    }

    fields = []
    values = []

    for column, value in data.items():

        if column in notification_columns:

            fields.append(column)
            values.append(value)

    table_info = get_table_info(
        connection,
        "notifications",
    )

    existing_fields = set(fields)

    for row in table_info:

        column_name = row[1]
        not_null = row[3]
        default_value = row[4]
        is_primary_key = row[5]

        if (
            is_primary_key
            or not_null != 1
            or column_name in existing_fields
        ):
            continue

        if default_value is not None:
            continue

        if column_name == "type":

            fields.append(column_name)
            values.append("gift_received")

        elif column_name == "read":

            fields.append(column_name)
            values.append(0)

        elif column_name in (
            "timestamp",
            "date",
            "updated_at",
        ):

            fields.append(column_name)
            values.append(timestamp)

        else:

            fields.append(column_name)
            values.append("")

    if not fields:
        return

    placeholders = ", ".join(
        ["?"] * len(fields)
    )

    try:

        connection.execute(
            f"""
            INSERT INTO notifications
            ({", ".join(fields)})
            VALUES ({placeholders})
            """,
            values,
        )

    except Exception:
        # Notification failure must never cancel a gift.
        pass


# =========================================================
# SELECTED GIFT
# =========================================================

selected_gift_id = st.session_state.get(
    "gift_store_selected_gift_id"
)


if selected_gift_id:

    selected_row = connection.execute(
        f"""
        SELECT
            id,
            {name_column},
            {emoji_column},
            {price_column},
            creator_value
        FROM gift_catalog
        WHERE id = ?
          AND is_active = 1
        LIMIT 1
        """,
        (selected_gift_id,),
    ).fetchone()

    if selected_row:

        selected_gift_name = (
            selected_row[1]
            or "Gift"
        )

        selected_gift_emoji = (
            selected_row[2]
            or "🎁"
        )

        selected_gift_price = int(
            selected_row[3]
            or 0
        )

        selected_creator_value = int(
            selected_row[4]
            or 0
        )

        st.markdown(
            f"### {selected_gift_emoji} "
            f"{selected_gift_name}"
        )

        st.write(
            f"**{selected_gift_price:,} Gift Credits per gift**  "
            f"| Creator value: "
            f"**{selected_creator_value:,} credits**"
        )

        # =================================================
        # FIND RECIPIENT
        # =================================================

        user_columns = get_columns(
            connection,
            "users",
        )

        searchable_columns = [
            column
            for column in (
                "username",
                "full_name",
                "email",
            )
            if column in user_columns
        ]

        recipient_search = st.text_input(
            "Recipient username, name, or email",
            key="gift_store_recipient_search",
            placeholder=(
                "Enter the LifeGrid user's "
                "username or name"
            ),
        ).strip()

        found_users = []

        if (
            recipient_search
            and searchable_columns
        ):

            conditions = " OR ".join(
                [
                    f"""
                    LOWER(
                        COALESCE({column}, '')
                    ) LIKE LOWER(?)
                    """
                    for column in searchable_columns
                ]
            )

            search_value = (
                f"%{recipient_search}%"
            )

            username_select = (
                "username"
                if "username" in user_columns
                else "id"
            )

            fullname_select = (
                "full_name"
                if "full_name" in user_columns
                else "id"
            )

            email_select = (
                "email"
                if "email" in user_columns
                else "id"
            )

            found_users = connection.execute(
                f"""
                SELECT
                    id,
                    {username_select},
                    {fullname_select},
                    {email_select}
                FROM users
                WHERE id != ?
                  AND ({conditions})
                ORDER BY id ASC
                LIMIT 25
                """,
                (
                    USER_ID,
                    *(
                        [search_value]
                        * len(searchable_columns)
                    ),
                ),
            ).fetchall()

        if (
            recipient_search
            and not found_users
        ):

            st.warning(
                "No other LifeGrid user was found "
                "matching that search."
            )

        if found_users:

            recipient_options = {}

            for row in found_users:

                recipient_id = row[0]

                recipient_username = (
                    row[1]
                    or f"User {recipient_id}"
                )

                recipient_name = (
                    row[2]
                    or ""
                )

                recipient_email = (
                    row[3]
                    or ""
                )

                label_parts = [
                    str(recipient_username)
                ]

                if (
                    recipient_name
                    and str(recipient_name)
                    != str(recipient_username)
                ):

                    label_parts.append(
                        str(recipient_name)
                    )

                if recipient_email:

                    label_parts.append(
                        str(recipient_email)
                    )

                label = " — ".join(
                    label_parts
                )

                recipient_options[
                    label
                ] = recipient_id

            selected_recipient_label = (
                st.selectbox(
                    "Choose recipient",
                    options=list(
                        recipient_options.keys()
                    ),
                    key="gift_store_recipient_choice",
                )
            )

            selected_recipient_id = (
                recipient_options[
                    selected_recipient_label
                ]
            )

            try:

                selected_recipient_id = int(
                    selected_recipient_id
                )

            except (
                TypeError,
                ValueError,
            ):

                st.error(
                    "The selected LifeGrid recipient "
                    "could not be resolved to a valid account."
                )

                st.stop()

            send_col1, send_col2 = st.columns(2)

            with send_col1:

                gift_quantity = st.number_input(
                    "Quantity",
                    min_value=1,
                    max_value=1000000,
                    value=1,
                    step=1,
                    key="gift_store_send_quantity",
                )

            total_send_credits = (
                int(selected_gift_price)
                * int(gift_quantity)
            )

            with send_col2:

                st.metric(
                    "Gift Credits Required",
                    f"{total_send_credits:,}",
                )

            gift_message = st.text_area(
                "Message (optional)",
                max_chars=500,
                key="gift_store_send_message",
                placeholder=(
                    "Add a short message "
                    "with your gift..."
                ),
            )

            available_to_send = int(
                gift_credits
                or 0
            )

            if (
                total_send_credits
                > available_to_send
            ):

                st.error(
                    f"Insufficient Gift Credits. "
                    f"You have "
                    f"{available_to_send:,}, "
                    f"but this gift requires "
                    f"{total_send_credits:,}."
                )

            else:

                if st.button(
                    (
                        f"🎁 Send "
                        f"{gift_quantity} × "
                        f"{selected_gift_emoji} "
                        f"{selected_gift_name}"
                    ),
                    type="primary",
                    use_container_width=True,
                    key="gift_store_send_gift_button",
                ):

                    timestamp = now()

                    reference = make_reference(
                        "LG-GIFT-SEND"
                    )

                    try:

                        # =================================
                        # VERIFY RECIPIENT
                        # =================================

                        recipient_exists = (
                            connection.execute(
                                """
                                SELECT id
                                FROM users
                                WHERE id = ?
                                LIMIT 1
                                """,
                                (
                                    selected_recipient_id,
                                ),
                            ).fetchone()
                        )

                        if not recipient_exists:

                            st.error(
                                "That LifeGrid account "
                                "no longer exists."
                            )

                            st.stop()

                        if (
                            int(selected_recipient_id)
                            == int(USER_ID)
                        ):

                            st.error(
                                "You cannot send "
                                "a gift to yourself."
                            )

                            st.stop()

                        # =================================
                        # REFRESH SENDER BALANCE
                        # =================================

                        sender_balance_row = (
                            connection.execute(
                                """
                                SELECT balance
                                FROM gift_credit_balances
                                WHERE user_id = ?
                                LIMIT 1
                                """,
                                (USER_ID,),
                            ).fetchone()
                        )

                        if not sender_balance_row:

                            connection.rollback()

                            st.error(
                                "Your Gift Credit account "
                                "could not be found."
                            )

                            st.stop()

                        current_sender_credits = int(
                            sender_balance_row[0]
                            or 0
                        )

                        if (
                            current_sender_credits
                            < total_send_credits
                        ):

                            connection.rollback()

                            st.error(
                                "Your available Gift Credits "
                                "are no longer sufficient. "
                                "Please refresh the page "
                                "and try again."
                            )

                            st.stop()

                        # =================================
                        # ATOMIC GIFT CREDIT DEBIT
                        # =================================

                        debit_cursor = connection.execute(
                            """
                            UPDATE gift_credit_balances
                            SET
                                balance =
                                    COALESCE(balance, 0)
                                    - ?,
                                lifetime_sent =
                                    COALESCE(
                                        lifetime_sent,
                                        0
                                    ) + ?,
                                updated_at = ?
                            WHERE user_id = ?
                              AND COALESCE(balance, 0) >= ?
                            """,
                            (
                                total_send_credits,
                                total_send_credits,
                                timestamp,
                                USER_ID,
                                total_send_credits,
                            ),
                        )

                        if debit_cursor.rowcount != 1:

                            connection.rollback()

                            st.error(
                                "Your Gift Credit balance "
                                "changed before the transfer "
                                "could be completed. "
                                "Please try again."
                            )

                            st.stop()

                        # =================================
                        # GET GIFT CODE
                        # =================================

                        gift_code_row = (
                            connection.execute(
                                """
                                SELECT gift_code
                                FROM gift_catalog
                                WHERE id = ?
                                LIMIT 1
                                """,
                                (
                                    selected_row[0],
                                ),
                            ).fetchone()
                        )

                        gift_code = (
                            gift_code_row[0]
                            if gift_code_row
                            and gift_code_row[0]
                            else "GIFT"
                        )

                        creator_value_total = (
                            selected_creator_value
                            * int(gift_quantity)
                        )

                        # =================================
                        # RECORD GIFT SENT
                        # =================================

                        gifts_sent_columns = (
                            get_columns(
                                connection,
                                "gifts_sent",
                            )
                        )

                        gifts_sent_data = {
                            "sender_user_id": USER_ID,

                            # Current schema
                            "receiver_user_id":
                                selected_recipient_id,

                            # Legacy schema
                            "recipient_user_id":
                                selected_recipient_id,

                            "gift_id":
                                int(selected_row[0]),

                            "gift_code":
                                str(gift_code),

                            "gift_name":
                                str(selected_gift_name),

                            "quantity":
                                int(gift_quantity),

                            # Existing column
                            "credits":
                                total_send_credits,

                            # FIX FOR YOUR ERROR
                            "total_credits":
                                total_send_credits,

                            "creator_value":
                                creator_value_total,

                            "transaction_reference":
                                reference,

                            "reference":
                                reference,

                            "status":
                                "Completed",

                            "created_at":
                                timestamp,
                        }

                        gift_fields = [
                            column
                            for column
                            in gifts_sent_data
                            if column
                            in gifts_sent_columns
                        ]

                        gift_values = [
                            gifts_sent_data[column]
                            for column
                            in gift_fields
                        ]

                        # =================================
                        # LEGACY NOT NULL COMPATIBILITY
                        # =================================

                        gift_table_info = (
                            get_table_info(
                                connection,
                                "gifts_sent",
                            )
                        )

                        existing_gift_fields = set(
                            gift_fields
                        )

                        for row in gift_table_info:

                            column_name = row[1]
                            not_null = row[3]
                            default_value = row[4]
                            primary_key = row[5]

                            if primary_key:
                                continue

                            if not_null != 1:
                                continue

                            if default_value is not None:
                                continue

                            if (
                                column_name
                                in existing_gift_fields
                            ):
                                continue

                            if (
                                column_name
                                == "recipient_user_id"
                            ):

                                gift_fields.append(
                                    column_name
                                )

                                gift_values.append(
                                    selected_recipient_id
                                )

                            elif (
                                column_name
                                == "receiver_user_id"
                            ):

                                gift_fields.append(
                                    column_name
                                )

                                gift_values.append(
                                    selected_recipient_id
                                )

                            elif (
                                column_name
                                == "total_credits"
                            ):

                                gift_fields.append(
                                    column_name
                                )

                                gift_values.append(
                                    total_send_credits
                                )

                            elif column_name in (
                                "credits",
                                "gift_credits",
                                "credit_amount",
                            ):

                                gift_fields.append(
                                    column_name
                                )

                                gift_values.append(
                                    total_send_credits
                                )

                            elif column_name == "quantity":

                                gift_fields.append(
                                    column_name
                                )

                                gift_values.append(
                                    int(gift_quantity)
                                )

                            elif column_name in (
                                "created_at",
                                "updated_at",
                                "timestamp",
                                "date",
                            ):

                                gift_fields.append(
                                    column_name
                                )

                                gift_values.append(
                                    timestamp
                                )

                            elif column_name in (
                                "status",
                                "transaction_status",
                            ):

                                gift_fields.append(
                                    column_name
                                )

                                gift_values.append(
                                    "Completed"
                                )

                            elif column_name in (
                                "reference",
                                "transaction_reference",
                                "transaction_id",
                                "reference_id",
                            ):

                                gift_fields.append(
                                    column_name
                                )

                                gift_values.append(
                                    reference
                                )

                            else:

                                gift_fields.append(
                                    column_name
                                )

                                gift_values.append(
                                    ""
                                )

                            existing_gift_fields.add(
                                column_name
                            )

                        if not gift_fields:

                            raise sqlite3.OperationalError(
                                "No compatible columns were "
                                "found in gifts_sent."
                            )

                        placeholders = ", ".join(
                            ["?"] * len(gift_fields)
                        )

                        connection.execute(
                            f"""
                            INSERT INTO gifts_sent
                            ({", ".join(gift_fields)})
                            VALUES ({placeholders})
                            """,
                            gift_values,
                        )

                        # =================================
                        # CREATOR GIFT EARNINGS
                        # =================================

                        earnings_columns = (
                            get_columns(
                                connection,
                                "creator_gift_earnings",
                            )
                        )

                        earnings_data = {
                            "creator_user_id":
                                selected_recipient_id,

                            "sender_user_id":
                                USER_ID,

                            "gift_id":
                                int(selected_row[0]),

                            "gift_code":
                                str(gift_code),

                            "credits":
                                total_send_credits,

                            "creator_value":
                                creator_value_total,

                            "transaction_reference":
                                reference,

                            "reference":
                                reference,

                            "status":
                                "Pending",

                            "created_at":
                                timestamp,
                        }

                        earnings_fields = [
                            column
                            for column
                            in earnings_data
                            if column
                            in earnings_columns
                        ]

                        earnings_values = [
                            earnings_data[column]
                            for column
                            in earnings_fields
                        ]

                        if earnings_fields:

                            connection.execute(
                                f"""
                                INSERT INTO
                                creator_gift_earnings
                                ({", ".join(earnings_fields)})
                                VALUES (
                                    {", ".join(["?"] * len(earnings_fields))}
                                )
                                """,
                                earnings_values,
                            )

                        # =================================
                        # SYNC TO CREATOR EARNINGS & PROFILE
                        # =================================
                        try:
                            connection.execute(
                                """
                                INSERT OR IGNORE INTO creator_earnings
                                    (earning_reference, creator_id, supporter_id, amount,
                                     platform_fee, currency, status, created_at)
                                VALUES (?, ?, ?, ?, ?, ?, 'Completed', ?)
                                """,
                                (
                                    reference,
                                    selected_recipient_id,
                                    USER_ID,
                                    float(creator_value_total),
                                    float(max(0, total_send_credits - creator_value_total)),
                                    wallet_currency or "NGN",
                                    timestamp,
                                ),
                            )
                            connection.execute(
                                """
                                UPDATE creator_profiles
                                SET total_earnings = COALESCE(total_earnings, 0) + ?
                                WHERE user_id = ?
                                """,
                                (float(creator_value_total), selected_recipient_id),
                            )
                        except Exception:
                            pass

                        # =================================
                        # PLATFORM REVENUE
                        # =================================

                        platform_revenue = max(
                            0,
                            total_send_credits
                            - creator_value_total,
                        )

                        insert_compatible(
                            connection=connection,
                            table_name=(
                                "platform_revenue_ledger"
                            ),
                            data={
                                "transaction_reference":
                                    reference,
                                "reference":
                                    reference,
                                "user_id":
                                    USER_ID,
                                "credits":
                                    total_send_credits,
                                "platform_revenue":
                                    platform_revenue,
                                "wallet_currency":
                                    wallet_currency,
                                "wallet_amount":
                                    0,
                                "status":
                                    "Completed",
                                "created_at":
                                    timestamp,
                            },
                            transaction_reference=reference,
                            timestamp=timestamp,
                            currency=wallet_currency,
                            amount=0,
                            credits=total_send_credits,
                            user_id=USER_ID,
                        )

                        # =================================
                        # RECIPIENT GIFT ACCOUNT
                        # =================================

                        recipient_balance_exists = (
                            connection.execute(
                                """
                                SELECT id
                                FROM gift_credit_balances
                                WHERE user_id = ?
                                LIMIT 1
                                """,
                                (
                                    selected_recipient_id,
                                ),
                            ).fetchone()
                        )

                        if not recipient_balance_exists:

                            balance_columns = (
                                get_columns(
                                    connection,
                                    "gift_credit_balances",
                                )
                            )

                            recipient_balance_data = {
                                "user_id":
                                    selected_recipient_id,
                                "balance":
                                    0,
                                "lifetime_purchased":
                                    0,
                                "lifetime_received":
                                    0,
                                "lifetime_sent":
                                    0,
                                "updated_at":
                                    timestamp,
                            }

                            recipient_fields = [
                                column
                                for column
                                in recipient_balance_data
                                if column
                                in balance_columns
                            ]

                            recipient_values = [
                                recipient_balance_data[column]
                                for column
                                in recipient_fields
                            ]

                            recipient_placeholders = (
                                ", ".join(
                                    ["?"]
                                    * len(recipient_fields)
                                )
                            )

                            connection.execute(
                                f"""
                                INSERT INTO
                                gift_credit_balances
                                ({", ".join(recipient_fields)})
                                VALUES (
                                    {recipient_placeholders}
                                )
                                """,
                                recipient_values,
                            )

                        # =================================
                        # UPDATE RECIPIENT RECEIVED
                        # =================================

                        connection.execute(
                            """
                            UPDATE gift_credit_balances
                            SET
                                lifetime_received =
                                    COALESCE(
                                        lifetime_received,
                                        0
                                    ) + ?,
                                updated_at = ?
                            WHERE user_id = ?
                            """,
                            (
                                creator_value_total,
                                timestamp,
                                selected_recipient_id,
                            ),
                        )

                        # =================================
                        # NOTIFY RECIPIENT
                        # =================================

                        send_gift_notification(
                            connection=connection,
                            recipient_user_id=(
                                selected_recipient_id
                            ),
                            sender_user_id=USER_ID,
                            gift_name=selected_gift_name,
                            gift_emoji=selected_gift_emoji,
                            quantity=int(gift_quantity),
                            credits=total_send_credits,
                            reference=reference,
                        )

                        # =================================
                        # COMMIT ENTIRE GIFT TRANSACTION
                        # =================================

                        connection.commit()

                        new_sender_balance = (
                            current_sender_credits
                            - total_send_credits
                        )

                        st.success(
                            f"🎉 Gift sent successfully! "
                            f"{gift_quantity} × "
                            f"{selected_gift_emoji} "
                            f"{selected_gift_name} "
                            f"sent for "
                            f"{total_send_credits:,} "
                            f"Gift Credits."
                        )

                        st.info(
                            f"🎁 Remaining Gift Credits: "
                            f"{new_sender_balance:,}"
                        )

                        st.caption(
                            f"Transaction Reference: "
                            f"{reference}"
                        )

                        if gift_message.strip():

                            st.caption(
                                f"Message sent: "
                                f"{gift_message.strip()}"
                            )

                        # Clear selected gift after
                        # successful transaction.

                        st.session_state[
                            "gift_store_selected_gift_id"
                        ] = None

                        st.session_state[
                            "gift_store_selected_gift_name"
                        ] = ""

                        st.session_state[
                            "gift_store_selected_gift_emoji"
                        ] = "🎁"

                        st.session_state[
                            "gift_store_selected_gift_price"
                        ] = 0

                        st.session_state.pop(
                            "gift_store_recipient_search",
                            None,
                        )

                        st.session_state.pop(
                            "gift_store_recipient_choice",
                            None,
                        )

                        st.session_state.pop(
                            "gift_store_send_quantity",
                            None,
                        )

                        st.session_state.pop(
                            "gift_store_send_message",
                            None,
                        )

                        st.rerun()

                    except Exception as error:

                        connection.rollback()

                        st.error(
                            "The gift could not be sent. "
                            "Your Gift Credits were not deducted."
                        )

                        st.exception(error)

        else:

            st.info(
                "Enter another LifeGrid user's "
                "username, name, or email above "
                "to find the recipient."
            )

    else:

        st.session_state[
            "gift_store_selected_gift_id"
        ] = None

        st.warning(
            "The selected gift is no longer available."
        )

else:

    st.info(
        "Choose a gift below and click "
        "**Send this Gift** to select the "
        "gift you want to send."
    )


# =========================================================
# SEND BUTTONS ON GIFT CARDS
# =========================================================

if catalog_rows:

    st.markdown(
        "### 💌 Choose a Gift to Send"
    )

    columns_per_row = 4

    for start in range(
        0,
        len(catalog_rows),
        columns_per_row,
    ):

        gift_row = catalog_rows[
            start:start + columns_per_row
        ]

        send_columns = st.columns(
            columns_per_row
        )

        for display_column, gift in zip(
            send_columns,
            gift_row,
        ):

            gift_name = (
                gift[1]
                or "Gift"
            )

            gift_emoji = (
                gift[2]
                or "🎁"
            )

            try:
                credit_cost = int(
                    gift[3]
                    or 0
                )
            except (
                TypeError,
                ValueError,
            ):
                credit_cost = 0

            with display_column:

                if st.button(
                    f"{gift_emoji} Send {gift_name}",
                    key=(
                        f"gift_store_select_send_"
                        f"{gift[0]}"
                    ),
                    use_container_width=True,
                ):

                    st.session_state[
                        "gift_store_selected_gift_id"
                    ] = gift[0]

                    st.session_state[
                        "gift_store_selected_gift_name"
                    ] = gift_name

                    st.session_state[
                        "gift_store_selected_gift_emoji"
                    ] = gift_emoji

                    st.session_state[
                        "gift_store_selected_gift_price"
                    ] = credit_cost

                    st.rerun()


# =========================================================
# STATISTICS
# =========================================================

st.divider()

st.subheader(
    "📊 Gift Credit Statistics"
)

stat1, stat2, stat3, stat4 = st.columns(4)

with stat1:

    st.metric(
        "Current Balance",
        f"{gift_credits:,}",
    )

with stat2:

    st.metric(
        "Purchased",
        f"{lifetime_purchased:,}",
    )

with stat3:

    st.metric(
        "Received",
        f"{lifetime_received:,}",
    )

with stat4:

    st.metric(
        "Sent",
        f"{lifetime_sent:,}",
    )


# =========================================================
# PURCHASE HISTORY
# =========================================================

st.divider()

st.subheader(
    "🧾 Gift Credit Purchase History"
)

history_rows = connection.execute(
    """
    SELECT
        transaction_reference,
        reference,
        credits,
        wallet_currency,
        wallet_amount,
        status,
        created_at
    FROM gift_credit_transactions
    WHERE user_id = ?
      AND (
            transaction_type = 'Purchase'
            OR transaction_type IS NULL
          )
    ORDER BY id DESC
    LIMIT 20
    """,
    (USER_ID,),
).fetchall()


if history_rows:

    for history in history_rows:

        reference = (
            history[0]
            or history[1]
            or "N/A"
        )

        credits = int(
            history[2]
            or 0
        )

        currency = (
            history[3]
            or wallet_currency
        )

        amount = float(
            history[4]
            or 0
        )

        status = (
            history[5]
            or "Completed"
        )

        created_at = (
            history[6]
            or ""
        )

        with st.container(
            border=True
        ):

            h1, h2, h3 = st.columns(3)

            with h1:

                st.write(
                    f"**{credits:,} Gift Credits**"
                )

            with h2:

                st.write(
                    f"**{currency} "
                    f"{amount:,.2f}**"
                )

            with h3:

                st.write(
                    f"**{status}**"
                )

            st.caption(
                f"Reference: {reference} | "
                f"{created_at}"
            )

else:

    st.info(
        "No Gift Credit purchases have "
        "been made yet."
    )


# =========================================================
# PAYMENT SECURITY NOTICE
# =========================================================

st.divider()

st.caption(
    "Payment security: LifeGrid issues Gift Credits only after direct Flutterwave API verification. "
    "A checkout redirect, screenshot, or customer claim alone is not proof of payment. "
    "Internal LifeGrid wallet funds are not deducted for these external checkout purchases."
)
