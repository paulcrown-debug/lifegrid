import uuid
from decimal import Decimal
from datetime import datetime

import streamlit as st

try:
    from database import get_connection
except ImportError:
    import sqlite3
    def get_connection():
        return sqlite3.connect("lifegrid.db", check_same_thread=False)

st.set_page_config(
    page_title="Creator Receiving Account | LifeGrid",
    page_icon="🏦",
    layout="wide",
)

if "user" not in st.session_state or not st.session_state["user"]:
    st.warning("Please log in to access your Creator Receiving Account.")
    st.stop()

current_user = st.session_state["user"]
if isinstance(current_user, dict):
    user_id = int(current_user.get("id") or current_user.get("user_id") or 0)
    username = str(current_user.get("username") or current_user.get("name") or "User")
    user_currency = str(current_user.get("currency") or current_user.get("currency_code") or "USD").upper()
else:
    user_id = int(current_user)
    username = "User"
    user_currency = "USD"

if user_id <= 0:
    st.error("Unable to identify your LifeGrid account.")
    st.stop()

connection = get_connection()

def get_columns(table_name):
    try:
        return {row[1] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()}
    except Exception:
        return set()

def ensure_core_schemas():
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS receiving_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            receiving_id TEXT UNIQUE NOT NULL,
            currency TEXT DEFAULT 'NGN',
            status TEXT DEFAULT 'Active',
            verification_status TEXT DEFAULT 'Pending',
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
            creator_status TEXT DEFAULT 'active',
            total_earnings REAL DEFAULT 0,
            currency TEXT DEFAULT 'NGN'
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS creator_earnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            earning_reference TEXT UNIQUE,
            creator_id INTEGER NOT NULL,
            supporter_id INTEGER,
            amount REAL DEFAULT 0,
            platform_fee REAL DEFAULT 0,
            currency TEXT DEFAULT 'NGN',
            status TEXT DEFAULT 'Completed',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS creator_kyc (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            kyc_level INTEGER DEFAULT 1,
            document_type TEXT,
            document_number TEXT,
            verification_status TEXT DEFAULT 'Pending',
            rejection_reason TEXT,
            submitted_at TEXT,
            reviewed_at TEXT,
            reviewed_by TEXT
        )
        """
    )
    connection.commit()

    # Rebuild legacy UNIQUE(user_id) if it restricts multi-currency
    try:
        indexes = connection.execute("PRAGMA index_list(receiving_accounts)").fetchall()
        unique_user_index = False
        index_sql = []
        for index in indexes:
            index_name = index[1]
            is_unique = bool(index[2])
            is_partial = bool(index[4]) if len(index) > 4 else False
            index_info = connection.execute(f'PRAGMA index_info("{index_name}")').fetchall()
            indexed_columns = [row[2] for row in index_info]
            sql_row = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
                (index_name,),
            ).fetchone()
            if sql_row and sql_row[0]:
                index_sql.append(sql_row[0])
            if is_unique and indexed_columns == ["user_id"] and not is_partial:
                unique_user_index = True

        table_sql_row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'receiving_accounts'"
        ).fetchone()
        table_sql = (table_sql_row[0] or "") if table_sql_row else ""
        inline_user_unique = False
        for fragment in table_sql.replace("\n", " ").split(","):
            if "user_id" in fragment.lower() and "unique" in fragment.lower():
                inline_user_unique = True

        if unique_user_index or inline_user_unique:
            columns = connection.execute("PRAGMA table_info(receiving_accounts)").fetchall()
            if columns:
                temp_name = "receiving_accounts_multi_migration"
                connection.execute(f'DROP TABLE IF EXISTS "{temp_name}"')
                definitions = []
                column_names = []
                for row in columns:
                    name, data_type, not_null, default_value, primary_key = row[1], row[2] or "", row[3], row[4], row[5]
                    quoted_name = '"' + name.replace('"', '""') + '"'
                    definition = f"{quoted_name} {data_type}".strip()
                    if primary_key:
                        definition += " PRIMARY KEY"
                        if name.lower() == "id" and "INT" in data_type.upper() and "AUTOINCREMENT" in table_sql.upper():
                            definition += " AUTOINCREMENT"
                    if not_null and not primary_key:
                        definition += " NOT NULL"
                    if default_value is not None:
                        definition += f" DEFAULT {default_value}"
                    definitions.append(definition)
                    column_names.append(quoted_name)
                connection.execute(f'CREATE TABLE "{temp_name}" ({", ".join(definitions)})')
                cols = ", ".join(column_names)
                connection.execute(f'INSERT INTO "{temp_name}" ({cols}) SELECT {cols} FROM receiving_accounts')
                connection.execute("DROP TABLE receiving_accounts")
                connection.execute(f'ALTER TABLE "{temp_name}" RENAME TO receiving_accounts')
                for statement in index_sql:
                    try:
                        connection.execute(statement)
                    except Exception:
                        pass
                connection.commit()

        duplicate = connection.execute(
            "SELECT 1 FROM receiving_accounts GROUP BY user_id, currency HAVING COUNT(*) > 1 LIMIT 1"
        ).fetchone()
        if not duplicate:
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_receiving_accounts_user_currency "
                "ON receiving_accounts(user_id, currency)"
            )
        connection.commit()
    except Exception:
        pass

ensure_core_schemas()

# Supported currencies and display symbols
SUPPORTED_CURRENCIES = ["USD", "NGN", "KES", "GHS", "EUR", "GBP", "CAD", "AUD", "ZAR", "USDT"]

CURRENCY_SYMBOLS = {
    "USD": "$",
    "NGN": "₦",
    "KES": "KSh ",
    "GHS": "GH₵ ",
    "EUR": "€",
    "GBP": "£",
    "CAD": "CA$ ",
    "AUD": "AU$ ",
    "ZAR": "R ",
    "USDT": "USDT "
}

creator = connection.execute(
    """
    SELECT user_id, display_name, creator_status, total_earnings, currency
    FROM creator_profiles WHERE user_id = ? LIMIT 1
    """,
    (user_id,),
).fetchone()

def safe_switch_page(candidates, fallback_label):
    """Resilient page switcher that dynamically detects page filenames."""
    if not hasattr(st, "switch_page"):
        st.info(f"Please open {fallback_label} from the sidebar menu.")
        return
    import os
    pages_dir = "pages"
    existing_files = []
    if os.path.exists(pages_dir):
        try:
            existing_files = [f for f in os.listdir(pages_dir) if f.endswith(".py")]
        except Exception:
            existing_files = []

    for cand in candidates:
        rel_path = f"pages/{cand}" if not cand.startswith("pages/") else cand
        fname = os.path.basename(rel_path)
        if os.path.exists(rel_path) or fname in existing_files:
            try:
                st.switch_page(rel_path)
                return
            except Exception:
                pass

    for cand in candidates:
        cand_clean = os.path.basename(cand).replace(".py", "").lower()
        keywords = [k for k in cand_clean.split() if len(k) > 3 and not k.isdigit() and k != "-"]
        for f in existing_files:
            f_lower = f.lower()
            if any(kw in f_lower for kw in keywords):
                try:
                    st.switch_page(f"pages/{f}")
                    return
                except Exception:
                    pass

    st.info(f"💡 Please open **{fallback_label}** directly from the sidebar navigation.")

if not creator:
    st.title("🏦 Creator Receiving Account")
    st.info("👋 You don't have an active Creator Profile yet.")
    st.write("Activate your LifeGrid Creator Account below to enable receiving accounts, fan gifts, and earnings withdrawals.")
    if st.button("✨ Activate Creator Account Now", type="primary"):
        connection.execute(
            """
            INSERT OR REPLACE INTO creator_profiles (user_id, display_name, creator_status, total_earnings, currency)
            VALUES (?, ?, 'active', 0.0, ?)
            """,
            (user_id, username, user_currency),
        )
        connection.commit()
        st.success("🎉 Creator Account successfully activated!")
        st.rerun()
    connection.close()
    st.stop()

creator_name = str(creator[1] or username)
creator_status = str(creator[2] or "active")
creator_currency = str(creator[4] or user_currency).upper()

# Ensure at least one receiving account exists
accounts = connection.execute(
    """
    SELECT id, user_id, receiving_id, currency, status, verification_status, created_at
    FROM receiving_accounts WHERE user_id = ? ORDER BY id ASC
    """,
    (user_id,),
).fetchall()

if not accounts:
    new_id = "LG-" + uuid.uuid4().hex[:8].upper()
    connection.execute(
        """
        INSERT INTO receiving_accounts (user_id, receiving_id, currency, status, verification_status, created_at)
        VALUES (?, ?, ?, 'Active', 'Verified', ?)
        """,
        (user_id, new_id, creator_currency, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    connection.commit()
    accounts = connection.execute(
        """
        SELECT id, user_id, receiving_id, currency, status, verification_status, created_at
        FROM receiving_accounts WHERE user_id = ? ORDER BY id ASC
        """,
        (user_id,),
    ).fetchall()

# Check KYC Level
kyc_row = connection.execute(
    "SELECT kyc_level, verification_status FROM creator_kyc WHERE user_id = ? LIMIT 1",
    (user_id,),
).fetchone()
kyc_level = int(kyc_row[0]) if (kyc_row and kyc_row[0]) else 1
kyc_status = str(kyc_row[1]) if (kyc_row and kyc_row[1]) else "Pending Level 2"

st.title("🏦 Creator Receiving Account & Wallet")
st.caption("Manage multi-currency payout addresses, review gifts received, and monitor disbursement balances.")

# Navigation / Shortcut Banner
nav_col1, nav_col2, nav_col3, nav_col4 = st.columns([2, 1, 1, 1])
with nav_col1:
    st.write(f"Logged in as: **@{username}** ({creator_name})")
with nav_col2:
    if st.button("📊 Analytics & Ledger", use_container_width=True):
        safe_switch_page([
            "pages/18 - Creator Analytics & Ledger Dashboard.py",
            "pages/18 - Creator Analytics.py",
            "pages/Creator Analytics.py"
        ], "Creator Analytics")
with nav_col3:
    if st.button("🎁 Gift Store", use_container_width=True):
        safe_switch_page([
            "pages/12 - Gift Store.py",
            "pages/Gift Store.py",
            "pages/10 - Gifts.py"
        ], "Gift Store")
with nav_col4:
    if st.button("💸 Withdraw Funds", type="primary", use_container_width=True):
        safe_switch_page([
            "pages/14 - Creator Withdrawal.py",
            "pages/Creator Withdrawal.py"
        ], "Withdraw Funds")

st.divider()

# Prominent Currency Selector
stored_curr = st.session_state.get("selected_currency") or creator_currency
if stored_curr not in SUPPORTED_CURRENCIES:
    stored_curr = "USD"
curr_idx = SUPPORTED_CURRENCIES.index(stored_curr) if stored_curr in SUPPORTED_CURRENCIES else 0

c_col1, c_col2 = st.columns([2, 3])
with c_col1:
    selected_currency = st.selectbox(
        "💱 Active Operating Currency (Applies to Gifts, Wallet & Withdrawals):",
        SUPPORTED_CURRENCIES,
        index=curr_idx,
        help="Switching currency updates your active receiving account and sets the default currency for Gift purchases and payouts across LifeGrid."
    )

# Broadcast selection to session state so Gift Store, Gifts, and Withdrawals adapt
st.session_state["selected_currency"] = selected_currency
st.session_state["user_currency"] = selected_currency
st.session_state["gift_currency"] = selected_currency
if isinstance(st.session_state.get("user"), dict):
    st.session_state["user"]["currency"] = selected_currency

with c_col2:
    sym = CURRENCY_SYMBOLS.get(selected_currency, "")
    st.info(f"💡 Active currency is set to **{selected_currency}** (`{sym}`). All gifts, wallet earnings, and withdrawal views now use **{selected_currency}**.")

# Manual account creation expander
with st.expander("➕ Add a receiving account in another currency"):
    existing_currencies = {str(row[3] or "").upper() for row in accounts}
    available_currencies = [code for code in SUPPORTED_CURRENCIES if code not in existing_currencies]
    if available_currencies:
        new_currency = st.selectbox("Account currency to add", available_currencies)
        if st.button("Create receiving account", type="primary"):
            new_id = "LG-" + uuid.uuid4().hex[:8].upper()
            try:
                connection.execute(
                    """
                    INSERT INTO receiving_accounts (user_id, receiving_id, currency, status, verification_status, created_at)
                    VALUES (?, ?, ?, 'Active', 'Verified', ?)
                    """,
                    (user_id, new_id, new_currency, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                )
                connection.commit()
                st.session_state["selected_currency"] = new_currency
                st.success(f"{new_currency} receiving account created.")
                st.rerun()
            except Exception as exc:
                connection.rollback()
                st.error(f"Could not create the account: {exc}")
    else:
        st.info("You already have an account for every currency currently supported.")

# Ensure receiving account exists for active selected currency
selected_account = None
for acc in accounts:
    if str(acc[3] or "").upper() == selected_currency:
        selected_account = acc
        break

if not selected_account:
    new_id = "LG-" + uuid.uuid4().hex[:8].upper()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        connection.execute(
            """
            INSERT INTO receiving_accounts (user_id, receiving_id, currency, status, verification_status, created_at)
            VALUES (?, ?, ?, 'Active', 'Verified', ?)
            """,
            (user_id, new_id, selected_currency, now_str),
        )
        connection.commit()
    except Exception:
        pass
    selected_account = connection.execute(
        """
        SELECT id, user_id, receiving_id, currency, status, verification_status, created_at
        FROM receiving_accounts WHERE user_id = ? AND UPPER(currency) = ? LIMIT 1
        """,
        (user_id, selected_currency),
    ).fetchone()

if not selected_account:
    selected_account = accounts[0]

receiving_id = str(selected_account[2])
receiving_currency = str(selected_account[3] or selected_currency).upper()
receiving_status = str(selected_account[4] or "Active")
verification_status = str(selected_account[5] or "Verified")
account_created = str(selected_account[6] or "")

st.subheader(f"🏦 Selected Receiving Account ({receiving_currency})")
info1, info2, info3, info4 = st.columns(4)
with info1:
    st.metric("Receiving Account ID", receiving_id)
with info2:
    st.metric("Account Status", receiving_status)
with info3:
    st.metric("Currency", receiving_currency)
with info4:
    badge = "🛡️ Tier 2 (Verified)" if kyc_level >= 2 else "⚠️ Tier 1 (Standard)"
    st.metric("AML / KYC Tier", badge)

st.write(f"**Creator Profile:** {creator_name} ({creator_status.title()})")
if account_created:
    st.caption(f"Account Activated: {account_created}")

earnings_columns = get_columns("creator_earnings")
earnings = []
if "earning_reference" in earnings_columns:
    platform_fee_expr = "platform_fee" if "platform_fee" in earnings_columns else "0"
    if "supporter_id" in earnings_columns:
        earnings = connection.execute(
            f"""
            SELECT ce.earning_reference, ce.amount, {platform_fee_expr}, ce.currency,
                   ce.status, ce.created_at, u.username
            FROM creator_earnings ce LEFT JOIN users u ON u.id = ce.supporter_id
            WHERE ce.creator_id = ? AND UPPER(COALESCE(ce.currency, ?)) = ?
            ORDER BY ce.id DESC
            """,
            (user_id, receiving_currency, receiving_currency),
        ).fetchall()
    else:
        earnings = connection.execute(
            f"""
            SELECT earning_reference, amount, {platform_fee_expr}, currency,
                   status, created_at, NULL
            FROM creator_earnings
            WHERE creator_id = ? AND UPPER(COALESCE(currency, ?)) = ?
            ORDER BY id DESC
            """,
            (user_id, receiving_currency, receiving_currency),
        ).fetchall()

total_earnings = Decimal("0.00")
completed_earnings = Decimal("0.00")
pending_earnings = Decimal("0.00")
total_platform_fees = Decimal("0.00")

for earning in earnings:
    amount = Decimal(str(earning[1] or 0))
    fee = Decimal(str(earning[2] or 0))
    total_earnings += amount
    total_platform_fees += fee
    status = str(earning[4] or "").lower()
    if status == "completed":
        completed_earnings += amount
    elif status in ("pending", "processing", "in review"):
        pending_earnings += amount

available_earnings = completed_earnings
curr_sym = CURRENCY_SYMBOLS.get(receiving_currency, f"{receiving_currency} ")

st.divider()
st.subheader(f"💰 {receiving_currency} Gifts & Earnings Balance")
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Available Balance", f"{curr_sym}{available_earnings:,.2f}")
with col2:
    st.metric("Total Gifts Earned", f"{curr_sym}{total_earnings:,.2f}")
with col3:
    st.metric("Pending Clearance", f"{curr_sym}{pending_earnings:,.2f}")
with col4:
    st.metric("Platform Fees Deducted", f"{curr_sym}{total_platform_fees:,.2f}")

st.markdown("#### ⚡ Withdrawal Limits & Eligibility")
limit_col1, limit_col2 = st.columns(2)
with limit_col1:
    if receiving_currency == "NGN":
        tier_limit = "₦25,000,000" if kyc_level >= 2 else "₦250,000"
    elif receiving_currency == "USD":
        tier_limit = "$100,000" if kyc_level >= 2 else "$500"
    elif receiving_currency == "KES":
        tier_limit = "KSh 13,000,000" if kyc_level >= 2 else "KSh 65,000"
    elif receiving_currency == "GHS":
        tier_limit = "GH₵ 1,500,000" if kyc_level >= 2 else "GH₵ 7,500"
    else:
        tier_limit = f"{curr_sym}100,000" if kyc_level >= 2 else f"{curr_sym}500"
    st.info(f"**Current Payout Limit:** {tier_limit} per transaction ({badge})")
with limit_col2:
    if kyc_level < 2:
        st.write("Upgrade your limit by completing Level 2 KYC verification.")
        if st.button("🛡️ Complete KYC Verification (Page 17)"):
            safe_switch_page([
                "pages/17 - Identity & KYC Verification.py",
                "pages/17 - Identity & KYC.py",
                "pages/Identity & KYC Verification.py"
            ], "Identity & KYC Verification")
    else:
        st.success("✅ Your identity has been verified. High-volume transfers are unlocked.")

st.divider()
st.subheader(f"📜 Recent {receiving_currency} Earnings & Fan Gifts")
if not earnings:
    st.info(f"No {receiving_currency} fan gift earnings recorded yet.")
else:
    for earning in earnings[:15]:
        reference, raw_amount, raw_fee, transaction_currency, status, created_at, supporter = earning
        amount = Decimal(str(raw_amount or 0))
        platform_fee = Decimal(str(raw_fee or 0))
        tx_curr = str(transaction_currency or receiving_currency).upper()
        sym = CURRENCY_SYMBOLS.get(tx_curr, f"{tx_curr} ")
        with st.container(border=True):
            left, right = st.columns([4, 1])
            with left:
                st.write("**🎁 Fan Gift Earning Received**")
                st.write(f"**Net Earning:** {sym}{amount:,.2f}")
                if supporter:
                    st.write(f"**Supporter:** @{supporter}")
                st.write(f"**Platform Handling Fee:** {sym}{platform_fee:,.2f}")
                st.caption(f"Ref: `{reference}` | Date: {created_at}")
            with right:
                st.metric("Status", str(status or "Completed").title())

st.divider()
st.caption("LifeGrid Creator Receiving Account & Wallet • Your life, your growth, your connections.")
connection.close()
