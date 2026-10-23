import io
import csv
from decimal import Decimal
from datetime import datetime, date, timedelta

import streamlit as st
import pandas as pd

try:
    from database import get_connection
except ImportError:
    import sqlite3
    def get_connection():
        return sqlite3.connect("lifegrid.db", check_same_thread=False)


# =========================================================
# PAGE CONFIGURATION
# =========================================================

st.set_page_config(
    page_title="Creator Analytics & Ledger | LifeGrid",
    page_icon="📈",
    layout="wide",
)


# =========================================================
# AUTHENTICATION
# =========================================================

if "user" not in st.session_state or not st.session_state["user"]:
    st.warning("Please log in to access your Creator Analytics & Ledger Dashboard.")
    st.stop()

current_user = st.session_state["user"]
if isinstance(current_user, dict):
    user_id = int(current_user.get("id") or current_user.get("user_id") or 0)
    username = str(current_user.get("username") or current_user.get("name") or "Creator")
    user_currency = str(current_user.get("currency") or current_user.get("currency_code") or "NGN").upper()
else:
    user_id = int(current_user)
    username = "Creator"
    user_currency = "NGN"

if user_id <= 0:
    st.error("Unable to identify your LifeGrid account.")
    st.stop()

connection = get_connection()


# =========================================================
# SCHEMA ENSURANCE
# =========================================================

def get_columns(table_name):
    try:
        return {row[1] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()}
    except Exception:
        return set()

def ensure_tables():
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
        CREATE TABLE IF NOT EXISTS withdrawal_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_reference TEXT UNIQUE NOT NULL,
            creator_id INTEGER NOT NULL,
            currency TEXT DEFAULT 'NGN',
            gross_amount REAL NOT NULL,
            platform_charge REAL NOT NULL,
            net_disbursed REAL NOT NULL,
            payout_method TEXT,
            bank_name TEXT,
            account_number TEXT,
            account_name TEXT,
            status TEXT DEFAULT 'Pending',
            rejection_reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at TIMESTAMP,
            processed_by TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS receiving_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            receiving_id TEXT UNIQUE NOT NULL,
            currency TEXT DEFAULT 'NGN',
            status TEXT DEFAULT 'Active',
            verification_status TEXT DEFAULT 'Verified',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.commit()

ensure_tables()


# =========================================================
# PROFILE & CONTEXT
# =========================================================

creator = connection.execute(
    "SELECT display_name, creator_status, total_earnings, currency FROM creator_profiles WHERE user_id = ? LIMIT 1",
    (user_id,),
).fetchone()

if not creator:
    connection.execute(
        "INSERT OR IGNORE INTO creator_profiles (user_id, display_name, creator_status, total_earnings, currency) VALUES (?, ?, 'active', 0.0, ?)",
        (user_id, username, user_currency),
    )
    connection.commit()
    display_name = username
    creator_currency = user_currency
else:
    display_name = str(creator[0] or username)
    creator_currency = str(creator[3] or user_currency).upper()


# =========================================================
# HEADER & NAVIGATION
# =========================================================

def safe_switch_page(candidates, fallback_label):
    """Resilient page switcher that dynamically detects page filenames and catches StreamlitPageNotFoundError."""
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

    # 1. Check exact candidate matches on disk
    for cand in candidates:
        rel_path = f"pages/{cand}" if not cand.startswith("pages/") else cand
        fname = os.path.basename(rel_path)
        if os.path.exists(rel_path) or fname in existing_files:
            try:
                st.switch_page(rel_path)
                return
            except Exception:
                pass

    # 2. Fuzzy match against files in pages/
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


st.title("📊 Creator Financial Analytics & Audit Ledger")
st.caption("Real-time revenue metrics, supporter breakdowns, and double-entry transaction audit history.")

top_bar1, top_bar2, top_bar3 = st.columns([2, 1, 1])
with top_bar1:
    st.write(f"Creator: **@{username}** ({display_name}) | Base Currency: **{creator_currency}**")
with top_bar2:
    if st.button("🏦 Receiving Accounts", use_container_width=True):
        safe_switch_page([
            "pages/Creator Receiving Account.py",
            "pages/13 - Creator Receiving Account.py",
            "pages/Creator_Receiving_Account.py",
            "pages/15 - Creator Receiving Account.py"
        ], "Creator Receiving Account")
with top_bar3:
    if st.button("💸 Withdraw Funds", type="primary", use_container_width=True):
        safe_switch_page([
            "pages/14 - Creator Withdrawal.py",
            "pages/Creator Withdrawal.py",
            "pages/14_-_Creator_Withdrawal.py"
        ], "Withdraw Funds")


# =========================================================
# DATA RETRIEVAL
# =========================================================

# Get all unique currencies with transactions
currencies_raw = connection.execute(
    """
    SELECT DISTINCT currency FROM creator_earnings WHERE creator_id = ? AND currency IS NOT NULL
    UNION
    SELECT DISTINCT currency FROM withdrawal_requests WHERE creator_id = ? AND currency IS NOT NULL
    UNION
    SELECT DISTINCT currency FROM receiving_accounts WHERE user_id = ? AND currency IS NOT NULL
    """,
    (user_id, user_id, user_id),
).fetchall()

found_currencies = sorted(list({str(row[0]).upper() for row in currencies_raw if row and row[0]}))
if not found_currencies:
    found_currencies = [creator_currency]
elif creator_currency not in found_currencies:
    found_currencies.insert(0, creator_currency)

active_currency = st.selectbox("Select Payout Currency to Analyze", found_currencies, index=0)

# Fetch earnings for active currency
earnings_rows = connection.execute(
    """
    SELECT ce.earning_reference, ce.amount, ce.platform_fee, ce.currency,
           ce.status, ce.created_at, COALESCE(u.username, 'FanSupporter')
    FROM creator_earnings ce
    LEFT JOIN users u ON u.id = ce.supporter_id
    WHERE ce.creator_id = ? AND UPPER(COALESCE(ce.currency, ?)) = ?
    ORDER BY ce.created_at ASC, ce.id ASC
    """,
    (user_id, active_currency, active_currency),
).fetchall()

# Fetch withdrawals for active currency
withdrawals_rows = connection.execute(
    """
    SELECT request_reference, gross_amount, platform_charge, net_disbursed,
           status, created_at, payout_method
    FROM withdrawal_requests
    WHERE creator_id = ? AND UPPER(COALESCE(currency, ?)) = ?
    ORDER BY created_at ASC, id ASC
    """,
    (user_id, active_currency, active_currency),
).fetchall()


# =========================================================
# FINANCIAL CALCULATIONS
# =========================================================

gross_earnings = Decimal("0.00")
platform_fees = Decimal("0.00")
net_earnings = Decimal("0.00")
pending_earnings = Decimal("0.00")
unique_supporters = set()

for row in earnings_rows:
    ref, amt, fee, curr, status, created_at, supporter = row
    amount_dec = Decimal(str(amt or 0))
    fee_dec = Decimal(str(fee or 0))
    st_norm = str(status or "").lower()

    if st_norm == "completed":
        net_earnings += amount_dec
        platform_fees += fee_dec
        gross_earnings += (amount_dec + fee_dec)
        if supporter:
            unique_supporters.add(supporter)
    elif st_norm in ("pending", "processing"):
        pending_earnings += amount_dec

completed_withdrawals = Decimal("0.00")
pending_withdrawals = Decimal("0.00")

for w in withdrawals_rows:
    w_ref, w_gross, w_charge, w_net, w_status, w_date, w_method = w
    w_status_norm = str(w_status or "").lower()
    gross_w = Decimal(str(w_gross or 0))
    if w_status_norm in ("approved", "completed", "paid"):
        completed_withdrawals += gross_w
    elif w_status_norm in ("pending", "processing"):
        pending_withdrawals += gross_w

available_balance = max(Decimal("0.00"), net_earnings - completed_withdrawals - pending_withdrawals)


# =========================================================
# KPI METRICS SECTION
# =========================================================

st.divider()
st.subheader(f"💵 Financial Overview ({active_currency})")

kpi1, kpi2, kpi3, kpi4 = st.columns(4)
with kpi1:
    st.metric(
        "Available for Payout",
        f"{active_currency} {available_balance:,.2f}",
        help="Funds cleared and available for immediate withdrawal to your bank or crypto account."
    )
with kpi2:
    st.metric(
        "Net Earnings (Take-Home)",
        f"{active_currency} {net_earnings:,.2f}",
        help="Total earnings credited to your creator balance after platform fee deduction."
    )
with kpi3:
    st.metric(
        "Gross Fan Gifts",
        f"{active_currency} {gross_earnings:,.2f}",
        help="Total gross value of all gifts sent to you by fans."
    )
with kpi4:
    st.metric(
        "Total Disbursed",
        f"{active_currency} {completed_withdrawals:,.2f}",
        help="Total funds already paid out to your bank account."
    )

sub_kpi1, sub_kpi2, sub_kpi3, sub_kpi4 = st.columns(4)
with sub_kpi1:
    st.metric("Platform Processing Fees", f"{active_currency} {platform_fees:,.2f}")
with sub_kpi2:
    st.metric("Pending Payout Requests", f"{active_currency} {pending_withdrawals:,.2f}")
with sub_kpi3:
    st.metric("Total Completed Gifts", f"{len(earnings_rows):,}")
with sub_kpi4:
    st.metric("Unique Fan Supporters", f"{len(unique_supporters):,}")


# =========================================================
# VISUAL ANALYTICS & CHARTS
# =========================================================

st.divider()
st.subheader("📈 Performance & Trend Analytics")

chart_tab1, chart_tab2 = st.tabs(["📅 Daily Revenue Trend", "🏆 Top Supporter Leaderboard"])

with chart_tab1:
    if earnings_rows:
        trend_data = {}
        for row in earnings_rows:
            amt = float(row[1] or 0)
            date_str = str(row[5] or "")[:10]
            if date_str:
                trend_data[date_str] = trend_data.get(date_str, 0.0) + amt

        if trend_data:
            df_trend = pd.DataFrame(list(trend_data.items()), columns=["Date", "Net Earning"]).sort_values("Date")
            df_trend.set_index("Date", inplace=True)
            st.line_chart(df_trend)
        else:
            st.info("No dated transactions available for charting.")
    else:
        st.info("No earnings data recorded yet for the selected currency.")

with chart_tab2:
    if earnings_rows:
        supporter_totals = {}
        for row in earnings_rows:
            supporter = row[6] or "FanSupporter"
            amt = float(row[1] or 0)
            supporter_totals[supporter] = supporter_totals.get(supporter, 0.0) + amt

        sorted_supporters = sorted(supporter_totals.items(), key=lambda x: x[1], reverse=True)[:10]
        if sorted_supporters:
            df_fans = pd.DataFrame(sorted_supporters, columns=["Supporter", f"Total Gifted ({active_currency})"])
            st.bar_chart(df_fans.set_index("Supporter"))
        else:
            st.info("No supporters recorded yet.")
    else:
        st.info("Leaderboard will populate as supporters send gifts.")


# =========================================================
# DOUBLE-ENTRY AUDIT LEDGER
# =========================================================

st.divider()
st.subheader("📜 Double-Entry Financial Audit Ledger")
st.caption("Chronological ledger accounting for every inflow and outflow, with strict running balance tracking.")

ledger_entries = []

# Add earnings (Credits)
for row in earnings_rows:
    ref, amt, fee, curr, status, created_at, supporter = row
    amount_dec = Decimal(str(amt or 0))
    fee_dec = Decimal(str(fee or 0))
    st_norm = str(status or "Completed").title()
    
    # Entry 1: Gift Credit
    ledger_entries.append({
        "timestamp": str(created_at or ""),
        "reference": ref,
        "type": "🎁 Gift Earning",
        "description": f"Fan gift received from @{supporter}",
        "inflow": float(amount_dec),
        "outflow": 0.0,
        "fee": float(fee_dec),
        "status": st_norm,
        "raw_time": str(created_at or ""),
    })

# Add withdrawals (Debits)
for w in withdrawals_rows:
    w_ref, w_gross, w_charge, w_net, w_status, w_date, w_method = w
    gross_w = Decimal(str(w_gross or 0))
    charge_w = Decimal(str(w_charge or 0))
    w_status_norm = str(w_status or "Pending").title()

    ledger_entries.append({
        "timestamp": str(w_date or ""),
        "reference": w_ref,
        "type": "🏦 Bank Payout",
        "description": f"Creator withdrawal payout ({w_method or 'Bank Transfer'})",
        "inflow": 0.0,
        "outflow": float(gross_w),
        "fee": float(charge_w),
        "status": w_status_norm,
        "raw_time": str(w_date or ""),
    })

# Sort chronologically
ledger_entries.sort(key=lambda x: x["raw_time"])

# Compute running balance
running_balance = Decimal("0.00")
table_rows = []

for entry in ledger_entries:
    if entry["status"].lower() in ("completed", "approved", "paid"):
        running_balance += Decimal(str(entry["inflow"])) - Decimal(str(entry["outflow"]))
    entry["running_balance"] = float(running_balance)
    table_rows.append({
        "Date": entry["timestamp"][:19],
        "Reference": entry["reference"],
        "Type": entry["type"],
        "Description": entry["description"],
        f"Inflow (+)": f"{entry['inflow']:,.2f}" if entry["inflow"] > 0 else "-",
        f"Outflow (-)": f"{entry['outflow']:,.2f}" if entry["outflow"] > 0 else "-",
        "Fee Paid": f"{entry['fee']:,.2f}" if entry["fee"] > 0 else "-",
        "Balance": f"{entry['running_balance']:,.2f}",
        "Status": entry["status"],
    })

# Reconciliation Check
discrepancy = abs(running_balance - (net_earnings - completed_withdrawals))
rec_col1, rec_col2 = st.columns([3, 1])
with rec_col1:
    if discrepancy < Decimal("0.01"):
        st.success(f"✅ **Ledger Reconciled & Mathematically Verified:** Running balance matches creator net take-home ({active_currency} {running_balance:,.2f}).")
    else:
        st.warning(f"⚠️ Variance detected in historical ledger: difference of {active_currency} {discrepancy:,.2f}.")

with rec_col2:
    # CSV Export Button
    if table_rows:
        csv_buffer = io.StringIO()
        writer = csv.DictWriter(csv_buffer, fieldnames=list(table_rows[0].keys()))
        writer.writeheader()
        writer.writerows(table_rows)
        csv_data = csv_buffer.getvalue().encode("utf-8")
        st.download_button(
            label="📥 Download CSV Statement",
            data=csv_data,
            file_name=f"LifeGrid_Ledger_{active_currency}_{date.today().isoformat()}.csv",
            mime="text/csv",
            use_container_width=True,
        )

# Render Table
if table_rows:
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, height=450)
else:
    st.info(f"No financial transactions found for {active_currency}. Transactions will appear here as gifts and payouts occur.")

st.divider()
st.caption("LifeGrid Financial Systems • Real-time creator ledger and regulatory compliance engine.")
connection.close()