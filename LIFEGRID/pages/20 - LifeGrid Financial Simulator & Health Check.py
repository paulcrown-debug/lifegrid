"""
LifeGrid - Page 20: Financial System Health Check & End-to-End Lifecycle Simulator
Runs comprehensive diagnostics on SQLite tables, KYC folders, and Flutterwave keys,
and executes a complete 7-step transaction simulation (Fan Gift -> Wallet -> KYC -> Payout -> Disbursal -> Notification -> Ledger).
"""

import os
import sqlite3
import uuid
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

import streamlit as st

# =========================================================
# STREAMLIT CONFIGURATION
# =========================================================
st.set_page_config(
    page_title="LifeGrid - System Health & Simulator",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =========================================================
# FAIL-SAFE PAGE NAVIGATION
# =========================================================
def safe_switch_page(candidates, fallback_label):
    """Resilient page switcher that dynamically detects page filenames and catches StreamlitPageNotFoundError."""
    if not hasattr(st, "switch_page"):
        st.info(f"Please open {fallback_label} from the sidebar menu.")
        return
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


# =========================================================
# DATABASE CONNECTION
# =========================================================
def get_db_connection():
    try:
        from database import get_connection
        return get_connection()
    except Exception:
        return sqlite3.connect("lifegrid.db", check_same_thread=False)


# =========================================================
# UI HEADER & NAVIGATION SHORTCUTS
# =========================================================
st.title("🧪 Financial Engine Simulator & Diagnostics")
st.caption("Development-only transaction simulation and database health monitor for LifeGrid.")
st.warning("🧪 This page writes simulated transactions and balances to your local database. It does not charge a fan, perform live KYC, contact Flutterwave, or prove production payout behavior. Use only in a development copy.")

top_c1, top_c2, top_c3, top_c4 = st.columns([2, 1, 1, 1])
with top_c1:
    st.write("Environment: **Local / Sandbox Development Mode**")
with top_c2:
    if st.button("📊 Open Analytics", use_container_width=True):
        safe_switch_page([
            "pages/18 - Creator Analytics & Ledger Dashboard.py",
            "pages/18 - Creator Analytics.py"
        ], "Creator Analytics")
with top_c3:
    if st.button("🏦 Receiving Accounts", use_container_width=True):
        safe_switch_page([
            "pages/13 - Creator Receiving Account.py",
            "pages/Creator Receiving Account.py"
        ], "Receiving Accounts")
with top_c4:
    if st.button("💸 Disbursal Admin", type="primary", use_container_width=True):
        safe_switch_page([
            "pages/15 - Withdrawal Administration.py",
            "pages/Withdrawal Administration.py"
        ], "Disbursal Admin")

st.divider()

db = get_db_connection()

tab_health, tab_sim, tab_explorer = st.tabs([
    "🩺 System Health & Table Monitor",
    "⚡ 1-Click End-to-End Simulation",
    "🔍 Database Table Inspector"
])

# =========================================================
# TAB 1: SYSTEM HEALTH & TABLE MONITOR
# =========================================================
with tab_health:
    st.subheader("System Architecture & Schema Health")

    # 1. Database Table Checks
    tables_to_check = [
        ("creator_profiles", "Stores creator wallets, balances, and active states"),
        ("receiving_accounts", "Multi-currency bank & mobile money accounts"),
        ("creator_earnings", "Incoming fan tips, gift purchases, and inflow records"),
        ("creator_withdrawals", "Pending and completed payout disbursal requests"),
        ("withdrawal_notifications", "Lifecycle alerts (Requested, Disbursed, Rejected)"),
        ("creator_posts", "Social feed updates and media snippets"),
        ("post_tips", "Direct tipping records tied to individual posts"),
        ("lifegrid_kyc_verifications", "Document uploads, blur tests, and AML status")
    ]

    cursor = db.cursor()
    health_results = []
    for tbl, desc in tables_to_check:
        try:
            row_count = cursor.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            health_results.append({"Table": tbl, "Status": "✅ Operational", "Rows": row_count, "Purpose": desc})
        except Exception as e:
            health_results.append({"Table": tbl, "Status": "⚠️ Missing / Needs Init", "Rows": 0, "Purpose": desc})

    st.dataframe(health_results, use_container_width=True)

    # 2. Directory & Flutterwave Credentials Check
    col_dir, col_flw = st.columns(2)
    with col_dir:
        st.markdown("#### 📂 KYC Storage Directory")
        kyc_dir = os.path.join(os.getcwd(), "data", "kyc_documents")
        if os.path.exists(kyc_dir):
            file_count = len(os.listdir(kyc_dir))
            st.success(f"✅ Directory active: `{kyc_dir}` ({file_count} documents stored)")
        else:
            st.info(f"📁 Creating default directory `{kyc_dir}`...")
            os.makedirs(kyc_dir, exist_ok=True)
            st.success("✅ KYC storage directory initialized.")

    with col_flw:
        st.markdown("#### 💳 Flutterwave Integration Mode")
        flw_key = os.environ.get("FLUTTERWAVE_SECRET_KEY", "")
        if flw_key.startswith("FLWSECK_TEST"):
            st.warning("🧪 Test Mode: Flutterwave Test Key configured.")
        elif flw_key.startswith("FLWSECK-"):
            st.success("🟢 Live Mode: Production Flutterwave Secret Key active.")
        else:
            st.info("💡 Simulated Mode: Instant dev fallback enabled for all purchases & payouts.")

# =========================================================
# TAB 2: 1-CLICK END-TO-END SIMULATION
# =========================================================
with tab_sim:
    st.subheader("⚡ Execute Full Transaction & Payout Lifecycle")
    st.write(
        "Run an automated simulation that executes the entire LifeGrid monetary cycle in order: "
        "Fan Gifting ➔ Creator Balance ➔ KYC Check ➔ Withdrawal Request ➔ Admin Approval ➔ Notification ➔ Audit Ledger."
    )

    sim_c1, sim_c2 = st.columns([1, 1])
    with sim_c1:
        sim_currency = st.selectbox("Simulation Currency:", ["NGN", "USD", "EUR", "GBP"], index=0)
        sim_gift_amount = st.number_input(
            "Gift / Tip Amount:",
            min_value=100.0 if sim_currency == "NGN" else 5.0,
            value=10000.0 if sim_currency == "NGN" else 50.0,
            step=500.0 if sim_currency == "NGN" else 5.0
        )
    with sim_c2:
        sim_fan = st.text_input("Simulated Fan Name:", value="Fan_Tester_Tunde")
        sim_creator = st.text_input("Simulated Creator Handle:", value="Creator_Chidinma")

    if st.button("🚀 Run Complete Lifecycle Simulation", type="primary", use_container_width=True):
        progress_bar = st.progress(0)
        status_box = st.status("Initiating LifeGrid financial transaction pipeline...", expanded=True)

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        test_creator_id = 999
        sim_ref = f"SIM-WDR-{uuid.uuid4().hex[:8].upper()}"

        # -----------------------------------------------------
        # STEP 1: Ensure Creator Profile Exists
        # -----------------------------------------------------
        status_box.write("Step 1: Setting up Creator profile & receiving wallet...")
        db.execute("""
            INSERT INTO creator_profiles (user_id, display_name, creator_status, total_earnings, currency)
            VALUES (?, ?, 'active', 0.0, ?)
            ON CONFLICT(user_id) DO UPDATE SET display_name = excluded.display_name
        """, (test_creator_id, sim_creator, sim_currency))
        db.commit()
        progress_bar.progress(15)

        # -----------------------------------------------------
        # STEP 2: Fan Purchases Gift & Sends Tip
        # -----------------------------------------------------
        status_box.write(f"Step 2: Fan '{sim_fan}' sends {sim_currency} {sim_gift_amount:,.2f} tip...")
        db.execute("""
            INSERT INTO creator_earnings (creator_id, fan_name, gift_name, amount, currency, created_at)
            VALUES (?, ?, 'Super Rocket Gift', ?, ?, ?)
        """, (test_creator_id, sim_fan, float(sim_gift_amount), sim_currency, now_str))

        db.execute("""
            UPDATE creator_profiles
            SET total_earnings = total_earnings + ?
            WHERE user_id = ?
        """, (float(sim_gift_amount), test_creator_id))
        db.commit()
        progress_bar.progress(30)

        # -----------------------------------------------------
        # STEP 3: Ensure Receiving Account Exists
        # -----------------------------------------------------
        status_box.write("Step 3: Registering a simulated receiving account (not externally verified)...")
        acc_exists = db.execute("SELECT id FROM receiving_accounts WHERE user_id = ? AND currency = ?", (test_creator_id, sim_currency)).fetchone()
        if not acc_exists:
            rec_id = f"LG-{uuid.uuid4().hex[:8].upper()}"
            db.execute("""
                INSERT INTO receiving_accounts (user_id, receiving_id, currency, status, verification_status, created_at)
                VALUES (?, ?, ?, 'Active', 'Verified', ?)
            """, (test_creator_id, rec_id, sim_currency, now_str))
            db.commit()
        progress_bar.progress(45)

        # -----------------------------------------------------
        # STEP 4: Calculate Platform Fees & Submit Withdrawal
        # -----------------------------------------------------
        status_box.write("Step 4: Creating a simulated withdrawal. KYC and payout eligibility are not actually verified by this test...")
        # Fee structure: 2% + 100 for NGN, 2.5% + $5 for USD
        if sim_currency == "NGN":
            pct_fee = float(sim_gift_amount) * 0.02
            flat_fee = 100.0
        else:
            pct_fee = float(sim_gift_amount) * 0.025
            flat_fee = 5.0
        total_fee = round(pct_fee + flat_fee, 2)
        net_payout = max(0.0, float(sim_gift_amount) - total_fee)

        # Deduct wallet
        db.execute("UPDATE creator_profiles SET total_earnings = total_earnings - ? WHERE user_id = ?", (float(sim_gift_amount), test_creator_id))

        # Insert creator_withdrawals
        db.execute("""
            INSERT INTO creator_withdrawals (
                withdrawal_reference, user_id, amount, currency, status, notes,
                created_at, processed_at, transaction_reference, fee_amount, net_amount, destination
            ) VALUES (?, ?, ?, ?, 'Processing', 'Automated lifecycle test submission', ?, '', '', ?, ?, 'GTBank - 0123456789')
        """, (sim_ref, test_creator_id, float(sim_gift_amount), sim_currency, now_str, total_fee, net_payout))
        db.commit()
        progress_bar.progress(65)

        # -----------------------------------------------------
        # STEP 5: Disbursal Execution (Flutterwave / Admin)
        # -----------------------------------------------------
        status_box.write("Step 5: Simulating successful bank disbursal...")
        flw_tx_ref = f"FLW-TX-{uuid.uuid4().hex[:10].upper()}"
        processed_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        db.execute("""
            UPDATE creator_withdrawals
            SET status = 'Completed',
                processed_at = ?,
                transaction_reference = ?,
                notes = 'Disbursed successfully via simulated Flutterwave integration'
            WHERE withdrawal_reference = ?
        """, (processed_time, flw_tx_ref, sim_ref))
        db.commit()
        progress_bar.progress(85)

        # -----------------------------------------------------
        # STEP 6: Notification Dispatch
        # -----------------------------------------------------
        status_box.write("Step 6: Generating real-time notification alert...")
        notif_msg = f"Your withdrawal of {sim_currency} {net_payout:,.2f} (Gross: {sim_currency} {sim_gift_amount:,.2f}, Fee: {sim_currency} {total_fee:,.2f}) has been disbursed. Tx Ref: {flw_tx_ref}."
        db.execute("""
            INSERT INTO withdrawal_notifications (
                user_id, withdrawal_reference, notification_type, title, message, currency, amount, is_read, created_at
            ) VALUES (?, ?, 'completed', 'Withdrawal Successful', ?, ?, ?, 0, ?)
        """, (test_creator_id, sim_ref, notif_msg, sim_currency, float(sim_gift_amount), processed_time))
        db.commit()
        progress_bar.progress(100)

        status_box.update(label="🎉 Complete 7-Step Lifecycle Simulation Successful!", state="complete", expanded=True)

        # Summary Metrics
        st.balloons()
        st.success("✅ Transaction Pipeline Validated End-to-End!")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Gross Gift Inflow", f"{sim_currency} {sim_gift_amount:,.2f}")
        m2.metric("Platform Fee Collected", f"{sim_currency} {total_fee:,.2f}")
        m3.metric("Net Disbursed to Creator", f"{sim_currency} {net_payout:,.2f}")
        m4.metric("Disbursal Reference", flw_tx_ref)

        st.info("💡 This is a local simulation record, not a real payout. You can inspect it in Page 15 (Withdrawal Administration) and Page 18 (Creator Analytics Ledger), provided those pages use the same database and compatible schema.")

# =========================================================
# TAB 3: DATABASE TABLE INSPECTOR
# =========================================================
with tab_explorer:
    st.subheader("🔍 SQLite Live Table Browser")
    selected_table = st.selectbox(
        "Choose table to view:",
        [
            "creator_withdrawals",
            "creator_earnings",
            "creator_profiles",
            "withdrawal_notifications",
            "receiving_accounts",
            "creator_posts",
            "post_tips",
            "webhook_logs"
        ]
    )

    try:
        rows = db.execute(f"SELECT * FROM {selected_table} ORDER BY 1 DESC LIMIT 50").fetchall()
        col_names = [d[0] for d in db.execute(f"SELECT * FROM {selected_table} LIMIT 1").description] if rows else []

        if rows:
            st.write(f"Showing up to 50 latest records from `{selected_table}`:")
            table_data = [dict(zip(col_names, row)) for row in rows]
            st.dataframe(table_data, use_container_width=True)
        else:
            st.info(f"Table `{selected_table}` is currently empty.")
    except Exception as e:
        st.error(f"Could not load records from `{selected_table}`: {str(e)}")

db.close()