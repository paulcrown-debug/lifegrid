"""
LifeGrid Crypto Payment & Deposit Gateway Service.
Supports real multi-blockchain crypto deposits (USDT, BTC, ETH, USDC)
via NOWPayments API, with automatic wallet asset settlement in Turso.
Fail-closed architecture: never returns fake addresses in production.
"""

import os
import json
import uuid
import hashlib
import urllib.request
import urllib.error
from datetime import datetime, timezone
from decimal import Decimal

# Try importing Streamlit secrets if running inside Streamlit
try:
    import streamlit as st
    STREAMLIT_SECRETS = st.secrets
except Exception:
    STREAMLIT_SECRETS = {}


def get_secret(key_name, default=""):
    """Fetch key from environment variables or Streamlit secrets."""
    val = os.environ.get(key_name)
    if val:
        return val.strip()
    if isinstance(STREAMLIT_SECRETS, dict) and key_name in STREAMLIT_SECRETS:
        return str(STREAMLIT_SECRETS[key_name]).strip()
    return default


def get_nowpayments_api_key():
    """Retrieve NOWPayments API key."""
    return (
        get_secret("NOWPAYMENTS_API_KEY")
        or get_secret("NOW_PAYMENTS_API_KEY")
        or get_secret("CRYPTO_API_KEY")
    )


def is_crypto_gateway_configured():
    """Check if crypto gateway API key is configured with a valid live key."""
    key = get_nowpayments_api_key()
    return bool(key and len(key) >= 15 and not key.startswith("YOUR_"))


def get_crypto_gateway_mode():
    """Returns 'Production' if key is set, else 'Sandbox / Demo'."""
    if is_crypto_gateway_configured():
        return "Production"
    return "Sandbox / Demo"


SUPPORTED_CRYPTO_CURRENCIES = {
    "USDT_TRC20": {
        "asset_code": "USDT",
        "network": "Tron (TRC-20)",
        "pay_currency": "usdttrc20",
        "display_name": "USDT • Tron (TRC-20) — Lowest Fee & Fast",
        "symbol": "USDT",
        "min_deposit": 5.0,
    },
    "USDT_ERC20": {
        "asset_code": "USDT",
        "network": "Ethereum (ERC-20)",
        "pay_currency": "usdterc20",
        "display_name": "USDT • Ethereum (ERC-20)",
        "symbol": "USDT",
        "min_deposit": 10.0,
    },
    "USDC": {
        "asset_code": "USDC",
        "network": "Ethereum (ERC-20)",
        "pay_currency": "usdc",
        "display_name": "USDC • USD Coin",
        "symbol": "USDC",
        "min_deposit": 10.0,
    },
    "BTC": {
        "asset_code": "BTC",
        "network": "Bitcoin",
        "pay_currency": "btc",
        "display_name": "BTC • Bitcoin Network",
        "symbol": "BTC",
        "min_deposit": 0.0002,
    },
    "ETH": {
        "asset_code": "ETH",
        "network": "Ethereum",
        "pay_currency": "eth",
        "display_name": "ETH • Ethereum Network",
        "symbol": "ETH",
        "min_deposit": 0.003,
    },
}


def create_crypto_deposit_order(
    user_id,
    asset_key,
    amount_usd,
    connection,
    description="LifeGrid Crypto Wallet Deposit"
):
    """
    Creates a crypto deposit invoice.
    Calls NOWPayments API when live, or creates a labeled sandbox session.
    Fails closed: never provides mock addresses as real deposit targets.
    """
    config = SUPPORTED_CRYPTO_CURRENCIES.get(asset_key, SUPPORTED_CRYPTO_CURRENCIES["USDT_TRC20"])
    asset_code = config["asset_code"]
    network = config["network"]
    pay_currency = config["pay_currency"]

    ref = f"LG-CRYPTO-{uuid.uuid4().hex[:10].upper()}"
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    api_key = get_nowpayments_api_key()

    if is_crypto_gateway_configured():
        # Live Call to NOWPayments API
        url = "https://api.nowpayments.io/v1/payment"
        payload = {
            "price_amount": float(amount_usd),
            "price_currency": "usd",
            "pay_currency": pay_currency,
            "order_id": ref,
            "order_description": description,
        }
        headers = {
            "x-api-key": api_key,
            "Content-Type": "application/json",
            "User-Agent": "LifeGrid/1.0",
        }
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                deposit_address = data.get("pay_address")
                if not deposit_address:
                    return {"success": False, "error": "Gateway returned response without deposit address."}
                pay_amount = float(data.get("pay_amount") or amount_usd)
                payment_id = str(data.get("payment_id") or "")
                status = str(data.get("payment_status") or "waiting")
        except urllib.error.HTTPError as http_err:
            try:
                err_body = json.loads(http_err.read().decode("utf-8"))
                msg = err_body.get("message") or str(http_err)
            except Exception:
                msg = str(http_err)
            return {"success": False, "error": f"NOWPayments API Error ({http_err.code}): {msg}"}
        except Exception as e:
            # FAIL CLOSED: Do not substitute a fake address
            return {"success": False, "error": f"Crypto payment gateway unreachable: {str(e)}"}
    else:
        # Sandbox / Demo Mode: Explicitly labeled mock address
        deposit_address = f"DEMO-MOCK-ADDRESS-DO-NOT-SEND-FUNDS-{asset_code}"
        pay_amount = float(amount_usd)
        payment_id = f"DEMO-{ref}"
        status = "sandbox_pending"

    # Save to crypto_transactions table
    cursor = connection.cursor()
    cursor.execute(
        """
        INSERT INTO crypto_transactions (
            user_id,
            transaction_type,
            asset_code,
            network,
            amount,
            recipient_user_id,
            recipient_address,
            description,
            status,
            reference,
            created_at
        )
        VALUES (?, 'DEPOSIT', ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            asset_code,
            network,
            pay_amount,
            user_id,
            deposit_address,
            f"{description} (Ref: {ref})",
            status,
            ref,
            now_str,
        ),
    )
    connection.commit()

    return {
        "success": True,
        "reference": ref,
        "payment_id": payment_id,
        "asset_code": asset_code,
        "network": network,
        "pay_amount": pay_amount,
        "deposit_address": deposit_address,
        "status": status,
        "is_demo": not is_crypto_gateway_configured(),
        "mode": get_crypto_gateway_mode(),
    }


def settle_crypto_deposit_to_wallet(user_id, asset_code, network, amount, reference, connection):
    """
    Idempotently credits user's wallet_assets balance and logs to financial_audit_ledger.
    Matches the Turso schema columns exactly.
    """
    cursor = connection.cursor()
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # Check if this reference was already credited
    cursor.execute(
        """
        SELECT id, status FROM crypto_transactions
        WHERE reference = ?
        """,
        (reference,)
    )
    row = cursor.fetchone()
    if row and str(row[1]).lower() == "completed":
        return True, "Deposit was already settled into wallet."

    # Update crypto_transactions status
    cursor.execute(
        """
        UPDATE crypto_transactions
        SET status = 'completed'
        WHERE reference = ?
        """,
        (reference,)
    )

    # Check if wallet_assets record exists
    cursor.execute(
        """
        SELECT id, balance, available_balance FROM wallet_assets
        WHERE user_id = ? AND asset_code = ? AND network = ?
        """,
        (user_id, asset_code, network)
    )
    asset_row = cursor.fetchone()

    new_bal = amount
    if asset_row:
        new_bal = float(asset_row[1] or 0.0) + float(amount)
        cursor.execute(
            """
            UPDATE wallet_assets
            SET balance = balance + ?,
                available_balance = available_balance + ?,
                updated_at = ?
            WHERE id = ?
            """,
            (amount, amount, now_str, asset_row[0])
        )
    else:
        cursor.execute(
            """
            INSERT INTO wallet_assets (
                user_id, asset_type, asset_code, network,
                balance, available_balance, pending_balance, asset_status,
                created_at, updated_at
            )
            VALUES (?, 'CRYPTO', ?, ?, ?, ?, 0.0, 'Active', ?, ?)
            """,
            (user_id, asset_code, network, amount, amount, now_str, now_str)
        )

    # Log to financial_audit_ledger using exact schema
    try:
        ledger_ref = f"LEDGER-CRYPTO-{uuid.uuid4().hex[:8].upper()}"
        prev_hash = "CRYPTO-SETTLE-ROOT"
        entry_raw = f"{ledger_ref}|{user_id}|{reference}|CRYPTO_DEPOSIT|{amount}|{asset_code}|{new_bal}|{prev_hash}"
        entry_hash = hashlib.sha256(entry_raw.encode("utf-8")).hexdigest()

        cursor.execute(
            """
            INSERT INTO financial_audit_ledger (
                ledger_entry_id, user_id, transaction_ref, event_type,
                debit, credit, fee, balance_after, currency,
                entry_hash, prev_hash, created_at
            )
            VALUES (?, ?, ?, 'CRYPTO_DEPOSIT', 0.0, ?, 0.0, ?, ?, ?, ?, ?)
            """,
            (
                ledger_ref,
                user_id,
                reference,
                float(amount),
                float(new_bal),
                asset_code,
                entry_hash,
                prev_hash,
                now_str
            )
        )
    except Exception as audit_err:
        print(f"[AUDIT WARNING] Ledger write error: {audit_err}")

    connection.commit()
    return True, f"Successfully credited {amount} {asset_code} to your LifeGrid wallet!"


def verify_crypto_deposit_status(reference, connection):
    """
    Verifies deposit status with NOWPayments API.
    Only settles after actual provider verification.
    """
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT user_id, asset_code, network, amount, status, recipient_address
        FROM crypto_transactions
        WHERE reference = ?
        """,
        (reference,)
    )
    row = cursor.fetchone()
    if not row:
        return False, "Deposit reference not found."

    user_id, asset_code, network, amount, current_status, recip_addr = row

    if str(current_status).lower() == "completed":
        return True, "Deposit is already completed and credited."

    # If Live NOWPayments Gateway is configured
    if is_crypto_gateway_configured():
        api_key = get_nowpayments_api_key()
        # Find payment by order_id or reference
        url = f"https://api.nowpayments.io/v1/payment/?limit=10&page=0"
        headers = {
            "x-api-key": api_key,
            "User-Agent": "LifeGrid/1.0",
        }
        try:
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                payments = data.get("data", [])
                matching = None
                for p in payments:
                    if p.get("order_id") == reference:
                        matching = p
                        break

                if not matching:
                    return False, "Deposit invoice created; awaiting payment broadcast on the blockchain."

                pay_status = str(matching.get("payment_status", "")).lower()
                if pay_status in ("finished", "confirmed"):
                    return settle_crypto_deposit_to_wallet(user_id, asset_code, network, amount, reference, connection)
                elif pay_status in ("waiting", "partially_paid"):
                    return False, f"Payment detected ({pay_status}); awaiting network confirmation."
                elif pay_status in ("failed", "refunded", "expired"):
                    cursor.execute(
                        "UPDATE crypto_transactions SET status = ? WHERE reference = ?",
                        (pay_status, reference)
                    )
                    connection.commit()
                    return False, f"Payment marked as {pay_status} by NOWPayments."
                else:
                    return False, f"Current blockchain status: {pay_status}"
        except Exception as e:
            return False, f"Unable to reach NOWPayments verification endpoint: {str(e)}"
    else:
        # Sandbox mode
        return False, "In Sandbox mode. Configure NOWPAYMENTS_API_KEY to verify live blockchain payments. For testing balances, use the Development Crypto Balance tool."
