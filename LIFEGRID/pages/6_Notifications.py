import sqlite3
import streamlit as st
from datetime import datetime

from database import get_connection

# =========================================================
# PAGE CONFIGURATION
# =========================================================
st.set_page_config(
    page_title="Notifications | LifeGrid",
    page_icon="🔔",
    layout="wide",
)

# =========================================================
# LOGIN PROTECTION
# =========================================================
if "user" not in st.session_state or not st.session_state.user:
    st.warning("Please log in to access your LifeGrid notifications.")

    if st.button("Go to Login"):
        try:
            st.switch_page("app.py")
        except Exception:
            pass

    st.stop()

user = st.session_state.user
user_id = int(user["id"])

# =========================================================
# DATABASE INITIALIZATION
# =========================================================
def initialize_notifications_table():
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            notification_type TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            reference_type TEXT,
            reference_id TEXT,
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )

    # Safe upgrade in case reference_id was previously created as INTEGER
    try:
        cursor.execute("PRAGMA table_info(notifications)")
        cols = {row[1]: row[2] for row in cursor.fetchall()}
        if "reference_id" not in cols:
            cursor.execute("ALTER TABLE notifications ADD COLUMN reference_id TEXT")
    except Exception:
        pass

    connection.commit()
    connection.close()

initialize_notifications_table()

# =========================================================
# HELPER FUNCTIONS
# =========================================================
def get_notification_counts():
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM notifications
        WHERE user_id = ?
          AND is_read = 0
        """,
        (user_id,),
    )
    unread = cursor.fetchone()[0]

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM notifications
        WHERE user_id = ?
        """,
        (user_id,),
    )
    total = cursor.fetchone()[0]

    connection.close()
    return unread, total


def mark_notification_as_read(notification_id):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        UPDATE notifications
        SET is_read = 1
        WHERE id = ?
          AND user_id = ?
        """,
        (notification_id, user_id),
    )

    connection.commit()
    connection.close()


def mark_all_as_read():
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        UPDATE notifications
        SET is_read = 1
        WHERE user_id = ?
        """,
        (user_id,),
    )

    connection.commit()
    connection.close()


def clear_read_notifications():
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        DELETE FROM notifications
        WHERE user_id = ?
          AND is_read = 1
        """,
        (user_id,),
    )

    connection.commit()
    connection.close()


def create_test_notification(
    notification_type,
    title,
    message,
    reference_type=None,
    reference_id=None,
):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT INTO notifications (
            user_id,
            notification_type,
            title,
            message,
            reference_type,
            reference_id,
            is_read
        )
        VALUES (?, ?, ?, ?, ?, ?, 0)
        """,
        (
            user_id,
            notification_type,
            title,
            message,
            reference_type,
            str(reference_id) if reference_id else None,
        ),
    )

    connection.commit()
    connection.close()


def get_notification_icon(notification_type):
    icons = {
        "Message": "💬",
        "Connection": "🤝",
        "Help": "🆘",
        "Wallet": "💰",
        "Gift": "🎁",
        "Creator": "⭐",
        "Security": "🔐",
        "Live": "📺",
        "Goal": "🎯",
        "System": "🌍",
        "Payout": "💳",
        "Transaction": "🧾",
        "Withdrawal": "🏧",
    }
    for key, icon in icons.items():
        if key.lower() == str(notification_type or "").strip().lower():
            return icon
    return "🔔"


def get_notifications(filter_choice="All"):
    connection = get_connection()
    cursor = connection.cursor()

    if filter_choice == "Unread Only":
        cursor.execute(
            """
            SELECT
                id,
                notification_type,
                title,
                message,
                reference_type,
                reference_id,
                is_read,
                created_at
            FROM notifications
            WHERE user_id = ? AND is_read = 0
            ORDER BY id DESC
            """,
            (user_id,),
        )
    elif filter_choice == "Financial (Wallet/Gifts/Payouts)":
        cursor.execute(
            """
            SELECT
                id,
                notification_type,
                title,
                message,
                reference_type,
                reference_id,
                is_read,
                created_at
            FROM notifications
            WHERE user_id = ? AND (
                LOWER(notification_type) IN ('wallet', 'gift', 'creator', 'payout', 'transaction', 'withdrawal')
                OR LOWER(title) LIKE '%payout%'
                OR LOWER(title) LIKE '%withdrawal%'
                OR LOWER(title) LIKE '%transfer%'
            )
            ORDER BY id DESC
            """,
            (user_id,),
        )
    elif filter_choice == "Social & Connections":
        cursor.execute(
            """
            SELECT
                id,
                notification_type,
                title,
                message,
                reference_type,
                reference_id,
                is_read,
                created_at
            FROM notifications
            WHERE user_id = ? AND LOWER(notification_type) IN ('message', 'connection', 'live')
            ORDER BY id DESC
            """,
            (user_id,),
        )
    elif filter_choice == "Help & Requests":
        cursor.execute(
            """
            SELECT
                id,
                notification_type,
                title,
                message,
                reference_type,
                reference_id,
                is_read,
                created_at
            FROM notifications
            WHERE user_id = ? AND LOWER(notification_type) IN ('help', 'goal')
            ORDER BY id DESC
            """,
            (user_id,),
        )
    else:
        cursor.execute(
            """
            SELECT
                id,
                notification_type,
                title,
                message,
                reference_type,
                reference_id,
                is_read,
                created_at
            FROM notifications
            WHERE user_id = ?
            ORDER BY id DESC
            """,
            (user_id,),
        )

    rows = cursor.fetchall()
    connection.close()
    return rows


# =========================================================
# LOAD COUNTS
# =========================================================
unread_count, total_count = get_notification_counts()

# =========================================================
# PAGE HEADER
# =========================================================
st.title("🔔 Notifications")

st.write(
    "Stay updated with important activity happening "
    "across your LifeGrid account."
)

# =========================================================
# SUMMARY
# =========================================================
summary_col1, summary_col2, summary_col3 = st.columns(3)

with summary_col1:
    st.metric(
        "Unread",
        unread_count,
    )

with summary_col2:
    st.metric(
        "All Notifications",
        total_count,
    )

with summary_col3:
    if unread_count > 0:
        st.warning(
            f"You have {unread_count} unread "
            f"notification{'s' if unread_count != 1 else ''}."
        )
    else:
        st.success("You're all caught up.")

st.divider()

# =========================================================
# NOTIFICATION CONTROLS & FILTER
# =========================================================
st.subheader("⚙️ Notification Controls")

control_col1, control_col2, filter_col = st.columns([1, 1, 2])

with control_col1:
    if st.button(
        "✅ Mark All as Read",
        use_container_width=True,
    ):
        if unread_count == 0:
            st.info("There are no unread notifications.")
        else:
            mark_all_as_read()
            st.success("All notifications marked as read.")
            st.rerun()

with control_col2:
    if st.button(
        "🗑️ Clear Read Notifications",
        use_container_width=True,
    ):
        if total_count == 0:
            st.info("There are no notifications to clear.")
        else:
            clear_read_notifications()
            st.success("Read notifications cleared.")
            st.rerun()

with filter_col:
    active_filter = st.selectbox(
        "Filter Activity Feed",
        [
            "All",
            "Unread Only",
            "Financial (Wallet/Gifts/Payouts)",
            "Social & Connections",
            "Help & Requests",
        ],
        index=0,
        label_visibility="collapsed",
    )

st.divider()

# =========================================================
# LOAD NOTIFICATIONS
# =========================================================
notifications = get_notifications(active_filter)

# =========================================================
# DISPLAY NOTIFICATIONS
# =========================================================
st.subheader("📬 Your Notifications")

if not notifications:
    st.info(
        f"You don't have any notifications under '{active_filter}'. "
        "New activity will appear here."
    )
else:
    for notification in notifications:
        (
            notification_id,
            notification_type,
            title,
            message,
            reference_type,
            reference_id,
            is_read,
            created_at,
        ) = notification

        icon = get_notification_icon(notification_type)

        if is_read:
            status_label = "Read"
        else:
            status_label = "Unread"

        with st.container(border=True):
            notification_col1, notification_col2 = st.columns(
                [5, 1]
            )

            with notification_col1:
                if is_read:
                    st.markdown(
                        f"### 📭 {icon} {title}"
                    )
                else:
                    st.markdown(
                        f"### 🔵 {icon} {title}"
                    )

                st.write(message)

                type_col, date_col, ref_col = st.columns([1, 1, 2])

                with type_col:
                    st.caption(
                        f"Type: {notification_type}"
                    )

                with date_col:
                    st.caption(
                        f"Date: {created_at}"
                    )

                with ref_col:
                    if reference_type and reference_id:
                        st.caption(
                            f"Reference: "
                            f"{reference_type} #{reference_id}"
                        )

            with notification_col2:
                if not is_read:
                    if st.button(
                        "Mark Read",
                        key=f"mark_read_{notification_id}",
                        use_container_width=True,
                    ):
                        mark_notification_as_read(
                            notification_id
                        )
                        st.rerun()
                else:
                    st.caption("✓ Read")

st.divider()

# =========================================================
# NOTIFICATION TESTING
# =========================================================
with st.expander("🧪 Development Notification Test", expanded=False):
    st.info(
        "This testing section helps us verify that LifeGrid "
        "notifications and financial events are working correctly during development. "
        "It can be removed or restricted before production."
    )

    with st.form("notification_test_form"):
        col_t1, col_t2 = st.columns(2)
        with col_t1:
            notification_type = st.selectbox(
                "Notification Type",
                [
                    "Wallet",
                    "Payout",
                    "Gift",
                    "Message",
                    "Connection",
                    "Help",
                    "Creator",
                    "Live",
                    "Goal",
                    "Security",
                    "System",
                ],
            )
            notification_title = st.text_input(
                "Notification Title",
                value="Payout Disbursed Successfully",
            )
        with col_t2:
            test_ref_type = st.selectbox(
                "Reference Type",
                ["Payout_Ref", "Transaction_Ref", "Gift_Ref", "Message_Ref", "None"],
                index=0,
            )
            test_ref_id = st.text_input(
                "Reference ID / Code",
                value="FLW-TRF-982341",
            )

        notification_message = st.text_area(
            "Notification Message",
            value="Your withdrawal of NGN 35,000.00 was disbursed by Flutterwave.",
        )

        create_notification = st.form_submit_button(
            "🔔 Create Test Notification",
            type="primary",
            use_container_width=True,
        )

    if create_notification:
        if not notification_title.strip():
            st.error("Please enter a notification title.")
        elif not notification_message.strip():
            st.error("Please enter a notification message.")
        else:
            ref_type_val = None if test_ref_type == "None" else test_ref_type
            ref_id_val = None if test_ref_type == "None" or not test_ref_id.strip() else test_ref_id.strip()
            create_test_notification(
                notification_type,
                notification_title.strip(),
                notification_message.strip(),
                reference_type=ref_type_val,
                reference_id=ref_id_val,
            )
            st.success("Test notification created successfully.")
            st.rerun()

# =========================================================
# LIFEGRID NOTIFICATION CATEGORIES
# =========================================================
st.divider()

st.subheader("🌍 LifeGrid Activity")

category_col1, category_col2, category_col3 = st.columns(3)

with category_col1:
    st.markdown("### 💬 Messages")
    st.write(
        "Receive notifications when you receive "
        "new messages from your connections."
    )

    st.markdown("### 🤝 Connections")
    st.write(
        "Stay informed about connection requests "
        "and accepted connections."
    )

    st.markdown("### 🆘 Help")
    st.write(
        "Get updates when help is requested, "
        "accepted, completed, or confirmed."
    )

with category_col2:
    st.markdown("### 💰 Wallet")
    st.write(
        "Receive notifications about deposits, "
        "withdrawals, gifts, earnings, and other "
        "wallet activity."
    )

    st.markdown("### 🎁 Gifts")
    st.write(
        "Stay informed when someone sends you "
        "a gift or other supported contribution."
    )

    st.markdown("### ⭐ Creator")
    st.write(
        "Receive updates related to creator activity, "
        "audience engagement, and monetization."
    )

with category_col3:
    st.markdown("### 📺 Live")
    st.write(
        "Receive relevant notifications about "
        "live activity and supported live events."
    )

    st.markdown("### 🎯 Goals")
    st.write(
        "Stay updated when important goal activity "
        "takes place on your account."
    )

    st.markdown("### 🔐 Security")
    st.write(
        "Receive alerts for important account and "
        "security activity."
    )

# =========================================================
# FOOTER
# =========================================================
st.divider()
st.caption(
    "LifeGrid Notifications • Stay Connected • Stay Informed"
)
