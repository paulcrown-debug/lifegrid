import sqlite3
import os

import streamlit as st

from database import get_connection
from auth import log_activity


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="Connections | LifeGrid",
    page_icon="🤝",
    layout="wide",
)


# ============================================================
# LOGIN CHECK
# ============================================================

if "user" not in st.session_state or not st.session_state.user:
    st.warning("Please log in to access Connections.")
    st.stop()

current_user = st.session_state.user
current_user_id = int(current_user["id"])


# ============================================================
# SAFE NAVIGATION HELPER
# ============================================================

def safe_switch_page(candidates, fallback_message=""):
    """
    Search for existing page files dynamically to avoid StreamlitPageNotFoundError.
    """
    if not hasattr(st, "switch_page"):
        if fallback_message:
            st.info(fallback_message)
        return

    pages_dir = os.path.join(os.getcwd(), "pages")
    existing_pages = []
    if os.path.exists(pages_dir):
        for f in os.listdir(pages_dir):
            if f.endswith(".py"):
                existing_pages.append(f"pages/{f}")

    for candidate in candidates:
        if candidate in existing_pages or os.path.exists(candidate):
            try:
                st.switch_page(candidate)
                return
            except Exception:
                pass

        clean_target = candidate.lower().replace("pages/", "").replace(".py", "")
        for ep in existing_pages:
            clean_ep = ep.lower().replace("pages/", "").replace(".py", "")
            if clean_target in clean_ep or any(part in clean_ep for part in clean_target.split("_")):
                try:
                    st.switch_page(ep)
                    return
                except Exception:
                    pass

    if fallback_message:
        st.info(fallback_message)


# ============================================================
# DATABASE HELPERS
# ============================================================

def get_columns(table_name):
    conn = get_connection()
    try:
        rows = conn.execute(
            f"PRAGMA table_info({table_name})"
        ).fetchall()
        return [row[1] for row in rows]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def get_user(user_id):
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT
                id,
                username,
                full_name,
                country,
                bio,
                skills,
                interests
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()

        if row is None:
            return None

        return {
            "id": row[0],
            "username": row[1],
            "full_name": row[2],
            "country": row[3],
            "bio": row[4],
            "skills": row[5],
            "interests": row[6],
        }
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def get_display_name(user):
    if not user:
        return "LifeGrid User"

    full_name = user.get("full_name")
    username = user.get("username")

    if full_name:
        return str(full_name)

    if username:
        return str(username)

    return "LifeGrid User"


# ============================================================
# NOTIFICATIONS
# ============================================================

def create_notification(
    user_id,
    title,
    message,
    notification_type="Connection",
    reference_type="connection",
    reference_id=None,
):
    conn = get_connection()
    try:
        columns = get_columns("notifications")

        if "user_id" not in columns:
            return

        if "title" not in columns:
            return

        if "message" not in columns:
            return

        insert_columns = [
            "user_id",
            "title",
            "message",
        ]

        values = [
            user_id,
            title,
            message,
        ]

        if "notification_type" in columns:
            insert_columns.append("notification_type")
            values.append(notification_type)

        if "reference_type" in columns:
            insert_columns.append("reference_type")
            values.append(reference_type)

        if "reference_id" in columns:
            insert_columns.append("reference_id")
            values.append(reference_id)

        if "is_read" in columns:
            insert_columns.append("is_read")
            values.append(0)

        placeholders = ", ".join(
            ["?"] * len(insert_columns)
        )
        column_text = ", ".join(insert_columns)
        query = (
            "INSERT INTO notifications "
            f"({column_text}) "
            f"VALUES ({placeholders})"
        )

        conn.execute(
            query,
            values,
        )
        conn.commit()

    except sqlite3.Error:
        pass
    finally:
        conn.close()


# ============================================================
# ACTIVITY LOG
# ============================================================

def record_activity(
    activity_title,
    activity_description,
    reference_id=None,
):
    try:
        log_activity(
            user_id=current_user_id,
            activity_type="connection",
            activity_title=activity_title,
            activity_description=activity_description,
            reference_type="connection",
            reference_id=reference_id,
        )
    except Exception:
        pass


# ============================================================
# FIND EXISTING CONNECTION
# ============================================================

def get_existing_connection(user_a, user_b):
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT
                id,
                requester_id,
                receiver_id,
                status,
                requested_by,
                created_at
            FROM connections
            WHERE
                (
                    requester_id = ?
                    AND receiver_id = ?
                )
                OR
                (
                    requester_id = ?
                    AND receiver_id = ?
                )
            ORDER BY id DESC
            LIMIT 1
            """,
            (
                user_a,
                user_b,
                user_b,
                user_a,
            ),
        ).fetchone()

        if row is None:
            return None

        return {
            "id": row[0],
            "requester_id": row[1],
            "receiver_id": row[2],
            "status": row[3],
            "requested_by": row[4],
            "created_at": row[5],
        }

    except sqlite3.Error:
        return None
    finally:
        conn.close()


# ============================================================
# CHECK IF CONNECTED
# ============================================================

def are_connected(user_a, user_b):
    if int(user_a) == int(user_b):
        return False

    existing = get_existing_connection(
        int(user_a),
        int(user_b),
    )

    if not existing:
        return False

    return existing["status"] == "accepted"


# ============================================================
# SEND CONNECTION REQUEST
# ============================================================

def send_connection_request(receiver_id):
    receiver_id = int(receiver_id)

    if receiver_id == current_user_id:
        return (
            False,
            "You cannot send a connection request to yourself.",
        )

    receiver = get_user(receiver_id)

    if receiver is None:
        return (
            False,
            "The selected LifeGrid user could not be found.",
        )

    existing = get_existing_connection(
        current_user_id,
        receiver_id,
    )

    if existing:
        status = str(
            existing["status"]
            or ""
        ).lower()

        if status == "accepted":
            return (
                False,
                "You are already connected to this person.",
            )

        if status == "pending":
            if (
                int(existing["requester_id"])
                == current_user_id
            ):
                return (
                    False,
                    "You have already sent a connection request to this person.",
                )

            return (
                False,
                "This person has already sent you a connection request. "
                "Please open Connection Requests and respond to it.",
            )

        if status == "declined":
            conn = get_connection()
            try:
                conn.execute(
                    """
                    DELETE FROM connections
                    WHERE id = ?
                    """,
                    (existing["id"],),
                )
                conn.commit()
            except sqlite3.Error as error:
                return (
                    False,
                    f"Could not create a new request: {error}",
                )
            finally:
                conn.close()

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO connections
            (
                requester_id,
                receiver_id,
                status,
                requested_by
            )
            VALUES
            (
                ?,
                ?,
                'pending',
                ?
            )
            """,
            (
                current_user_id,
                receiver_id,
                current_user_id,
            ),
        )
        connection_id = cursor.lastrowid
        conn.commit()

    except sqlite3.IntegrityError as error:
        return (
            False,
            f"Could not send connection request: {error}",
        )
    except sqlite3.Error as error:
        return (
            False,
            f"Database error: {error}",
        )
    finally:
        conn.close()

    sender_name = get_display_name(
        current_user
    )

    create_notification(
        user_id=receiver_id,
        title="New Connection Request",
        message=(
            f"{sender_name} sent you a "
            "LifeGrid connection request."
        ),
        notification_type="Connection",
        reference_type="connection",
        reference_id=connection_id,
    )

    record_activity(
        activity_title="Connection request sent",
        activity_description=(
            f"Connection request sent to "
            f"user {receiver_id}."
        ),
        reference_id=connection_id,
    )

    return (
        True,
        "Connection request sent successfully.",
    )


# ============================================================
# GET PENDING REQUESTS
# ============================================================

def get_pending_requests():
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT
                c.id,
                c.requester_id,
                c.receiver_id,
                c.status,
                c.created_at,
                u.username,
                u.full_name,
                u.country,
                u.bio,
                u.skills,
                u.interests
            FROM connections c
            INNER JOIN users u
                ON u.id = c.requester_id
            WHERE
                c.receiver_id = ?
                AND c.status = 'pending'
            ORDER BY c.id DESC
            """,
            (current_user_id,),
        ).fetchall()

        requests = []
        for row in rows:
            requests.append(
                {
                    "id": row[0],
                    "requester_id": row[1],
                    "receiver_id": row[2],
                    "status": row[3],
                    "created_at": row[4],
                    "username": row[5],
                    "full_name": row[6],
                    "country": row[7],
                    "bio": row[8],
                    "skills": row[9],
                    "interests": row[10],
                }
            )
        return requests
    except sqlite3.Error:
        return []
    finally:
        conn.close()


# ============================================================
# RESPOND TO CONNECTION REQUEST
# ============================================================

def respond_to_request(
    connection_id,
    new_status,
):
    allowed_statuses = {
        "accepted",
        "declined",
    }

    if new_status not in allowed_statuses:
        return False, "Invalid connection response."

    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT
                id,
                requester_id,
                receiver_id,
                status
            FROM connections
            WHERE
                id = ?
                AND receiver_id = ?
                AND status = 'pending'
            """,
            (
                connection_id,
                current_user_id,
            ),
        ).fetchone()

        if row is None:
            return (
                False,
                "This connection request is no longer pending.",
            )

        requester_id = int(row[1])

        conn.execute(
            """
            UPDATE connections
            SET
                status = ?,
                responded_at = CURRENT_TIMESTAMP
            WHERE
                id = ?
                AND receiver_id = ?
                AND status = 'pending'
            """,
            (
                new_status,
                connection_id,
                current_user_id,
            ),
        )
        conn.commit()

    except sqlite3.Error as error:
        return (
            False,
            f"Could not update the connection request: {error}",
        )
    finally:
        conn.close()

    current_user_name = get_display_name(
        current_user
    )

    if new_status == "accepted":
        create_notification(
            user_id=requester_id,
            title="Connection Request Accepted",
            message=(
                f"{current_user_name} accepted "
                "your LifeGrid connection request."
            ),
            notification_type="Connection",
            reference_type="connection",
            reference_id=connection_id,
        )

        record_activity(
            activity_title="Connection request accepted",
            activity_description=(
                f"Connection request "
                f"{connection_id} was accepted."
            ),
            reference_id=connection_id,
        )

        return (
            True,
            "Connection request accepted.",
        )

    create_notification(
        user_id=requester_id,
        title="Connection Request Declined",
        message=(
            f"{current_user_name} declined "
            "your LifeGrid connection request."
        ),
        notification_type="Connection",
        reference_type="connection",
        reference_id=connection_id,
    )

    record_activity(
        activity_title="Connection request declined",
        activity_description=(
            f"Connection request "
            f"{connection_id} was declined."
        ),
        reference_id=connection_id,
    )

    return (
        True,
        "Connection request declined.",
    )


# ============================================================
# GET MY ACCEPTED CONNECTIONS
# ============================================================

def get_my_connections():
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT
                c.id,
                c.requester_id,
                c.receiver_id,
                c.status,
                c.created_at,
                u.id,
                u.username,
                u.full_name,
                u.country,
                u.bio,
                u.skills,
                u.interests
            FROM connections c
            INNER JOIN users u
                ON u.id =
                    CASE
                        WHEN c.requester_id = ?
                        THEN c.receiver_id
                        ELSE c.requester_id
                    END
            WHERE
                (
                    c.requester_id = ?
                    OR c.receiver_id = ?
                )
                AND c.status = 'accepted'
            ORDER BY c.id DESC
            """,
            (
                current_user_id,
                current_user_id,
                current_user_id,
            ),
        ).fetchall()

        connections = []
        for row in rows:
            connections.append(
                {
                    "id": row[0],
                    "requester_id": row[1],
                    "receiver_id": row[2],
                    "status": row[3],
                    "created_at": row[4],
                    "user_id": row[5],
                    "username": row[6],
                    "full_name": row[7],
                    "country": row[8],
                    "bio": row[9],
                    "skills": row[10],
                    "interests": row[11],
                }
            )
        return connections
    except sqlite3.Error:
        return []
    finally:
        conn.close()


# ============================================================
# GET PEOPLE
# ============================================================

def get_people(search_text=""):
    conn = get_connection()
    try:
        search_text = search_text.strip()

        if search_text:
            search_value = (
                f"%{search_text.lower()}%"
            )

            rows = conn.execute(
                """
                SELECT
                    id,
                    username,
                    full_name,
                    country,
                    bio,
                    skills,
                    interests
                FROM users
                WHERE
                    id != ?
                    AND is_active = 1
                    AND (
                        LOWER(COALESCE(full_name, ''))
                            LIKE ?
                        OR LOWER(COALESCE(username, ''))
                            LIKE ?
                        OR LOWER(COALESCE(country, ''))
                            LIKE ?
                        OR LOWER(COALESCE(bio, ''))
                            LIKE ?
                        OR LOWER(COALESCE(skills, ''))
                            LIKE ?
                        OR LOWER(COALESCE(interests, ''))
                            LIKE ?
                    )
                ORDER BY username
                """,
                (
                    current_user_id,
                    search_value,
                    search_value,
                    search_value,
                    search_value,
                    search_value,
                    search_value,
                ),
            ).fetchall()

        else:
            rows = conn.execute(
                """
                SELECT
                    id,
                    username,
                    full_name,
                    country,
                    bio,
                    skills,
                    interests
                FROM users
                WHERE
                    id != ?
                    AND is_active = 1
                ORDER BY username
                """,
                (current_user_id,),
            ).fetchall()

        people = []
        for row in rows:
            people.append(
                {
                    "id": row[0],
                    "username": row[1],
                    "full_name": row[2],
                    "country": row[3],
                    "bio": row[4],
                    "skills": row[5],
                    "interests": row[6],
                }
            )
        return people
    except sqlite3.Error:
        return []
    finally:
        conn.close()


# ============================================================
# OPEN MESSAGES
# ============================================================

def open_messages(user_id):
    st.session_state[
        "message_recipient_id"
    ] = int(user_id)

    safe_switch_page(
        [
            "pages/7_Messages.py",
            "pages/07_Messages.py",
            "pages/06 - Messages.py",
            "pages/Messages.py",
            "pages/06_Messages.py",
        ],
        fallback_message="Please select 'Messages' from the left sidebar to open your conversation."
    )


# ============================================================
# OPEN HELP
# ============================================================

def open_request_help(user_id):
    st.session_state[
        "help_recipient_id"
    ] = int(user_id)

    st.session_state[
        "help_action"
    ] = "request"

    safe_switch_page(
        [
            "pages/4_Help.py",
            "pages/04_Help.py",
            "pages/03 - Help.py",
            "pages/Help.py",
            "pages/04 - Help.py",
        ],
        fallback_message="Please select 'Help' from the left sidebar to request assistance."
    )


def open_offer_help(user_id):
    st.session_state[
        "help_recipient_id"
    ] = int(user_id)

    st.session_state[
        "help_action"
    ] = "offer"

    safe_switch_page(
        [
            "pages/4_Help.py",
            "pages/04_Help.py",
            "pages/03 - Help.py",
            "pages/Help.py",
            "pages/04 - Help.py",
        ],
        fallback_message="Please select 'Help' from the left sidebar to offer assistance."
    )


# ============================================================
# DISPLAY PERSON
# ============================================================

def display_person(person):
    person_id = int(
        person["id"]
    )

    name = (
        person.get("full_name")
        or person.get("username")
        or "LifeGrid User"
    )

    with st.container(border=True):
        info_col, action_col = st.columns(
            [4, 1]
        )

        with info_col:
            st.markdown(
                f"### 👤 {name}"
            )

            username = person.get(
                "username"
            )

            if username:
                st.write(
                    f"@{username}"
                )

            country = person.get(
                "country"
            )

            if country:
                st.write(
                    f"🌍 {country}"
                )

            bio = person.get(
                "bio"
            )

            if bio:
                st.write(bio)

            skills = person.get(
                "skills"
            )

            if skills:
                st.write(
                    f"🛠️ Skills: {skills}"
                )

            interests = person.get(
                "interests"
            )

            if interests:
                st.write(
                    f"⭐ Interests: {interests}"
                )

        with action_col:
            existing = get_existing_connection(
                current_user_id,
                person_id,
            )

            if not existing:
                if st.button(
                    "🤝 Connect",
                    key=f"connect_{person_id}",
                    use_container_width=True,
                ):
                    success, message = (
                        send_connection_request(
                            person_id
                        )
                    )

                    if success:
                        st.success(message)
                        st.rerun()
                    else:
                        st.warning(message)

            else:
                status = str(
                    existing["status"]
                    or ""
                ).lower()

                requester_id = int(
                    existing["requester_id"]
                )

                receiver_id = int(
                    existing["receiver_id"]
                )

                if status == "accepted":
                    st.success(
                        "Connected"
                    )

                    if st.button(
                        "💬 Message",
                        key=f"message_{person_id}",
                        use_container_width=True,
                    ):
                        open_messages(
                            person_id
                        )

                    if st.button(
                        "🤲 Request Help",
                        key=f"request_help_{person_id}",
                        use_container_width=True,
                    ):
                        open_request_help(
                            person_id
                        )

                    if st.button(
                        "🙋 Offer Help",
                        key=f"offer_help_{person_id}",
                        use_container_width=True,
                    ):
                        open_offer_help(
                            person_id
                        )

                elif (
                    status == "pending"
                    and requester_id
                    == current_user_id
                ):
                    st.info(
                        "Request Sent"
                    )

                elif (
                    status == "pending"
                    and receiver_id
                    == current_user_id
                ):
                    st.info(
                        "Request Received"
                    )

                elif status == "declined":
                    if st.button(
                        "🤝 Connect Again",
                        key=f"reconnect_{person_id}",
                        use_container_width=True,
                    ):
                        success, message = (
                            send_connection_request(
                                person_id
                            )
                        )

                        if success:
                            st.success(message)
                            st.rerun()
                        else:
                            st.warning(message)


# ============================================================
# PAGE HEADER
# ============================================================

st.title("🤝 Connections")

st.write(
    "Discover people, build meaningful connections, "
    "and connect with members of the LifeGrid community."
)


# ============================================================
# TABS
# ============================================================

tab_discover, tab_connections, tab_requests = (
    st.tabs(
        [
            "🔎 Discover People",
            "🤝 My Connections",
            "📩 Requests",
        ]
    )
)


# ============================================================
# DISCOVER PEOPLE
# ============================================================

with tab_discover:
    st.subheader(
        "Discover LifeGrid Users"
    )

    st.write(
        "Search for people by name, username, "
        "country, skills, interests, or profile information."
    )

    search_text = st.text_input(
        "Search people",
        placeholder=(
            "Example: construction, Nigeria, developer..."
        ),
        key="connections_search",
    )

    people = get_people(
        search_text
    )

    if search_text.strip():
        st.caption(
            f"{len(people)} profile(s) found."
        )
    else:
        st.caption(
            f"{len(people)} active profile(s) available."
        )

    if not people:
        st.info(
            "No matching LifeGrid users were found."
        )
    else:
        for person in people:
            display_person(
                person
            )


# ============================================================
# MY CONNECTIONS
# ============================================================

with tab_connections:
    st.subheader(
        "My Connections"
    )

    connections = (
        get_my_connections()
    )

    if not connections:
        st.info(
            "You do not have any accepted "
            "connections yet."
        )
    else:
        st.write(
            f"You have {len(connections)} "
            "accepted connection(s)."
        )

        for person in connections:
            person_id = int(
                person["user_id"]
            )

            name = (
                person.get("full_name")
                or person.get("username")
                or "LifeGrid User"
            )

            with st.container(
                border=True
            ):
                info_col, action_col = (
                    st.columns([4, 1])
                )

                with info_col:
                    st.markdown(
                        f"### 👤 {name}"
                    )

                    username = person.get(
                        "username"
                    )

                    if username:
                        st.write(
                            f"@{username}"
                        )

                    country = person.get(
                        "country"
                    )

                    if country:
                        st.write(
                            f"🌍 {country}"
                        )

                    bio = person.get(
                        "bio"
                    )

                    if bio:
                        st.write(bio)

                    skills = person.get(
                        "skills"
                    )

                    if skills:
                        st.write(
                            f"🛠️ Skills: {skills}"
                        )

                    interests = person.get(
                        "interests"
                    )

                    if interests:
                        st.write(
                            f"⭐ Interests: {interests}"
                        )

                with action_col:
                    st.success(
                        "Connected"
                    )

                    if st.button(
                        "💬 Message",
                        key=(
                            f"my_message_"
                            f"{person_id}"
                        ),
                        use_container_width=True,
                    ):
                        open_messages(
                            person_id
                        )

                    if st.button(
                        "🤲 Request Help",
                        key=(
                            f"my_request_help_"
                            f"{person_id}"
                        ),
                        use_container_width=True,
                    ):
                        open_request_help(
                            person_id
                        )

                    if st.button(
                        "🙋 Offer Help",
                        key=(
                            f"my_offer_help_"
                            f"{person_id}"
                        ),
                        use_container_width=True,
                    ):
                        open_offer_help(
                            person_id
                        )


# ============================================================
# CONNECTION REQUESTS
# ============================================================

with tab_requests:
    st.subheader(
        "Connection Requests"
    )

    requests = (
        get_pending_requests()
    )

    if not requests:
        st.info(
            "You have no pending "
            "connection requests."
        )
    else:
        st.write(
            f"You have {len(requests)} "
            "pending request(s)."
        )

        for request in requests:
            requester_id = int(
                request["requester_id"]
            )

            requester_name = (
                request.get("full_name")
                or request.get("username")
                or "LifeGrid User"
            )

            with st.container(
                border=True
            ):
                st.markdown(
                    f"### 👤 {requester_name}"
                )

                username = request.get(
                    "username"
                )

                if username:
                    st.write(
                        f"@{username}"
                    )

                country = request.get(
                    "country"
                )

                if country:
                    st.write(
                        f"🌍 {country}"
                    )

                bio = request.get(
                    "bio"
                )

                if bio:
                    st.write(bio)

                skills = request.get(
                    "skills"
                )

                if skills:
                    st.write(
                        f"🛠️ Skills: {skills}"
                    )

                interests = request.get(
                    "interests"
                )

                if interests:
                    st.write(
                        f"⭐ Interests: {interests}"
                    )

                st.caption(
                    "Requested: "
                    f"{request.get('created_at')}"
                )

                accept_col, decline_col = (
                    st.columns(2)
                )

                with accept_col:
                    if st.button(
                        "✅ Accept",
                        key=(
                            f"accept_request_"
                            f"{request['id']}"
                        ),
                        use_container_width=True,
                    ):
                        success, message = (
                            respond_to_request(
                                int(request["id"]),
                                "accepted",
                            )
                        )

                        if success:
                            st.success(message)
                            st.rerun()
                        else:
                            st.error(message)

                with decline_col:
                    if st.button(
                        "❌ Decline",
                        key=(
                            f"decline_request_"
                            f"{request['id']}"
                        ),
                        use_container_width=True,
                    ):
                        success, message = (
                            respond_to_request(
                                int(request["id"]),
                                "declined",
                            )
                        )

                        if success:
                            st.success(message)
                            st.rerun()
                        else:
                            st.error(message)


# ============================================================
# INFORMATION
# ============================================================

st.divider()

st.info(
    "💡 LifeGrid Connections allows you to discover "
    "people, send and receive connection requests, "
    "accept or decline requests, message connections, "
    "request help, and offer help."
)