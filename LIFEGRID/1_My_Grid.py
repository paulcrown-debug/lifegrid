import streamlit as st
from datetime import datetime


st.set_page_config(
    page_title="My Grid - LifeGrid",
    page_icon="🌍",
    layout="wide",
)


# --------------------------------------------------
# CHECK LOGIN
# --------------------------------------------------

if not st.session_state.get("logged_in", False):
    st.warning("Please log in to access My Grid.")
    st.stop()


user = st.session_state.get("user")

if not user:
    st.warning("User information could not be loaded.")
    st.stop()


# --------------------------------------------------
# PAGE HEADER
# --------------------------------------------------

st.title("🌍 My Grid")

st.write(
    f"Welcome back, **{user.get('full_name') or user.get('username')}**."
)

st.caption(
    "Your personal space for managing your life, goals, "
    "connections, help, opportunities, and future LifeGrid activities."
)

st.divider()


# --------------------------------------------------
# ACCOUNT SUMMARY
# --------------------------------------------------

st.subheader("📊 Your LifeGrid Overview")

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric(
        "Account",
        "Active",
    )

with col2:
    st.metric(
        "Goals",
        "0",
    )

with col3:
    st.metric(
        "Help Activities",
        "0",
    )

with col4:
    st.metric(
        "Connections",
        "0",
    )


st.divider()


# --------------------------------------------------
# QUICK ACTIONS
# --------------------------------------------------

st.subheader("⚡ Quick Actions")

action1, action2, action3, action4 = st.columns(4)

with action1:
    if st.button(
        "🎯 My Goals",
        use_container_width=True,
    ):
        st.info(
            "The Goals system will be added next."
        )

with action2:
    if st.button(
        "🤝 Get Help",
        use_container_width=True,
    ):
        st.info(
            "The Help system will be connected soon."
        )

with action3:
    if st.button(
        "💰 My Wallet",
        use_container_width=True,
    ):
        st.info(
            "The LifeGrid Wallet will be connected soon."
        )

with action4:
    if st.button(
        "📺 Live",
        use_container_width=True,
    ):
        st.info(
            "Live streaming will be connected soon."
        )


st.divider()


# --------------------------------------------------
# PERSONAL GRID
# --------------------------------------------------

st.subheader("🧩 My Personal Grid")

grid1, grid2, grid3 = st.columns(3)

with grid1:

    st.markdown("### 🎯 Goals")

    st.write(
        "Set personal goals and track your progress."
    )

    st.progress(0)

    st.caption("No goals added yet.")

with grid2:

    st.markdown("### 🤝 Help")

    st.write(
        "Give help, request help, and keep track of "
        "your help activities."
    )

    st.info("No help activities yet.")

with grid3:

    st.markdown("### 🌱 Growth")

    st.write(
        "Build useful habits, activities, skills, "
        "and opportunities."
    )

    st.info("Your growth journey starts here.")


st.divider()


# --------------------------------------------------
# LIFEGRID ACTIVITY
# --------------------------------------------------

st.subheader("🕒 Recent Activity")

st.info(
    "Your LifeGrid activity will appear here as you "
    "use the platform."
)


st.divider()


# --------------------------------------------------
# ACCOUNT INFORMATION
# --------------------------------------------------

st.subheader("👤 My Account")

account_col1, account_col2 = st.columns(2)

with account_col1:

    st.write(
        f"**Username:** {user.get('username', '')}"
    )

    st.write(
        f"**Email:** {user.get('email', '')}"
    )

    st.write(
        f"**Full Name:** "
        f"{user.get('full_name') or 'Not provided'}"
    )

with account_col2:

    st.write(
        f"**Country:** "
        f"{user.get('country') or 'Not provided'}"
    )

    st.write(
        f"**Currency:** "
        f"{user.get('currency') or 'NGN'}"
    )

    st.write(
        f"**Dashboard Date:** "
        f"{datetime.now().strftime('%d %B %Y')}"
    )


st.divider()


# --------------------------------------------------
# FUTURE LIFEGRID FEATURES
# --------------------------------------------------

st.subheader("🚀 LifeGrid Platform")

st.write(
    "LifeGrid is being built as a complete platform "
    "for connection, personal growth, helping others, "
    "earning opportunities, business, communication, "
    "and community."
)

future1, future2, future3 = st.columns(3)

with future1:

    st.markdown("**💬 Communication**")

    st.caption(
        "Messaging, notifications, connections, "
        "and community activity."
    )

with future2:

    st.markdown("**💼 Opportunities**")

    st.caption(
        "Marketplace, services, jobs, business, "
        "and digital opportunities."
    )

with future3:

    st.markdown("**💰 Earnings**")

    st.caption(
        "Wallet, receiving account, gifts, "
        "creator earnings, and approved monetization."
    )


st.divider()

st.caption(
    "LifeGrid — Your life. Your growth. Your connections."
)