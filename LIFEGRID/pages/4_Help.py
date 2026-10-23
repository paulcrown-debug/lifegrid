import sqlite3
import uuid
from datetime import datetime

import streamlit as st

from database import get_connection

st.set_page_config(
    page_title="Help | LifeGrid",
    page_icon="🤝",
    layout="wide",
)

if "user" not in st.session_state or st.session_state.user is None:
    st.warning("Please log in to access Help.")
    st.stop()

current_user = st.session_state.user
current_user_id = int(current_user["id"])


def columns(conn, table):
    try:
        return [
            r[1]
            for r in conn.execute(
                f"PRAGMA table_info({table})"
            ).fetchall()
        ]
    except sqlite3.Error:
        return []


def ensure_help_columns():
    conn = get_connection()

    try:
        cols = columns(conn, "help_requests")

        additions = {
            "target_helper_id": "INTEGER",
            "accepted_at": "TIMESTAMP",
            "completed_at": "TIMESTAMP",
            "confirmed_at": "TIMESTAMP",
            "wallet_amount": "REAL DEFAULT 0",
            "wallet_transfer_reference": "TEXT",
        }

        for name, typ in additions.items():
            if name not in cols:
                conn.execute(
                    f"ALTER TABLE help_requests ADD COLUMN {name} {typ}"
                )

        conn.commit()

    finally:
        conn.close()


def ensure_notifications_table():
    conn = get_connection()

    try:
        conn.execute(
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        conn.commit()

    finally:
        conn.close()


def create_notification(
    conn,
    user_id,
    notification_type,
    title,
    message,
    reference_type=None,
    reference_id=None,
):
    if not user_id:
        return

    notification_cols = columns(conn, "notifications")

    if not notification_cols:
        return

    fields = [
        "user_id",
        "notification_type",
        "title",
        "message",
    ]

    values = [
        int(user_id),
        notification_type,
        title,
        message,
    ]

    if "reference_type" in notification_cols:
        fields.append("reference_type")
        values.append(reference_type)

    if "reference_id" in notification_cols:
        fields.append("reference_id")
        values.append(reference_id)

    if "is_read" in notification_cols:
        fields.append("is_read")
        values.append(0)

    marks = ",".join("?" for _ in values)

    conn.execute(
        f"""
        INSERT INTO notifications (
            {", ".join(fields)}
        )
        VALUES ({marks})
        """,
        values,
    )


def user_row(conn, user_id):
    cols = columns(conn, "users")

    wanted = [
        x
        for x in (
            "id",
            "username",
            "full_name",
            "email",
            "currency",
        )
        if x in cols
    ]

    if not wanted:
        return {
            "id": user_id,
            "username": "LifeGrid user",
            "full_name": "",
            "currency": "USD",
        }

    row = conn.execute(
        f"""
        SELECT {", ".join(wanted)}
        FROM users
        WHERE id=?
        """,
        (user_id,),
    ).fetchone()

    if not row:
        return {
            "id": user_id,
            "username": "LifeGrid user",
            "full_name": "",
            "currency": "USD",
        }

    data = dict(zip(wanted, row))

    data.setdefault("currency", "USD")
    data.setdefault("full_name", "")
    data.setdefault("username", "LifeGrid user")

    return data


def name_of(conn, user_id):
    u = user_row(conn, user_id)

    return (
        u.get("full_name")
        or u.get("username")
        or "LifeGrid user"
    )


def wallet(conn, user_id, create=True):
    cols = columns(conn, "wallets")

    required = {
        "user_id",
        "currency",
        "balance",
        "pending_balance",
        "available_balance",
    }

    if not required.issubset(cols):
        return None

    row = conn.execute(
        """
        SELECT
            user_id,
            currency,
            balance,
            available_balance,
            pending_balance,
            wallet_status
        FROM wallets
        WHERE user_id=?
        """,
        (user_id,),
    ).fetchone()

    if row is None and create:
        currency = (
            user_row(conn, user_id).get("currency")
            or "USD"
        )

        conn.execute(
            """
            INSERT INTO wallets (
                user_id,
                currency,
                balance,
                available_balance,
                pending_balance,
                wallet_status
            )
            VALUES (?,?,?,?,?,?)
            """,
            (
                user_id,
                currency,
                0,
                0,
                0,
                "Active",
            ),
        )

        conn.commit()

        row = conn.execute(
            """
            SELECT
                user_id,
                currency,
                balance,
                available_balance,
                pending_balance,
                wallet_status
            FROM wallets
            WHERE user_id=?
            """,
            (user_id,),
        ).fetchone()

    if row is None:
        return None

    balance = round(
        float(row[2] or 0),
        2,
    )

    pending = round(
        float(row[4] or 0),
        2,
    )

    available = round(
        max(0.0, balance - pending),
        2,
    )

    return {
        "user_id": int(row[0]),
        "currency": row[1] or "USD",
        "balance": balance,
        "available_balance": available,
        "pending_balance": pending,
        "wallet_status": row[5] or "Active",
    }


def reference():
    return (
        "LG-HELP-"
        + datetime.now().strftime("%Y%m%d%H%M%S")
        + "-"
        + uuid.uuid4().hex[:8].upper()
    )


def record_transaction(
    conn,
    user_id,
    transaction_type,
    amount,
    currency,
    description,
    ref,
    counterparty,
):
    cols = columns(
        conn,
        "wallet_transactions",
    )

    if not cols:
        return

    data = {
        "user_id": user_id,
        "transaction_type": transaction_type,
        "amount": round(float(amount), 2),
        "currency": currency,
        "description": description,
        "reference": ref,
        "status": "Completed",
        "asset_type": "FIAT",
        "asset_code": currency,
        "network": "",
        "counterparty_user_id": counterparty,
    }

    usable = [
        (k, v)
        for k, v in data.items()
        if k in cols
    ]

    if (
        "user_id" not in cols
        or "amount" not in cols
    ):
        return

    names = ", ".join(
        k for k, _ in usable
    )

    marks = ", ".join(
        "?" for _ in usable
    )

    conn.execute(
        f"""
        INSERT INTO wallet_transactions (
            {names}
        )
        VALUES ({marks})
        """,
        tuple(v for _, v in usable),
    )


def transfer_help(
    conn,
    request_id,
    requester_id,
    helper_id,
    amount,
    title,
):
    amount = round(
        float(amount or 0),
        2,
    )

    if amount <= 0:
        conn.execute(
            """
            UPDATE help_requests
            SET
                status='Confirmed',
                confirmed_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (request_id,),
        )

        create_notification(
            conn,
            helper_id,
            "Help",
            "Help Confirmed",
            f'The requester confirmed the completed Help request "{title}".',
            "help_request",
            request_id,
        )

        conn.commit()

        return True, {
            "reference": None,
            "amount": 0,
            "currency": "USD",
            "helper_id": helper_id,
        }

    if requester_id == helper_id:
        return (
            False,
            "The requester and helper cannot be the same account.",
        )

    try:
        conn.execute("BEGIN IMMEDIATE")

        req = conn.execute(
            """
            SELECT
                requester_id,
                helper_id,
                target_helper_id,
                status,
                wallet_amount,
                wallet_transfer_reference
            FROM help_requests
            WHERE id=?
            """,
            (request_id,),
        ).fetchone()

        if not req:
            conn.rollback()
            return False, "Help request was not found."

        if req[3] != "Completed":
            conn.rollback()

            return (
                False,
                "This Help request must be marked Completed "
                "before confirmation.",
            )

        actual_helper = int(
            req[1]
            or req[2]
            or helper_id
            or 0
        )

        if actual_helper != int(helper_id):
            conn.rollback()

            return (
                False,
                "The helper account could not be verified.",
            )

        sender = wallet(
            conn,
            actual_helper,
            create=True,
        )

        receiver = wallet(
            conn,
            requester_id,
            create=True,
        )

        if not sender or not receiver:
            conn.rollback()

            return (
                False,
                "A required development wallet could not be found.",
            )

        if sender["wallet_status"] != "Active":
            conn.rollback()

            return (
                False,
                "The helper wallet is not active.",
            )

        if receiver["wallet_status"] != "Active":
            conn.rollback()

            return (
                False,
                "The requester wallet is not active.",
            )

        if sender["currency"] != receiver["currency"]:
            conn.rollback()

            return (
                False,
                "Currency mismatch between the helper "
                "and requester wallets.",
            )

        available = round(
            max(
                0.0,
                sender["balance"]
                - sender["pending_balance"],
            ),
            2,
        )

        if available < amount:
            conn.rollback()

            return (
                False,
                f"The helper does not have enough available "
                f"wallet balance to transfer "
                f"{sender['currency']} {amount:,.2f}. "
                f"Actual wallet balance: "
                f"{sender['balance']:,.2f}. "
                f"Pending: "
                f"{sender['pending_balance']:,.2f}. "
                f"Available: "
                f"{available:,.2f}.",
            )

        conn.execute(
            """
            UPDATE wallets
            SET available_balance=?
            WHERE user_id=?
            """,
            (
                available,
                actual_helper,
            ),
        )

        receiver_available_before = round(
            max(
                0.0,
                receiver["balance"]
                - receiver["pending_balance"],
            ),
            2,
        )

        conn.execute(
            """
            UPDATE wallets
            SET available_balance=?
            WHERE user_id=?
            """,
            (
                receiver_available_before,
                requester_id,
            ),
        )

        conn.execute(
            """
            UPDATE wallets
            SET
                balance=balance-?,
                available_balance=available_balance-?
            WHERE user_id=?
            """,
            (
                amount,
                amount,
                actual_helper,
            ),
        )

        conn.execute(
            """
            UPDATE wallets
            SET
                balance=balance+?,
                available_balance=available_balance+?
            WHERE user_id=?
            """,
            (
                amount,
                amount,
                requester_id,
            ),
        )

        ref = reference()

        outgoing_ref = ref + "-OUT"
        incoming_ref = ref + "-IN"

        record_transaction(
            conn,
            actual_helper,
            "Help Funds Sent",
            amount,
            sender["currency"],
            f"Help confirmed: {title}",
            outgoing_ref,
            requester_id,
        )

        record_transaction(
            conn,
            requester_id,
            "Help Funds Received",
            amount,
            sender["currency"],
            f"Help received: {title}",
            incoming_ref,
            actual_helper,
        )

        conn.execute(
            """
            UPDATE help_requests
            SET
                status='Confirmed',
                confirmed_at=CURRENT_TIMESTAMP,
                wallet_transfer_reference=?
            WHERE id=?
            """,
            (
                ref,
                request_id,
            ),
        )

        create_notification(
            conn,
            actual_helper,
            "Help",
            "Help Confirmed",
            f'The requester confirmed the completed Help request "{title}". '
            f'{sender["currency"]} {amount:,.2f} was transferred from your development wallet.',
            "help_request",
            request_id,
        )

        create_notification(
            conn,
            requester_id,
            "Wallet",
            "Help Support Received",
            f'You confirmed the Help request "{title}" and '
            f'received {sender["currency"]} {amount:,.2f} '
            f'in your development wallet.',
            "help_request",
            request_id,
        )

        conn.commit()

        return True, {
            "reference": ref,
            "amount": amount,
            "currency": sender["currency"],
            "helper_id": actual_helper,
        }

    except sqlite3.Error as exc:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass

        return False, f"Database transaction failed: {exc}"


ensure_help_columns()
ensure_notifications_table()


# Load requests with a stable explicit column list.
conn = get_connection()

try:
    hr_cols = columns(
        conn,
        "help_requests",
    )

    required = {
        "id",
        "requester_id",
        "title",
        "description",
        "status",
    }

    if not required.issubset(hr_cols):
        st.error(
            "The Help database table is missing required "
            "columns. Please restart LifeGrid after updating "
            "the database."
        )

        st.stop()

    select_cols = [
        "id",
        "requester_id",
        "helper_id",
        "title",
        "description",
        "category",
        "help_type",
        "target_date",
        "status",
        "created_at",
        "accepted_at",
        "target_helper_id",
        "completed_at",
        "confirmed_at",
        "wallet_amount",
        "wallet_transfer_reference",
    ]

    select_cols = [
        c
        for c in select_cols
        if c in hr_cols
    ]

    rows = conn.execute(
        f"""
        SELECT {", ".join(select_cols)}
        FROM help_requests
        ORDER BY id DESC
        """
    ).fetchall()

finally:
    conn.close()


index = {
    name: i
    for i, name in enumerate(select_cols)
}


def val(row, key, default=None):
    i = index.get(key)

    if i is None:
        return default

    return row[i]


my_requests = [
    r
    for r in rows
    if int(
        val(
            r,
            "requester_id",
            -1,
        )
    ) == current_user_id
]


helping = [
    r
    for r in rows
    if int(
        val(
            r,
            "helper_id",
            -1,
        )
        or -1
    ) == current_user_id
]


open_requests = [
    r
    for r in rows
    if val(r, "status") == "Open"
    and int(
        val(
            r,
            "requester_id",
            -1,
        )
    ) != current_user_id
]


st.title("🤝 LifeGrid Help")

st.write(
    "Request help, offer help, complete help, "
    "and confirm development-wallet support."
)

st.caption(
    "Development wallet only • Available balance "
    "is always calculated as Balance − Pending."
)


request_tab, offer_tab, providing_tab = st.tabs(
    [
        "🤲 Request Help",
        "🙋 Offer Help",
        "💼 Help I Am Providing",
    ]
)


with request_tab:

    st.subheader("Create a Help Request")

    with st.form(
        "create_help_form",
        clear_on_submit=True,
    ):

        title = st.text_input(
            "What do you need help with?",
            placeholder=(
                "Example: I need help with my business plan"
            ),
        )

        description = st.text_area(
            "Describe the help you need"
        )

        category = st.selectbox(
            "Help Category",
            [
                "General",
                "Business",
                "Education",
                "Career",
                "Finance",
                "Technology",
                "Construction",
                "Community",
                "Other",
            ],
        )

        help_type = st.selectbox(
            "Type of Help",
            [
                "Advice",
                "Information",
                "Practical Help",
                "Financial Help",
                "Professional Help",
                "Connection / Introduction",
                "Other",
            ],
        )

        wallet_amount = st.number_input(
            "Development Wallet Support Amount",
            min_value=0.0,
            value=0.0,
            step=1.0,
            format="%.2f",
        )

        submit = st.form_submit_button(
            "🤲 Publish Help Request",
            use_container_width=True,
        )

    if submit:

        if (
            not title.strip()
            or not description.strip()
        ):
            st.error(
                "Please enter both the help title "
                "and description."
            )

        else:

            conn = get_connection()

            try:
                cols = columns(
                    conn,
                    "help_requests",
                )

                fields = [
                    "requester_id",
                    "title",
                    "description",
                    "category",
                    "help_type",
                    "status",
                ]

                values = [
                    current_user_id,
                    title.strip(),
                    description.strip(),
                    category,
                    help_type,
                    "Open",
                ]

                if "target_date" in cols:
                    fields.append("target_date")
                    values.append(None)

                if "target_helper_id" in cols:
                    fields.append("target_helper_id")
                    values.append(None)

                if "wallet_amount" in cols:
                    fields.append("wallet_amount")
                    values.append(
                        round(
                            float(wallet_amount),
                            2,
                        )
                    )

                marks = ",".join(
                    "?"
                    for _ in values
                )

                cursor = conn.execute(
                    f"""
                    INSERT INTO help_requests (
                        {", ".join(fields)}
                    )
                    VALUES ({marks})
                    """,
                    values,
                )

                request_id = cursor.lastrowid

                create_notification(
                    conn,
                    current_user_id,
                    "Help",
                    "Help Request Published",
                    f'Your Help request "{title.strip()}" '
                    "has been published successfully and is now "
                    "available for other LifeGrid users to offer help.",
                    "help_request",
                    request_id,
                )

                conn.commit()

                st.success(
                    "Your Help request has been published."
                )

                st.rerun()

            except sqlite3.Error as exc:

                conn.rollback()

                st.error(
                    f"Could not create the Help request: {exc}"
                )

            finally:
                conn.close()

    st.divider()

    st.subheader("My Help Requests")

    if not my_requests:
        st.info(
            "You have not created any Help requests yet."
        )

    for row in my_requests:

        rid = val(row, "id")
        status = val(row, "status")

        amount = float(
            val(
                row,
                "wallet_amount",
                0,
            )
            or 0
        )

        helper_id = (
            val(row, "helper_id")
            or val(row, "target_helper_id")
        )

        st.markdown("---")

        st.subheader(
            val(
                row,
                "title",
                "Help request",
            )
        )

        st.write(
            val(
                row,
                "description",
                "",
            )
        )

        st.caption(
            f"Status: {status} • "
            f"Category: {val(row, 'category', 'General')} • "
            f"Type: {val(row, 'help_type', 'Other')}"
        )

        if amount > 0:
            st.info(
                f"💳 Development wallet support: "
                f"{amount:,.2f}"
            )

        if helper_id:

            conn = get_connection()

            try:
                st.caption(
                    f"Helper: "
                    f"{name_of(conn, int(helper_id))}"
                )

            finally:
                conn.close()

        if status == "Accepted":

            st.info(
                "Your helper has accepted this request. "
                "Wait for the help to be completed."
            )

        elif status == "Completed":

            st.warning(
                "The help is marked completed. "
                "Please confirm that you received the help."
            )

            if st.button(
                "✅ Confirm Help Received",
                key=f"confirm_{rid}",
                use_container_width=True,
            ):

                conn = get_connection()

                try:

                    current = conn.execute(
                        """
                        SELECT
                            requester_id,
                            helper_id,
                            target_helper_id,
                            status,
                            wallet_amount,
                            wallet_transfer_reference,
                            title
                        FROM help_requests
                        WHERE id=?
                        """,
                        (rid,),
                    ).fetchone()

                    if (
                        not current
                        or int(current[0])
                        != current_user_id
                    ):

                        st.error(
                            "You are not authorized "
                            "to confirm this Help request."
                        )

                    elif current[3] != "Completed":

                        st.error(
                            "This Help request is no longer "
                            "waiting for confirmation."
                        )

                    else:

                        helper_id_now = (
                            current[1]
                            or current[2]
                        )

                        ok, result = transfer_help(
                            conn,
                            rid,
                            current_user_id,
                            int(helper_id_now),
                            float(
                                current[4]
                                or 0
                            ),
                            current[6]
                            or "Help",
                        )

                        if ok:

                            if result["amount"] > 0:

                                st.success(
                                    "Help confirmed. "
                                    f"{result['currency']} "
                                    f"{result['amount']:,.2f} "
                                    "transferred successfully."
                                )

                                st.caption(
                                    "Transaction reference: "
                                    f"{result['reference']}"
                                )

                            else:

                                st.success(
                                    "Help received "
                                    "and confirmed."
                                )

                            st.rerun()

                        else:

                            st.error(
                                "Help was not confirmed because "
                                "the development wallet transfer "
                                f"could not be completed: {result}"
                            )

                            st.warning(
                                "No wallet funds were moved. "
                                "The Help request remains "
                                "waiting for confirmation."
                            )

                finally:
                    conn.close()

        elif status == "Confirmed":

            st.success(
                "✅ Help received and confirmed."
            )

            ref = val(
                row,
                "wallet_transfer_reference",
            )

            if amount > 0 and ref:

                st.caption(
                    "Transaction reference: "
                    f"{ref}"
                )


with offer_tab:

    st.subheader("Open Help Requests")

    if not open_requests:

        st.info(
            "There are no open Help requests right now."
        )

    for row in open_requests:

        rid = val(
            row,
            "id",
        )

        st.markdown("---")

        st.subheader(
            val(
                row,
                "title",
                "Help request",
            )
        )

        st.write(
            val(
                row,
                "description",
                "",
            )
        )

        conn = get_connection()

        try:

            requester_name = name_of(
                conn,
                int(
                    val(
                        row,
                        "requester_id",
                    )
                ),
            )

        finally:
            conn.close()

        st.caption(
            f"Requester: {requester_name} • "
            f"{val(row, 'category', 'General')} • "
            f"{val(row, 'help_type', 'Other')}"
        )

        amount = float(
            val(
                row,
                "wallet_amount",
                0,
            )
            or 0
        )

        if amount > 0:

            st.info(
                f"💳 Requested wallet support: "
                f"{amount:,.2f}"
            )

        if st.button(
            "🙋 Accept This Help Request",
            key=f"accept_{rid}",
            use_container_width=True,
        ):

            conn = get_connection()

            try:

                request_data = conn.execute(
                    """
                    SELECT
                        requester_id,
                        title,
                        status
                    FROM help_requests
                    WHERE id=?
                    """,
                    (rid,),
                ).fetchone()

                result = conn.execute(
                    """
                    UPDATE help_requests
                    SET
                        helper_id=?,
                        status='Accepted',
                        accepted_at=CURRENT_TIMESTAMP
                    WHERE id=?
                      AND status='Open'
                    """,
                    (
                        current_user_id,
                        rid,
                    ),
                )

                if result.rowcount:

                    requester_id = int(
                        request_data[0]
                    )

                    request_title = (
                        request_data[1]
                        or "Help request"
                    )

                    create_notification(
                        conn,
                        requester_id,
                        "Help",
                        "Help Request Accepted",
                        f'{name_of(conn, current_user_id)} '
                        f'has accepted your Help request '
                        f'"{request_title}".',
                        "help_request",
                        rid,
                    )

                    create_notification(
                        conn,
                        current_user_id,
                        "Help",
                        "Help Request Accepted",
                        f'You accepted the Help request '
                        f'"{request_title}".',
                        "help_request",
                        rid,
                    )

                    conn.commit()

                    st.success(
                        "You accepted this Help request."
                    )

                    st.rerun()

                else:

                    conn.rollback()

                    st.error(
                        "This Help request was already "
                        "accepted by another user."
                    )

            except sqlite3.Error as exc:

                conn.rollback()

                st.error(
                    f"Could not accept the request: {exc}"
                )

            finally:
                conn.close()


with providing_tab:

    st.subheader("💼 Help I Am Providing")

    if not helping:

        st.info(
            "You are not currently helping anyone."
        )

    for row in helping:

        rid = val(
            row,
            "id",
        )

        status = val(
            row,
            "status",
        )

        amount = float(
            val(
                row,
                "wallet_amount",
                0,
            )
            or 0
        )

        requester_id = int(
            val(
                row,
                "requester_id",
            )
        )

        st.markdown("---")

        st.subheader(
            val(
                row,
                "title",
                "Help request",
            )
        )

        st.write(
            val(
                row,
                "description",
                "",
            )
        )

        conn = get_connection()

        try:

            requester_name = name_of(
                conn,
                requester_id,
            )

            own = wallet(
                conn,
                current_user_id,
                create=True,
            )

        finally:
            conn.close()

        st.caption(
            f"Requester: {requester_name} • "
            f"Status: {status}"
        )

        if amount > 0:

            st.info(
                f"💳 Development wallet support: "
                f"{amount:,.2f}"
            )

        if own:

            st.caption(
                f"Your development wallet: "
                f"{own['currency']} "
                f"{own['balance']:,.2f} balance • "
                f"{own['pending_balance']:,.2f} pending • "
                f"{own['available_balance']:,.2f} available"
            )

        if status == "Accepted":

            if st.button(
                "✅ Mark Help as Completed",
                key=f"complete_{rid}",
                use_container_width=True,
            ):

                conn = get_connection()

                try:

                    request_data = conn.execute(
                        """
                        SELECT
                            requester_id,
                            title,
                            status
                        FROM help_requests
                        WHERE id=?
                        """,
                        (rid,),
                    ).fetchone()

                    result = conn.execute(
                        """
                        UPDATE help_requests
                        SET
                            status='Completed',
                            completed_at=CURRENT_TIMESTAMP
                        WHERE id=?
                          AND helper_id=?
                          AND status='Accepted'
                        """,
                        (
                            rid,
                            current_user_id,
                        ),
                    )

                    if result.rowcount:

                        requester_id_for_notification = int(
                            request_data[0]
                        )

                        request_title = (
                            request_data[1]
                            or "Help request"
                        )

                        create_notification(
                            conn,
                            requester_id_for_notification,
                            "Help",
                            "Help Completed",
                            f'The Help request '
                            f'"{request_title}" has been '
                            "marked as completed by the helper. "
                            "Please review and confirm that "
                            "you received the help.",
                            "help_request",
                            rid,
                        )

                        create_notification(
                            conn,
                            current_user_id,
                            "Help",
                            "Help Marked Completed",
                            f'You marked the Help request '
                            f'"{request_title}" as completed. '
                            "The requester can now confirm it.",
                            "help_request",
                            rid,
                        )

                        conn.commit()

                        st.success(
                            "Help marked as completed. "
                            "The requester can now confirm it."
                        )

                        st.rerun()

                    else:

                        conn.rollback()

                        st.error(
                            "The Help request could not "
                            "be marked completed."
                        )

                except sqlite3.Error as exc:

                    conn.rollback()

                    st.error(
                        f"Could not complete the Help request: "
                        f"{exc}"
                    )

                finally:
                    conn.close()

        elif status == "Completed":

            st.info(
                "Waiting for the requester to confirm "
                "the completed Help and, if applicable, "
                "transfer the wallet support."
            )

        elif status == "Confirmed":

            st.success(
                "✅ The requester confirmed the Help."
            )

            ref = val(
                row,
                "wallet_transfer_reference",
            )

            if amount > 0 and ref:

                st.caption(
                    "Transaction reference: "
                    f"{ref}"
                )


st.divider()

st.caption(
    "LifeGrid Help • Development wallet transactions "
    "are recorded in the wallet transaction ledger "
    "when support is transferred."
)