import sqlite3
import streamlit as st

from database import get_connection
from auth import hash_password, verify_password


st.set_page_config(
    page_title="My Account | LifeGrid",
    page_icon="👤",
    layout="wide",
)


# ---------------------------------------------------------
# LOGIN CHECK
# ---------------------------------------------------------
if "user" not in st.session_state or not st.session_state.user:
    st.warning("Please log in to access your account.")
    st.stop()


user = st.session_state.user
user_id = int(user["id"])


# ---------------------------------------------------------
# DATABASE HELPERS
# ---------------------------------------------------------
def get_user():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            id,
            username,
            email,
            full_name,
            country,
            currency,
            is_active,
            created_at
        FROM users
        WHERE id = ?
        """,
        (user_id,),
    )

    row = cursor.fetchone()
    conn.close()

    return row


def update_profile(full_name, country, currency):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE users
        SET full_name = ?,
            country = ?,
            currency = ?
        WHERE id = ?
        """,
        (full_name, country, currency, user_id),
    )

    conn.commit()
    conn.close()


def change_password(current_password, new_password):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT password_hash FROM users WHERE id = ?",
        (user_id,),
    )

    row = cursor.fetchone()

    if not row:
        conn.close()
        return False, "Account could not be found."

    stored_hash = row[0]

    if not verify_password(current_password, stored_hash):
        conn.close()
        return False, "Current password is incorrect."

    if len(new_password) < 8:
        conn.close()
        return False, "New password must contain at least 8 characters."

    new_hash = hash_password(new_password)

    cursor.execute(
        """
        UPDATE users
        SET password_hash = ?
        WHERE id = ?
        """,
        (new_hash, user_id),
    )

    conn.commit()
    conn.close()

    return True, "Password changed successfully."


# ---------------------------------------------------------
# LOAD USER
# ---------------------------------------------------------
user_data = get_user()

if not user_data:
    st.error("Unable to load your account information.")
    st.stop()


(
    database_user_id,
    username,
    email,
    full_name,
    country,
    currency,
    is_active,
    created_at,
) = user_data


# ---------------------------------------------------------
# PAGE HEADER
# ---------------------------------------------------------
st.title("👤 My Account")
st.write("Manage your LifeGrid profile, account information, and security.")


# ---------------------------------------------------------
# ACCOUNT STATUS
# ---------------------------------------------------------
col1, col2, col3 = st.columns(3)

with col1:
    st.metric("Username", username)

with col2:
    st.metric(
        "Account Status",
        "Active" if is_active else "Inactive",
    )

with col3:
    st.metric("Currency", currency or "NGN")


st.divider()


# ---------------------------------------------------------
# PROFILE
# ---------------------------------------------------------
st.subheader("Personal Information")

with st.form("profile_form"):
    new_full_name = st.text_input(
        "Full Name",
        value=full_name or "",
        placeholder="Enter your full name",
    )

    new_country = st.text_input(
        "Country",
        value=country or "",
        placeholder="Enter your country",
    )

    supported_currencies = [
        "NGN",
        "USD",
        "GBP",
        "EUR",
    ]

    current_currency = currency if currency in supported_currencies else "NGN"

    new_currency = st.selectbox(
        "Preferred Currency",
        supported_currencies,
        index=supported_currencies.index(current_currency),
    )

    save_profile = st.form_submit_button(
        "Save Profile",
        use_container_width=True,
    )

    if save_profile:
        update_profile(
            new_full_name.strip(),
            new_country.strip(),
            new_currency,
        )

        # Keep session information updated.
        st.session_state.user["full_name"] = new_full_name.strip()
        st.session_state.user["country"] = new_country.strip()
        st.session_state.user["currency"] = new_currency

        st.success("Your profile has been updated successfully.")
        st.rerun()


st.divider()


# ---------------------------------------------------------
# LOGIN INFORMATION
# ---------------------------------------------------------
st.subheader("Login Information")

info_col1, info_col2 = st.columns(2)

with info_col1:
    st.text_input(
        "Username",
        value=username,
        disabled=True,
    )

with info_col2:
    st.text_input(
        "Email Address",
        value=email or "",
        disabled=True,
    )


st.caption(
    "Your username and email address cannot be changed from this page."
)


st.divider()


# ---------------------------------------------------------
# PASSWORD
# ---------------------------------------------------------
st.subheader("Change Password")

with st.form("change_password_form"):
    current_password = st.text_input(
        "Current Password",
        type="password",
    )

    new_password = st.text_input(
        "New Password",
        type="password",
    )

    confirm_password = st.text_input(
        "Confirm New Password",
        type="password",
    )

    change_password_button = st.form_submit_button(
        "Change Password",
        use_container_width=True,
    )

    if change_password_button:

        if not current_password:
            st.error("Please enter your current password.")

        elif not new_password:
            st.error("Please enter a new password.")

        elif new_password != confirm_password:
            st.error("The new passwords do not match.")

        else:
            success, message = change_password(
                current_password,
                new_password,
            )

            if success:
                st.success(message)
            else:
                st.error(message)


st.divider()


# ---------------------------------------------------------
# ACCOUNT INFORMATION
# ---------------------------------------------------------
st.subheader("Account Information")

account_col1, account_col2 = st.columns(2)

with account_col1:
    st.write("**Account ID:**", database_user_id)
    st.write(
        "**Account Status:**",
        "Active" if is_active else "Inactive",
    )

with account_col2:
    st.write("**Created:**", created_at)
    st.write("**Preferred Currency:**", currency or "NGN")


st.divider()


# ---------------------------------------------------------
# FUTURE FEATURES
# ---------------------------------------------------------
st.subheader("More Account Features Coming")

future_col1, future_col2, future_col3 = st.columns(3)

with future_col1:
    st.info(
        "🪪 **Identity Verification**\n\n"
        "Account verification and trust features will be added."
    )

with future_col2:
    st.info(
        "🔐 **Security Center**\n\n"
        "Manage devices, sessions, login activity, and security settings."
    )

with future_col3:
    st.info(
        "🌍 **Global Preferences**\n\n"
        "More countries, currencies, languages, and regional settings."
    )