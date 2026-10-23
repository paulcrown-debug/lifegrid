import streamlit as st

from auth import (
    login_user,
    register_user,
    create_password_reset_code,
    reset_password,
)

from config import (
    APP_NAME,
    APP_VERSION,
    APP_DESCRIPTION,
    DEFAULT_CURRENCY,
    SUPPORTED_CURRENCIES,
)

from database import (
    get_connection,
    initialize_database,
)


# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title=APP_NAME,
    page_icon="🌍",
    layout="wide",
)


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

initialize_database()


# ============================================================
# SESSION STATE
# ============================================================

if "user" not in st.session_state:
    st.session_state.user = None

if "reset_user_id" not in st.session_state:
    st.session_state.reset_user_id = None

if "reset_code" not in st.session_state:
    st.session_state.reset_code = None


# ============================================================
# EXACT LIFEGRID PAGE PATHS
# ============================================================

PAGE_ACCOUNT = "pages/2 - My - Account.py"
PAGE_GOALS = "pages/3_Goals.py"
PAGE_HELP = "pages/4_Help.py"
PAGE_WALLET = "pages/5_Wallet.py"
PAGE_NOTIFICATIONS = "pages/6_Notifications.py"
PAGE_MESSAGES = "pages/7_Messages.py"
PAGE_CONNECTIONS = "pages/8_Connections.py"
PAGE_LIVE = "pages/9_Live.py"
PAGE_GIFT_STORE = "pages/12_Gift_Store.py"


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def get_user_goal_count(user_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM goals
        WHERE user_id = ?
        AND status != 'Completed'
        """,
        (user_id,),
    )

    count = cursor.fetchone()[0]
    conn.close()

    return count


def get_user_help_count(user_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM help_requests
        WHERE requester_id = ?
        OR helper_id = ?
        """,
        (user_id, user_id),
    )

    count = cursor.fetchone()[0]
    conn.close()

    return count


def get_user_connection_count(user_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM connections
        WHERE
            (requester_id = ? OR receiver_id = ?)
            AND status = 'accepted'
        """,
        (user_id, user_id),
    )

    count = cursor.fetchone()[0]
    conn.close()

    return count


def get_user_wallet(user_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT balance, pending_balance, currency, status
        FROM wallets
        WHERE user_id = ?
        """,
        (user_id,),
    )

    wallet = cursor.fetchone()
    conn.close()

    return wallet


def format_currency(amount, currency):
    symbols = {
        "NGN": "₦",
        "USD": "$",
        "GBP": "£",
        "EUR": "€",
    }

    symbol = symbols.get(currency, currency)

    return f"{symbol}{amount:,.2f}"


def logout():
    st.session_state.user = None
    st.session_state.reset_user_id = None
    st.session_state.reset_code = None
    st.rerun()


# ============================================================
# AUTHENTICATION SECTION
# ============================================================

if st.session_state.user is None:

    st.title("🌍 LifeGrid")

    st.write(
        "Your life, your growth, your connections."
    )

    st.write(APP_DESCRIPTION)

    st.divider()

    login_tab, register_tab, forgot_tab = st.tabs(
        [
            "🔐 Login",
            "📝 Create Account",
            "🔑 Forgot Password",
        ]
    )

    # ========================================================
    # LOGIN
    # ========================================================

    with login_tab:

        st.subheader("Welcome back")

        login_username = st.text_input(
            "Username or Email",
            key="login_username",
        )

        login_password = st.text_input(
            "Password",
            type="password",
            key="login_password",
        )

        if st.button(
            "Login",
            type="primary",
            use_container_width=True,
        ):

            if not login_username or not login_password:

                st.error(
                    "Please enter your username/email and password."
                )

            else:

                user = login_user(
                    login_username.strip(),
                    login_password,
                )

                if user is not None:

                    st.session_state.user = user

                    st.success(
                        "Login successful."
                    )

                    st.rerun()

                else:

                    st.error(
                        "Invalid username/email or password."
                    )

    # ========================================================
    # CREATE ACCOUNT
    # ========================================================

    with register_tab:

        st.subheader("Create your LifeGrid account")

        register_username = st.text_input(
            "Username",
            key="register_username",
        )

        register_email = st.text_input(
            "Email",
            key="register_email",
        )

        register_full_name = st.text_input(
            "Full Name",
            key="register_full_name",
        )

        register_country = st.text_input(
            "Country",
            value="Nigeria",
            key="register_country",
        )

        register_currency = st.selectbox(
            "Currency",
            SUPPORTED_CURRENCIES,
            index=(
                SUPPORTED_CURRENCIES.index(DEFAULT_CURRENCY)
                if DEFAULT_CURRENCY in SUPPORTED_CURRENCIES
                else 0
            ),
            key="register_currency",
        )

        register_password = st.text_input(
            "Password",
            type="password",
            key="register_password",
        )

        register_confirm_password = st.text_input(
            "Confirm Password",
            type="password",
            key="register_confirm_password",
        )

        if st.button(
            "Create Account",
            type="primary",
            use_container_width=True,
        ):

            if not register_username:

                st.error(
                    "Please enter a username."
                )

            elif not register_email:

                st.error(
                    "Please enter your email."
                )

            elif not register_password:

                st.error(
                    "Please enter a password."
                )

            elif register_password != register_confirm_password:

                st.error(
                    "Passwords do not match."
                )

            elif len(register_password) < 6:

                st.error(
                    "Password must contain at least 6 characters."
                )

            else:

                success, message = register_user(
                    username=register_username.strip(),
                    email=register_email.strip(),
                    password=register_password,
                    full_name=register_full_name.strip(),
                    country=register_country.strip(),
                    currency=register_currency,
                )

                if success:

                    st.success(message)

                    st.info(
                        "Your account has been created. "
                        "You can now log in."
                    )

                else:

                    st.error(message)

    # ========================================================
    # FORGOT PASSWORD
    # ========================================================

    with forgot_tab:

        st.subheader("Reset your password")

        reset_email = st.text_input(
            "Email",
            key="reset_email",
        )

        if st.button(
            "Send Reset Code",
            use_container_width=True,
        ):

            if not reset_email:

                st.error(
                    "Please enter your email."
                )

            else:

                success, result = create_password_reset_code(
                    reset_email.strip()
                )

                if success:

                    st.session_state.reset_user_id = result[
                        "user_id"
                    ]

                    st.session_state.reset_code = result[
                        "reset_code"
                    ]

                    st.success(
                        "A password reset code has been generated."
                    )

                    st.info(
                        "Development mode: your reset code is "
                        f"{result['reset_code']}"
                    )

                else:

                    st.error(
                        result
                    )

        # ----------------------------------------------------
        # RESET CODE / NEW PASSWORD
        # ----------------------------------------------------

        if st.session_state.reset_user_id:

            st.divider()

            st.subheader(
                "Enter your reset code"
            )

            entered_reset_code = st.text_input(
                "Reset Code",
                max_chars=6,
                key="entered_reset_code",
            )

            new_reset_password = st.text_input(
                "New Password",
                type="password",
                key="new_reset_password",
            )

            confirm_reset_password = st.text_input(
                "Confirm New Password",
                type="password",
                key="confirm_reset_password",
            )

            if st.button(
                "Reset Password",
                type="primary",
                use_container_width=True,
            ):

                if not entered_reset_code:

                    st.error(
                        "Please enter your reset code."
                    )

                elif not new_reset_password:

                    st.error(
                        "Please enter a new password."
                    )

                elif new_reset_password != confirm_reset_password:

                    st.error(
                        "Passwords do not match."
                    )

                else:

                    reset_success, reset_message = reset_password(
                        reset_email.strip(),
                        entered_reset_code.strip(),
                        new_reset_password,
                    )

                    if reset_success:

                        st.success(
                            reset_message
                        )

                        st.session_state.reset_user_id = None
                        st.session_state.reset_code = None

                        st.info(
                            "You can now log in with your new password."
                        )

                    else:

                        st.error(
                            reset_message
                        )


    # ========================================================
    # STOP HERE
    # ========================================================

    # The dashboard must never run while the user is logged out.
    st.stop()


# ============================================================
# LOGGED-IN USER
# ============================================================

user = st.session_state.user

if user is None:
    st.stop()

user_id = int(user["id"])

display_name = (
    user.get("full_name")
    or user.get("username")
    or "LifeGrid User"
)

currency = user.get(
    "currency",
    DEFAULT_CURRENCY,
)


# ============================================================
# SIDEBAR NAVIGATION
# ============================================================

with st.sidebar:

    st.markdown(
        f"## 🌍 {APP_NAME}"
    )

    st.caption(
        f"Welcome, {display_name}"
    )

    st.divider()

    if st.button(
        "🏠 My Grid",
        use_container_width=True,
    ):
        st.rerun()

    if st.button(
        "👤 My Account",
        use_container_width=True,
    ):
        st.switch_page(PAGE_ACCOUNT)

    if st.button(
        "🎯 My Goals",
        use_container_width=True,
    ):
        st.switch_page(PAGE_GOALS)

    if st.button(
        "🤝 Help",
        use_container_width=True,
    ):
        st.switch_page(PAGE_HELP)

    if st.button(
        "💰 Wallet",
        use_container_width=True,
    ):
        st.switch_page(PAGE_WALLET)

    if st.button(
        "🔔 Notifications",
        use_container_width=True,
    ):
        st.switch_page(PAGE_NOTIFICATIONS)

    if st.button(
        "💬 Messages",
        use_container_width=True,
    ):
        st.switch_page(PAGE_MESSAGES)

    if st.button(
        "🤝 Connections",
        use_container_width=True,
    ):
        st.switch_page(PAGE_CONNECTIONS)

    if st.button(
        "🔴 Live",
        use_container_width=True,
    ):
        st.switch_page(PAGE_LIVE)

    if st.button(
        "🎁 Gift Store",
        use_container_width=True,
    ):
        st.switch_page(PAGE_GIFT_STORE)

    st.divider()

    if st.button(
        "🚪 Logout",
        use_container_width=True,
    ):
        logout()


# ============================================================
# MY GRID DASHBOARD
# ============================================================

st.title(
    f"🌍 Welcome to {APP_NAME}, {display_name}"
)

st.write(
    "Your life, your growth, your connections."
)

st.caption(
    APP_DESCRIPTION
)

st.divider()


# ============================================================
# OVERVIEW METRICS
# ============================================================

goal_count = get_user_goal_count(
    user_id
)

help_count = get_user_help_count(
    user_id
)

connection_count = get_user_connection_count(
    user_id
)

wallet = get_user_wallet(
    user_id
)


col1, col2, col3, col4 = st.columns(4)

with col1:

    st.metric(
        "Active Account",
        "Yes",
    )

with col2:

    st.metric(
        "Goals",
        goal_count,
    )

with col3:

    st.metric(
        "Help Activity",
        help_count,
    )

with col4:

    st.metric(
        "Connections",
        connection_count,
    )


# ============================================================
# WALLET SUMMARY
# ============================================================

st.subheader(
    "💰 Wallet Summary"
)

wallet_col1, wallet_col2, wallet_col3 = st.columns(3)

if wallet:

    wallet_balance = float(
        wallet[0] or 0
    )

    pending_balance = float(
        wallet[1] or 0
    )

    wallet_currency = wallet[2] or currency

    wallet_status = wallet[3] or "Active"

else:

    wallet_balance = 0.0

    pending_balance = 0.0

    wallet_currency = currency

    wallet_status = "Active"


with wallet_col1:

    st.metric(
        "Available Balance",
        format_currency(
            wallet_balance,
            wallet_currency,
        ),
    )


with wallet_col2:

    st.metric(
        "Pending Balance",
        format_currency(
            pending_balance,
            wallet_currency,
        ),
    )


with wallet_col3:

    st.metric(
        "Wallet Status",
        wallet_status,
    )


# ============================================================
# QUICK ACTIONS
# ============================================================

st.subheader(
    "⚡ Quick Actions"
)

quick_col1, quick_col2, quick_col3, quick_col4 = st.columns(4)

with quick_col1:

    if st.button(
        "🎯 My Goals",
        use_container_width=True,
    ):
        st.switch_page(PAGE_GOALS)


with quick_col2:

    if st.button(
        "🤝 Get Help",
        use_container_width=True,
    ):
        st.switch_page(PAGE_HELP)


with quick_col3:

    if st.button(
        "💰 My Wallet",
        use_container_width=True,
    ):
        st.switch_page(PAGE_WALLET)


with quick_col4:

    if st.button(
        "🤝 Connections",
        use_container_width=True,
    ):
        st.switch_page(PAGE_CONNECTIONS)


quick_col5, quick_col6, quick_col7, quick_col8 = st.columns(4)

with quick_col5:

    if st.button(
        "🔔 Notifications",
        use_container_width=True,
    ):
        st.switch_page(PAGE_NOTIFICATIONS)


with quick_col6:

    if st.button(
        "💬 Messages",
        use_container_width=True,
    ):
        st.switch_page(PAGE_MESSAGES)


with quick_col7:

    if st.button(
        "🔴 Live",
        use_container_width=True,
    ):
        st.switch_page(PAGE_LIVE)


with quick_col8:

    if st.button(
        "🎁 Gift Store",
        use_container_width=True,
    ):
        st.switch_page(PAGE_GIFT_STORE)


# ============================================================
# PERSONAL GRID
# ============================================================

st.subheader(
    "🧩 Personal Grid"
)

st.write(
    "Your LifeGrid brings your goals, help activities, "
    "connections, wallet and future opportunities together "
    "in one place."
)


# ============================================================
# HELP
# ============================================================

st.subheader(
    "🤝 Help"
)

help_col1, help_col2 = st.columns(2)

with help_col1:

    st.info(
        "Request help from people in the LifeGrid community."
    )

with help_col2:

    st.info(
        "Offer help and participate in meaningful activities."
    )


# ============================================================
# GROWTH
# ============================================================

st.subheader(
    "📈 Growth"
)

growth_col1, growth_col2, growth_col3 = st.columns(3)

with growth_col1:

    st.info(
        "🎯 Goals\n\n"
        "Set personal goals and track your progress."
    )

with growth_col2:

    st.info(
        "🤝 Connections\n\n"
        "Build meaningful connections with other users."
    )

with growth_col3:

    st.info(
        "💡 Opportunities\n\n"
        "Discover future opportunities on LifeGrid."
    )


# ============================================================
# RECENT ACTIVITY
# ============================================================

st.subheader(
    "🕒 Recent Activity"
)

st.info(
    "Your recent LifeGrid activities will appear here."
)


# ============================================================
# LIFEGRID PLATFORM
# ============================================================

st.subheader(
    "🌍 LifeGrid Platform"
)

platform_col1, platform_col2, platform_col3, platform_col4 = st.columns(4)

with platform_col1:

    st.write(
        "💬 Messaging"
    )

    st.caption(
        "Connect and communicate with other users."
    )

with platform_col2:

    st.write(
        "📺 Live"
    )

    st.caption(
        "Join Live Rooms, interact in real time, "
        "and connect with the LifeGrid community."
    )

with platform_col3:

    st.write(
        "🎁 Gift Store"
    )

    st.caption(
        "Send gifts to other LifeGrid users and "
        "support creators during Live."
    )

with platform_col4:

    st.write(
        "🛍️ Marketplace"
    )

    st.caption(
        "Services, products and opportunities will "
        "be added as LifeGrid develops."
    )


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "LifeGrid • Communication • Opportunities • Earning"
)

st.caption(
    f"Version {APP_VERSION}"
)
