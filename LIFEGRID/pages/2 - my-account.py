"""
LifeGrid - My Account Page
Complete user account management: Profile details, LifeGrid Receiving ID,
primary currency preference, wallet balance overview, KYC status,
password security, activity logs, and seamless ecosystem navigation.
"""

import sqlite3
import streamlit as st
from datetime import datetime

from auth import hash_password, verify_password, log_activity
from database import get_connection

st.set_page_config(
    page_title="My Account | LifeGrid",
    page_icon="👤",
    layout="wide",
)

# ============================================================
# LOGIN CHECK
# ============================================================
if "user" not in st.session_state or st.session_state.user is None:
    st.warning("Please log in to access your account.")
    st.stop()

user_id = int(st.session_state.user["id"])

# ============================================================
# DATABASE SETUP & MIGRATION HELPERS
# ============================================================
def ensure_profile_tables():
    """Safely ensure all profile, wallet, and receiving account columns exist."""
    conn = get_connection()
    cursor = conn.cursor()

    # 1. Update users table with profile fields
    user_additions = {
        "bio": "TEXT DEFAULT ''",
        "skills": "TEXT DEFAULT ''",
        "interests": "TEXT DEFAULT ''",
        "help_offered": "TEXT DEFAULT ''",
        "help_needed": "TEXT DEFAULT ''",
        "profile_visibility": "TEXT DEFAULT 'Public'",
        "currency": "TEXT DEFAULT 'USD'",
        "receiving_id": "TEXT",
    }
    cursor.execute("PRAGMA table_info(users)")
    existing_user_cols = {row[1] for row in cursor.fetchall()}

    for col, defn in user_additions.items():
        if col not in existing_user_cols:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {defn}")

    # 2. Ensure receiving_accounts table exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS receiving_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            currency TEXT NOT NULL DEFAULT 'USD',
            receiving_id TEXT UNIQUE,
            account_type TEXT DEFAULT 'internal_wallet',
            account_status TEXT DEFAULT 'Active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Existing installations may have created receiving_accounts before this
    # page was added. CREATE TABLE IF NOT EXISTS does not add new columns to
    # existing tables, so migrate the optional compatibility columns before
    # inserting a receiving account.
    cursor.execute("PRAGMA table_info(receiving_accounts)")
    receiving_cols = {row[1] for row in cursor.fetchall()}
    receiving_additions = {
        "account_type": "TEXT DEFAULT 'internal_wallet'",
        "account_status": "TEXT DEFAULT 'Active'",
        "verification_status": "TEXT DEFAULT 'Not Verified'",
        "updated_at": "TIMESTAMP",
    }
    for col, defn in receiving_additions.items():
        if col not in receiving_cols:
            cursor.execute(f"ALTER TABLE receiving_accounts ADD COLUMN {col} {defn}")

    cursor.execute(
        "SELECT receiving_id FROM receiving_accounts WHERE user_id = ? LIMIT 1",
        (user_id,),
    )
    existing_receiving_row = cursor.fetchone()

    # 3. Ensure wallets table exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wallets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            currency TEXT NOT NULL DEFAULT 'USD',
            balance REAL DEFAULT 0.0,
            available_balance REAL DEFAULT 0.0,
            pending_balance REAL DEFAULT 0.0,
            wallet_status TEXT DEFAULT 'Active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 4. Ensure creator_profiles exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS creator_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            display_name TEXT,
            total_earnings REAL DEFAULT 0.0,
            pending_balance REAL DEFAULT 0.0,
            kyc_tier INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("PRAGMA table_info(creator_profiles)")
    creator_cols = {row[1] for row in cursor.fetchall()}
    creator_additions = {
        "kyc_tier": "INTEGER DEFAULT 1",
        "display_name": "TEXT",
        "total_earnings": "REAL DEFAULT 0.0",
        "pending_balance": "REAL DEFAULT 0.0",
    }
    for col, defn in creator_additions.items():
        if col not in creator_cols:
            cursor.execute(f"ALTER TABLE creator_profiles ADD COLUMN {col} {defn}")

    # Ensure this user has a receiving ID
    cursor.execute("SELECT receiving_id FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    current_rec_id = row[0] if row else None

    if not current_rec_id:
        existing_receiving_id = (
            existing_receiving_row[0]
            if existing_receiving_row and existing_receiving_row[0]
            else None
        )
        # Prefer an existing Wallet receiving ID so gifts/payments keep
        # resolving to the same account across pages.
        generated_rec_id = existing_receiving_id or f"LG-REC-{user_id:04d}"
        cursor.execute(
            "UPDATE users SET receiving_id = ? WHERE id = ?",
            (generated_rec_id, user_id),
        )
        if not existing_receiving_row:
            cursor.execute("""
                INSERT OR IGNORE INTO receiving_accounts
                    (user_id, currency, receiving_id, account_type, account_status)
                VALUES (?, 'USD', ?, 'internal_wallet', 'Active')
            """, (user_id, generated_rec_id))

    conn.commit()
    conn.close()

ensure_profile_tables()

# ============================================================
# LOAD CURRENT USER DATA
# ============================================================
conn = get_connection()
cursor = conn.cursor()

cursor.execute("""
    SELECT
        id, username, email, password_hash, full_name, country, currency,
        is_active, created_at, last_login_at, failed_login_attempts,
        last_failed_login_at, bio, skills, interests, help_offered,
        help_needed, profile_visibility, receiving_id
    FROM users
    WHERE id = ?
""", (user_id,))
user_row = cursor.fetchone()

# Wallet metrics
cursor.execute("SELECT currency, balance, available_balance, pending_balance FROM wallets WHERE user_id = ?", (user_id,))
wallet_row = cursor.fetchone()
wallet_info = {
    "currency": wallet_row[0] if wallet_row else "USD",
    "balance": float(wallet_row[1] or 0.0) if wallet_row else 0.0,
    "available": float(wallet_row[2] or 0.0) if wallet_row else 0.0,
    "pending": float(wallet_row[3] or 0.0) if wallet_row else 0.0,
}

# KYC status from creator_profiles
kyc_level = 1
try:
    cursor.execute("PRAGMA table_info(creator_profiles)")
    cp_cols = {row[1] for row in cursor.fetchall()}
    if "kyc_tier" in cp_cols:
        cursor.execute("SELECT kyc_tier FROM creator_profiles WHERE user_id = ?", (user_id,))
        kyc_row = cursor.fetchone()
        kyc_level = int(kyc_row[0]) if kyc_row and kyc_row[0] is not None else 1
except Exception:
    kyc_level = 1

conn.close()

if user_row is None:
    st.error("Your account could not be found.")
    st.stop()

user = {
    "id": user_row[0],
    "username": user_row[1],
    "email": user_row[2],
    "password_hash": user_row[3],
    "full_name": user_row[4] or "",
    "country": user_row[5] or "",
    "currency": user_row[6] or "USD",
    "is_active": user_row[7],
    "created_at": user_row[8],
    "last_login_at": user_row[9],
    "failed_login_attempts": user_row[10] or 0,
    "last_failed_login_at": user_row[11],
    "bio": user_row[12] or "",
    "skills": user_row[13] or "",
    "interests": user_row[14] or "",
    "help_offered": user_row[15] or "",
    "help_needed": user_row[16] or "",
    "profile_visibility": user_row[17] or "Public",
    "receiving_id": user_row[18] or f"LG-REC-{user_id:04d}",
}

# ============================================================
# PAGE HEADER & IDENTIFIERS
# ============================================================
st.title("👤 My Account")
st.caption("Manage your LifeGrid profile, Receiving ID, currency preferences, security, and wallet overview.")

# Highlight Card: LifeGrid Receiving ID & Quick Status
rec_col1, rec_col2, rec_col3 = st.columns([2, 1, 1])

with rec_col1:
    with st.container(border=True):
        st.markdown("##### 🎁 Your LifeGrid Receiving ID")
        st.code(user["receiving_id"], language="text")
        st.caption("Share this ID with other LifeGrid users to receive gifts, contributions, and community tips directly into your wallet.")

with rec_col2:
    with st.container(border=True):
        st.markdown("##### 💳 Wallet Balance")
        st.write(f"**{wallet_info['currency']} {wallet_info['available']:,.2f}**")
        st.caption(f"Total: {wallet_info['currency']} {wallet_info['balance']:,.2f}")

with rec_col3:
    with st.container(border=True):
        st.markdown("##### 🛡️ KYC Status")
        if kyc_level >= 2:
            st.success("Level 2 (Verified)")
            st.caption("High-tier withdrawal limits unlocked.")
        else:
            st.info("Level 1 (Standard)")
            st.caption("Submit ID in KYC verification to unlock Level 2.")

# ============================================================
# PROFILE COMPLETION
# ============================================================
st.markdown("---")
profile_fields = [
    user["full_name"],
    user["country"],
    user["bio"],
    user["skills"],
    user["interests"],
    user["help_offered"],
    user["help_needed"],
]
completed_fields = sum(1 for field in profile_fields if str(field).strip())
profile_completion = int((completed_fields / len(profile_fields)) * 100)

col_p1, col_p2, col_p3 = st.columns(3)
with col_p1:
    st.metric("Profile Completion", f"{profile_completion}%")
with col_p2:
    st.metric("Profile Visibility", user["profile_visibility"])
with col_p3:
    st.metric("Primary Currency", user["currency"])

st.progress(profile_completion / 100)

# ============================================================
# PROFILE & PREFERENCES EDIT FORM
# ============================================================
st.markdown("---")
st.subheader("📝 Profile & Preferences")

currency_options = ["USD", "NGN", "GBP", "EUR", "CAD"]

with st.form("profile_form"):
    col1, col2 = st.columns(2)

    with col1:
        full_name = st.text_input("Full Name", value=user["full_name"], placeholder="Enter your full name")
        country = st.text_input("Country", value=user["country"], placeholder="Enter your country")
        
        pref_currency = st.selectbox(
            "Primary Operating Currency",
            currency_options,
            index=currency_options.index(user["currency"]) if user["currency"] in currency_options else 0,
            help="Default currency used across Gifts, Goals, and your Wallet."
        )

        skills = st.text_area(
            "Skills",
            value=user["skills"],
            placeholder="Example: Software development, business analysis, construction, graphic design...",
            help="List skills you can offer to other LifeGrid community members."
        )

        interests = st.text_area(
            "Interests",
            value=user["interests"],
            placeholder="Example: Entrepreneurship, fintech, sports, farming, AI...",
            help="Tell people what topics interest you."
        )

    with col2:
        bio = st.text_area(
            "About Me",
            value=user["bio"],
            height=120,
            placeholder="Tell the LifeGrid community about your mission and background..."
        )

        help_offered = st.text_area(
            "What I Can Help With",
            value=user["help_offered"],
            placeholder="Example: I can offer tech mentoring, accounting advice, or career guidance...",
            help="Types of assistance you can provide to community requests."
        )

        help_needed = st.text_area(
            "What I Need Help With",
            value=user["help_needed"],
            placeholder="Example: I am seeking collaborators for my project, business advice...",
            help="Areas where you would love community support."
        )

        profile_visibility = st.selectbox(
            "Profile Visibility",
            ["Public", "Connections Only", "Private"],
            index=["Public", "Connections Only", "Private"].index(user["profile_visibility"])
            if user["profile_visibility"] in ["Public", "Connections Only", "Private"] else 0,
        )

    save_profile = st.form_submit_button("💾 Save Profile & Preferences", use_container_width=True, type="primary")

if save_profile:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE users
        SET full_name = ?,
            country = ?,
            currency = ?,
            bio = ?,
            skills = ?,
            interests = ?,
            help_offered = ?,
            help_needed = ?,
            profile_visibility = ?
        WHERE id = ?
    """, (
        full_name.strip(),
        country.strip(),
        pref_currency,
        bio.strip(),
        skills.strip(),
        interests.strip(),
        help_offered.strip(),
        help_needed.strip(),
        profile_visibility,
        user_id,
    ))

    # Also sync wallet currency if wallet exists
    cursor.execute("UPDATE wallets SET currency = ? WHERE user_id = ?", (pref_currency, user_id))

    conn.commit()
    conn.close()

    # Synchronize session state
    st.session_state.user["full_name"] = full_name.strip()
    st.session_state.user["country"] = country.strip()
    st.session_state.user["currency"] = pref_currency

    log_activity(
        user_id,
        "Account",
        "Profile & Preferences Updated",
        f"Updated name, country, bio, and currency ({pref_currency}).",
    )

    st.success("✅ Your profile and preferences have been updated.")
    st.rerun()

# ============================================================
# PROFILE PREVIEW
# ============================================================
st.markdown("---")
st.subheader("👀 Community Profile Preview")

prev_col1, prev_col2 = st.columns([1, 2])
with prev_col1:
    with st.container(border=True):
        st.markdown("### 👤")
        st.markdown(f"**{user['full_name'] or '@' + user['username']}**")
        st.caption(f"@{user['username']} • ID #{user['id']}")
        if user["country"]:
            st.write(f"🌍 {user['country']}")
        st.write(f"🔒 {user['profile_visibility']}")
        st.write(f"🎁 **Receiving ID:** `{user['receiving_id']}`")

with prev_col2:
    with st.container(border=True):
        if user["bio"]:
            st.markdown("**About Me**")
            st.write(user["bio"])
        if user["skills"]:
            st.markdown("**Skills**")
            st.write(user["skills"])
        if user["interests"]:
            st.markdown("**Interests**")
            st.write(user["interests"])
        if user["help_offered"]:
            st.markdown("**Can Help With**")
            st.write(user["help_offered"])
        if user["help_needed"]:
            st.markdown("**Looking For Help With**")
            st.write(user["help_needed"])
        if not any([user["bio"], user["skills"], user["interests"], user["help_offered"], user["help_needed"]]):
            st.info("Your profile preview will appear here once you fill out your information above.")

# ============================================================
# SECURITY & CHANGE PASSWORD
# ============================================================
st.markdown("---")
st.subheader("🔑 Security & Password")

sec_col1, sec_col2 = st.columns(2)

with sec_col1:
    st.markdown("##### Change Account Password")
    with st.form("change_password_form"):
        current_password = st.text_input("Current Password", type="password")
        new_password = st.text_input("New Password", type="password", help="Minimum 8 characters.")
        confirm_password = st.text_input("Confirm New Password", type="password")
        change_btn = st.form_submit_button("🔄 Update Password", use_container_width=True)

    if change_btn:
        if not current_password:
            st.error("Please enter your current password.")
        elif not new_password:
            st.error("Please enter a new password.")
        elif len(new_password) < 8:
            st.error("New password must be at least 8 characters.")
        elif new_password != confirm_password:
            st.error("The new passwords do not match.")
        elif not verify_password(current_password, user["password_hash"]):
            st.error("Your current password is incorrect.")
        else:
            new_hash = hash_password(new_password)
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE users
                SET password_hash = ?, failed_login_attempts = 0, last_failed_login_at = NULL
                WHERE id = ?
            """, (new_hash, user_id))
            conn.commit()
            conn.close()

            log_activity(user_id, "Security", "Password Changed", "User updated password from My Account.")
            st.success("✅ Password updated successfully.")
            st.rerun()

with sec_col2:
    st.markdown("##### Account Security Health")
    with st.container(border=True):
        st.write(f"**Username:** `{user['username']}`")
        st.write(f"**Email:** `{user['email']}`")
        st.write(f"**Status:** {'🟢 Active' if user['is_active'] else '🔴 Inactive'}")
        st.write(f"**Failed Logins:** {user['failed_login_attempts']}")
        st.write(f"**Last Login:** {user['last_login_at'] or 'First session'}")
        st.write(f"**Member Since:** {user['created_at']}")

# ============================================================
# RECENT SECURITY & ACCOUNT ACTIVITY
# ============================================================
st.markdown("---")
st.subheader("📋 Recent Account Activity")

conn = get_connection()
cursor = conn.cursor()
cursor.execute("""
    SELECT activity_type, activity_title, activity_description, created_at
    FROM activity_logs
    WHERE user_id = ?
    ORDER BY id DESC LIMIT 10
""", (user_id,))
activities = cursor.fetchall()
conn.close()

if activities:
    for act in activities:
        with st.container(border=True):
            a_col1, a_col2 = st.columns([1, 4])
            with a_col1:
                st.write(f"**{act[0]}**")
                st.caption(str(act[3]))
            with a_col2:
                st.write(f"**{act[1]}**")
                if act[2]:
                    st.caption(act[2])
else:
    st.info("No activity recorded yet.")

st.markdown("---")

# ============================================================
# DANGER ZONE / ACCOUNT DELETION
# ============================================================
st.markdown("--- ")
st.subheader("⚠️ Danger Zone & Account Deletion")

with st.container(border=True):
    st.markdown("##### 🗑️ Delete LifeGrid Account")
    st.warning(
        "**Warning:** Deleting your account will deactivate your profile and remove access to your "
        "wallet, receiving accounts, active goals, and social connections. "
        "This action is permanent and cannot be undone once confirmed."
    )

    delete_expander = st.expander("Proceed with Account Deletion", expanded=False)
    with delete_expander:
        st.markdown(
            f"To confirm permanent deletion of your account, please enter your **current password** and type **** below:"
        )

        with st.form("delete_account_form"):
            del_password = st.text_input("Current Password", type="password", key="del_acc_pwd")
            del_confirmation = st.text_input(
                "Type confirmation phrase",
                placeholder=f"DELETE {user['username']}",
                key="del_acc_confirm"
            )
            deletion_mode = st.radio(
                "Deletion Method",
                [
                    "Soft Deactivate (Disable login, hide profile & community data)",
                    "Permanent Purge (Completely remove profile, credentials & personal data)"
                ],
                index=0,
                help="Soft deactivation is standard for audit/financial history; permanent purge wipes the database records."
            )
            confirm_delete_btn = st.form_submit_button("🚨 Permanently Delete My Account", type="primary", use_container_width=True)

        if confirm_delete_btn:
            expected_phrase = f"DELETE {user['username']}"
            if not del_password:
                st.error("Please enter your current password to authorize deletion.")
            elif not verify_password(del_password, user["password_hash"]):
                st.error("Incorrect password. Account deletion aborted.")
            elif del_confirmation.strip() != expected_phrase:
                st.error(f"Confirmation phrase does not match. Please type exactly '{expected_phrase}'.")
            else:
                try:
                    conn = get_connection()
                    cursor = conn.cursor()

                    if "Soft Deactivate" in deletion_mode:
                        # Soft delete: mark user inactive, randomize credentials and blank sensitive profile
                        cursor.execute("""
                            UPDATE users
                            SET is_active = 0,
                                bio = '[Account Closed]',
                                help_offered = '',
                                help_needed = '',
                                profile_visibility = 'Private'
                            WHERE id = ?
                        """, (user_id,))
                        
                        # Also deactivate receiving accounts
                        try:
                            cursor.execute("UPDATE receiving_accounts SET account_status = 'Deactivated' WHERE user_id = ?", (user_id,))
                        except Exception:
                            pass

                        conn.commit()
                        conn.close()

                        try:
                            log_activity(user_id, "Account", "Account Deactivated", "User soft-deleted their account.")
                        except Exception:
                            pass
                    else:
                        # Permanent purge: clean up user and related user records safely
                        tables_to_clean = [
                            "receiving_accounts",
                            "creator_profiles",
                            "goals",
                            "activity_logs",
                            "connections",
                            "notifications"
                        ]
                        for tbl in tables_to_clean:
                            try:
                                cursor.execute(f"DELETE FROM {tbl} WHERE user_id = ?", (user_id,))
                            except Exception:
                                pass
                        
                        # Handle connections where user might be connected_user_id or receiver
                        try:
                            cursor.execute("DELETE FROM connections WHERE friend_id = ? OR target_user_id = ?", (user_id, user_id))
                        except Exception:
                            pass

                        # Finally remove the user
                        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
                        conn.commit()
                        conn.close()

                    st.success("Your LifeGrid account has been deleted. Logging you out...")
                    st.session_state.user = None
                    for key in list(st.session_state.keys()):
                        del st.session_state[key]
                    st.rerun()

                except Exception as e:
                    st.error(f"Failed to process account deletion: {e}")

st.caption("LifeGrid • Your life, your growth, your connections.")