"""LifeGrid Flutterwave service helpers.

Live payment and payout operations fail closed when a valid LIVE secret key is missing.
The Nigerian bank list is an offline display fallback only; account resolution and all
payment verification calls always require the configured live Flutterwave API.
"""

import os
from decimal import Decimal, InvalidOperation
from typing import Any

import requests
import streamlit as st


# Offline bank names are for selection/display only, never proof of account validity.
DEFAULT_NG_BANKS = [
    {"name": "Access Bank", "code": "044"},
    {"name": "Citibank Nigeria", "code": "023"},
    {"name": "Ecobank Nigeria", "code": "050"},
    {"name": "Fidelity Bank", "code": "070"},
    {"name": "First Bank of Nigeria", "code": "011"},
    {"name": "First City Monument Bank (FCMB)", "code": "214"},
    {"name": "Guaranty Trust Bank (GTBank)", "code": "058"},
    {"name": "Heritage Bank", "code": "030"},
    {"name": "Jaiz Bank", "code": "301"},
    {"name": "Keystone Bank", "code": "082"},
    {"name": "Kuda Bank", "code": "50211"},
    {"name": "Moniepoint MFB", "code": "50515"},
    {"name": "OPay Digital Services (Paycom)", "code": "999992"},
    {"name": "PalmPay", "code": "999991"},
    {"name": "Polaris Bank", "code": "076"},
    {"name": "Providus Bank", "code": "101"},
    {"name": "Stanbic IBTC Bank", "code": "221"},
    {"name": "Standard Chartered Bank", "code": "068"},
    {"name": "Sterling Bank", "code": "232"},
    {"name": "Union Bank of Nigeria", "code": "032"},
    {"name": "United Bank for Africa (UBA)", "code": "033"},
    {"name": "Unity Bank", "code": "215"},
    {"name": "Wema Bank", "code": "035"},
    {"name": "Zenith Bank", "code": "057"},
]


def _read_secret(name: str, nested_name: str = "") -> str:
    """Read an environment value or Streamlit secret without exposing it."""
    env_value = os.environ.get(name, "")
    if isinstance(env_value, str) and env_value.strip():
        return env_value.strip()

    try:
        value = st.secrets.get(name, "")
        if isinstance(value, str) and value.strip():
            return value.strip()
        section = st.secrets.get("flutterwave")
        if section is not None and hasattr(section, "get"):
            value = section.get(nested_name or name.lower()) or section.get(name)
            if isinstance(value, str) and value.strip():
                return value.strip()
    except Exception:
        pass
    return ""


def _get_secret_key() -> str:
    return _read_secret("FLUTTERWAVE_SECRET_KEY", "secret_key")


def _get_base_url() -> str:
    return (_read_secret("FLUTTERWAVE_BASE_URL", "base_url") or "https://api.flutterwave.com/v3").rstrip("/")


def _get_redirect_url() -> str:
    return _read_secret("FLUTTERWAVE_REDIRECT_URL", "redirect_url")


def is_flutterwave_configured() -> bool:
    """True only for a plausible live Flutterwave secret key, not a test key/place-holder."""
    key = _get_secret_key()
    if not key:
        return False
    upper = key.upper()
    if upper.startswith("FLWSECK_TEST") or "YOUR_LIVE_SECRET_KEY" in upper or "YOUR_TEST_KEY" in upper:
        return False
    # Live Flutterwave secret keys normally use the FLWSECK- prefix.
    return upper.startswith("FLWSECK-") and len(key) >= 20


def _headers() -> dict[str, str]:
    key = _get_secret_key()
    if not is_flutterwave_configured():
        raise RuntimeError(
            "A valid LIVE Flutterwave secret key is not configured. Test/simulated operations are disabled."
        )
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _response_json(response: requests.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def create_payment_link(
    *,
    tx_ref: str,
    amount: Any,
    currency: str,
    customer_email: str,
    customer_name: str = "LifeGrid User",
    title: str = "LifeGrid Gift Credits",
    description: str = "Purchase LifeGrid Gift Credits",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create Flutterwave Standard hosted checkout; no simulation/fake success is possible."""
    if not tx_ref or len(str(tx_ref).strip()) < 8:
        raise ValueError("A unique LifeGrid payment reference is required.")
    if not customer_email or "@" not in str(customer_email):
        raise ValueError("A valid customer email is required by Flutterwave.")

    try:
        amount_value = Decimal(str(amount))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("The checkout amount is invalid.") from exc
    if not amount_value.is_finite() or amount_value <= 0:
        raise ValueError("The checkout amount must be greater than zero.")

    currency_value = str(currency or "").strip().upper()
    if len(currency_value) != 3 or not currency_value.isalpha():
        raise ValueError("Use a valid three-letter payment currency code.")

    payload: dict[str, Any] = {
        "tx_ref": str(tx_ref).strip(),
        "amount": format(amount_value, "f"),
        "currency": currency_value,
        "customer": {
            "email": str(customer_email).strip(),
            "name": str(customer_name or "LifeGrid User").strip()[:100],
        },
        "customizations": {
            "title": str(title or "LifeGrid Gift Credits")[:45],
            "description": str(description or "Purchase LifeGrid Gift Credits")[:120],
        },
    }
    redirect_url = _get_redirect_url()
    if redirect_url:
        if not redirect_url.lower().startswith("https://"):
            raise ValueError("FLUTTERWAVE_REDIRECT_URL must be a public HTTPS URL.")
        payload["redirect_url"] = redirect_url
    if meta:
        payload["meta"] = meta

    try:
        response = requests.post(
            f"{_get_base_url()}/payments",
            json=payload,
            headers=_headers(),
            timeout=25,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Could not reach Flutterwave to create checkout: {exc}") from exc

    body = _response_json(response)
    if response.status_code not in (200, 201) or str(body.get("status", "")).lower() != "success":
        message = body.get("message") or f"Flutterwave checkout request failed (HTTP {response.status_code})."
        raise RuntimeError(str(message))

    data = body.get("data") or {}
    checkout_url = str(data.get("link") or "").strip()
    if not checkout_url.startswith("https://"):
        raise RuntimeError("Flutterwave did not return a valid HTTPS checkout URL.")
    return {"success": True, "tx_ref": str(tx_ref), "checkout_url": checkout_url, "provider_data": data}


def verify_transaction(transaction_id: Any) -> dict[str, Any]:
    """Verify a payment by Flutterwave transaction ID."""
    clean_id = str(transaction_id or "").strip()
    if not clean_id.isdigit():
        raise ValueError("Flutterwave transaction ID must be numeric.")
    try:
        response = requests.get(
            f"{_get_base_url()}/transactions/{clean_id}/verify",
            headers=_headers(),
            timeout=25,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Could not reach Flutterwave to verify payment: {exc}") from exc
    body = _response_json(response)
    if response.status_code != 200 or str(body.get("status", "")).lower() != "success":
        message = body.get("message") or f"Flutterwave verification failed (HTTP {response.status_code})."
        raise RuntimeError(str(message))
    data = body.get("data") or {}
    if not isinstance(data, dict):
        raise RuntimeError("Flutterwave returned an invalid verification response.")
    return {"success": True, "data": data}


def verify_transaction_by_reference(tx_ref: str) -> dict[str, Any]:
    """Verify a payment by LifeGrid's unique transaction reference."""
    reference = str(tx_ref or "").strip()
    if len(reference) < 8:
        raise ValueError("A valid LifeGrid payment reference is required for verification.")
    try:
        response = requests.get(
            f"{_get_base_url()}/transactions/verify_by_reference",
            params={"tx_ref": reference},
            headers=_headers(),
            timeout=25,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Could not reach Flutterwave to verify payment: {exc}") from exc
    body = _response_json(response)
    if response.status_code != 200 or str(body.get("status", "")).lower() != "success":
        message = body.get("message") or f"Flutterwave reference verification failed (HTTP {response.status_code})."
        raise RuntimeError(str(message))
    data = body.get("data") or {}
    if not isinstance(data, dict):
        raise RuntimeError("Flutterwave returned an invalid reference-verification response.")
    return {"success": True, "data": data}


@st.cache_data(ttl=3600)
def get_supported_banks(country: str = "NG"):
    """Return API bank data if available; fallback list is only for display."""
    country_code = str(country or "NG").strip().upper()
    if not is_flutterwave_configured():
        return DEFAULT_NG_BANKS if country_code == "NG" else []
    try:
        response = requests.get(
            f"{_get_base_url()}/banks/{country_code}",
            headers=_headers(),
            timeout=10,
        )
        body = _response_json(response)
        data = body.get("data", [])
        if response.status_code == 200 and isinstance(data, list) and data:
            return data
    except Exception:
        pass
    return DEFAULT_NG_BANKS if country_code == "NG" else []


def resolve_bank_account(
    account_number: str,
    bank_code: str,
    fallback_name: str = "Creator Account",
) -> dict[str, Any]:
    """Resolve a real bank account with Flutterwave. No demo verification is returned."""
    clean_account = str(account_number or "").strip()
    clean_bank_code = str(bank_code or "").strip()
    if not clean_account or len(clean_account) != 10 or not clean_account.isdigit():
        return {
            "success": False,
            "account_name": "",
            "message": "Please enter a valid 10-digit Nigerian bank account number.",
            "is_simulated": False,
        }
    if not clean_bank_code:
        return {
            "success": False,
            "account_name": "",
            "message": "Select a valid bank from the bank list.",
            "is_simulated": False,
        }
    if not is_flutterwave_configured():
        return {
            "success": False,
            "account_name": "",
            "message": "Live Flutterwave credentials are not configured; real account resolution is unavailable.",
            "is_simulated": False,
        }
    try:
        response = requests.post(
            f"{_get_base_url()}/accounts/resolve",
            json={"account_number": clean_account, "account_bank": clean_bank_code},
            headers=_headers(),
            timeout=15,
        )
        body = _response_json(response)
        if response.status_code == 200 and str(body.get("status", "")).lower() == "success":
            data = body.get("data") or {}
            return {
                "success": True,
                "account_name": str(data.get("account_name") or ""),
                "message": body.get("message") or "Account resolved successfully.",
                "is_simulated": False,
            }
        return {
            "success": False,
            "account_name": "",
            "message": str(body.get("message") or f"Flutterwave returned HTTP {response.status_code}."),
            "is_simulated": False,
        }
    except requests.Timeout:
        return {
            "success": False,
            "account_name": "",
            "message": "Flutterwave account resolution timed out. Please try again.",
            "is_simulated": False,
        }
    except requests.RequestException as exc:
        return {
            "success": False,
            "account_name": "",
            "message": f"Could not contact Flutterwave: {exc}",
            "is_simulated": False,
        }


def verify_bank_account(account_number: str, bank_code: str, fallback_name: str = "Creator Account"):
    """Backward-compatible wrapper returning the real resolved account name or None."""
    result = resolve_bank_account(account_number, bank_code, fallback_name)
    return result.get("account_name") if result.get("success") else None
