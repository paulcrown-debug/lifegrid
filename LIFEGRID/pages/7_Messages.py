import sqlite3

import streamlit as st

from database import get_connection


st.set_page_config(
    page_title="Messages | LifeGrid",
    page_icon="💬",
    layout="wide",
)


# ============================================================
# LOGIN PROTECTION
# ============================================================

if "user" not in st.session_state or not st.session_state.user:
    st.warning("Please log in to access LifeGrid Messages.")

    if st.button("Go to Login", use_container_width=True):
        st.switch_page("app.py")

    st.stop()


user = st.session_state.user

try:
    user_id = int(user["id"])
except (KeyError, TypeError, ValueError):
    st.error("Your login session is invalid. Please log in again.")
    st.stop()


# ============================================================
# DATABASE SETUP
# ============================================================


def ensure_message_tables():
    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_one_id INTEGER NOT NULL,
                user_two_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_one_id, user_two_id),
                FOREIGN KEY (user_one_id) REFERENCES users(id),
                FOREIGN KEY (user_two_id) REFERENCES users(id)
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                sender_id INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                is_read INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id),
                FOREIGN KEY (sender_id) REFERENCES users(id),
                FOREIGN KEY (receiver_id) REFERENCES users(id)
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                notification_type TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                reference_type TEXT,
                reference_id INTEGER,
                is_read INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )

        connection.commit()

    finally:
        connection.close()


try:
    ensure_message_tables()
except sqlite3.Error as error:
    st.error(f"Could not prepare the messaging database: {error}")
    st.stop()


# ============================================================
# DATABASE HELPERS
# ============================================================


def get_or_create_conversation(first_user_id, second_user_id):
    first_user_id = int(first_user_id)
    second_user_id = int(second_user_id)

    if first_user_id == second_user_id:
        return None

    user_one_id = min(first_user_id, second_user_id)
    user_two_id = max(first_user_id, second_user_id)

    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT id
            FROM conversations
            WHERE user_one_id = ?
              AND user_two_id = ?
            """,
            (user_one_id, user_two_id),
        )

        row = cursor.fetchone()

        if row:
            return int(row[0])

        try:
            cursor.execute(
                """
                INSERT INTO conversations (
                    user_one_id,
                    user_two_id
                )
                VALUES (?, ?)
                """,
                (user_one_id, user_two_id),
            )
            connection.commit()
            return int(cursor.lastrowid)

        except sqlite3.IntegrityError:
            connection.rollback()
            cursor.execute(
                """
                SELECT id
                FROM conversations
                WHERE user_one_id = ?
                  AND user_two_id = ?
                """,
                (user_one_id, user_two_id),
            )
            row = cursor.fetchone()
            return int(row[0]) if row else None

    finally:
        connection.close()


def create_message_notification(receiver_id, sender_name, message_id):
    receiver_id = int(receiver_id)
    message_id = int(message_id)

    connection = get_connection()

    try:
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
                receiver_id,
                "Message",
                "New message",
                f"You received a new message from {sender_name}.",
                "message",
                message_id,
            ),
        )
        connection.commit()

    except sqlite3.Error:
        connection.rollback()

    finally:
        connection.close()


def send_message(conversation_id, sender_id, receiver_id, message_text):
    conversation_id = int(conversation_id)
    sender_id = int(sender_id)
    receiver_id = int(receiver_id)
    message_text = message_text.strip()

    if not message_text:
        return None, "Please enter a message."

    if sender_id == receiver_id:
        return None, "You cannot send a private message to yourself."

    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT id
            FROM conversations
            WHERE id = ?
              AND (
                  (user_one_id = ? AND user_two_id = ?)
                  OR
                  (user_one_id = ? AND user_two_id = ?)
              )
            """,
            (
                conversation_id,
                sender_id,
                receiver_id,
                receiver_id,
                sender_id,
            ),
        )

        verified = cursor.fetchone()

        if not verified:
            return None, "This conversation could not be verified."

        cursor.execute(
            """
            INSERT INTO messages (
                conversation_id,
                sender_id,
                receiver_id,
                message,
                is_read
            )
            VALUES (?, ?, ?, ?, 0)
            """,
            (
                conversation_id,
                sender_id,
                receiver_id,
                message_text,
            ),
        )

        message_id = int(cursor.lastrowid)

        cursor.execute(
            """
            UPDATE conversations
            SET updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND (
                  user_one_id = ?
                  OR user_two_id = ?
              )
            """,
            (conversation_id, sender_id, sender_id),
        )

        connection.commit()
        return message_id, None

    except sqlite3.Error as error:
        connection.rollback()
        return None, f"Could not send the message: {error}"

    finally:
        connection.close()


def get_active_users(current_user_id):
    connection = get_connection()

    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT
                id,
                username,
                full_name,
                country
            FROM users
            WHERE id != ?
              AND is_active = 1
            ORDER BY username COLLATE NOCASE
            """,
            (current_user_id,),
        )
        return cursor.fetchall()

    except sqlite3.Error:
        return []

    finally:
        connection.close()


def get_conversations(current_user_id):
    connection = get_connection()

    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT
                id,
                user_one_id,
                user_two_id,
                updated_at
            FROM conversations
            WHERE user_one_id = ?
               OR user_two_id = ?
            ORDER BY updated_at DESC, id DESC
            """,
            (current_user_id, current_user_id),
        )
        return cursor.fetchall()

    finally:
        connection.close()


def get_other_user(other_user_id):
    connection = get_connection()

    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT
                id,
                username,
                full_name,
                country
            FROM users
            WHERE id = ?
              AND is_active = 1
            """,
            (int(other_user_id),),
        )
        return cursor.fetchone()

    finally:
        connection.close()


def get_latest_message(conversation_id, current_user_id, other_user_id):
    connection = get_connection()

    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT
                message,
                sender_id,
                receiver_id,
                created_at
            FROM messages
            WHERE conversation_id = ?
              AND (
                  (sender_id = ? AND receiver_id = ?)
                  OR
                  (sender_id = ? AND receiver_id = ?)
              )
            ORDER BY id DESC
            LIMIT 1
            """,
            (
                int(conversation_id),
                int(current_user_id),
                int(other_user_id),
                int(other_user_id),
                int(current_user_id),
            ),
        )
        return cursor.fetchone()

    finally:
        connection.close()


def get_unread_count(conversation_id, current_user_id, other_user_id):
    connection = get_connection()

    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM messages
            WHERE conversation_id = ?
              AND receiver_id = ?
              AND sender_id = ?
              AND is_read = 0
            """,
            (
                int(conversation_id),
                int(current_user_id),
                int(other_user_id),
            ),
        )
        return int(cursor.fetchone()[0])

    finally:
        connection.close()


def get_conversation_messages(conversation_id, current_user_id, other_user_id):
    connection = get_connection()

    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT
                id,
                sender_id,
                receiver_id,
                message,
                is_read,
                created_at
            FROM messages
            WHERE conversation_id = ?
              AND (
                  (sender_id = ? AND receiver_id = ?)
                  OR
                  (sender_id = ? AND receiver_id = ?)
              )
            ORDER BY id ASC
            """,
            (
                int(conversation_id),
                int(current_user_id),
                int(other_user_id),
                int(other_user_id),
                int(current_user_id),
            ),
        )
        messages = cursor.fetchall()

        cursor.execute(
            """
            UPDATE messages
            SET is_read = 1
            WHERE conversation_id = ?
              AND receiver_id = ?
              AND sender_id = ?
              AND is_read = 0
            """,
            (
                int(conversation_id),
                int(current_user_id),
                int(other_user_id),
            ),
        )
        connection.commit()

        return messages

    finally:
        connection.close()


def get_message_statistics(current_user_id):
    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM messages
            WHERE receiver_id = ?
              AND is_read = 0
            """,
            (current_user_id,),
        )
        unread = int(cursor.fetchone()[0])

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM messages
            WHERE sender_id = ?
            """,
            (current_user_id,),
        )
        sent = int(cursor.fetchone()[0])

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM messages
            WHERE receiver_id = ?
            """,
            (current_user_id,),
        )
        received = int(cursor.fetchone()[0])

        return unread, sent, received

    finally:
        connection.close()


# ============================================================
# PAGE HEADER
# ============================================================

st.title("💬 LifeGrid Messages")
st.write("Communicate privately with other LifeGrid members.")
st.caption(
    "Private one-to-one messaging with conversation history, "
    "read status, notifications, and Connections integration."
)
st.divider()


# ============================================================
# MESSAGE STATISTICS
# ============================================================

unread_messages, messages_sent, messages_received = get_message_statistics(
    user_id
)

stat_col1, stat_col2, stat_col3 = st.columns(3)

with stat_col1:
    st.metric("Unread Messages", unread_messages)

with stat_col2:
    st.metric("Messages Sent", messages_sent)

with stat_col3:
    st.metric("Messages Received", messages_received)

st.divider()


# ============================================================
# ACTIVE USERS
# ============================================================

other_users = get_active_users(user_id)


# ============================================================
# NEW MESSAGE
# ============================================================

st.subheader("✉️ Send a New Message")

if not other_users:
    st.info("There are no other active LifeGrid users yet.")
else:
    user_options = {}

    for other_user in other_users:
        other_user_id, username, full_name, country = other_user
        other_user_id = int(other_user_id)

        display_name = full_name.strip() if full_name else username
        label = f"{display_name} (@{username})"

        if country:
            label += f" • {country}"

        user_options[label] = other_user_id

    option_labels = list(user_options.keys())

    # Connections can place a recipient in session state before opening
    # this page. This makes Connections -> Message open the correct user.
    requested_recipient_id = st.session_state.get("message_recipient_id")
    default_user_index = 0

    if requested_recipient_id is not None:
        try:
            requested_recipient_id = int(requested_recipient_id)

            for index, label in enumerate(option_labels):
                if user_options[label] == requested_recipient_id:
                    default_user_index = index
                    break
        except (TypeError, ValueError):
            default_user_index = 0

    selected_user_label = st.selectbox(
        "Select a LifeGrid user",
        option_labels,
        index=default_user_index,
        key="message_recipient_select",
    )

    selected_user_id = int(user_options[selected_user_label])

    # The recipient has now been consumed by this page.
    if "message_recipient_id" in st.session_state:
        st.session_state.pop("message_recipient_id", None)

    message_text = st.text_area(
        "Message",
        placeholder="Write your message...",
        height=120,
        key="new_message_text",
    )

    if st.button(
        "📨 Send Message",
        type="primary",
        use_container_width=True,
        key="send_new_message",
    ):
        if not message_text.strip():
            st.error("Please enter a message.")
        elif selected_user_id == user_id:
            st.error("You cannot send a private message to yourself.")
        else:
            try:
                conversation_id = get_or_create_conversation(
                    user_id,
                    selected_user_id,
                )

                if conversation_id is None:
                    st.error("Unable to create the conversation.")
                else:
                    message_id, send_error = send_message(
                        conversation_id,
                        user_id,
                        selected_user_id,
                        message_text,
                    )

                    if send_error:
                        st.error(send_error)
                    else:
                        sender_name = (
                            user.get("full_name")
                            or user.get("username")
                            or "A LifeGrid user"
                        )

                        create_message_notification(
                            selected_user_id,
                            sender_name,
                            message_id,
                        )

                        st.session_state["selected_conversation"] = conversation_id
                        st.success("Message sent successfully.")
                        st.rerun()

            except sqlite3.Error as error:
                st.error(f"Could not send the message: {error}")

st.divider()


# ============================================================
# CONVERSATION LIST
# ============================================================

st.subheader("💬 My Conversations")

conversations = get_conversations(user_id)

if not conversations:
    st.info("You don't have any conversations yet.")
else:
    for conversation in conversations:
        conversation_id, user_one_id, user_two_id, updated_at = conversation

        conversation_id = int(conversation_id)
        user_one_id = int(user_one_id)
        user_two_id = int(user_two_id)

        if user_id not in (user_one_id, user_two_id):
            continue

        other_user_id = (
            user_two_id if user_one_id == user_id else user_one_id
        )

        other_user = get_other_user(other_user_id)

        if not other_user:
            continue

        _, other_username, other_full_name, other_country = other_user
        other_display_name = (
            other_full_name.strip()
            if other_full_name
            else other_username
        )

        latest_message = get_latest_message(
            conversation_id,
            user_id,
            other_user_id,
        )

        conversation_unread = get_unread_count(
            conversation_id,
            user_id,
            other_user_id,
        )

        with st.container(border=True):
            conversation_col1, conversation_col2 = st.columns([5, 1])

            with conversation_col1:
                st.markdown(f"### 👤 {other_display_name}")
                st.caption(f"@{other_username}")

                if other_country:
                    st.caption(f"Country: {other_country}")

                if latest_message:
                    (
                        latest_text,
                        latest_sender_id,
                        latest_receiver_id,
                        latest_created_at,
                    ) = latest_message

                    latest_sender_id = int(latest_sender_id)
                    latest_receiver_id = int(latest_receiver_id)

                    if latest_sender_id == user_id:
                        prefix = "You: "
                    elif latest_sender_id == other_user_id and latest_receiver_id == user_id:
                        prefix = f"{other_display_name}: "
                    else:
                        continue

                    st.write(f"{prefix}{latest_text}")
                    st.caption(f"Last message: {latest_created_at}")
                else:
                    st.caption("No messages yet.")

            with conversation_col2:
                if conversation_unread > 0:
                    st.error(f"{conversation_unread} unread")
                else:
                    st.success("Up to date")

                if st.button(
                    "Open",
                    key=f"open_conversation_{conversation_id}",
                    use_container_width=True,
                ):
                    st.session_state["selected_conversation"] = conversation_id
                    st.rerun()


# ============================================================
# SELECTED CONVERSATION
# ============================================================

selected_conversation = st.session_state.get("selected_conversation")

if selected_conversation is not None:
    try:
        selected_conversation = int(selected_conversation)
    except (TypeError, ValueError):
        st.session_state.pop("selected_conversation", None)
        selected_conversation = None


if selected_conversation is not None:
    st.divider()
    st.subheader("📖 Private Conversation")

    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                user_one_id,
                user_two_id
            FROM conversations
            WHERE id = ?
              AND (
                  user_one_id = ?
                  OR user_two_id = ?
              )
            """,
            (
                selected_conversation,
                user_id,
                user_id,
            ),
        )

        selected_conversation_data = cursor.fetchone()

    finally:
        connection.close()

    if not selected_conversation_data:
        st.error("You do not have access to this conversation.")
        st.session_state.pop("selected_conversation", None)
    else:
        conversation_user_one, conversation_user_two = selected_conversation_data
        conversation_user_one = int(conversation_user_one)
        conversation_user_two = int(conversation_user_two)

        other_user_id = (
            conversation_user_two
            if conversation_user_one == user_id
            else conversation_user_one
        )

        selected_other_user = get_other_user(other_user_id)

        if not selected_other_user:
            st.error("The other participant could not be found.")
        else:
            (
                _,
                selected_other_username,
                selected_other_full_name,
                selected_other_country,
            ) = selected_other_user

            selected_other_name = (
                selected_other_full_name.strip()
                if selected_other_full_name
                else selected_other_username
            )

            st.markdown(f"### Chat with {selected_other_name}")

            if selected_other_country:
                st.caption(f"Country: {selected_other_country}")

            conversation_messages = get_conversation_messages(
                selected_conversation,
                user_id,
                other_user_id,
            )

            if not conversation_messages:
                st.info("No messages in this conversation yet.")
            else:
                for conversation_message in conversation_messages:
                    (
                        message_id,
                        sender_id,
                        receiver_id,
                        message,
                        is_read,
                        created_at,
                    ) = conversation_message

                    sender_id = int(sender_id)
                    receiver_id = int(receiver_id)

                    valid_message = (
                        sender_id == user_id and receiver_id == other_user_id
                    ) or (
                        sender_id == other_user_id and receiver_id == user_id
                    )

                    if not valid_message:
                        continue

                    if sender_id == user_id:
                        st.markdown("### 🟢 You")
                    else:
                        st.markdown(f"### 🔵 {selected_other_name}")

                    st.write(message)
                    st.caption(str(created_at))
                    st.divider()

            st.markdown("#### ✉️ Reply")

            reply_text = st.text_area(
                "Write a reply",
                key=f"reply_{selected_conversation}",
                height=100,
            )

            if st.button(
                "📨 Send Reply",
                key=f"send_reply_{selected_conversation}",
                type="primary",
                use_container_width=True,
            ):
                if not reply_text.strip():
                    st.error("Please enter a reply.")
                else:
                    message_id, send_error = send_message(
                        selected_conversation,
                        user_id,
                        other_user_id,
                        reply_text,
                    )

                    if send_error:
                        st.error(send_error)
                    else:
                        sender_name = (
                            user.get("full_name")
                            or user.get("username")
                            or "A LifeGrid user"
                        )

                        create_message_notification(
                            other_user_id,
                            sender_name,
                            message_id,
                        )

                        st.success("Reply sent successfully.")
                        st.rerun()

            if st.button(
                "✖ Close Conversation",
                key=f"close_conversation_{selected_conversation}",
            ):
                st.session_state.pop("selected_conversation", None)
                st.rerun()


# ============================================================
# FUTURE FEATURES
# ============================================================

st.divider()
st.subheader("🚀 Future Messaging Features")

future_col1, future_col2, future_col3 = st.columns(3)

with future_col1:
    st.markdown("### ⚡ Real-Time Chat")
    st.write("Faster live conversations and real-time message updates.")

with future_col2:
    st.markdown("### 📎 Media & Files")
    st.write("Future support for images, documents, voice, and approved media.")

with future_col3:
    st.markdown("### 🛡️ Safety")
    st.write("Blocking, reporting, moderation, privacy controls, and account safety features.")

st.divider()
st.caption("LifeGrid Messages • Connect • Communicate • Grow")
