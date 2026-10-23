import uuid
import hashlib
import io
import csv
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime

import streamlit as st

from database import get_connection

try:
    from services.flutterwave import (
        get_supported_banks,
        verify_bank_account,
        resolve_bank_account,
        is_flutterwave_configured,
    )
except Exception:
    get_supported_banks = None
    verify_bank_account = None
    resolve_bank_account = None
    def is_flutterwave_configured():
        return False


# ============================================================
# PAGE SETTINGS
# ============================================================

st.set_page_config(
    page_title="Creator Withdrawal | LifeGrid",
    page_icon="💸",
    layout="wide",
)


# ============================================================
# LOGIN
# ============================================================

if "user" not in st.session_state or not st.session_state["user"]:
    st.warning("Please log in to access Creator Withdrawal.")
    st.stop()

current_user = st.session_state["user"]


def get_user_id(user):
    if isinstance(user, dict):
        return int(user.get("id") or user.get("user_id") or 0)

    if hasattr(user, "id"):
        return int(user.id)

    if hasattr(user, "user_id"):
        return int(user.user_id)

    try:
        return int(user)
    except (TypeError, ValueError):
        return 0


def get_user_currency(user):
    if isinstance(user, dict):
        return str(
            user.get("currency")
            or user.get("currency_code")
            or "USD"
        ).upper()

    return "USD"


user_id = get_user_id(current_user)
user_currency = get_user_currency(current_user)

if user_id <= 0:
    st.error("Unable to identify your LifeGrid account.")
    st.stop()


# ============================================================
# DATABASE
# ============================================================

connection = get_connection()



def get_columns(table_name):
    rows = connection.execute(
        f"PRAGMA table_info({table_name})"
    ).fetchall()
    return {row[1] for row in rows}


def get_table_info(table_name):
    try:
        rows = connection.execute(
            f"PRAGMA table_info({table_name})"
        ).fetchall()
        return {
            row[1]: {
                "cid": row[0],
                "name": row[1],
                "type": (row[2] or "").upper(),
                "notnull": bool(row[3]),
                "dflt_value": row[4],
                "pk": bool(row[5]),
            }
            for row in rows
        }
    except Exception:
        return {}


def add_test_creator_earnings(target_creator_id, test_amount, test_currency, test_asset_type="FIAT"):
    table_info = get_table_info("creator_earnings")
    if not table_info:
        return False
    import uuid
    from datetime import datetime
    ref = f"DEV-{test_currency.upper()}-{uuid.uuid4().hex[:8].upper()}"

    # Find a valid supporter_id if required by schema
    supporter_candidate = user_id if (user_id and user_id > 0) else 1
    try:
        user_row = connection.execute("SELECT id FROM users LIMIT 1").fetchone()
        if user_row and user_row[0]:
            supporter_candidate = int(user_row[0])
    except Exception:
        pass

    columns = set(table_info.keys())
    payload = {}

    if "creator_id" in columns:
        payload["creator_id"] = target_creator_id
    if "supporter_id" in columns:
        payload["supporter_id"] = supporter_candidate
    if "amount" in columns:
        payload["amount"] = float(test_amount)
    if "net_amount" in columns:
        payload["net_amount"] = float(test_amount)
    if "currency" in columns:
        payload["currency"] = test_currency.upper()
    if "status" in columns:
        payload["status"] = "Completed"
    if "earning_reference" in columns:
        payload["earning_reference"] = ref
    if "reference" in columns:
        payload["reference"] = ref
    if "asset_type" in columns:
        payload["asset_type"] = test_asset_type.upper()
    if "asset_code" in columns:
        payload["asset_code"] = test_currency.upper()
    if "platform_fee" in columns:
        payload["platform_fee"] = 0.0
    if "description" in columns:
        payload["description"] = f"Development Mode test {test_currency.upper()} balance"
    if "source" in columns:
        payload["source"] = "Test Seed"
    if "source_type" in columns:
        payload["source_type"] = "test"
    if "created_at" in columns:
        payload["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Fallback to satisfy any remaining NOT NULL column without default value
    for col_name, info in table_info.items():
        if info["pk"]:
            continue
        if info["notnull"] and info["dflt_value"] is None and col_name not in payload:
            col_type = info["type"]
            if any(t in col_type for t in ["INT", "REAL", "FLOA", "NUM", "DOUB"]):
                if "id" in col_name.lower():
                    payload[col_name] = supporter_candidate
                else:
                    payload[col_name] = 0
            else:
                payload[col_name] = "Test"

    col_names = list(payload.keys())
    placeholders = ", ".join(["?"] * len(col_names))
    col_list_str = ", ".join(col_names)
    sql = f"INSERT INTO creator_earnings ({col_list_str}) VALUES ({placeholders})"
    values = [payload[c] for c in col_names]

    connection.execute(sql, values)
    connection.commit()
    return True


def ensure_column(table_name, column_name, definition):
    columns = get_columns(table_name)

    if column_name not in columns:
        connection.execute(
            f"ALTER TABLE {table_name} "
            f"ADD COLUMN {column_name} {definition}"
        )
        connection.commit()


def ensure_withdrawal_compatibility():
    """
    Preserve the existing creator_withdrawals table used by
    Page 15. Only add optional fields when they are missing.
    No existing columns are renamed or removed.
    """
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS creator_withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            withdrawal_reference TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL,
            receiving_account_id INTEGER,
            amount REAL NOT NULL,
            currency TEXT NOT NULL,
            payout_method TEXT NOT NULL,
            destination TEXT DEFAULT '',
            payout_details TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Pending',
            notes TEXT DEFAULT '',
            requested_at TIMESTAMP NOT NULL
        )
        """
    )

    connection.commit()

    # Core columns that may be missing on older database schemas
    ensure_column("creator_withdrawals", "withdrawal_reference", "TEXT")
    ensure_column("creator_withdrawals", "receiving_account_id", "INTEGER")
    ensure_column("creator_withdrawals", "amount", "REAL DEFAULT 0.0")
    ensure_column("creator_withdrawals", "currency", "TEXT DEFAULT 'USD'")
    ensure_column("creator_withdrawals", "payout_method", "TEXT DEFAULT 'Bank Transfer'")
    ensure_column("creator_withdrawals", "destination", "TEXT DEFAULT ''")
    ensure_column("creator_withdrawals", "payout_details", "TEXT DEFAULT ''")
    ensure_column("creator_withdrawals", "status", "TEXT DEFAULT 'Pending'")
    ensure_column("creator_withdrawals", "notes", "TEXT DEFAULT ''")
    ensure_column("creator_withdrawals", "requested_at", "TIMESTAMP DEFAULT ''")

    # Multi-asset fields. Existing records remain FIAT.
    ensure_column(
        "creator_withdrawals",
        "asset_type",
        "TEXT DEFAULT 'FIAT'",
    )
    ensure_column(
        "creator_withdrawals",
        "asset_code",
        "TEXT",
    )
    ensure_column(
        "creator_withdrawals",
        "network",
        "TEXT",
    )
    ensure_column(
        "creator_withdrawals",
        "transaction_reference",
        "TEXT",
    )
    ensure_column(
        "creator_withdrawals",
        "processed_at",
        "TIMESTAMP",
    )

    # Platform charges & fee tracking columns
    ensure_column("creator_withdrawals", "gross_amount", "REAL DEFAULT 0.0")
    ensure_column("creator_withdrawals", "fee_amount", "REAL DEFAULT 0.0")
    ensure_column("creator_withdrawals", "platform_fee", "REAL DEFAULT 0.0")
    ensure_column("creator_withdrawals", "gateway_fee", "REAL DEFAULT 0.0")
    ensure_column("creator_withdrawals", "net_amount", "REAL DEFAULT 0.0")


def normalize_money(value):
    return Decimal(str(value or 0)).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

def calculate_withdrawal_fee(gross_amount, asset_code):
    """
    LifeGrid Platform Fee Architecture:
    - NGN: 2.0% platform handling fee + ₦100 fixed gateway transfer fee.
      (Flutterwave charges ~₦10.75-₦53.75, so ₦100 covers Flutterwave with a margin, plus LifeGrid earns the 2.0%).
    - USD: 2.5% platform handling fee + $5.00 fixed processing fee.
    - Crypto (USDT, USDC, BTC, ETH): 1.5% platform handling fee + 1.00 flat fee.
    - Other: 2.0% platform handling fee + 2.00 flat fee.
    """
    try:
        gross = Decimal(str(gross_amount or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        gross = Decimal("0.00")

    code = (asset_code or "USD").upper()

    if code == "NGN":
        gateway_fee = Decimal("100.00")
        platform_pct = Decimal("0.02")  # 2%
        platform_fee = (gross * platform_pct).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_fee = platform_fee + gateway_fee
    elif code == "USD":
        gateway_fee = Decimal("5.00")
        platform_pct = Decimal("0.025")  # 2.5%
        platform_fee = (gross * platform_pct).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_fee = platform_fee + gateway_fee
    elif code in ("USDT", "USDC"):
        gateway_fee = Decimal("1.00")
        platform_pct = Decimal("0.015")  # 1.5%
        platform_fee = (gross * platform_pct).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_fee = platform_fee + gateway_fee
    elif code in ("BTC", "ETH"):
        gateway_fee = Decimal("0.0005")
        platform_pct = Decimal("0.015")  # 1.5%
        platform_fee = (gross * platform_pct).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        total_fee = platform_fee + gateway_fee
    else:
        gateway_fee = Decimal("2.00")
        platform_pct = Decimal("0.02")
        platform_fee = (gross * platform_pct).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_fee = platform_fee + gateway_fee

    if gross <= Decimal("0.00"):
        total_fee = Decimal("0.00")
        platform_fee = Decimal("0.00")
        gateway_fee = Decimal("0.00")

    net_amount = max(Decimal("0.00"), gross - total_fee)

    return {
        "gross_amount": gross,
        "platform_fee": platform_fee,
        "gateway_fee": gateway_fee,
        "total_fee": total_fee,
        "net_amount": net_amount,
        "platform_pct_str": f"{float(platform_pct)*100:.1f}%",
        "gateway_fee_str": f"{gateway_fee:,.2f}",
    }


# ============================================================
# PAYOUT SAFEGUARDS & KYC TIERED LIMITS CONFIGURATION
# ============================================================

TIERED_PAYOUT_POLICY = {
    "NGN": {
        "symbol": "₦",
        "standard": {
            "min": Decimal("2000.00"),
            "max": Decimal("1000000.00"),       # ₦1,000,000 per request
            "daily_cap": Decimal("3000000.00"),   # ₦3,000,000 daily
            "max_daily_requests": 5,
            "tier_label": "Tier 1 (Standard)",
        },
        "verified": {
            "min": Decimal("2000.00"),
            "max": Decimal("25000000.00"),      # ₦25,000,000 per request after KYC
            "daily_cap": Decimal("50000000.00"),  # ₦50,000,000 daily after KYC
            "max_daily_requests": 15,
            "tier_label": "Tier 2 (KYC Verified)",
        },
    },
    "USD": {
        "symbol": "$",
        "standard": {
            "min": Decimal("10.00"),
            "max": Decimal("5000.00"),          # $5,000 per request
            "daily_cap": Decimal("15000.00"),     # $15,000 daily
            "max_daily_requests": 5,
            "tier_label": "Tier 1 (Standard)",
        },
        "verified": {
            "min": Decimal("10.00"),
            "max": Decimal("100000.00"),        # $100,000 per request after KYC
            "daily_cap": Decimal("250000.00"),    # $250,000 daily after KYC
            "max_daily_requests": 15,
            "tier_label": "Tier 2 (KYC Verified)",
        },
    },
    "DEFAULT": {
        "symbol": "",
        "standard": {
            "min": Decimal("5.00"),
            "max": Decimal("5000.00"),
            "daily_cap": Decimal("15000.00"),
            "max_daily_requests": 5,
            "tier_label": "Tier 1 (Standard)",
        },
        "verified": {
            "min": Decimal("5.00"),
            "max": Decimal("100000.00"),
            "daily_cap": Decimal("250000.00"),
            "max_daily_requests": 15,
            "tier_label": "Tier 2 (KYC Verified)",
        },
    },
}


def get_policy_limits(currency_code, is_kyc_verified=False):
    cur = str(currency_code or "").upper().strip()
    config = TIERED_PAYOUT_POLICY.get(cur, TIERED_PAYOUT_POLICY["DEFAULT"])
    tier_key = "verified" if is_kyc_verified else "standard"
    policy_data = dict(config[tier_key])
    policy_data["symbol"] = config["symbol"]
    return policy_data


def check_creator_kyc_verified(target_user_id, receiving_account_verif_status=""):
    """
    Detects if the creator has completed KYC verification.
    Checks lifegrid_kyc_verifications, receiving_accounts, creator_profiles, and users tables.
    """
    # 0. Check dedicated lifegrid_kyc_verifications table
    try:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT verification_status FROM lifegrid_kyc_verifications WHERE user_id = ? LIMIT 1",
            (target_user_id,),
        )
        k_row = cursor.fetchone()
        if k_row and str(k_row[0] or "").strip().lower() in ("verified", "approved", "completed"):
            return True
    except Exception:
        pass
    # 1. Receiving account verification status
    if str(receiving_account_verif_status or "").strip().lower() in ("verified", "approved", "completed"):
        return True

    # 2. Check creator_profiles table
    creator_cols = get_columns("creator_profiles")
    kyc_cols = [c for c in creator_cols if any(k in c.lower() for k in ("kyc", "verif", "tier"))]
    if kyc_cols:
        try:
            cursor = connection.cursor()
            select_cols = ", ".join(kyc_cols)
            cursor.execute(f"SELECT {select_cols} FROM creator_profiles WHERE user_id = ? LIMIT 1", (target_user_id,))
            row = cursor.fetchone()
            if row:
                for val in row:
                    if str(val or "").strip().lower() in ("verified", "approved", "completed", "tier_2", "tier_3", "1", "true"):
                        return True
        except Exception:
            pass

    # 3. Check users table
    user_cols = get_columns("users")
    user_kyc_cols = [c for c in user_cols if any(k in c.lower() for k in ("kyc", "verif", "tier", "is_verified"))]
    if user_kyc_cols:
        try:
            cursor = connection.cursor()
            select_cols = ", ".join(user_kyc_cols)
            cursor.execute(f"SELECT {select_cols} FROM users WHERE id = ? LIMIT 1", (target_user_id,))
            row = cursor.fetchone()
            if row:
                for val in row:
                    if str(val or "").strip().lower() in ("verified", "approved", "completed", "tier_2", "tier_3", "1", "true"):
                        return True
        except Exception:
            pass

    return False


def get_daily_withdrawal_usage(target_user_id, asset_type, asset_code):
    """Calculates count and total sum of withdrawals requested in the last 24 hours."""
    cols = get_columns("creator_withdrawals")
    time_col = (
        "requested_at"
        if "requested_at" in cols
        else ("created_at" if "created_at" in cols else None)
    )
    if not time_col:
        return 0, Decimal("0.00")

    status_filter = "status != 'Rejected'" if "status" in cols else "1=1"
    user_filter = "user_id = ?" if "user_id" in cols else "1=1"
    code_col = "asset_code" if "asset_code" in cols else "currency"

    sql = f"""
        SELECT COUNT(*), COALESCE(SUM(amount), 0)
        FROM creator_withdrawals
        WHERE {user_filter}
          AND {code_col} = ?
          AND {status_filter}
          AND {time_col} >= datetime('now', '-1 day')
    """
    params = (target_user_id, asset_code) if "user_id" in cols else (asset_code,)
    cursor = connection.cursor()
    cursor.execute(sql, params)
    row = cursor.fetchone()
    count = int(row[0] or 0)
    total_val = normalize_money(row[1] or 0)
    return count, total_val


def verify_account_password(target_user_id, password_candidate):
    """Verifies user password against the users table or auth module."""
    if not password_candidate:
        return False

    table_info = get_table_info("users")
    cols = set(table_info.keys())
    if not cols or "id" not in cols:
        return True

    cursor = connection.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ? LIMIT 1", (target_user_id,))
    row = cursor.fetchone()
    if not row:
        return True

    user_dict = {desc[0]: row[idx] for idx, desc in enumerate(cursor.description)}
    stored_hash = user_dict.get("password_hash") or user_dict.get("password") or ""

    if not stored_hash:
        return True

    # Exact match (for development / plain passwords)
    if stored_hash == password_candidate:
        return True

    # SHA-256 match
    cand_sha256 = hashlib.sha256(password_candidate.encode("utf-8")).hexdigest()
    if stored_hash.lower() == cand_sha256.lower():
        return True

    # Check bcrypt if available
    try:
        import bcrypt
        if bcrypt.checkpw(password_candidate.encode("utf-8"), stored_hash.encode("utf-8")):
            return True
    except Exception:
        pass

    return False


def get_creator():
    columns = get_columns("creator_profiles")

    required = {
        "user_id",
        "display_name",
        "creator_status",
        "total_earnings",
        "currency",
    }

    if not required.issubset(columns):
        return None

    return connection.execute(
        """
        SELECT
            user_id,
            display_name,
            creator_status,
            total_earnings,
            currency
        FROM creator_profiles
        WHERE user_id = ?
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()


def get_receiving_accounts():
    columns = get_columns("receiving_accounts")

    required = {
        "id",
        "user_id",
        "receiving_id",
        "currency",
        "status",
        "verification_status",
    }

    if not required.issubset(columns):
        return []

    return connection.execute(
        """
        SELECT
            id,
            user_id,
            receiving_id,
            currency,
            status,
            verification_status
        FROM receiving_accounts
        WHERE user_id = ?
        ORDER BY id ASC
        """,
        (user_id,),
    ).fetchall()


def get_creator_earnings_columns():
    return get_columns("creator_earnings")


def get_completed_fiat_earnings(currency_code):
    columns = get_creator_earnings_columns()

    required = {
        "earning_reference",
        "creator_id",
        "amount",
        "currency",
        "status",
    }

    if not required.issubset(columns):
        return Decimal("0.00")

    asset_expression = (
        "COALESCE(asset_type, 'FIAT')"
        if "asset_type" in columns
        else "'FIAT'"
    )

    row = connection.execute(
        f"""
        SELECT COALESCE(SUM(amount), 0)
        FROM creator_earnings
        WHERE creator_id = ?
          AND status = 'Completed'
          AND UPPER(currency) = ?
          AND {asset_expression} = 'FIAT'
        """,
        (creator_id, currency_code.upper()),
    ).fetchone()

    return normalize_money(row[0] if row else 0)


def get_completed_crypto_earnings(asset_code):
    columns = get_creator_earnings_columns()

    required = {
        "earning_reference",
        "creator_id",
        "amount",
        "currency",
        "status",
    }

    if not required.issubset(columns):
        return Decimal("0.00")

    if "asset_type" not in columns:
        return Decimal("0.00")

    row = connection.execute(
        """
        SELECT COALESCE(SUM(amount), 0)
        FROM creator_earnings
        WHERE creator_id = ?
          AND status = 'Completed'
          AND UPPER(COALESCE(asset_type, 'FIAT')) = 'CRYPTO'
          AND UPPER(currency) = ?
        """,
        (creator_id, asset_code.upper()),
    ).fetchone()

    return normalize_money(row[0] if row else 0)


def get_reserved_withdrawal(asset_type, asset_code):
    columns = get_columns("creator_withdrawals")

    asset_expression = (
        "COALESCE(asset_type, 'FIAT')"
        if "asset_type" in columns
        else "'FIAT'"
    )

    code_expression = (
        "UPPER(COALESCE(asset_code, currency))"
        if "asset_code" in columns
        else "UPPER(currency)"
    )

    row = connection.execute(
        f"""
        SELECT COALESCE(SUM(amount), 0)
        FROM creator_withdrawals
        WHERE user_id = ?
          AND status IN ('Pending', 'Processing')
          AND UPPER({asset_expression}) = ?
          AND {code_expression} = ?
        """,
        (
            user_id,
            asset_type.upper(),
            asset_code.upper(),
        ),
    ).fetchone()

    return normalize_money(row[0] if row else 0)


def get_completed_withdrawal(asset_type, asset_code):
    columns = get_columns("creator_withdrawals")

    asset_expression = (
        "COALESCE(asset_type, 'FIAT')"
        if "asset_type" in columns
        else "'FIAT'"
    )

    code_expression = (
        "UPPER(COALESCE(asset_code, currency))"
        if "asset_code" in columns
        else "UPPER(currency)"
    )

    row = connection.execute(
        f"""
        SELECT COALESCE(SUM(amount), 0)
        FROM creator_withdrawals
        WHERE user_id = ?
          AND status = 'Completed'
          AND UPPER({asset_expression}) = ?
          AND {code_expression} = ?
        """,
        (
            user_id,
            asset_type.upper(),
            asset_code.upper(),
        ),
    ).fetchone()

    return normalize_money(row[0] if row else 0)


def get_withdrawals():
    columns = get_columns("creator_withdrawals")

    ref_expression = (
        "withdrawal_reference"
        if "withdrawal_reference" in columns
        else "'LG-WD-UNKNOWN'"
    )

    amount_expression = (
        "amount"
        if "amount" in columns
        else "0"
    )

    currency_expression = (
        "currency"
        if "currency" in columns
        else "'USD'"
    )

    payout_method_expression = (
        "payout_method"
        if "payout_method" in columns
        else "''"
    )

    if "destination" in columns and "payout_details" in columns:
        destination_expression = (
            "COALESCE(NULLIF(destination, ''), payout_details, '')"
        )
    elif "destination" in columns:
        destination_expression = "COALESCE(destination, '')"
    elif "payout_details" in columns:
        destination_expression = "COALESCE(payout_details, '')"
    else:
        destination_expression = "''"

    status_expression = (
        "status"
        if "status" in columns
        else "'Pending'"
    )

    notes_expression = (
        "notes"
        if "notes" in columns
        else "''"
    )

    time_expression = (
        "COALESCE(requested_at, created_at, '')"
        if ("requested_at" in columns and "created_at" in columns)
        else (
            "COALESCE(requested_at, '')"
            if "requested_at" in columns
            else (
                "COALESCE(created_at, '')"
                if "created_at" in columns
                else "''"
            )
        )
    )

    asset_expression = (
        "COALESCE(asset_type, 'FIAT')"
        if "asset_type" in columns
        else "'FIAT'"
    )

    asset_code_expression = (
        "COALESCE(asset_code, currency)"
        if "asset_code" in columns
        else "currency"
    )

    network_expression = (
        "COALESCE(network, '')"
        if "network" in columns
        else "''"
    )

    transaction_expression = (
        "COALESCE(transaction_reference, '')"
        if "transaction_reference" in columns
        else "''"
    )

    processed_expression = (
        "processed_at"
        if "processed_at" in columns
        else "NULL"
    )

    fee_expression = (
        "COALESCE(fee_amount, platform_fee, 0.0)"
        if ("fee_amount" in columns or "platform_fee" in columns)
        else "0.0"
    )

    net_expression = (
        "COALESCE(net_amount, amount, 0.0)"
        if "net_amount" in columns
        else amount_expression
    )

    return connection.execute(
        f"""
        SELECT
            {ref_expression},
            {amount_expression},
            {currency_expression},
            {payout_method_expression},
            {destination_expression},
            {status_expression},
            {notes_expression},
            {time_expression},
            {asset_expression},
            {asset_code_expression},
            {network_expression},
            {transaction_expression},
            {processed_expression},
            {fee_expression},
            {net_expression}
        FROM creator_withdrawals
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (user_id,),
    ).fetchall()


def create_withdrawal(
    amount,
    asset_type,
    asset_code,
    payout_method,
    destination,
    notes,
    network,
    receiving_account_id,
    fee_amount=0.0,
    platform_fee=0.0,
    gateway_fee=0.0,
    net_amount=0.0,
):
    reference = (
        "LG-WD-"
        + uuid.uuid4().hex[:12].upper()
    )

    requested_at = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    table_info = get_table_info("creator_withdrawals")
    columns = set(table_info.keys())

    payload = {}

    if "withdrawal_reference" in columns:
        payload["withdrawal_reference"] = reference
    if "user_id" in columns:
        payload["user_id"] = user_id
    if "receiving_account_id" in columns:
        payload["receiving_account_id"] = receiving_account_id
    if "amount" in columns:
        payload["amount"] = float(amount)
    if "gross_amount" in columns:
        payload["gross_amount"] = float(amount)
    if "fee_amount" in columns:
        payload["fee_amount"] = float(fee_amount)
    if "platform_fee" in columns:
        payload["platform_fee"] = float(platform_fee)
    if "gateway_fee" in columns:
        payload["gateway_fee"] = float(gateway_fee)
    if "net_amount" in columns:
        payload["net_amount"] = float(net_amount if net_amount > 0 else (float(amount) - float(fee_amount)))
    if "currency" in columns:
        payload["currency"] = asset_code
    if "payout_method" in columns:
        payload["payout_method"] = payout_method
    if "destination" in columns:
        payload["destination"] = destination
    if "payout_details" in columns:
        payload["payout_details"] = destination
    if "status" in columns:
        payload["status"] = "Pending"
    if "notes" in columns:
        payload["notes"] = notes
    if "requested_at" in columns:
        payload["requested_at"] = requested_at
    if "created_at" in columns:
        payload["created_at"] = requested_at
    if "asset_type" in columns:
        payload["asset_type"] = asset_type
    if "asset_code" in columns:
        payload["asset_code"] = asset_code
    if "network" in columns:
        payload["network"] = network
    if "transaction_reference" in columns:
        payload["transaction_reference"] = ""

    # Fallback to satisfy any remaining NOT NULL column without default value
    for col_name, info in table_info.items():
        if info["pk"]:
            continue
        if info["notnull"] and info["dflt_value"] is None and col_name not in payload:
            col_type = info["type"]
            if any(t in col_type for t in ["INT", "REAL", "FLOA", "NUM", "DOUB"]):
                payload[col_name] = 0
            else:
                payload[col_name] = ""

    col_names = list(payload.keys())
    placeholders = ", ".join(["?"] * len(col_names))
    sql = f"INSERT INTO creator_withdrawals ({', '.join(col_names)}) VALUES ({placeholders})"
    values = [payload[c] for c in col_names]

    connection.execute(sql, values)
    connection.commit()

    return reference


# ============================================================
# DATABASE SETUP
# ============================================================

try:
    ensure_withdrawal_compatibility()
except Exception as exc:
    connection.close()
    st.error(
        f"Withdrawal database setup failed: {exc}"
    )
    st.stop()


# ============================================================
# CREATOR ACCOUNT
# ============================================================

creator = get_creator()

if not creator:
    st.title("💸 Creator Withdrawal")
    st.info(
        "You need an active Creator Account before "
        "you can create a withdrawal request."
    )
    st.write(
        "Please open **Creator Earnings** and activate "
        "your Creator Account first."
    )
    connection.close()
    st.stop()


creator_id = creator[0]
creator_name = str(creator[1] or "Creator")
creator_status = str(
    creator[2] or "Inactive"
)
creator_currency = str(
    creator[4] or user_currency
).upper()

if creator_status.lower() != "active":
    st.title("💸 Creator Withdrawal")
    st.warning(
        "Your Creator Account is not currently active."
    )
    connection.close()
    st.stop()


# ============================================================
# RECEIVING ACCOUNT
# ============================================================

receiving_accounts = get_receiving_accounts()

if not receiving_accounts:
    st.title("💸 Creator Withdrawal")
    st.warning(
        "Your Creator Receiving Account could not be found."
    )
    st.info(
        "Open **Creator Receiving Account** first "
        "to create your receiving account."
    )
    connection.close()
    st.stop()


# ============================================================
# PAGE HEADER
# ============================================================

st.title("💸 Creator Withdrawal / Payout")
st.caption(
    "Multi-currency creator withdrawal system for LifeGrid."
)

st.info(
    "🛠️ Development Mode: withdrawal requests are recorded "
    "for testing. No real bank, mobile-money, or crypto "
    "transfer is performed yet."
)


# ============================================================
# RECEIVING ACCOUNT SUMMARY
# ============================================================

st.subheader("🏦 Creator Receiving Account")

if len(receiving_accounts) == 1:
    selected_account = receiving_accounts[0]
else:
    def format_acc_label(acc):
        cur = str(acc[3] or creator_currency).upper()
        rec_id = str(acc[2])
        status = str(acc[4] or "Active")
        verif = str(acc[5] or "Pending")
        return f"{rec_id} — {cur} (Status: {status} | Verification: {verif})"

    selected_account = st.selectbox(
        "Select Receiving Account / Currency",
        options=receiving_accounts,
        format_func=format_acc_label,
    )

receiving_account_id = selected_account[0]
receiving_id = str(selected_account[2])
receiving_currency = str(
    selected_account[3] or creator_currency
).upper()
receiving_status = str(
    selected_account[4] or "Active"
)
verification_status = str(
    selected_account[5] or "Pending"
)

info1, info2, info3, info4 = st.columns(4)

with info1:
    st.metric(
        "Receiving Account",
        receiving_id,
    )

with info2:
    st.metric(
        "Currency",
        receiving_currency,
    )

with info3:
    st.metric(
        "Account Status",
        receiving_status,
    )

with info4:
    st.metric(
        "Verification",
        verification_status,
    )

st.write(f"**Creator:** {creator_name}")


# ============================================================
# ASSET BALANCE SELECTION
# ============================================================

st.divider()
st.subheader("💰 Available Creator Assets")

asset_type = st.radio(
    "Asset Type",
    ["FIAT", "CRYPTO"],
    horizontal=True,
)

if asset_type == "FIAT":
    asset_code = receiving_currency

    completed_balance = get_completed_fiat_earnings(
        asset_code
    )

    reserved_balance = get_reserved_withdrawal(
        "FIAT",
        asset_code,
    )

    completed_withdrawals = get_completed_withdrawal(
        "FIAT",
        asset_code,
    )

    available_balance = max(
        Decimal("0.00"),
        completed_balance
        - reserved_balance
        - completed_withdrawals,
    )

    st.caption(
        "Fiat balance is kept separately by currency. "
        "LifeGrid does not silently convert one fiat currency "
        "into another."
    )

else:
    crypto_options = [
        "BTC",
        "ETH",
        "USDT",
        "USDC",
    ]

    asset_code = st.selectbox(
        "Cryptocurrency",
        crypto_options,
    )

    completed_balance = get_completed_crypto_earnings(
        asset_code
    )

    reserved_balance = get_reserved_withdrawal(
        "CRYPTO",
        asset_code,
    )

    completed_withdrawals = get_completed_withdrawal(
        "CRYPTO",
        asset_code,
    )

    available_balance = max(
        Decimal("0.00"),
        completed_balance
        - reserved_balance
        - completed_withdrawals,
    )

    st.caption(
        "Crypto withdrawals are architecture-ready but "
        "remain disabled for real settlement until a "
        "supported crypto payment provider is integrated."
    )


bal1, bal2, bal3, bal4 = st.columns(4)

with bal1:
    st.metric(
        "Completed Earnings",
        f"{asset_code} {completed_balance:,.2f}",
    )

with bal2:
    st.metric(
        "Pending / Processing",
        f"{asset_code} {reserved_balance:,.2f}",
    )

with bal3:
    st.metric(
        "Completed Withdrawals",
        f"{asset_code} {completed_withdrawals:,.2f}",
    )

with bal4:
    st.metric(
        "Available",
        f"{asset_code} {available_balance:,.2f}",
    )


# ============================================================
# WITHDRAWAL REQUEST
# ============================================================

st.divider()
st.subheader("📝 Create Withdrawal Request")

# Always accessible Dev Mode test balance tool
with st.expander("🛠️ Development: Add Test Balance / Seed Funds", expanded=(available_balance <= Decimal("0.00"))):
    st.caption(
        f"Since you are in Development Mode, you can add test completed earnings for **{asset_code}** "
        "at any time to test both standard and high-limit KYC withdrawals:"
    )
    if asset_code == "NGN":
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("➕ Add ₦50,000", use_container_width=True, key="dev_add_50k_ngn"):
                if add_test_creator_earnings(creator_id, 50000.0, "NGN", "FIAT"):
                    st.success("Added ₦50,000 NGN!")
                    st.rerun()
        with c2:
            if st.button("➕ Add ₦1,000,000 (Tier 1 Max)", use_container_width=True, key="dev_add_1m_ngn"):
                if add_test_creator_earnings(creator_id, 1000000.0, "NGN", "FIAT"):
                    st.success("Added ₦1,000,000 NGN!")
                    st.rerun()
        with c3:
            if st.button("➕ Add ₦10,000,000 (KYC Test)", use_container_width=True, key="dev_add_10m_ngn"):
                if add_test_creator_earnings(creator_id, 10000000.0, "NGN", "FIAT"):
                    st.success("Added ₦10,000,000 NGN!")
                    st.rerun()
    elif asset_code == "USD":
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("➕ Add $500", use_container_width=True, key="dev_add_500_usd"):
                if add_test_creator_earnings(creator_id, 500.0, "USD", "FIAT"):
                    st.success("Added $500 USD!")
                    st.rerun()
        with c2:
            if st.button("➕ Add $5,000 (Tier 1 Max)", use_container_width=True, key="dev_add_5k_usd"):
                if add_test_creator_earnings(creator_id, 5000.0, "USD", "FIAT"):
                    st.success("Added $5,000 USD!")
                    st.rerun()
        with c3:
            if st.button("➕ Add $25,000 (KYC Test)", use_container_width=True, key="dev_add_25k_usd"):
                if add_test_creator_earnings(creator_id, 25000.0, "USD", "FIAT"):
                    st.success("Added $25,000 USD!")
                    st.rerun()
    else:
        c1, c2 = st.columns(2)
        with c1:
            if st.button(f"➕ Add 1.0 {asset_code}", use_container_width=True, key=f"dev_add_1_{asset_code}"):
                if add_test_creator_earnings(creator_id, 1.0, asset_code, asset_type):
                    st.success(f"Added 1.0 {asset_code}!")
                    st.rerun()
        with c2:
            if st.button(f"➕ Add 10.0 {asset_code}", use_container_width=True, key=f"dev_add_10_{asset_code}"):
                if add_test_creator_earnings(creator_id, 10.0, asset_code, asset_type):
                    st.success(f"Added 10.0 {asset_code}!")
                    st.rerun()

    custom_c1, custom_c2 = st.columns([3, 1])
    with custom_c1:
        default_seed = 500000.0 if asset_code == "NGN" else 2000.0
        step_seed = 50000.0 if asset_code == "NGN" else 500.0
        custom_seed = st.number_input(
            f"Or enter custom test balance to deposit ({asset_code}):",
            min_value=1.0,
            max_value=100000000.0,
            value=default_seed,
            step=step_seed,
            key=f"custom_seed_{asset_code}",
        )
    with custom_c2:
        st.write("")
        st.write("")
        if st.button("➕ Deposit Funds", use_container_width=True, key=f"btn_custom_seed_{asset_code}"):
            if add_test_creator_earnings(creator_id, custom_seed, asset_code, asset_type):
                st.success(f"Added {asset_code} {custom_seed:,.2f} balance!")
                st.rerun()

if available_balance <= Decimal("0.00"):
    st.warning(
        f"There is currently no available {asset_code} balance for withdrawal. "
        "Use the Test Balance tool above to add test funds."
    )
else:
    st.write(
        f"Maximum available: "
        f"**{asset_code} {available_balance:,.2f}**"
    )

    payout_method_options = [
        "Bank Account",
        "Mobile Money",
        "LifeGrid Internal Account",
    ]

    if asset_type == "CRYPTO":
        payout_method_options = [
            "Crypto Wallet",
            "LifeGrid Internal Account",
        ]

    payout_method = st.selectbox(
        "Payout Method",
        payout_method_options,
    )

    network = ""

    destination = ""

    if asset_type == "FIAT":
        if payout_method == "Bank Account":
            if receiving_currency == "NGN":
                if is_flutterwave_configured and not is_flutterwave_configured():
                    st.info(
                        "ℹ️ **Flutterwave Demo Mode:** API key not set in `.streamlit/secrets.toml`. "
                        "Displaying local Nigerian banks with simulated test verification."
                    )

                banks = []
                if get_supported_banks:
                    try:
                        banks = get_supported_banks(country="NG") or []
                    except Exception:
                        banks = []

                if banks:
                    bank_dict = {b["name"]: b["code"] for b in banks if "name" in b and "code" in b}
                    bank_names = sorted(list(bank_dict.keys()))

                    selected_bank_name = st.selectbox(
                        "Select Nigerian Bank",
                        bank_names,
                    )
                    selected_bank_code = bank_dict[selected_bank_name]

                    col_acc, col_btn = st.columns([3, 1])
                    with col_acc:
                        account_number = st.text_input(
                            "Account Number (10 digits)",
                            max_chars=10,
                            placeholder="e.g. 0123456789",
                        )
                    with col_btn:
                        st.write("")
                        st.write("")
                        verify_clicked = st.button("🔍 Verify", use_container_width=True)

                    clean_account = account_number.strip()
                    cache_key = f"flw_{selected_bank_code}_{clean_account}"
                    attempt_key = f"flw_att_{selected_bank_code}_{clean_account}"
                    error_key = f"flw_err_{selected_bank_code}_{clean_account}"

                    verified_name = st.session_state.get(cache_key, "")
                    error_msg = st.session_state.get(error_key, "")

                    # Run lookup only if explicitly requested or on first 10-digit entry for this bank+account
                    should_verify = (
                        (verify_clicked or (len(clean_account) == 10 and attempt_key not in st.session_state))
                        and not verified_name
                        and len(clean_account) == 10
                    )

                    if should_verify:
                        st.session_state[attempt_key] = True
                        with st.spinner("Verifying account name with Flutterwave..."):
                            if resolve_bank_account:
                                res = resolve_bank_account(
                                    clean_account,
                                    selected_bank_code,
                                    fallback_name=creator_name,
                                )
                                if res.get("success"):
                                    verified_name = res.get("account_name", "")
                                    st.session_state[cache_key] = verified_name
                                    st.session_state.pop(error_key, None)
                                    error_msg = ""
                                else:
                                    error_msg = res.get("message", "Could not verify account name.")
                                    st.session_state[error_key] = error_msg
                            elif verify_bank_account:
                                resolved_name = verify_bank_account(
                                    clean_account,
                                    selected_bank_code,
                                    fallback_name=creator_name,
                                )
                                if resolved_name:
                                    verified_name = resolved_name
                                    st.session_state[cache_key] = resolved_name
                                    st.session_state.pop(error_key, None)
                                    error_msg = ""
                                else:
                                    error_msg = "Could not verify account name. In Test Mode, Flutterwave only resolves sandbox accounts."
                                    st.session_state[error_key] = error_msg

                    if verified_name:
                        st.success(f"✅ Verified Account Name: **{verified_name}**")
                        destination = f"{selected_bank_name} | {clean_account} | {verified_name}"
                    else:
                        if error_msg and len(clean_account) == 10:
                            st.warning(f"⚠️ {error_msg}")
                            st.caption(
                                "💡 **Flutterwave Test Mode:** Sandbox test keys only resolve official test accounts "
                                "(e.g., Bank: **Access Bank**, Account: ). Real accounts resolve once production keys are active."
                            )
                            if st.button("🧪 Use Creator Name for Testing", key="use_fallback_acc_name"):
                                verified_name = f"{creator_name} (Test Verified)"
                                st.session_state[cache_key] = verified_name
                                st.session_state.pop(error_key, None)
                                st.rerun()

                        destination = f"{selected_bank_name} | {clean_account}" if clean_account else ""
                else:
                    destination = st.text_input(
                        "Nigerian Bank Account Details",
                        placeholder="Bank Name, 10-digit Account Number, Account Name",
                    )
            elif receiving_currency == "USD":
                st.caption("USD Payout / Domiciliary Wire Transfer Details")
                usd_col1, usd_col2 = st.columns(2)
                with usd_col1:
                    usd_bank = st.text_input("Bank Name", placeholder="e.g. GTBank USD Domiciliary, Access Bank, or US Bank")
                    usd_acc = st.text_input("Account Number / IBAN", placeholder="e.g. 0123456789 or US12...")
                with usd_col2:
                    usd_swift = st.text_input("SWIFT / BIC Code", placeholder="e.g. GTBINGLAXXX")
                    usd_beneficiary = st.text_input("Beneficiary Full Name", value=creator_name)

                parts = [p.strip() for p in [usd_bank, usd_acc, f"SWIFT: {usd_swift}" if usd_swift else "", usd_beneficiary] if p.strip()]
                destination = " | ".join(parts)
            else:
                destination = st.text_input(
                    f"{receiving_currency} Bank Account Details",
                    placeholder="Bank Name, Account Number / IBAN, SWIFT Code, Beneficiary Name",
                )

        elif payout_method == "Mobile Money":
            destination = st.text_input(
                "Mobile Money Details",
                placeholder="Network Provider, Phone Number, Registered Name",
            )
        else:
            destination = st.text_input(
                "LifeGrid Internal Account",
                placeholder="Enter LifeGrid username or account reference",
            )
    else:
        if payout_method == "Crypto Wallet":
            network_options = {
                "BTC": ["Bitcoin"],
                "ETH": ["Ethereum"],
                "USDT": [
                    "Ethereum",
                    "Tron",
                    "BSC",
                ],
                "USDC": [
                    "Ethereum",
                    "Solana",
                    "BSC",
                ],
            }

            network = st.selectbox(
                "Blockchain Network",
                network_options.get(
                    asset_code,
                    ["Other"],
                ),
            )

            destination = st.text_input(
                "Cryptocurrency Wallet Address",
                placeholder="Enter your wallet address for this network",
            )
        else:
            destination = st.text_input(
                "LifeGrid Internal Account",
                placeholder="Enter LifeGrid username or account reference",
            )

    # KYC status detection & Development Simulator
    is_kyc_detected = check_creator_kyc_verified(user_id, verification_status)

    kyc_col1, kyc_col2 = st.columns([3, 2])
    with kyc_col1:
        if is_kyc_detected:
            st.success("🎖️ **Account Tier:** Tier 2 (KYC Verified) — Higher limits unlocked!")
            is_kyc_active = True
        else:
            st.info("ℹ️ **Account Tier:** Tier 1 (Standard). Complete full KYC to unlock up to ₦25,000,000 / $100,000 per request.")
            is_kyc_active = False

    with kyc_col2:
        dev_kyc_override = st.checkbox(
            "🧪 Dev: Simulate KYC Verified Tier",
            value=is_kyc_detected,
            help="Simulates a verified KYC status so you can test high-value payouts immediately.",
        )
        if dev_kyc_override:
            is_kyc_active = True

    policy = get_policy_limits(asset_code, is_kyc_verified=is_kyc_active)
    min_limit = policy["min"]
    max_limit = policy["max"]
    daily_cap = policy["daily_cap"]
    max_daily_requests = policy["max_daily_requests"]
    tier_label = policy["tier_label"]
    sym = policy["symbol"]

    daily_count, daily_total = get_daily_withdrawal_usage(user_id, asset_type, asset_code)
    daily_remaining = max(Decimal("0.00"), daily_cap - daily_total)

    with st.expander(f"🛡️ Payout Policy: {tier_label}", expanded=True):
        p_col1, p_col2, p_col3 = st.columns(3)
        with p_col1:
            st.caption(f"**Min per Request:** {sym}{min_limit:,.2f}")
        with p_col2:
            st.caption(f"**Max per Request:** {sym}{max_limit:,.2f}")
        with p_col3:
            st.caption(f"**24h Limit Remaining:** {sym}{daily_remaining:,.2f}")
        if daily_count > 0:
            st.caption(f"ℹ️ Past 24 hours: **{daily_count}** request(s) totaling **{sym}{daily_total:,.2f}**")

    amount_text = st.text_input(
        f"Withdrawal Amount ({asset_code})",
        placeholder="0.00",
    )

    # Live Fee Preview
    try:
        preview_gross = Decimal(amount_text.replace(",", "").strip()).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        preview_gross = Decimal("0.00")

    fee_preview = calculate_withdrawal_fee(preview_gross, asset_code)

    if preview_gross > Decimal("0.00"):
        with st.container(border=True):
            st.markdown("##### 🧾 Payout & Platform Fee Breakdown")
            fcol1, fcol2, fcol3 = st.columns(3)
            with fcol1:
                st.metric("Requested (Gross)", f"{asset_code} {preview_gross:,.2f}", help="Total amount deducted from your creator balance.")
            with fcol2:
                st.metric(
                    f"Platform Fee ({fee_preview['platform_pct_str']} + Fixed)",
                    f"-{asset_code} {fee_preview['total_fee']:,.2f}",
                    help=f"LifeGrid {fee_preview['platform_pct_str']} handling fee ({asset_code} {fee_preview['platform_fee']:,.2f}) + gateway transfer fee ({asset_code} {fee_preview['gateway_fee']:,.2f})."
                )
            with fcol3:
                st.metric("Net Disbursed to Bank", f"{asset_code} {fee_preview['net_amount']:,.2f}", help="Exact funds disbursed to your receiving bank account.")
    else:
        st.caption(
            f"ℹ️ Platform charges: **{fee_preview['platform_pct_str']}** handling fee + "
            f"**{asset_code} {fee_preview['gateway_fee_str']}** gateway transfer charge."
        )

    notes = st.text_area(
        "Notes (Optional)",
        placeholder=(
            "Optional note about this withdrawal request."
        ),
    )

    with st.container(border=True):
        st.markdown("##### 🔐 Security Confirmation")
        st.caption("Protecting your earnings: verify your credentials before submitting.")
        sec_col1, sec_col2 = st.columns([2, 1])
        with sec_col1:
            security_password = st.text_input(
                "Account Password / PIN",
                type="password",
                placeholder="Enter password to confirm",
                key="payout_security_password",
            )
        with sec_col2:
            st.write("")
            st.write("")
            bypass_security = st.checkbox(
                "🧪 Dev Bypass",
                value=True,
                help="Skip password verification during development testing.",
            )

    submit_request = st.button(
        "💸 Submit Withdrawal Request",
        use_container_width=True,
    )

    if submit_request:
        try:
            amount = Decimal(
                amount_text.replace(",", "").strip()
            ).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
        except (InvalidOperation, ValueError):
            amount = Decimal("0.00")

        if amount <= Decimal("0.00"):
            st.error(
                "Please enter a valid withdrawal amount."
            )

        elif amount > available_balance:
            st.error(
                f"The requested amount ({asset_code} {amount:,.2f}) is greater "
                f"than your available balance ({asset_code} {available_balance:,.2f})."
            )
            st.info(
                f"💡 Note: Your current available balance is **{asset_code} {available_balance:,.2f}**. "
                f"To test high-value KYC withdrawals (e.g. up to {sym}{max_limit:,.2f}), use the "
                f"'🛠️ Development: Add Test Balance / Seed Funds' tool above to top up your test balance first."
            )

        elif amount < min_limit:
            st.error(
                f"Minimum withdrawal amount for {asset_code} is {sym}{min_limit:,.2f}."
            )

        elif fee_preview['net_amount'] <= Decimal("0.00"):
            st.error(
                f"The requested amount ({asset_code} {amount:,.2f}) must be higher than the "
                f"platform processing fee ({asset_code} {fee_preview['total_fee']:,.2f})."
            )

        elif amount > max_limit:
            st.error(
                f"Maximum withdrawal amount per request for {asset_code} is {sym}{max_limit:,.2f}."
            )

        elif daily_count >= max_daily_requests:
            st.error(
                f"Daily request limit reached: maximum {max_daily_requests} requests per 24 hours."
            )

        elif daily_total + amount > daily_cap:
            st.error(
                f"Daily velocity limit exceeded. Remaining 24h allowance is {sym}{daily_remaining:,.2f}."
            )

        elif not destination.strip():
            st.error(
                "Please enter the payout destination."
            )

        elif not bypass_security and not verify_account_password(user_id, security_password):
            st.error(
                "❌ Security verification failed: invalid account password or PIN."
            )

        else:
            final_fee_info = calculate_withdrawal_fee(amount, asset_code)
            reference = create_withdrawal(
                amount=amount,
                asset_type=asset_type,
                asset_code=asset_code,
                payout_method=payout_method,
                destination=destination.strip(),
                notes=notes.strip(),
                network=network,
                receiving_account_id=(
                    receiving_account_id
                    if asset_type == "FIAT"
                    else None
                ),
                fee_amount=float(final_fee_info["total_fee"]),
                platform_fee=float(final_fee_info["platform_fee"]),
                gateway_fee=float(final_fee_info["gateway_fee"]),
                net_amount=float(final_fee_info["net_amount"]),
            )

            st.success(
                f"✅ Withdrawal request submitted successfully! Reference: **{reference}**"
            )
            st.info(
                f"💸 **Gross Deducted:** {asset_code} {amount:,.2f}  |  "
                f"🏢 **Platform Charge:** -{asset_code} {final_fee_info['total_fee']:,.2f}  |  "
                f"🏦 **Net Payout to Bank:** {asset_code} {final_fee_info['net_amount']:,.2f}"
            )
            st.write(
                "**Status:** Pending"
            )

            st.info(
                "This is a simulated withdrawal request. "
                "No real payment has been processed."
            )

            st.rerun()


# ============================================================
# WITHDRAWAL HISTORY
# ============================================================

st.divider()
st.subheader("📜 Withdrawal History")

withdrawals = get_withdrawals()

if not withdrawals:
    st.info(
        "No withdrawal requests have been created yet."
    )
else:
    # Export Payout Statement
    csv_buffer = io.StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerow([
        "Withdrawal Reference",
        "Asset Code",
        "Gross Amount",
        "Platform Fee",
        "Net Payout",
        "Asset Type",
        "Payout Method",
        "Destination / Account",
        "Status",
        "Requested At",
        "Processed At",
        "Transaction Reference",
        "Notes",
    ])
    for w in withdrawals:
        fee_val = float(w[13] or 0.0) if len(w) > 13 else 0.0
        net_val = float(w[14] or w[1]) if len(w) > 14 else float(w[1])
        writer.writerow([
            w[0],
            w[9],
            f"{float(normalize_money(w[1])):.2f}",
            f"{fee_val:.2f}",
            f"{net_val:.2f}",
            w[8],
            w[3],
            w[4],
            w[5],
            w[7],
            w[12] or "",
            w[11] or "",
            w[6] or "",
        ])
    csv_text = csv_buffer.getvalue()

    st.download_button(
        label="📥 Download Payout Statement (CSV)",
        data=csv_text,
        file_name=f"lifegrid_payout_statement_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    for withdrawal in withdrawals:
        reference = withdrawal[0]
        amount = withdrawal[1]
        transaction_currency = withdrawal[2]
        method = withdrawal[3]
        destination_value = withdrawal[4]
        status = withdrawal[5]
        notes_value = withdrawal[6]
        requested_at = withdrawal[7]
        history_asset_type = withdrawal[8]
        history_asset_code = withdrawal[9]
        history_network = withdrawal[10]
        transaction_reference = withdrawal[11]
        processed_at = withdrawal[12]
        history_fee = float(withdrawal[13] or 0.0) if len(withdrawal) > 13 else 0.0
        history_net = float(withdrawal[14] or amount) if len(withdrawal) > 14 else float(amount)

        amount_decimal = normalize_money(amount)

        with st.container(border=True):
            left, right = st.columns([4, 1])

            with left:
                st.write(
                    "**Creator Withdrawal Request**"
                )

                st.write(
                    f"**Gross Amount:** "
                    f"{str(history_asset_code).upper()} "
                    f"{amount_decimal:,.2f}"
                )
                if history_fee > 0:
                    st.caption(
                        f"Platform Charge: -{str(history_asset_code).upper()} {history_fee:,.2f}  |  "
                        f"**Net Payout:** {str(history_asset_code).upper()} {history_net:,.2f}"
                    )

                st.write(
                    f"**Asset Type:** "
                    f"{str(history_asset_type).upper()}"
                )

                st.write(
                    f"**Payout Method:** {method}"
                )

                if history_network:
                    st.write(
                        f"**Network:** {history_network}"
                    )

                if destination_value:
                    if history_asset_type == "CRYPTO":
                        display_destination = (
                            destination_value
                            if len(destination_value) <= 16
                            else destination_value[:8]
                            + "..."
                            + destination_value[-6:]
                        )
                    else:
                        display_destination = destination_value

                    st.write(
                        f"**Destination:** "
                        f"{display_destination}"
                    )

                st.caption(
                    f"Withdrawal Reference: {reference}"
                )

                if transaction_reference:
                    st.caption(
                        f"Transaction Reference: "
                        f"{transaction_reference}"
                    )

                st.caption(
                    f"Requested: {requested_at}"
                )

                if processed_at:
                    st.caption(
                        f"Processed: {processed_at}"
                    )

                if notes_value:
                    st.caption(
                        f"Note: {notes_value}"
                    )

            with right:
                if status == "Pending":
                    st.warning("Pending")
                elif status == "Processing":
                    st.info("Processing")
                elif status == "Completed":
                    st.success("Completed")
                elif status == "Rejected":
                    st.error("Rejected")
                else:
                    st.write(status)


# ============================================================
# REAL PAYMENT ROADMAP
# ============================================================

st.divider()
st.subheader("🌍 Real Payment Roadmap")

roadmap1, roadmap2, roadmap3 = st.columns(3)

with roadmap1:
    st.markdown("### 💳 Fiat Payments")
    st.write(
        "Real fiat deposits will use a payment provider "
        "with the transaction currency stored on every payment."
    )
    st.write(
        "Supported provider currencies will be enabled "
        "according to the provider and LifeGrid account."
    )

with roadmap2:
    st.markdown("### 🏦 Fiat Payouts")
    st.write(
        "Production bank/mobile-money payouts will use "
        "verified recipients and provider transfer APIs."
    )

with roadmap3:
    st.markdown("### ₿ Crypto")
    st.write(
        "Crypto will use a separate supported crypto "
        "payment provider. Asset, network, wallet address, "
        "transaction hash and status will be recorded."
    )


# ============================================================
# DEVELOPMENT RULES
# ============================================================

st.divider()

with st.expander("ℹ️ Development Mode Rules"):
    st.write(
        "• Existing creator_withdrawals records are preserved."
    )
    st.write(
        "• Existing Page 15-compatible columns are preserved."
    )
    st.write(
        "• Optional asset fields are added only when missing."
    )
    st.write(
        "• Fiat balances are separated by currency."
    )
    st.write(
        "• Crypto balances are separated by asset."
    )
    st.write(
        "• LifeGrid does not silently convert currencies."
    )
    st.write(
        "• Every request receives a unique LG-WD reference."
    )
    st.write(
        "• Pending and Processing requests reserve funds."
    )
    st.write(
        "• No real bank transfer is performed."
    )
    st.write(
        "• No real mobile-money transfer is performed."
    )
    st.write(
        "• No real cryptocurrency transfer is performed."
    )
    st.write(
        "• Production payment integration will be added "
        "after the development workflow is tested."
    )


st.divider()
st.caption(
    "LifeGrid Creator Withdrawal • "
    "Your life, your growth, your connections."
)

connection.close()