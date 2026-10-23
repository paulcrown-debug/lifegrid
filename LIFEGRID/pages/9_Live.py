import sqlite3
import uuid
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime

import streamlit as st

from database import get_connection

try:
    from streamlit_webrtc import WebRtcMode, webrtc_streamer

    WEBRTC_AVAILABLE = True
except ImportError:
    WEBRTC_AVAILABLE = False


# ---------------------------------------------------------
# PAGE CONFIGURATION
# ---------------------------------------------------------

st.set_page_config(
    page_title="Live | LifeGrid",
    page_icon="🔴",
    layout="wide",
)


# ---------------------------------------------------------
# LOGIN CHECK
# ---------------------------------------------------------

if not st.session_state.get("user"):
    st.warning("Please log in to access LifeGrid Live.")
    st.stop()


# ---------------------------------------------------------
# CURRENT USER
# ---------------------------------------------------------

user_id = int(st.session_state["user"]["id"])
username = st.session_state["user"].get("username", "User")
full_name = st.session_state["user"].get("full_name") or username


# ---------------------------------------------------------
# TIME HELPERS
# ---------------------------------------------------------

def format_live_time(value):
    if not value:
        return "Not started"

    try:
        dt = datetime.fromisoformat(value)
        return dt.strftime("%d %b %Y, %I:%M:%S %p")
    except (TypeError, ValueError):
        return str(value)


def calculate_live_duration(started_at, ended_at=None):
    if not started_at:
        return "—"

    try:
        start = datetime.fromisoformat(started_at)
        end = datetime.fromisoformat(ended_at) if ended_at else datetime.now()
        seconds = max(0, int((end - start).total_seconds()))

        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        if hours:
            return f"{hours}h {minutes}m {seconds}s"

        if minutes:
            return f"{minutes}m {seconds}s"

        return f"{seconds}s"

    except (TypeError, ValueError):
        return "—"


def parse_datetime_local(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------
# DATABASE SETUP
# ---------------------------------------------------------

def initialize_live_database():
    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS live_streams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                broadcaster_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                category TEXT,
                status TEXT DEFAULT 'scheduled',
                viewer_count INTEGER DEFAULT 0,
                stream_key TEXT,
                scheduled_at TEXT,
                started_at TEXT,
                ended_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS live_viewers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stream_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                joined_at TEXT DEFAULT CURRENT_TIMESTAMP,
                left_at TEXT,
                UNIQUE(stream_id, user_id)
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS live_chat (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stream_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS live_reactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stream_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                reaction TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        conn.commit()

        # -------------------------------------------------
        # Upgrade existing live_streams tables safely.
        # -------------------------------------------------

        columns = conn.execute(
            "PRAGMA table_info(live_streams)"
        ).fetchall()

        column_names = {row[1] for row in columns}

        if "scheduled_at" not in column_names:
            conn.execute(
                "ALTER TABLE live_streams ADD COLUMN scheduled_at TEXT"
            )

        conn.commit()

    finally:
        conn.close()


initialize_live_database()


# ---------------------------------------------------------
# CONNECTION / NOTIFICATION HELPERS
# ---------------------------------------------------------

def get_connected_user_ids():
    """
    Return accepted connection IDs for the current user.

    The function checks the actual connections table structure
    so Live remains compatible with the existing LifeGrid
    Connections module.
    """

    conn = get_connection()

    try:
        table_exists = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'connections'
            """
        ).fetchone()

        if not table_exists:
            return []

        columns = conn.execute(
            "PRAGMA table_info(connections)"
        ).fetchall()

        column_names = {row[1] for row in columns}

        if not {
            "requester_id",
            "receiver_id",
            "status",
        }.issubset(column_names):
            return []

        rows = conn.execute(
            """
            SELECT requester_id, receiver_id
            FROM connections
            WHERE status = 'accepted'
              AND (
                    requester_id = ?
                    OR receiver_id = ?
                  )
            """,
            (
                user_id,
                user_id,
            ),
        ).fetchall()

        connected_ids = set()

        for requester_id, receiver_id in rows:
            if requester_id == user_id:
                connected_ids.add(int(receiver_id))
            elif receiver_id == user_id:
                connected_ids.add(int(requester_id))

        return list(connected_ids)

    except sqlite3.Error:
        return []

    finally:
        conn.close()


def add_notification(
    target_user_id,
    title,
    message,
    reference_id,
):
    """
    Add one Live notification.

    Duplicate notifications for the same user, Live session,
    notification title, and notification type are prevented.
    """

    if not target_user_id:
        return False

    conn = get_connection()

    try:
        columns = conn.execute(
            "PRAGMA table_info(notifications)"
        ).fetchall()

        names = {row[1] for row in columns}

        required = {
            "user_id",
            "notification_type",
            "title",
            "message",
            "reference_type",
            "reference_id",
            "is_read",
            "created_at",
        }

        if not required.issubset(names):
            return False

        existing = conn.execute(
            """
            SELECT id
            FROM notifications
            WHERE user_id = ?
              AND notification_type = 'live'
              AND reference_type = 'live_stream'
              AND reference_id = ?
              AND title = ?
            LIMIT 1
            """,
            (
                target_user_id,
                str(reference_id),
                title,
            ),
        ).fetchone()

        if existing:
            return False

        conn.execute(
            """
            INSERT INTO notifications (
                user_id,
                notification_type,
                title,
                message,
                reference_type,
                reference_id,
                is_read,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                target_user_id,
                "live",
                title,
                message,
                "live_stream",
                str(reference_id),
                0,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )

        conn.commit()
        return True

    except sqlite3.Error:
        return False

    finally:
        conn.close()


def notify_connected_users(
    title,
    message,
    reference_id,
):
    """
    Send a Live notification to all accepted connections
    of the current broadcaster.
    """

    connected_ids = get_connected_user_ids()

    sent_count = 0

    for target_id in connected_ids:
        if target_id == user_id:
            continue

        if add_notification(
            target_id,
            title,
            message,
            reference_id,
        ):
            sent_count += 1

    return sent_count


def notify_live_scheduled(
    stream_id,
    title,
    scheduled_at,
):
    """
    Notify accepted connections that a Live has been scheduled.
    """

    display_name = full_name or username

    notification_title = "🔴 Live Scheduled"

    notification_message = (
        f"{display_name} has scheduled a Live session: "
        f"'{title}' for {format_live_time(scheduled_at)}."
    )

    return notify_connected_users(
        notification_title,
        notification_message,
        stream_id,
    )


def notify_live_started(
    stream_id,
    title,
):
    """
    Notify accepted connections that a Live is now active.
    """

    display_name = full_name or username

    notification_title = "🔴 Live Now"

    notification_message = (
        f"{display_name} is Live now — '{title}'."
    )

    return notify_connected_users(
        notification_title,
        notification_message,
        stream_id,
    )


# ---------------------------------------------------------
# DATABASE HELPERS
# ---------------------------------------------------------

def get_active_streams():
    conn = get_connection()

    try:
        return conn.execute(
            """
            SELECT
                ls.id,
                ls.broadcaster_id,
                ls.title,
                ls.description,
                ls.category,
                ls.status,
                ls.viewer_count,
                ls.started_at,
                u.username,
                u.full_name
            FROM live_streams ls
            JOIN users u ON u.id = ls.broadcaster_id
            WHERE ls.status = 'live'
            ORDER BY ls.started_at DESC, ls.id DESC
            """
        ).fetchall()

    finally:
        conn.close()


def get_my_active_stream():
    conn = get_connection()

    try:
        return conn.execute(
            """
            SELECT
                id,
                title,
                description,
                category,
                status,
                viewer_count,
                started_at
            FROM live_streams
            WHERE broadcaster_id = ?
              AND status = 'live'
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()

    finally:
        conn.close()


def get_stream(stream_id):
    conn = get_connection()

    try:
        return conn.execute(
            """
            SELECT
                ls.id,
                ls.broadcaster_id,
                ls.title,
                ls.description,
                ls.category,
                ls.status,
                ls.viewer_count,
                ls.started_at,
                ls.ended_at,
                ls.scheduled_at,
                u.username,
                u.full_name
            FROM live_streams ls
            JOIN users u ON u.id = ls.broadcaster_id
            WHERE ls.id = ?
            """,
            (stream_id,),
        ).fetchone()

    finally:
        conn.close()


def refresh_viewer_count(stream_id):
    conn = get_connection()

    try:
        conn.execute(
            """
            UPDATE live_streams
            SET viewer_count = (
                SELECT COUNT(*)
                FROM live_viewers
                WHERE live_viewers.stream_id = live_streams.id
                  AND live_viewers.left_at IS NULL
            )
            WHERE id = ?
            """,
            (stream_id,),
        )

        conn.commit()

    finally:
        conn.close()


# ---------------------------------------------------------
# SCHEDULED SESSION HELPERS
# ---------------------------------------------------------

def get_my_scheduled_streams():
    conn = get_connection()

    try:
        return conn.execute(
            """
            SELECT
                id,
                title,
                description,
                category,
                status,
                scheduled_at,
                created_at
            FROM live_streams
            WHERE broadcaster_id = ?
              AND status = 'scheduled'
            ORDER BY scheduled_at ASC, id ASC
            """,
            (user_id,),
        ).fetchall()

    finally:
        conn.close()


def get_scheduled_stream(stream_id):
    conn = get_connection()

    try:
        return conn.execute(
            """
            SELECT
                id,
                broadcaster_id,
                title,
                description,
                category,
                status,
                scheduled_at,
                started_at,
                ended_at
            FROM live_streams
            WHERE id = ?
              AND broadcaster_id = ?
              AND status = 'scheduled'
            """,
            (
                stream_id,
                user_id,
            ),
        ).fetchone()

    finally:
        conn.close()


def schedule_live_stream(
    title,
    description,
    category,
    scheduled_at,
):
    conn = get_connection()

    try:
        cursor = conn.execute(
            """
            INSERT INTO live_streams (
                broadcaster_id,
                title,
                description,
                category,
                status,
                viewer_count,
                scheduled_at
            )
            VALUES (?, ?, ?, ?, 'scheduled', 0, ?)
            """,
            (
                user_id,
                title,
                description,
                category,
                scheduled_at,
            ),
        )

        conn.commit()

        return cursor.lastrowid

    finally:
        conn.close()


def cancel_scheduled_stream(stream_id):
    conn = get_connection()

    try:
        result = conn.execute(
            """
            DELETE FROM live_streams
            WHERE id = ?
              AND broadcaster_id = ?
              AND status = 'scheduled'
            """,
            (
                stream_id,
                user_id,
            ),
        )

        conn.commit()

        return result.rowcount > 0

    finally:
        conn.close()


def start_scheduled_stream(stream_id):
    conn = get_connection()

    try:
        stream = conn.execute(
            """
            SELECT
                id,
                title,
                description,
                category,
                status,
                scheduled_at
            FROM live_streams
            WHERE id = ?
              AND broadcaster_id = ?
            """,
            (
                stream_id,
                user_id,
            ),
        ).fetchone()

        if not stream:
            return False, "Scheduled Live session not found."

        if stream[4] != "scheduled":
            return (
                False,
                "This scheduled Live session is no longer available.",
            )

        scheduled_dt = parse_datetime_local(stream[5])

        if not scheduled_dt:
            return False, "The scheduled start time is invalid."

        if datetime.now() < scheduled_dt:
            return (
                False,
                f"This Live is scheduled for "
                f"{format_live_time(stream[5])}.",
            )

        existing = conn.execute(
            """
            SELECT id
            FROM live_streams
            WHERE broadcaster_id = ?
              AND status = 'live'
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()

        if existing:
            return (
                False,
                "You already have another Live Room running.",
            )

        started_at = datetime.now().isoformat(
            timespec="seconds"
        )

        result = conn.execute(
            """
            UPDATE live_streams
            SET status = 'live',
                started_at = ?,
                ended_at = NULL,
                viewer_count = 0
            WHERE id = ?
              AND broadcaster_id = ?
              AND status = 'scheduled'
            """,
            (
                started_at,
                stream_id,
                user_id,
            ),
        )

        conn.commit()

        if result.rowcount == 0:
            return (
                False,
                "The scheduled Live could not be started.",
            )

        return True, "Your scheduled Live Room has started."

    finally:
        conn.close()


# ---------------------------------------------------------
# START IMMEDIATE LIVE
# ---------------------------------------------------------

def start_live_stream(
    title,
    description,
    category,
):
    conn = get_connection()

    try:
        existing = conn.execute(
            """
            SELECT id
            FROM live_streams
            WHERE broadcaster_id = ?
              AND status = 'live'
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()

        if existing:
            return existing[0]

        started_at = datetime.now().isoformat(
            timespec="seconds"
        )

        cursor = conn.execute(
            """
            INSERT INTO live_streams (
                broadcaster_id,
                title,
                description,
                category,
                status,
                viewer_count,
                scheduled_at,
                started_at
            )
            VALUES (?, ?, ?, ?, 'live', 0, NULL, ?)
            """,
            (
                user_id,
                title,
                description,
                category,
                started_at,
            ),
        )

        conn.commit()

        return cursor.lastrowid

    finally:
        conn.close()


# ---------------------------------------------------------
# END LIVE
# ---------------------------------------------------------

def end_live_stream(stream_id):
    ended_at = datetime.now().isoformat(
        timespec="seconds"
    )

    conn = get_connection()

    try:
        result = conn.execute(
            """
            UPDATE live_streams
            SET status = 'ended',
                ended_at = ?,
                viewer_count = 0
            WHERE id = ?
              AND broadcaster_id = ?
              AND status = 'live'
            """,
            (
                ended_at,
                stream_id,
                user_id,
            ),
        )

        conn.execute(
            """
            UPDATE live_viewers
            SET left_at = ?
            WHERE stream_id = ?
              AND left_at IS NULL
            """,
            (
                ended_at,
                stream_id,
            ),
        )

        conn.commit()

        return result.rowcount > 0

    finally:
        conn.close()


# ---------------------------------------------------------
# VIEWER HELPERS
# ---------------------------------------------------------

def join_stream(stream_id):
    stream = get_stream(stream_id)

    if not stream or stream[5] != "live":
        return (
            False,
            "This Live Room is no longer active.",
        )

    if stream[1] == user_id:
        return (
            True,
            "You are the broadcaster of this Live Room.",
        )

    now = datetime.now().isoformat(
        timespec="seconds"
    )

    conn = get_connection()

    try:
        existing = conn.execute(
            """
            SELECT id
            FROM live_viewers
            WHERE stream_id = ?
              AND user_id = ?
            """,
            (
                stream_id,
                user_id,
            ),
        ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE live_viewers
                SET joined_at = ?,
                    left_at = NULL
                WHERE id = ?
                """,
                (
                    now,
                    existing[0],
                ),
            )

        else:
            conn.execute(
                """
                INSERT INTO live_viewers (
                    stream_id,
                    user_id,
                    joined_at,
                    left_at
                )
                VALUES (?, ?, ?, NULL)
                """,
                (
                    stream_id,
                    user_id,
                    now,
                ),
            )

        conn.commit()

    finally:
        conn.close()

    refresh_viewer_count(stream_id)

    return True, "You joined the Live Room."


def leave_stream(stream_id):
    left_at = datetime.now().isoformat(
        timespec="seconds"
    )

    conn = get_connection()

    try:
        conn.execute(
            """
            UPDATE live_viewers
            SET left_at = ?
            WHERE stream_id = ?
              AND user_id = ?
              AND left_at IS NULL
            """,
            (
                left_at,
                stream_id,
                user_id,
            ),
        )

        conn.commit()

    finally:
        conn.close()

    refresh_viewer_count(stream_id)


# ---------------------------------------------------------
# CHAT
# ---------------------------------------------------------

def send_chat_message(
    stream_id,
    message,
):
    clean_message = message.strip()

    if not clean_message:
        return False

    stream = get_stream(stream_id)

    if not stream or stream[5] != "live":
        return False

    conn = get_connection()

    try:
        conn.execute(
            """
            INSERT INTO live_chat (
                stream_id,
                user_id,
                message
            )
            VALUES (?, ?, ?)
            """,
            (
                stream_id,
                user_id,
                clean_message[:500],
            ),
        )

        conn.commit()

        return True

    finally:
        conn.close()


def get_chat_messages(stream_id):
    conn = get_connection()

    try:
        rows = conn.execute(
            """
            SELECT
                lc.id,
                lc.message,
                lc.created_at,
                u.username,
                u.full_name
            FROM live_chat lc
            JOIN users u ON u.id = lc.user_id
            WHERE lc.stream_id = ?
            ORDER BY lc.id DESC
            LIMIT 50
            """,
            (stream_id,),
        ).fetchall()

        return list(reversed(rows))

    finally:
        conn.close()


# ---------------------------------------------------------
# REACTIONS
# ---------------------------------------------------------

def add_reaction(
    stream_id,
    reaction,
):
    allowed = {
        "heart",
        "like",
        "clap",
        "fire",
    }

    if reaction not in allowed:
        return

    stream = get_stream(stream_id)

    if not stream or stream[5] != "live":
        return

    conn = get_connection()

    try:
        conn.execute(
            """
            INSERT INTO live_reactions (
                stream_id,
                user_id,
                reaction
            )
            VALUES (?, ?, ?)
            """,
            (
                stream_id,
                user_id,
                reaction,
            ),
        )

        conn.commit()

    finally:
        conn.close()


# ---------------------------------------------------------
# CREATOR SUPPORT INTEGRATION
# ---------------------------------------------------------

CREATOR_PLATFORM_FEE_PERCENT = Decimal("1.00")


def ensure_live_creator_support_table():
    """Create the Live-specific creator support ledger if it does not exist."""
    conn = get_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS live_creator_support (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                live_stream_id INTEGER NOT NULL,
                supporter_id INTEGER NOT NULL,
                creator_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                platform_fee REAL NOT NULL,
                supporter_total REAL NOT NULL,
                currency TEXT NOT NULL,
                earning_reference TEXT NOT NULL UNIQUE,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def get_creator_profile_for_live(creator_id):
    """Return an active creator profile for the broadcaster, if available."""
    conn = get_connection()
    try:
        table = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'creator_profiles'
            """
        ).fetchone()
        if not table:
            return None

        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(creator_profiles)").fetchall()
        }
        required = {"user_id", "creator_status", "total_earnings", "currency"}
        if not required.issubset(columns):
            return None

        display_expression = "display_name" if "display_name" in columns else "NULL"
        return conn.execute(
            f"""
            SELECT {display_expression}, creator_status, total_earnings, currency
            FROM creator_profiles
            WHERE user_id = ?
              AND creator_status = 'active'
            LIMIT 1
            """,
            (creator_id,),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def get_wallet_for_creator_support(account_user_id):
    """Return the LifeGrid wallet needed for a creator support transaction."""
    conn = get_connection()
    try:
        table = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'wallets'
            """
        ).fetchone()
        if not table:
            return None

        return conn.execute(
            """
            SELECT id, user_id, currency, balance, available_balance,
                   pending_balance, wallet_status
            FROM wallets
            WHERE user_id = ?
            LIMIT 1
            """,
            (account_user_id,),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def add_creator_support_notification(target_user_id, title, message, reference_id):
    """Create a financial notification without changing the existing Live notification flow."""
    if not target_user_id:
        return False

    conn = get_connection()
    try:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(notifications)").fetchall()
        }
        required = {
            "user_id",
            "notification_type",
            "title",
            "message",
            "reference_type",
            "reference_id",
            "is_read",
            "created_at",
        }
        if not required.issubset(columns):
            return False

        existing = conn.execute(
            """
            SELECT id
            FROM notifications
            WHERE user_id = ?
              AND notification_type = 'creator_support'
              AND reference_type = 'live_creator_support'
              AND reference_id = ?
              AND title = ?
            LIMIT 1
            """,
            (target_user_id, str(reference_id), title),
        ).fetchone()
        if existing:
            return False

        conn.execute(
            """
            INSERT INTO notifications (
                user_id,
                notification_type,
                title,
                message,
                reference_type,
                reference_id,
                is_read,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                target_user_id,
                "creator_support",
                title,
                message,
                "live_creator_support",
                str(reference_id),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
        return True
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def calculate_creator_support(amount):
    """Calculate the same 1% development fee used by the Creator page."""
    contribution = Decimal(str(amount)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    fee = (contribution * CREATOR_PLATFORM_FEE_PERCENT / Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    total = contribution + fee
    return contribution, fee, total


def send_live_creator_support(stream_id, creator_id, amount, currency, message):
    """Transfer support from the viewer to the live creator atomically."""
    try:
        contribution, platform_fee, supporter_total = calculate_creator_support(amount)
    except (InvalidOperation, ValueError, TypeError):
        return False, "Please enter a valid support amount."

    if contribution <= 0:
        return False, "Support amount must be greater than zero."

    conn = get_connection()
    try:
        creator_profile = conn.execute(
            """
            SELECT user_id, creator_status, currency
            FROM creator_profiles
            WHERE user_id = ?
            LIMIT 1
            """,
            (creator_id,),
        ).fetchone()

        if not creator_profile or creator_profile[1] != "active":
            return False, "This broadcaster does not currently have an active Creator account."

        if creator_id == user_id:
            return False, "You cannot support your own Creator account."

        wallets = conn.execute(
            """
            SELECT id, user_id, currency, balance, available_balance,
                   pending_balance, wallet_status
            FROM wallets
            WHERE user_id IN (?, ?)
            """,
            (user_id, creator_id),
        ).fetchall()

        wallet_by_user = {int(row[1]): row for row in wallets}
        supporter_wallet = wallet_by_user.get(user_id)
        creator_wallet = wallet_by_user.get(int(creator_id))

        if not supporter_wallet:
            return False, "Your LifeGrid wallet could not be found."
        if not creator_wallet:
            return False, "The creator's LifeGrid wallet could not be found."

        supporter_currency = (supporter_wallet[2] or currency or "USD").upper()
        creator_currency = (creator_wallet[2] or creator_profile[2] or currency or "USD").upper()

        if supporter_currency != creator_currency:
            return (
                False,
                f"Currency mismatch: your wallet uses {supporter_currency}, "
                f"while this creator uses {creator_currency}.",
            )

        if supporter_wallet[6] and supporter_wallet[6].lower() != "active":
            return False, "Your wallet is not active."
        if creator_wallet[6] and creator_wallet[6].lower() != "active":
            return False, "The creator's wallet is not active."

        available = Decimal(str(supporter_wallet[4] or 0)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        if available < supporter_total:
            return (
                False,
                f"Insufficient available balance. You need {supporter_currency} "
                f"{supporter_total:.2f}, but only {supporter_currency} {available:.2f} is available.",
            )

        sender_balance = (
            Decimal(str(supporter_wallet[3] or 0)) - supporter_total
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        sender_pending = Decimal(str(supporter_wallet[5] or 0)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        sender_available = max(
            Decimal("0.00"), sender_balance - sender_pending
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        creator_balance = (
            Decimal(str(creator_wallet[3] or 0)) + contribution
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        creator_pending = Decimal(str(creator_wallet[5] or 0)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        creator_available = (
            creator_balance - creator_pending
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        earning_reference = f"LG-LIVE-CREATOR-{uuid.uuid4().hex[:12].upper()}"
        sender_wallet_reference = f"LG-LIVE-SENT-{uuid.uuid4().hex[:12].upper()}"
        recipient_wallet_reference = f"LG-LIVE-RECEIVED-{uuid.uuid4().hex[:12].upper()}"
        revenue_reference = f"LG-LIVE-REVENUE-{uuid.uuid4().hex[:12].upper()}"
        now = datetime.now().isoformat(timespec="seconds")
        clean_message = (message or "").strip()[:500]

        conn.execute("BEGIN")

        conn.execute(
            """
            UPDATE wallets
            SET balance = ?, available_balance = ?, updated_at = ?
            WHERE user_id = ?
            """,
            (
                float(sender_balance),
                float(sender_available),
                now,
                user_id,
            ),
        )

        conn.execute(
            """
            UPDATE wallets
            SET balance = ?, available_balance = ?, updated_at = ?
            WHERE user_id = ?
            """,
            (
                float(creator_balance),
                float(creator_available),
                now,
                creator_id,
            ),
        )

        conn.execute(
            """
            INSERT INTO wallet_transactions (
                user_id,
                transaction_type,
                amount,
                currency,
                description,
                reference,
                status,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                "creator_support_sent",
                -float(supporter_total),
                supporter_currency,
                f"Live creator support to {creator_id}",
                sender_wallet_reference,
                "Completed",
                now,
            ),
        )

        conn.execute(
            """
            INSERT INTO wallet_transactions (
                user_id,
                transaction_type,
                amount,
                currency,
                description,
                reference,
                status,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                creator_id,
                "creator_earnings_received",
                float(contribution),
                creator_currency,
                f"Live creator support from {username}",
                recipient_wallet_reference,
                "Completed",
                now,
            ),
        )

        conn.execute(
            """
            INSERT INTO creator_earnings (
                earning_reference,
                creator_id,
                supporter_id,
                amount,
                platform_fee,
                supporter_total,
                currency,
                message,
                status,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                earning_reference,
                creator_id,
                user_id,
                float(contribution),
                float(platform_fee),
                float(supporter_total),
                creator_currency,
                clean_message,
                "Completed",
                now,
            ),
        )

        conn.execute(
            """
            UPDATE creator_profiles
            SET total_earnings = COALESCE(total_earnings, 0) + ?,
                updated_at = ?
            WHERE user_id = ?
            """,
            (float(contribution), now, creator_id),
        )

        conn.execute(
            """
            INSERT INTO platform_revenue (
                revenue_reference,
                source_type,
                source_reference,
                payer_id,
                amount,
                currency,
                description,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                revenue_reference,
                "live_creator_support",
                earning_reference,
                user_id,
                float(platform_fee),
                creator_currency,
                f"Platform fee from Live creator support for stream {stream_id}",
                now,
            ),
        )

        conn.execute(
            """
            INSERT INTO live_creator_support (
                live_stream_id,
                supporter_id,
                creator_id,
                amount,
                platform_fee,
                supporter_total,
                currency,
                earning_reference,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                stream_id,
                user_id,
                creator_id,
                float(contribution),
                float(platform_fee),
                float(supporter_total),
                creator_currency,
                earning_reference,
                now,
            ),
        )

        conn.commit()

    except sqlite3.Error as exc:
        conn.rollback()
        return False, f"Creator support could not be completed: {exc}"
    except Exception as exc:
        conn.rollback()
        return False, f"Creator support could not be completed: {exc}"
    finally:
        conn.close()

    add_creator_support_notification(
        creator_id,
        "💰 Creator Support Received",
        f"{full_name or username} supported you during your Live with "
        f"{creator_currency} {contribution:.2f}.",
        earning_reference,
    )
    add_creator_support_notification(
        user_id,
        "❤️ Creator Support Sent",
        f"You supported the Live creator with {creator_currency} "
        f"{contribution:.2f}. Platform charge: {creator_currency} {platform_fee:.2f}.",
        earning_reference,
    )

    return (
        True,
        f"Support sent successfully. The creator received {creator_currency} "
        f"{contribution:.2f}; your total payment was {creator_currency} "
        f"{supporter_total:.2f}.",
    )


ensure_live_creator_support_table()


# ---------------------------------------------------------
# VIRTUAL GIFT INTEGRATION
# ---------------------------------------------------------

def ensure_live_gift_tables():
    """Ensure the Live page can use the Gift Store tables safely."""
    conn = get_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS gift_catalog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gift_code TEXT UNIQUE NOT NULL,
                gift_name TEXT NOT NULL,
                gift_icon TEXT NOT NULL,
                credit_price INTEGER NOT NULL,
                creator_value REAL NOT NULL DEFAULT 0,
                currency_code TEXT NOT NULL DEFAULT 'USD',
                is_active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS gift_credit_balances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                credit_balance INTEGER NOT NULL DEFAULT 0,
                lifetime_purchased INTEGER NOT NULL DEFAULT 0,
                lifetime_spent INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS gifts_sent (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_reference TEXT UNIQUE NOT NULL,
                sender_user_id INTEGER NOT NULL,
                recipient_user_id INTEGER NOT NULL,
                gift_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                total_credits INTEGER NOT NULL,
                creator_value REAL NOT NULL DEFAULT 0,
                currency_code TEXT NOT NULL DEFAULT 'USD',
                live_stream_id INTEGER,
                message TEXT,
                status TEXT NOT NULL DEFAULT 'Completed',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS creator_gift_earnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_reference TEXT UNIQUE NOT NULL,
                creator_user_id INTEGER NOT NULL,
                source_user_id INTEGER NOT NULL,
                gift_sent_id INTEGER,
                gross_value REAL NOT NULL DEFAULT 0,
                platform_fee REAL NOT NULL DEFAULT 0,
                net_earnings REAL NOT NULL DEFAULT 0,
                currency_code TEXT NOT NULL DEFAULT 'USD',
                status TEXT NOT NULL DEFAULT 'Pending',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS platform_revenue_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_reference TEXT UNIQUE NOT NULL,
                source_type TEXT NOT NULL,
                source_reference TEXT,
                gross_amount REAL NOT NULL DEFAULT 0,
                creator_amount REAL NOT NULL DEFAULT 0,
                platform_amount REAL NOT NULL DEFAULT 0,
                currency_code TEXT NOT NULL DEFAULT 'USD',
                status TEXT NOT NULL DEFAULT 'Recorded',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def get_gift_catalog_for_live():
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT id, gift_code, gift_name, gift_icon,
                   credit_price, creator_value, currency_code
            FROM gift_catalog
            WHERE is_active = 1
            ORDER BY sort_order ASC, id ASC
            """
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def get_gift_credit_balance(account_user_id):
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT credit_balance, lifetime_purchased, lifetime_spent
            FROM gift_credit_balances
            WHERE user_id = ?
            LIMIT 1
            """,
            (account_user_id,),
        ).fetchone()
        if not row:
            return 0, 0, 0
        return int(row[0] or 0), int(row[1] or 0), int(row[2] or 0)
    except sqlite3.Error:
        return 0, 0, 0
    finally:
        conn.close()


def add_live_gift_notification(target_user_id, title, message, reference_id):
    if not target_user_id:
        return False

    conn = get_connection()
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(notifications)").fetchall()}
        required = {
            "user_id", "notification_type", "title", "message",
            "reference_type", "reference_id", "is_read", "created_at"
        }
        if not required.issubset(columns):
            return False

        conn.execute(
            """
            INSERT INTO notifications (
                user_id, notification_type, title, message,
                reference_type, reference_id, is_read, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                target_user_id,
                "live_gift",
                title,
                message,
                "live_gift",
                str(reference_id),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
        return True
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def send_live_gift(stream_id, recipient_user_id, gift_id, quantity, message=""):
    """Send Gift Credits from the viewer to the Live broadcaster atomically."""
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        return False, "Invalid gift quantity."

    if quantity < 1:
        return False, "Gift quantity must be at least 1."

    if recipient_user_id == user_id:
        return False, "You cannot send a gift to yourself."

    conn = get_connection()
    reference = f"LG-LIVE-GIFT-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}-{uuid.uuid4().hex[:8].upper()}"
    now = datetime.utcnow().isoformat(timespec="seconds")

    try:
        stream = conn.execute(
            """
            SELECT id, broadcaster_id, title, status
            FROM live_streams
            WHERE id = ?
            LIMIT 1
            """,
            (stream_id,),
        ).fetchone()

        if not stream or stream[3] != "live":
            return False, "This Live Room is no longer active."

        if int(stream[1]) != int(recipient_user_id):
            return False, "The selected broadcaster does not match this Live Room."

        gift = conn.execute(
            """
            SELECT id, gift_code, gift_name, gift_icon,
                   credit_price, creator_value, currency_code
            FROM gift_catalog
            WHERE id = ? AND is_active = 1
            LIMIT 1
            """,
            (gift_id,),
        ).fetchone()

        if not gift:
            return False, "That gift is no longer available."

        gift_price = int(gift[4] or 0)
        creator_value_unit = Decimal(str(gift[5] or 0))
        total_credits = gift_price * quantity
        creator_value = (creator_value_unit * quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        gross_value = Decimal(str(total_credits)).quantize(Decimal("0.01"))
        platform_fee = max(Decimal("0.00"), gross_value - creator_value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        currency = str(gift[6] or "USD").upper()

        balance_row = conn.execute(
            """
            SELECT id, credit_balance, lifetime_purchased, lifetime_spent
            FROM gift_credit_balances
            WHERE user_id = ?
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()

        available_credits = int(balance_row[1] or 0) if balance_row else 0
        if available_credits < total_credits:
            return False, f"Insufficient Gift Credits. You need {total_credits:,}, but you have {available_credits:,}."

        clean_message = (message or "").strip()[:500]

        conn.execute("BEGIN")

        conn.execute(
            """
            UPDATE gift_credit_balances
            SET credit_balance = credit_balance - ?,
                lifetime_spent = lifetime_spent + ?,
                updated_at = ?
            WHERE user_id = ?
              AND credit_balance >= ?
            """,
            (total_credits, total_credits, now, user_id, total_credits),
        )

        if conn.execute("SELECT changes()").fetchone()[0] != 1:
            conn.rollback()
            return False, "The Gift Credit balance changed before the gift could be sent. Please try again."

        gift_sent_columns = {row[1] for row in conn.execute("PRAGMA table_info(gifts_sent)").fetchall()}
        gift_sent_values = {
            "transaction_reference": reference,
            "sender_user_id": user_id,
            "recipient_user_id": recipient_user_id,
            "gift_id": int(gift[0]),
            "quantity": quantity,
            "total_credits": total_credits,
            "creator_value": float(creator_value),
            "currency_code": currency,
            "live_stream_id": stream_id,
            "message": clean_message,
            "status": "Completed",
            "created_at": now,
        }
        gift_sent_names = [name for name in gift_sent_values if name in gift_sent_columns]
        placeholders = ", ".join("?" for _ in gift_sent_names)
        conn.execute(
            f"INSERT INTO gifts_sent ({', '.join(gift_sent_names)}) VALUES ({placeholders})",
            [gift_sent_values[name] for name in gift_sent_names],
        )
        gift_sent_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        earnings_reference = f"LG-LIVE-GIFT-EARNING-{uuid.uuid4().hex[:12].upper()}"
        earnings_columns = {row[1] for row in conn.execute("PRAGMA table_info(creator_gift_earnings)").fetchall()}
        earnings_values = {
            "transaction_reference": earnings_reference,
            "creator_user_id": recipient_user_id,
            "source_user_id": user_id,
            "gift_sent_id": gift_sent_id,
            "gross_value": float(gross_value),
            "platform_fee": float(platform_fee),
            "net_earnings": float(creator_value),
            "currency_code": currency,
            "status": "Pending",
            "created_at": now,
        }
        earnings_names = [name for name in earnings_values if name in earnings_columns]
        placeholders = ", ".join("?" for _ in earnings_names)
        conn.execute(
            f"INSERT INTO creator_gift_earnings ({', '.join(earnings_names)}) VALUES ({placeholders})",
            [earnings_values[name] for name in earnings_names],
        )

        revenue_reference = f"LG-LIVE-GIFT-REVENUE-{uuid.uuid4().hex[:12].upper()}"
        revenue_columns = {row[1] for row in conn.execute("PRAGMA table_info(platform_revenue_ledger)").fetchall()}
        revenue_values = {
            "transaction_reference": revenue_reference,
            "source_type": "live_gift",
            "source_reference": reference,
            "gross_amount": float(gross_value),
            "creator_amount": float(creator_value),
            "platform_amount": float(platform_fee),
            "currency_code": currency,
            "status": "Recorded",
            "created_at": now,
        }
        revenue_names = [name for name in revenue_values if name in revenue_columns]
        placeholders = ", ".join("?" for _ in revenue_names)
        conn.execute(
            f"INSERT INTO platform_revenue_ledger ({', '.join(revenue_names)}) VALUES ({placeholders})",
            [revenue_values[name] for name in revenue_names],
        )

        conn.commit()

    except sqlite3.Error as exc:
        conn.rollback()
        return False, f"The gift could not be sent: {exc}"
    except Exception as exc:
        conn.rollback()
        return False, f"The gift could not be sent: {exc}"
    finally:
        conn.close()

    gift_display = f"{gift[3]} {gift[2]}"
    add_live_gift_notification(
        recipient_user_id,
        "🎁 Live Gift Received",
        f"{full_name} sent you {quantity:,} × {gift_display} during your Live. "
        f"Creator earnings recorded: {currency} {creator_value:,.2f}.",
        reference,
    )
    add_live_gift_notification(
        user_id,
        "🎁 Live Gift Sent",
        f"You sent {quantity:,} × {gift_display} for {total_credits:,} Gift Credits.",
        reference,
    )

    return True, (
        f"{gift_display} sent successfully. "
        f"{total_credits:,} Gift Credits were used."
    )


def get_recent_live_gifts(stream_id, limit=10):
    """Return recent completed gifts for one active Live room."""
    conn = get_connection()

    try:
        tables = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name IN ('gifts_sent', 'gift_catalog', 'users')
            """
        ).fetchall()
        table_names = {row[0] for row in tables}

        if not {'gifts_sent', 'gift_catalog', 'users'}.issubset(table_names):
            return []

        gift_columns = {
            row[1] for row in conn.execute(
                "PRAGMA table_info(gifts_sent)"
            ).fetchall()
        }

        required = {
            'sender_user_id',
            'recipient_user_id',
            'gift_id',
            'quantity',
            'total_credits',
            'creator_value',
            'currency_code',
            'live_stream_id',
            'status',
            'created_at',
        }

        if not required.issubset(gift_columns):
            return []

        return conn.execute(
            """
            SELECT
                gs.quantity,
                gs.total_credits,
                gs.creator_value,
                gs.currency_code,
                gs.created_at,
                gc.gift_icon,
                gc.gift_name,
                u.username,
                u.full_name
            FROM gifts_sent gs
            JOIN gift_catalog gc ON gc.id = gs.gift_id
            JOIN users u ON u.id = gs.sender_user_id
            WHERE gs.live_stream_id = ?
              AND LOWER(COALESCE(gs.status, '')) = 'completed'
            ORDER BY gs.created_at DESC, gs.rowid DESC
            LIMIT ?
            """,
            (stream_id, int(limit)),
        ).fetchall()

    except sqlite3.Error:
        return []
    finally:
        conn.close()


ensure_live_gift_tables()


# ---------------------------------------------------------
# SESSION STATE
# ---------------------------------------------------------

if "selected_live_stream" not in st.session_state:
    st.session_state["selected_live_stream"] = None

if "live_camera_enabled" not in st.session_state:
    st.session_state["live_camera_enabled"] = False


# ---------------------------------------------------------
# PAGE HEADER
# ---------------------------------------------------------

st.title("🔴 LifeGrid Live")

st.caption(
    "Go live, schedule sessions, connect with viewers, chat, react, "
    "and build real-time community experiences."
)


# ---------------------------------------------------------
# WEBRTC STATUS
# ---------------------------------------------------------

if WEBRTC_AVAILABLE:
    st.success(
        "🎥 Live camera/video support is enabled on this installation."
    )
else:
    st.warning(
        "Camera/video support is not installed yet. The Live Room, chat, "
        "viewers, and reactions still work. Install streamlit-webrtc and "
        "av in the LifeGrid virtual environment to enable the camera."
    )


# ---------------------------------------------------------
# MY CURRENT LIVE SESSION
# ---------------------------------------------------------

my_stream = get_my_active_stream()

if my_stream:
    stream_id = my_stream[0]

    # Broadcasters are not registered as viewers. Do not call
    # leave_stream() here because Streamlit reruns this page frequently.
    st.success("🔴 You are currently LIVE.")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "Live Viewers",
            my_stream[5],
        )

    with col2:
        st.metric(
            "Category",
            my_stream[3] or "General",
        )

    with col3:
        st.metric(
            "Status",
            "LIVE",
        )

    with col4:
        st.metric(
            "Duration",
            calculate_live_duration(my_stream[6]),
        )

    st.subheader(my_stream[1])

    time_col1, time_col2 = st.columns(2)

    with time_col1:
        st.caption(
            f"🟢 **Start time:** "
            f"{format_live_time(my_stream[6])}"
        )

    with time_col2:
        st.caption(
            "🔴 **End time:** Will be recorded when you end this Live"
        )

    if my_stream[2]:
        st.write(my_stream[2])

    # -----------------------------------------------------
    # CAMERA
    # -----------------------------------------------------

    st.subheader("🎥 Your Live Video")

    if WEBRTC_AVAILABLE:
        st.caption(
            "Camera access is optional. Start it only after closing other "
            "apps that may be using your camera."
        )

        camera_enabled = st.checkbox(
            "📷 Enable my camera",
            value=st.session_state.get(
                "live_camera_enabled",
                False,
            ),
            key=f"camera_toggle_{stream_id}",
        )

        st.session_state["live_camera_enabled"] = camera_enabled

        if camera_enabled:
            st.info(
                "If the browser reports 'NotReadableError: Could not start "
                "video source', the camera is being used by another "
                "application or Windows/browser permission is blocking it. "
                "The Live Room itself remains active."
            )

            try:
                webrtc_streamer(
                    key=f"lifegrid-host-{stream_id}",
                    mode=WebRtcMode.SENDONLY,
                    media_stream_constraints={
                        "video": True,
                        "audio": True,
                    },
                    async_processing=True,
                )

            except Exception:
                st.warning(
                    "LifeGrid could not start the camera/microphone. "
                    "You can continue the Live without video."
                )

        else:
            st.success(
                "Your Live is active. Camera is currently off. "
                "Turn on 'Enable my camera' when you are ready."
            )

    else:
        st.info(
            "Camera/video support is not installed. The Live Room, chat, "
            "viewers, reactions, and timing still work normally."
        )

    st.divider()

    # -----------------------------------------------------
    # END LIVE
    # -----------------------------------------------------

    if st.button(
        "🔴 End Live",
        type="primary",
        use_container_width=True,
        key=f"end_live_{stream_id}",
    ):
        if end_live_stream(stream_id):
            ended_stream = get_stream(stream_id)

            st.session_state["selected_live_stream"] = None
            st.session_state["live_camera_enabled"] = False

            if ended_stream:
                st.success(
                    "Your Live Room has ended and all active viewers "
                    "were closed. "
                    f"End time: {format_live_time(ended_stream[8])}. "
                    f"Duration: "
                    f"{calculate_live_duration(ended_stream[7], ended_stream[8])}."
                )

            else:
                st.success(
                    "Your Live Room has ended and all active viewers "
                    "were closed."
                )

            st.rerun()

        else:
            st.error(
                "The Live Room could not be ended. "
                "It may already be closed."
            )

    st.divider()


# ---------------------------------------------------------
# SCHEDULED LIVE SESSIONS
# ---------------------------------------------------------

if not my_stream:
    st.subheader("📅 Scheduled Live Sessions")

    scheduled_sessions = get_my_scheduled_streams()

    if not scheduled_sessions:
        st.info(
            "You do not have any scheduled Live sessions yet."
        )

    else:
        current_time = datetime.now()

        for scheduled in scheduled_sessions:
            (
                scheduled_id,
                scheduled_title,
                scheduled_description,
                scheduled_category,
                scheduled_status,
                scheduled_at,
                created_at,
            ) = scheduled

            scheduled_datetime = parse_datetime_local(
                scheduled_at
            )

            is_ready = (
                scheduled_datetime is not None
                and current_time >= scheduled_datetime
            )

            with st.container(border=True):
                title_col, status_col = st.columns([4, 1])

                with title_col:
                    st.markdown(
                        f"### 📅 {scheduled_title}"
                    )

                    st.write(
                        f"**Category:** "
                        f"{scheduled_category or 'General'}"
                    )

                    st.write(
                        f"**Scheduled:** "
                        f"{format_live_time(scheduled_at)}"
                    )

                    if scheduled_description:
                        st.caption(
                            scheduled_description
                        )

                with status_col:
                    if is_ready:
                        st.success("🟢 READY")
                    else:
                        st.info("📅 SCHEDULED")

                if is_ready:
                    st.success(
                        "The scheduled time has arrived. "
                        "You can start this Live now."
                    )

                    start_col, cancel_col = st.columns(2)

                    with start_col:
                        if st.button(
                            "🔴 Start Scheduled Live",
                            type="primary",
                            use_container_width=True,
                            key=f"start_scheduled_{scheduled_id}",
                        ):
                            started, message = (
                                start_scheduled_stream(
                                    scheduled_id
                                )
                            )

                            if started:
                                notify_live_started(
                                    scheduled_id,
                                    scheduled_title,
                                )

                                st.session_state[
                                    "selected_live_stream"
                                ] = scheduled_id

                                st.session_state[
                                    "live_camera_enabled"
                                ] = True

                                st.success(message)
                                st.rerun()

                            else:
                                st.error(message)

                    with cancel_col:
                        if st.button(
                            "Cancel",
                            use_container_width=True,
                            key=f"cancel_scheduled_{scheduled_id}",
                        ):
                            if cancel_scheduled_stream(
                                scheduled_id
                            ):
                                st.success(
                                    "Scheduled Live cancelled."
                                )
                                st.rerun()

                            else:
                                st.error(
                                    "The scheduled Live could not "
                                    "be cancelled."
                                )

                else:
                    st.caption(
                        "The Start button will become available "
                        "when the scheduled time arrives."
                    )

                    if st.button(
                        "Cancel Scheduled Live",
                        use_container_width=True,
                        key=f"cancel_future_{scheduled_id}",
                    ):
                        if cancel_scheduled_stream(
                            scheduled_id
                        ):
                            st.success(
                                "Scheduled Live cancelled."
                            )
                            st.rerun()

                        else:
                            st.error(
                                "The scheduled Live could not "
                                "be cancelled."
                            )


# ---------------------------------------------------------
# GO LIVE / SCHEDULE LIVE
# ---------------------------------------------------------

if not my_stream:
    st.divider()

    go_col, schedule_col = st.columns(2)

    # -----------------------------------------------------
    # GO LIVE NOW
    # -----------------------------------------------------

    with go_col:
        st.subheader("📹 Go Live Now")

        with st.form("go_live_form"):
            live_title = st.text_input(
                "Live Title",
                placeholder="What would you like to talk about?",
                max_chars=120,
            )

            live_description = st.text_area(
                "Description",
                placeholder=(
                    "Tell viewers what your live session is about."
                ),
                max_chars=500,
            )

            live_category = st.selectbox(
                "Category",
                [
                    "General",
                    "Education",
                    "Business",
                    "Construction",
                    "Technology",
                    "Entertainment",
                    "Faith & Community",
                    "Jobs & Opportunities",
                    "Health & Fitness",
                    "Other",
                ],
                key="go_live_category",
            )

            start_live = st.form_submit_button(
                "🔴 Start Live",
                use_container_width=True,
            )

        if start_live:
            clean_title = live_title.strip()

            if not clean_title:
                st.error(
                    "Please enter a title for your live session."
                )

            else:
                try:
                    stream_id = start_live_stream(
                        clean_title,
                        live_description.strip(),
                        live_category,
                    )

                    notify_live_started(
                        stream_id,
                        clean_title,
                    )

                    st.session_state[
                        "selected_live_stream"
                    ] = stream_id

                    st.session_state[
                        "live_camera_enabled"
                    ] = True

                    st.success(
                        "Your Live Room has started."
                    )

                    st.rerun()

                except sqlite3.Error as exc:
                    st.error(
                        f"Could not start the Live Room: {exc}"
                    )

    # -----------------------------------------------------
    # SCHEDULE LIVE
    # -----------------------------------------------------

    with schedule_col:
        st.subheader("📅 Schedule a Live")

        with st.form("schedule_live_form"):
            scheduled_title = st.text_input(
                "Live Title",
                placeholder="What will your scheduled Live be about?",
                max_chars=120,
                key="scheduled_title",
            )

            scheduled_description = st.text_area(
                "Description",
                placeholder=(
                    "Tell viewers what they can expect."
                ),
                max_chars=500,
                key="scheduled_description",
            )

            scheduled_category = st.selectbox(
                "Category",
                [
                    "General",
                    "Education",
                    "Business",
                    "Construction",
                    "Technology",
                    "Entertainment",
                    "Faith & Community",
                    "Jobs & Opportunities",
                    "Health & Fitness",
                    "Other",
                ],
                key="scheduled_category",
            )

            schedule_date = st.date_input(
                "Live Date",
                value=datetime.now().date(),
                key="schedule_date",
            )

            schedule_time = st.time_input(
                "Live Start Time",
                value=datetime.now().replace(
                    second=0,
                    microsecond=0,
                ).time(),
                key="schedule_time",
            )

            schedule_live = st.form_submit_button(
                "📅 Schedule Live",
                use_container_width=True,
            )

        if schedule_live:
            clean_title = scheduled_title.strip()

            if not clean_title:
                st.error(
                    "Please enter a title for your scheduled Live."
                )

            else:
                scheduled_datetime = datetime.combine(
                    schedule_date,
                    schedule_time,
                )

                if scheduled_datetime <= datetime.now():
                    st.error(
                        "Please choose a future date and time."
                    )

                else:
                    try:
                        scheduled_at = (
                            scheduled_datetime.isoformat(
                                timespec="seconds"
                            )
                        )

                        schedule_id = schedule_live_stream(
                            clean_title,
                            scheduled_description.strip(),
                            scheduled_category,
                            scheduled_at,
                        )

                        notify_live_scheduled(
                            schedule_id,
                            clean_title,
                            scheduled_at,
                        )

                        st.success(
                            "Your Live session has been scheduled "
                            f"for {format_live_time(scheduled_at)}."
                        )

                        st.rerun()

                    except sqlite3.Error as exc:
                        st.error(
                            f"Could not schedule the Live Room: {exc}"
                        )


# ---------------------------------------------------------
# ACTIVE LIVE ROOMS
# ---------------------------------------------------------

st.divider()

st.subheader("🌍 Live Now")

active_streams = get_active_streams()

other_streams = [
    stream
    for stream in active_streams
    if stream[1] != user_id
]

if not other_streams:
    st.info(
        "There are currently no other active Live Rooms. "
        "Start a Live Room to begin building the LifeGrid "
        "live community."
    )

else:
    for stream in other_streams:
        stream_id = stream[0]
        broadcaster_id = stream[1]
        title = stream[2]
        description = stream[3]
        category = stream[4]
        viewer_count = stream[6]
        broadcaster_username = stream[8]
        broadcaster_name = (
            stream[9] or broadcaster_username
        )

        with st.container(border=True):
            col1, col2 = st.columns([4, 1])

            with col1:
                st.markdown(
                    f"### 🔴 {title}"
                )

                st.write(
                    f"**Broadcaster:** "
                    f"{broadcaster_name} "
                    f"(@{broadcaster_username})"
                )

                st.write(
                    f"**Category:** "
                    f"{category or 'General'}  •  "
                    f"**Viewers:** {viewer_count}"
                )

                st.caption(
                    f"🟢 Started: "
                    f"{format_live_time(stream[7])}"
                )

                if description:
                    st.caption(description)

            with col2:
                if broadcaster_id != user_id:
                    if st.button(
                        "Watch Live",
                        key=f"watch_{stream_id}",
                        use_container_width=True,
                    ):
                        joined, message = join_stream(
                            stream_id
                        )

                        if joined:
                            st.session_state[
                                "selected_live_stream"
                            ] = stream_id

                            st.rerun()

                        else:
                            st.warning(message)


# ---------------------------------------------------------
# SELECTED LIVE ROOM
# ---------------------------------------------------------

selected_stream_id = st.session_state.get(
    "selected_live_stream"
)

if selected_stream_id and not my_stream:
    selected_stream = get_stream(
        selected_stream_id
    )

    if selected_stream and selected_stream[5] == "live":
        st.divider()

        st.subheader(
            f"🔴 Watching: {selected_stream[2]}"
        )

        viewer_col, chat_col = st.columns(
            [2, 1]
        )

        with viewer_col:
            st.subheader("🎥 Live Video")

            if WEBRTC_AVAILABLE:
                st.info(
                    "The WebRTC camera component is available. "
                    "The current LifeGrid database room remains "
                    "the source of truth for the broadcaster, "
                    "viewers, chat, and reactions."
                )

            else:
                st.info(
                    "📹 Live video transport is not installed "
                    "on this deployment yet."
                )

            st.write(
                f"**Broadcaster:** "
                f"{selected_stream[11] or selected_stream[10]}"
            )

            st.write(
                f"**Category:** "
                f"{selected_stream[4] or 'General'}"
            )

            st.caption(
                f"🟢 **Started:** "
                f"{format_live_time(selected_stream[7])}"
            )

            st.caption(
                f"⏱️ **Live duration:** "
                f"{calculate_live_duration(selected_stream[7])}"
            )

            refresh_viewer_count(
                selected_stream_id
            )

            refreshed = get_stream(
                selected_stream_id
            )

            current_viewers = (
                refreshed[6]
                if refreshed
                else selected_stream[6]
            )

            st.metric(
                "Live Viewers",
                current_viewers,
            )

            # -------------------------------------------------
            # CREATOR SUPPORT
            # -------------------------------------------------

            creator_profile = get_creator_profile_for_live(
                selected_stream[1]
            )

            if creator_profile:
                creator_display_name = (
                    creator_profile[0]
                    or selected_stream[11]
                    or selected_stream[10]
                )
                creator_wallet = get_wallet_for_creator_support(selected_stream[1])
                creator_currency = (
                    creator_profile[3]
                    or (creator_wallet[2] if creator_wallet else None)
                    or "USD"
                )
                creator_currency = str(creator_currency).upper()

                st.markdown("### ❤️ Support This Creator")
                st.caption(
                    f"Support {creator_display_name} directly during this Live. "
                    f"The creator receives the full contribution. The current "
                    f"development platform charge is 1% and is paid by the supporter."
                )

                support_amount = st.number_input(
                    f"Support Amount ({creator_currency})",
                    min_value=0.01,
                    value=10.00,
                    step=1.00,
                    format="%.2f",
                    key=f"live_support_amount_{selected_stream_id}",
                )

                support_message = st.text_input(
                    "Message (optional)",
                    max_chars=500,
                    key=f"live_support_message_{selected_stream_id}",
                )

                support_contribution, support_fee, support_total = (
                    calculate_creator_support(support_amount)
                )

                st.caption(
                    f"Creator receives: {creator_currency} {support_contribution:.2f} "
                    f"| Platform charge: {creator_currency} {support_fee:.2f} "
                    f"| Total payment: {creator_currency} {support_total:.2f}"
                )

                if st.button(
                    "❤️ Support Creator",
                    type="primary",
                    use_container_width=True,
                    key=f"support_live_creator_{selected_stream_id}",
                ):
                    with st.spinner("Processing creator support..."):
                        support_ok, support_message_result = send_live_creator_support(
                            selected_stream_id,
                            selected_stream[1],
                            support_amount,
                            creator_currency,
                            support_message,
                        )

                    if support_ok:
                        st.success(support_message_result)
                        st.rerun()
                    else:
                        st.error(support_message_result)
            else:
                st.info(
                    "This broadcaster does not currently have an active Creator "
                    "account. Creator Support will appear here when the broadcaster "
                    "activates Creator Earnings."
                )

            # -------------------------------------------------
            # VIRTUAL GIFTS
            # -------------------------------------------------

            st.markdown("### 🎁 Send a Gift")

            gift_catalog = get_gift_catalog_for_live()
            gift_balance, _, _ = get_gift_credit_balance(user_id)

            if gift_catalog:
                st.caption(f"Your Gift Credits: **{gift_balance:,}**")

                gift_options = {
                    f"{row[3]} {row[2]} — {int(row[4]):,} Credits": row
                    for row in gift_catalog
                }

                selected_gift_label = st.selectbox(
                    "Choose a gift",
                    list(gift_options.keys()),
                    key=f"live_gift_select_{selected_stream_id}",
                )
                selected_gift = gift_options[selected_gift_label]

                gift_quantity = st.number_input(
                    "Quantity",
                    min_value=1,
                    max_value=100,
                    value=1,
                    step=1,
                    key=f"live_gift_quantity_{selected_stream_id}",
                )

                gift_total = int(selected_gift[4]) * int(gift_quantity)
                st.caption(
                    f"Total: **{gift_total:,} Gift Credits**  •  "
                    f"Creator value: **{float(selected_gift[5] or 0) * int(gift_quantity):,.2f} {str(selected_gift[6] or 'USD').upper()}**"
                )

                gift_message = st.text_input(
                    "Gift message (optional)",
                    max_chars=500,
                    key=f"live_gift_message_{selected_stream_id}",
                )

                if st.button(
                    "🎁 Send Gift",
                    type="primary",
                    use_container_width=True,
                    key=f"send_live_gift_{selected_stream_id}",
                ):
                    with st.spinner("Sending gift..."):
                        gift_ok, gift_result = send_live_gift(
                            selected_stream_id,
                            selected_stream[1],
                            selected_gift[0],
                            gift_quantity,
                            gift_message,
                        )

                    if gift_ok:
                        st.success(gift_result)
                        st.rerun()
                    else:
                        st.error(gift_result)
            else:
                st.info(
                    "No active gifts are available yet. Visit the Gift Store "
                    "to make sure the gift catalog is initialized."
                )

            # -------------------------------------------------
            # RECENT LIVE GIFTS
            # -------------------------------------------------

            recent_gifts = get_recent_live_gifts(
                selected_stream_id,
                limit=10,
            )

            if recent_gifts:
                st.markdown("### 🎁 Recent Gifts")

                for recent_gift in recent_gifts:
                    (
                        gift_quantity,
                        gift_credits,
                        creator_value,
                        gift_currency,
                        gift_created_at,
                        gift_icon,
                        gift_name,
                        sender_username,
                        sender_full_name,
                    ) = recent_gift

                    sender_display = sender_full_name or sender_username
                    gift_display = f"{gift_icon or '🎁'} {gift_name}"

                    st.caption(
                        f"**{sender_display}** sent {gift_quantity:,} × "
                        f"{gift_display} • {gift_credits:,} Gift Credits • "
                        f"Creator value: {str(gift_currency or 'USD').upper()} "
                        f"{float(creator_value or 0):,.2f} • "
                        f"{gift_created_at}"
                    )
            else:
                st.caption("No gifts have been sent in this Live yet.")

            reaction_col1, reaction_col2, reaction_col3, reaction_col4 = (
                st.columns(4)
            )

            reactions = [
                ("❤️", "heart"),
                ("👍", "like"),
                ("👏", "clap"),
                ("🔥", "fire"),
            ]

            for column, (
                emoji,
                reaction_name,
            ) in zip(
                [
                    reaction_col1,
                    reaction_col2,
                    reaction_col3,
                    reaction_col4,
                ],
                reactions,
            ):
                with column:
                    if st.button(
                        emoji,
                        key=(
                            f"reaction_"
                            f"{reaction_name}_"
                            f"{selected_stream_id}"
                        ),
                        use_container_width=True,
                    ):
                        add_reaction(
                            selected_stream_id,
                            reaction_name,
                        )

                        st.toast(
                            f"{emoji} reaction sent!"
                        )

            if st.button(
                "Leave Live Room",
                use_container_width=True,
                key=(
                    f"leave_live_"
                    f"{selected_stream_id}"
                ),
            ):
                leave_stream(
                    selected_stream_id
                )

                st.session_state[
                    "selected_live_stream"
                ] = None

                st.rerun()

        with chat_col:
            st.markdown("### 💬 Live Chat")

            chat_messages = get_chat_messages(
                selected_stream_id
            )

            if not chat_messages:
                st.caption(
                    "No messages yet. Start the conversation."
                )

            else:
                for chat_message in chat_messages:
                    message_text = chat_message[1]
                    message_time = chat_message[2]
                    message_username = chat_message[3]
                    message_name = (
                        chat_message[4]
                        or message_username
                    )

                    st.markdown(
                        f"**{message_name}**  \n"
                        f"{message_text}"
                    )

                    st.caption(message_time)
                    st.markdown("---")

            with st.form(
                f"live_chat_form_{selected_stream_id}"
            ):
                new_message = st.text_input(
                    "Message",
                    placeholder="Say something...",
                    max_chars=500,
                )

                send_message = (
                    st.form_submit_button(
                        "Send",
                        use_container_width=True,
                    )
                )

            if send_message:
                if send_chat_message(
                    selected_stream_id,
                    new_message,
                ):
                    st.rerun()

                else:
                    st.warning(
                        "Please enter a message and make sure "
                        "the Live Room is active."
                    )

    elif selected_stream:
        st.warning(
            "This Live Room has ended."
        )

        st.session_state[
            "selected_live_stream"
        ] = None

    else:
        st.session_state[
            "selected_live_stream"
        ] = None


# ---------------------------------------------------------
# RECENT ENDED SESSIONS
# ---------------------------------------------------------

def get_recent_ended_streams():
    conn = get_connection()

    try:
        return conn.execute(
            """
            SELECT
                ls.id,
                ls.title,
                ls.category,
                ls.started_at,
                ls.ended_at,
                ls.viewer_count
            FROM live_streams ls
            WHERE ls.broadcaster_id = ?
              AND ls.status = 'ended'
            ORDER BY ls.ended_at DESC, ls.id DESC
            LIMIT 10
            """,
            (user_id,),
        ).fetchall()

    finally:
        conn.close()


recent_sessions = get_recent_ended_streams()

if recent_sessions:
    st.divider()

    st.subheader(
        "🕘 Recent Live Sessions"
    )

    for session in recent_sessions:
        (
            session_id,
            title,
            category,
            started_at,
            ended_at,
            max_viewers,
        ) = session

        with st.container(border=True):
            st.markdown(
                f"**{title}**"
            )

            st.caption(
                f"Category: "
                f"{category or 'General'}"
            )

            start_col, end_col, duration_col, viewers_col = (
                st.columns(4)
            )

            with start_col:
                st.write(
                    f"**Start**\n"
                    f"{format_live_time(started_at)}"
                )

            with end_col:
                st.write(
                    f"**End**\n"
                    f"{format_live_time(ended_at)}"
                )

            with duration_col:
                st.write(
                    f"**Duration**\n"
                    f"{calculate_live_duration(started_at, ended_at)}"
                )

            with viewers_col:
                st.write(
                    f"**Viewer count**\n"
                    f"{max_viewers}"
                )


# ---------------------------------------------------------
# DEVELOPMENT ROADMAP
# ---------------------------------------------------------

st.divider()

st.subheader(
    "🚀 LifeGrid Live Development"
)

roadmap_col1, roadmap_col2 = st.columns(2)

with roadmap_col1:
    st.markdown(
        """
        **Working foundation**

        - Live Room creation
        - Broadcaster status
        - Scheduled Live sessions
        - Start time
        - End time
        - Live duration
        - Viewer registration
        - Viewer counts
        - Live chat
        - Reactions
        - Clean host end-session cleanup
        - Stale viewer protection
        - Real browser camera/microphone component
        - Live scheduling notifications
        - Live started notifications
        - Virtual Gift Credits
        - Live gift sending
        - Creator gift earnings
        - Gift notifications and transaction records
        - Live Creator Support
        - Wallet settlement
        - Platform revenue recording
        """
    )

with roadmap_col2:
    st.markdown(
        """
        **Next transport stage**

        - Shared multi-user video broadcast
        - WebRTC signaling/media server
        - Stream quality controls
        - Data-saving mode
        - Automatic scheduled reminders
        - Moderation and reporting
        """
    )