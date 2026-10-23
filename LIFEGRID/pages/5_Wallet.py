
import sqlite3
import uuid

import streamlit as st

from database import get_connection


# =========================================================
# PAGE CONFIGURATION
# =========================================================

st.set_page_config(
    page_title="Wallet | LifeGrid",
    page_icon="💰",
    layout="wide",
)


# =========================================================
# LOGIN PROTECTION
# =========================================================

if "user" not in st.session_state or not st.session_state.user:
    st.warning("Please log in to access your LifeGrid Wallet.")

    if st.button("Go to Login"):
        st.switch_page("app.py")

    st.stop()


user = st.session_state.user
user_id = int(user["id"])

user_currency = user.get("currency") or "NGN"


# =========================================================
# DATABASE HELPERS
# =========================================================

def ensure_column(connection, table_name, column_name, column_definition):
    """Add a column when it does not already exist."""

    cursor = connection.cursor()

    cursor.execute(
        f"PRAGMA table_info({table_name})"
    )

    columns = [row[1] for row in cursor.fetchall()]

    if column_name not in columns:
        cursor.execute(
            f"""
            ALTER TABLE {table_name}
            ADD COLUMN {column_name} {column_definition}
            """
        )

        connection.commit()


def create_notification(
    connection,
    recipient_id,
    title,
    message,
):
    """Create a LifeGrid notification when possible."""

    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO notifications (
                user_id,
                title,
                message
            )
            VALUES (?, ?, ?)
            """,
            (
                recipient_id,
                title,
                message,
            ),
        )

    except sqlite3.OperationalError:
        try:
            cursor.execute(
                """
                INSERT INTO notifications (
                    user_id,
                    notification_type,
                    title,
                    message
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    recipient_id,
                    "wallet",
                    title,
                    message,
                ),
            )

        except sqlite3.OperationalError:
            pass


def find_user_by_receiving_id(connection, receiving_id):
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT
            u.id,
            u.username,
            u.full_name,
            u.currency,
            ra.receiving_id,
            ra.currency,
            ra.account_status,
            ra.verification_status
        FROM receiving_accounts ra
        JOIN users u
            ON u.id = ra.user_id
        WHERE ra.receiving_id = ?
        """,
        (receiving_id,),
    )

    return cursor.fetchone()


def get_wallet(connection, wallet_user_id):
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT
            id,
            user_id,
            currency,
            balance,
            available_balance,
            pending_balance,
            wallet_status
        FROM wallets
        WHERE user_id = ?
        """,
        (wallet_user_id,),
    )

    return cursor.fetchone()


# =========================================================
# DATABASE SETUP
# =========================================================

connection = get_connection()
cursor = connection.cursor()


# ---------------------------------------------------------
# Wallet table
# ---------------------------------------------------------

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS wallets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE NOT NULL,
        currency TEXT DEFAULT 'NGN',
        balance REAL DEFAULT 0,
        available_balance REAL DEFAULT 0,
        pending_balance REAL DEFAULT 0,
        wallet_status TEXT DEFAULT 'Active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """
)


# ---------------------------------------------------------
# Receiving accounts
# ---------------------------------------------------------

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS receiving_accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE NOT NULL,
        receiving_id TEXT UNIQUE NOT NULL,
        currency TEXT DEFAULT 'NGN',
        account_status TEXT DEFAULT 'Active',
        verification_status TEXT DEFAULT 'Not Verified',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """
)


# ---------------------------------------------------------
# Wallet transactions
# ---------------------------------------------------------

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS wallet_transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        transaction_type TEXT NOT NULL,
        amount REAL NOT NULL,
        currency TEXT NOT NULL,
        description TEXT,
        reference TEXT UNIQUE,
        status TEXT DEFAULT 'Completed',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """
)


# ---------------------------------------------------------
# Development wallet assets
# ---------------------------------------------------------

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS wallet_assets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        asset_type TEXT NOT NULL,
        asset_code TEXT NOT NULL,
        network TEXT DEFAULT '',
        balance REAL DEFAULT 0,
        available_balance REAL DEFAULT 0,
        pending_balance REAL DEFAULT 0,
        asset_status TEXT DEFAULT 'Active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, asset_type, asset_code, network),
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """
)


# ---------------------------------------------------------
# Crypto transaction table
# ---------------------------------------------------------

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS crypto_transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        transaction_type TEXT NOT NULL,
        asset_code TEXT NOT NULL,
        network TEXT NOT NULL,
        amount REAL NOT NULL,
        recipient_user_id INTEGER,
        recipient_address TEXT,
        transaction_hash TEXT,
        description TEXT,
        status TEXT DEFAULT 'Development',
        reference TEXT UNIQUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """
)


# ---------------------------------------------------------
# Preserve compatibility with existing wallet transactions
# ---------------------------------------------------------

ensure_column(
    connection,
    "wallet_transactions",
    "asset_type",
    "TEXT DEFAULT 'FIAT'",
)

ensure_column(
    connection,
    "wallet_transactions",
    "asset_code",
    "TEXT",
)

ensure_column(
    connection,
    "wallet_transactions",
    "network",
    "TEXT",
)

ensure_column(
    connection,
    "wallet_transactions",
    "counterparty_user_id",
    "INTEGER",
)


# =========================================================
# CREATE USER WALLET
# =========================================================

cursor.execute(
    """
    SELECT id
    FROM wallets
    WHERE user_id = ?
    """,
    (user_id,),
)

wallet = cursor.fetchone()


if not wallet:
    cursor.execute(
        """
        INSERT INTO wallets (
            user_id,
            currency,
            balance,
            available_balance,
            pending_balance,
            wallet_status
        )
        VALUES (?, ?, 0, 0, 0, 'Active')
        """,
        (
            user_id,
            user_currency,
        ),
    )


# =========================================================
# CREATE RECEIVING ACCOUNT
# =========================================================

cursor.execute(
    """
    SELECT
        id,
        receiving_id,
        currency,
        account_status,
        verification_status
    FROM receiving_accounts
    WHERE user_id = ?
    """,
    (user_id,),
)

receiving_account = cursor.fetchone()


if not receiving_account:

    receiving_id = f"LG-{user_id:08d}"

    cursor.execute(
        """
        INSERT INTO receiving_accounts (
            user_id,
            receiving_id,
            currency,
            account_status,
            verification_status
        )
        VALUES (?, ?, ?, 'Active', 'Not Verified')
        """,
        (
            user_id,
            receiving_id,
            user_currency,
        ),
    )


connection.commit()


# =========================================================
# LOAD WALLET
# =========================================================

cursor.execute(
    """
    SELECT
        balance,
        available_balance,
        pending_balance,
        currency,
        wallet_status
    FROM wallets
    WHERE user_id = ?
    """,
    (user_id,),
)

wallet_data = cursor.fetchone()

balance = float(wallet_data[0] or 0)
available_balance = float(wallet_data[1] or 0)
pending_balance = float(wallet_data[2] or 0)
wallet_currency = wallet_data[3]
wallet_status = wallet_data[4]

# Keep the development wallet's spendable balance synchronized
# with the actual wallet balance. Pending funds are excluded.
if abs(available_balance - (balance - pending_balance)) > 0.0000001:
    available_balance = max(0.0, balance - pending_balance)
    sync_connection = get_connection()
    sync_connection.execute(
        """
        UPDATE wallets
        SET available_balance = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE user_id = ?
        """,
        (available_balance, user_id),
    )
    sync_connection.commit()
    sync_connection.close()


# =========================================================
# LOAD RECEIVING ACCOUNT
# =========================================================

cursor.execute(
    """
    SELECT
        receiving_id,
        currency,
        account_status,
        verification_status
    FROM receiving_accounts
    WHERE user_id = ?
    """,
    (user_id,),
)

receiving_account = cursor.fetchone()

receiving_id = receiving_account[0]
receiving_currency = receiving_account[1]
receiving_status = receiving_account[2]
verification_status = receiving_account[3]


connection.close()


# =========================================================
# PAGE HEADER
# =========================================================

st.title("💰 LifeGrid Wallet")

st.write(
    "Manage your LifeGrid balance, receiving account, "
    "earnings, gifts, help funds, transfers, and future withdrawals."
)

st.caption(
    "Development wallet • Real-money payments and blockchain "
    "transactions are not enabled yet."
)

st.divider()


# =========================================================
# WALLET OVERVIEW
# =========================================================

st.subheader("💳 Wallet Overview")

wallet_col1, wallet_col2, wallet_col3, wallet_col4 = st.columns(4)


with wallet_col1:
    st.metric(
        "Total Balance",
        f"{wallet_currency} {balance:,.2f}",
    )


with wallet_col2:
    st.metric(
        "Available",
        f"{wallet_currency} {available_balance:,.2f}",
    )


with wallet_col3:
    st.metric(
        "Pending",
        f"{wallet_currency} {pending_balance:,.2f}",
    )


with wallet_col4:
    st.metric(
        "Wallet Status",
        wallet_status,
    )


st.divider()


# =========================================================
# RECEIVING ACCOUNT
# =========================================================

st.subheader("🏦 My Receiving Account")

st.write(
    "Your Receiving Account is your LifeGrid identity "
    "for receiving supported funds."
)

account_col1, account_col2 = st.columns(2)


with account_col1:

    st.markdown(
        f"**Receiving ID:** `{receiving_id}`"
    )

    st.write(
        f"**Currency:** {receiving_currency}"
    )

    st.write(
        f"**Account Status:** {receiving_status}"
    )


with account_col2:

    if verification_status == "Verified":

        st.success(
            "✅ Receiving account verified"
        )

    else:

        st.warning(
            "⚠️ Verification is required before "
            "real-money features are enabled."
        )

    st.write(
        f"**Verification Status:** {verification_status}"
    )


st.divider()


# =========================================================
# FIAT AND CRYPTO ASSETS
# =========================================================

st.subheader("🌍 Supported Wallet Assets")

asset_col1, asset_col2 = st.columns(2)


with asset_col1:

    st.markdown("### 💵 Fiat")

    st.write(
        "LifeGrid can be designed to support multiple "
        "fiat currencies such as:"
    )

    st.write(
        "NGN • USD • GBP • EUR • CAD • AUD"
    )


with asset_col2:

    st.markdown("### 🪙 Crypto")

    st.write(
        "Development support is prepared for:"
    )

    st.write(
        "BTC • ETH • USDT • USDC"
    )

    st.warning(
        "Crypto shown here is development-only. "
        "No real blockchain transfer is performed."
    )


st.divider()


# =========================================================
# MONEY COMING INTO LIFEGRID
# =========================================================

st.subheader("💼 Money Coming Into Your LifeGrid Account")

income1, income2, income3, income4 = st.columns(4)


with income1:

    st.markdown("### 🤝 Help Funds")

    st.write(
        "Receive approved financial assistance "
        "through LifeGrid."
    )


with income2:

    st.markdown("### 🎁 Gifts")

    st.write(
        "Receive gifts from other LifeGrid users "
        "where supported."
    )


with income3:

    st.markdown("### 📺 Creator Earnings")

    st.write(
        "Future earnings from approved live streaming "
        "and creator activities."
    )


with income4:

    st.markdown("### 💼 Other Earnings")

    st.write(
        "Future marketplace, services, business, "
        "and approved LifeGrid earnings."
    )


st.divider()


# =========================================================
# INTERNAL FIAT TRANSFER
# =========================================================

st.subheader("💸 Send Funds to Another LifeGrid User")

st.info(
    "Development transfer system. This moves test balance "
    "between LifeGrid development wallets. It does not "
    "connect to a bank, card, Paystack, Flutterwave, "
    "or other real payment provider."
)


with st.form("internal_fiat_transfer_form"):

    recipient_receiving_id = st.text_input(
        "Recipient Receiving ID",
        placeholder="Example: LG-00000002",
    )

    transfer_amount = st.number_input(
        "Amount",
        min_value=0.01,
        value=10.00,
        step=10.00,
    )

    transfer_type = st.selectbox(
        "Transfer Type",
        [
            "Personal Transfer",
            "Gift",
            "Help Funds",
        ],
    )

    transfer_description = st.text_input(
        "Description",
        value="LifeGrid development transfer",
    )

    send_transfer = st.form_submit_button(
        "Send Development Funds",
        type="primary",
    )


if send_transfer:

    recipient_receiving_id = recipient_receiving_id.strip()

    if not recipient_receiving_id:

        st.error(
            "Please enter the recipient Receiving ID."
        )

    else:

        connection = get_connection()
        cursor = connection.cursor()

        recipient = find_user_by_receiving_id(
            connection,
            recipient_receiving_id,
        )

        sender_wallet = get_wallet(
            connection,
            user_id,
        )

        if not recipient:

            st.error(
                "No LifeGrid receiving account was found "
                "with that Receiving ID."
            )

            connection.close()

        else:

            recipient_user_id = int(recipient[0])
            recipient_username = recipient[1]
            recipient_currency = recipient[5]
            recipient_account_status = recipient[6]

            if recipient_user_id == user_id:

                st.error(
                    "You cannot send funds to your own wallet."
                )

                connection.close()

            elif recipient_account_status != "Active":

                st.error(
                    "The recipient receiving account is not active."
                )

                connection.close()

            elif sender_wallet is None:

                st.error(
                    "Your LifeGrid wallet could not be found."
                )

                connection.close()

            elif sender_wallet[6] != "Active":

                st.error(
                    "Your wallet is not active."
                )

                connection.close()

            elif sender_wallet[2] != recipient_currency:

                st.error(
                    "Currency mismatch. The sender and recipient "
                    "wallets must use the same currency for this "
                    "development transfer."
                )

                connection.close()

            else:
                # Re-synchronize the sender's spendable balance immediately
                # before the transfer so stale available_balance cannot reject
                # a valid transaction.
                sender_balance = float(sender_wallet[3] or 0)
                sender_pending = float(sender_wallet[5] or 0)
                sender_available = max(0.0, sender_balance - sender_pending)

                if abs(float(sender_wallet[4] or 0) - sender_available) > 0.0000001:
                    cursor.execute(
                        """
                        UPDATE wallets
                        SET available_balance = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE user_id = ?
                        """,
                        (sender_available, user_id),
                    )
                    connection.commit()
                    sender_wallet = get_wallet(connection, user_id)

                if sender_wallet is None:
                    st.error("Your LifeGrid wallet could not be loaded.")
                    connection.close()

                elif float(sender_wallet[4] or 0) < float(transfer_amount):
                    st.error(
                        "Insufficient available balance. "
                        f"Available: {wallet_currency} "
                        f"{float(sender_wallet[4] or 0):,.2f}"
                    )
                    connection.close()

                else:

                    recipient_wallet = get_wallet(
                        connection,
                        recipient_user_id,
                    )
    
                    if recipient_wallet is None:
    
                        cursor.execute(
                            """
                            INSERT INTO wallets (
                                user_id,
                                currency,
                                balance,
                                available_balance,
                                pending_balance,
                                wallet_status
                            )
                            VALUES (?, ?, 0, 0, 0, 'Active')
                            """,
                            (
                                recipient_user_id,
                                recipient_currency,
                            ),
                        )
    
                        connection.commit()
    
                        recipient_wallet = get_wallet(
                            connection,
                            recipient_user_id,
                        )
    
                    if recipient_wallet[6] != "Active":
    
                        st.error(
                            "The recipient wallet is not active."
                        )
    
                        connection.close()
    
                    else:
    
                        reference_base = uuid.uuid4().hex[:12].upper()
    
                        sender_reference = (
                            f"LGSEND-{reference_base}"
                        )
    
                        recipient_reference = (
                            f"LGRECV-{reference_base}"
                        )
    
                        if transfer_type == "Gift":
    
                            sender_transaction_type = "Gift Sent"
                            recipient_transaction_type = "Gift Received"
    
                        elif transfer_type == "Help Funds":
    
                            sender_transaction_type = "Help Funds Sent"
                            recipient_transaction_type = "Help Funds Received"
    
                        else:
    
                            sender_transaction_type = "Transfer Sent"
                            recipient_transaction_type = "Transfer Received"
    
    
                        # -----------------------------------------
                        # Debit sender
                        # -----------------------------------------
    
                        cursor.execute(
                            """
                            UPDATE wallets
                            SET
                                balance = balance - ?,
                                available_balance = available_balance - ?,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE user_id = ?
                            """,
                            (
                                transfer_amount,
                                transfer_amount,
                                user_id,
                            ),
                        )
    
    
                        # -----------------------------------------
                        # Credit recipient
                        # -----------------------------------------
    
                        cursor.execute(
                            """
                            UPDATE wallets
                            SET
                                balance = balance + ?,
                                available_balance = available_balance + ?,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE user_id = ?
                            """,
                            (
                                transfer_amount,
                                transfer_amount,
                                recipient_user_id,
                            ),
                        )
    
    
                        # -----------------------------------------
                        # Sender transaction
                        # -----------------------------------------
    
                        cursor.execute(
                            """
                            INSERT INTO wallet_transactions (
                                user_id,
                                transaction_type,
                                amount,
                                currency,
                                description,
                                reference,
                                status,
                                asset_type,
                                asset_code,
                                network,
                                counterparty_user_id
                            )
                            VALUES (
                                ?, ?, ?, ?, ?, ?, 'Completed',
                                'FIAT', ?, '', ?
                            )
                            """,
                            (
                                user_id,
                                sender_transaction_type,
                                transfer_amount,
                                wallet_currency,
                                transfer_description.strip(),
                                sender_reference,
                                wallet_currency,
                                recipient_user_id,
                            ),
                        )
    
    
                        # -----------------------------------------
                        # Recipient transaction
                        # -----------------------------------------
    
                        cursor.execute(
                            """
                            INSERT INTO wallet_transactions (
                                user_id,
                                transaction_type,
                                amount,
                                currency,
                                description,
                                reference,
                                status,
                                asset_type,
                                asset_code,
                                network,
                                counterparty_user_id
                            )
                            VALUES (
                                ?, ?, ?, ?, ?, ?, 'Completed',
                                'FIAT', ?, '', ?
                            )
                            """,
                            (
                                recipient_user_id,
                                recipient_transaction_type,
                                transfer_amount,
                                wallet_currency,
                                transfer_description.strip(),
                                recipient_reference,
                                wallet_currency,
                                user_id,
                            ),
                        )
    
    
                        # -----------------------------------------
                        # Notification
                        # -----------------------------------------
    
                        create_notification(
                            connection,
                            recipient_user_id,
                            "💰 Wallet Funds Received",
                            (
                                f"You received "
                                f"{wallet_currency} "
                                f"{transfer_amount:,.2f} "
                                f"from {user.get('username', 'a LifeGrid user')}."
                            ),
                        )
    
    
                        connection.commit()
                        connection.close()
    
    
                        st.success(
                            f"Transfer successful: "
                            f"{wallet_currency} "
                            f"{transfer_amount:,.2f} "
                            f"sent to {recipient_username}."
                        )
    
                        st.rerun()
    
    
    st.divider()
    
    
    # =========================================================
# CRYPTO DEVELOPMENT WALLET
# =========================================================

st.subheader("🪙 Crypto Development Wallet")

st.warning(
    "Development mode only. These balances are test balances. "
    "No real cryptocurrency is being sent to a blockchain."
)


crypto_assets = [
    ("BTC", "Bitcoin", "Bitcoin"),
    ("ETH", "Ethereum", "Ethereum"),
    ("USDT", "Tether", "Ethereum"),
    ("USDC", "USD Coin", "Ethereum"),
]


connection = get_connection()
cursor = connection.cursor()


for asset_code, asset_name, default_network in crypto_assets:

    cursor.execute(
        """
        SELECT id
        FROM wallet_assets
        WHERE user_id = ?
          AND asset_type = 'CRYPTO'
          AND asset_code = ?
          AND network = ?
        """,
        (
            user_id,
            asset_code,
            default_network,
        ),
    )

    asset_exists = cursor.fetchone()

    if not asset_exists:

        cursor.execute(
            """
            INSERT INTO wallet_assets (
                user_id,
                asset_type,
                asset_code,
                network,
                balance,
                available_balance,
                pending_balance,
                asset_status
            )
            VALUES (
                ?, 'CRYPTO', ?, ?, 0, 0, 0, 'Active'
            )
            """,
            (
                user_id,
                asset_code,
                default_network,
            ),
        )


connection.commit()


cursor.execute(
    """
    SELECT
        asset_code,
        network,
        balance,
        available_balance,
        pending_balance,
        asset_status
    FROM wallet_assets
    WHERE user_id = ?
      AND asset_type = 'CRYPTO'
    ORDER BY id
    """,
    (user_id,),
)

crypto_balances = cursor.fetchall()

connection.close()


crypto_cols = st.columns(4)


for index, crypto_balance in enumerate(crypto_balances):

    asset_code = crypto_balance[0]
    network = crypto_balance[1]
    asset_balance = crypto_balance[2]
    asset_available = crypto_balance[3]
    asset_status = crypto_balance[5]

    with crypto_cols[index % 4]:

        st.metric(
            asset_code,
            f"{asset_balance:,.8f}",
        )

        st.caption(
            f"{network} • Available: "
            f"{asset_available:,.8f}"
        )

        if asset_status == "Active":

            st.success("Active")

        else:

            st.warning(asset_status)


st.divider()


# =========================================================
# CRYPTO DEVELOPMENT TRANSFER
# =========================================================

st.subheader("🔗 Send Crypto to Another LifeGrid User")

st.info(
    "This is an internal development transfer only. "
    "It does not send cryptocurrency to a blockchain address."
)


with st.form("crypto_transfer_form"):

    crypto_asset = st.selectbox(
        "Crypto Asset",
        [
            "BTC",
            "ETH",
            "USDT",
            "USDC",
        ],
    )

    crypto_network_options = {
        "BTC": ["Bitcoin"],
        "ETH": ["Ethereum"],
        "USDT": ["Ethereum", "Tron"],
        "USDC": ["Ethereum"],
    }

    crypto_network = st.selectbox(
        "Network",
        crypto_network_options[crypto_asset],
    )

    crypto_recipient_id = st.text_input(
        "Recipient Receiving ID",
        placeholder="Example: LG-00000002",
    )

    crypto_amount = st.number_input(
        "Crypto Amount",
        min_value=0.00000001,
        value=0.0001,
        step=0.0001,
        format="%.8f",
    )

    crypto_description = st.text_input(
        "Description",
        value="LifeGrid development crypto transfer",
    )

    send_crypto = st.form_submit_button(
        "Send Development Crypto",
        type="primary",
    )


if send_crypto:

    crypto_recipient_id = crypto_recipient_id.strip()

    if not crypto_recipient_id:

        st.error(
            "Please enter the recipient Receiving ID."
        )

    else:

        connection = get_connection()
        cursor = connection.cursor()

        recipient = find_user_by_receiving_id(
            connection,
            crypto_recipient_id,
        )

        if not recipient:

            st.error(
                "No LifeGrid receiving account was found "
                "with that Receiving ID."
            )

            connection.close()

        else:

            crypto_recipient_user_id = int(recipient[0])
            crypto_recipient_username = recipient[1]

            if crypto_recipient_user_id == user_id:

                st.error(
                    "You cannot send crypto to your own wallet."
                )

                connection.close()

            else:

                cursor.execute(
                    """
                    SELECT
                        id,
                        balance,
                        available_balance,
                        asset_status
                    FROM wallet_assets
                    WHERE user_id = ?
                      AND asset_type = 'CRYPTO'
                      AND asset_code = ?
                      AND network = ?
                    """,
                    (
                        user_id,
                        crypto_asset,
                        crypto_network,
                    ),
                )

                sender_crypto = cursor.fetchone()


                if sender_crypto is None:

                    cursor.execute(
                        """
                        INSERT INTO wallet_assets (
                            user_id,
                            asset_type,
                            asset_code,
                            network,
                            balance,
                            available_balance,
                            pending_balance,
                            asset_status
                        )
                        VALUES (
                            ?, 'CRYPTO', ?, ?, 0, 0, 0, 'Active'
                        )
                        """,
                        (
                            user_id,
                            crypto_asset,
                            crypto_network,
                        ),
                    )

                    connection.commit()



                cursor.execute(
                    """
                    SELECT
                        id,
                        balance,
                        available_balance,
                        asset_status
                    FROM wallet_assets
                    WHERE user_id = ?
                      AND asset_type = 'CRYPTO'
                      AND asset_code = ?
                      AND network = ?
                    """,
                    (
                        user_id,
                        crypto_asset,
                        crypto_network,
                    ),
                )

                sender_crypto = cursor.fetchone()


                if sender_crypto is None:

                    st.error(
                        "Unable to load your crypto development wallet."
                    )

                    connection.close()

                elif sender_crypto[3] != "Active":

                    st.error(
                        "Your crypto asset wallet is not active."
                    )

                    connection.close()

                elif float(sender_crypto[2]) < float(crypto_amount):

                    st.error(
                        f"Insufficient {crypto_asset} "
                        "development balance."
                    )

                    connection.close()

                else:

                    cursor.execute(
                        """
                        SELECT
                            id,
                            balance,
                            available_balance,
                            asset_status
                        FROM wallet_assets
                        WHERE user_id = ?
                          AND asset_type = 'CRYPTO'
                          AND asset_code = ?
                          AND network = ?
                        """,
                        (
                            crypto_recipient_user_id,
                            crypto_asset,
                            crypto_network,
                        ),
                    )

                    recipient_crypto = cursor.fetchone()


                    if recipient_crypto is None:

                        cursor.execute(
                            """
                            INSERT INTO wallet_assets (
                                user_id,
                                asset_type,
                                asset_code,
                                network,
                                balance,
                                available_balance,
                                pending_balance,
                                asset_status
                            )
                            VALUES (
                                ?, 'CRYPTO', ?, ?, 0, 0, 0, 'Active'
                            )
                            """,
                            (
                                crypto_recipient_user_id,
                                crypto_asset,
                                crypto_network,
                            ),
                        )

                        connection.commit()

                        cursor.execute(
                            """
                            SELECT
                                id,
                                balance,
                                available_balance,
                                asset_status
                            FROM wallet_assets
                            WHERE user_id = ?
                              AND asset_type = 'CRYPTO'
                              AND asset_code = ?
                              AND network = ?
                            """,
                            (
                                crypto_recipient_user_id,
                                crypto_asset,
                                crypto_network,
                            ),
                        )

                        recipient_crypto = cursor.fetchone()


                    if recipient_crypto[3] != "Active":

                        st.error(
                            "The recipient crypto wallet is not active."
                        )

                        connection.close()

                    else:

                        crypto_reference = (
                            f"LGCRYPTO-{uuid.uuid4().hex[:12].upper()}"
                        )

                        crypto_transaction_hash = (
                            "DEV-"
                            + uuid.uuid4().hex.upper()
                        )


                        # -------------------------------------
                        # Debit sender crypto asset
                        # -------------------------------------

                        cursor.execute(
                            """
                            UPDATE wallet_assets
                            SET
                                balance = balance - ?,
                                available_balance = available_balance - ?,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE user_id = ?
                              AND asset_type = 'CRYPTO'
                              AND asset_code = ?
                              AND network = ?
                            """,
                            (
                                crypto_amount,
                                crypto_amount,
                                user_id,
                                crypto_asset,
                                crypto_network,
                            ),
                        )


                        # -------------------------------------
                        # Credit recipient crypto asset
                        # -------------------------------------

                        cursor.execute(
                            """
                            UPDATE wallet_assets
                            SET
                                balance = balance + ?,
                                available_balance = available_balance + ?,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE user_id = ?
                              AND asset_type = 'CRYPTO'
                              AND asset_code = ?
                              AND network = ?
                            """,
                            (
                                crypto_amount,
                                crypto_amount,
                                crypto_recipient_user_id,
                                crypto_asset,
                                crypto_network,
                            ),
                        )


                        # -------------------------------------
                        # Sender crypto transaction
                        # -------------------------------------

                        cursor.execute(
                            """
                            INSERT INTO crypto_transactions (
                                user_id,
                                transaction_type,
                                asset_code,
                                network,
                                amount,
                                recipient_user_id,
                                recipient_address,
                                transaction_hash,
                                description,
                                status,
                                reference
                            )
                            VALUES (
                                ?,
                                'Crypto Sent',
                                ?,
                                ?,
                                ?,
                                ?,
                                NULL,
                                ?,
                                ?,
                                'Development',
                                ?
                            )
                            """,
                            (
                                user_id,
                                crypto_asset,
                                crypto_network,
                                crypto_amount,
                                crypto_recipient_user_id,
                                crypto_transaction_hash,
                                crypto_description.strip(),
                                crypto_reference,
                            ),
                        )


                        # -------------------------------------
                        # Recipient crypto transaction
                        # -------------------------------------

                        recipient_crypto_reference = (
                            f"LGCRYPTO-"
                            f"{uuid.uuid4().hex[:12].upper()}"
                        )


                        cursor.execute(
                            """
                            INSERT INTO crypto_transactions (
                                user_id,
                                transaction_type,
                                asset_code,
                                network,
                                amount,
                                recipient_user_id,
                                recipient_address,
                                transaction_hash,
                                description,
                                status,
                                reference
                            )
                            VALUES (
                                ?,
                                'Crypto Received',
                                ?,
                                ?,
                                ?,
                                ?,
                                NULL,
                                ?,
                                ?,
                                'Development',
                                ?
                            )
                            """,
                            (
                                crypto_recipient_user_id,
                                crypto_asset,
                                crypto_network,
                                crypto_amount,
                                user_id,
                                crypto_transaction_hash,
                                crypto_description.strip(),
                                recipient_crypto_reference,
                            ),
                        )


                        # -------------------------------------
                        # Recipient notification
                        # -------------------------------------

                        create_notification(
                            connection,
                            crypto_recipient_user_id,
                            "🪙 Crypto Received",
                            (
                                f"You received "
                                f"{crypto_amount:.8f} "
                                f"{crypto_asset} "
                                f"on {crypto_network} "
                                f"from {user.get('username', 'a LifeGrid user')}."
                            ),
                        )


                        connection.commit()
                        connection.close()


                        st.success(
                            f"Development crypto transfer successful: "
                            f"{crypto_amount:.8f} {crypto_asset} "
                            f"to {crypto_recipient_username}."
                        )

                        st.caption(
                            f"Development transaction hash: "
                            f"`{crypto_transaction_hash}`"
                        )

                        st.rerun()


st.divider()


# =========================================================
# DEVELOPMENT TRANSACTION SIMULATOR
# =========================================================

st.subheader("🧪 Development Fiat Transaction Test")

st.info(
    "This section is for development testing only. "
    "It does not connect to a bank, card, Paystack, "
    "Flutterwave, or any other real payment provider."
)


with st.form("development_transaction_form"):

    transaction_type = st.selectbox(
        "Transaction Type",
        [
            "Test Deposit",
            "Test Gift",
            "Test Help Received",
            "Test Creator Earnings",
        ],
    )

    transaction_amount = st.number_input(
        "Amount",
        min_value=0.01,
        value=100.00,
        step=10.00,
    )

    transaction_description = st.text_input(
        "Description",
        value="LifeGrid development test transaction",
    )

    add_transaction = st.form_submit_button(
        "Add Test Transaction",
        type="primary",
    )


if add_transaction:

    transaction_reference = (
        f"LGTEST-{user_id}-"
        f"{st.session_state.get('wallet_test_counter', 0) + 1}"
    )

    st.session_state.wallet_test_counter = (
        st.session_state.get('wallet_test_counter', 0) + 1
    )


    if transaction_type == "Test Deposit":

        transaction_category = "Deposit"

    elif transaction_type == "Test Gift":

        transaction_category = "Gift"

    elif transaction_type == "Test Help Received":

        transaction_category = "Help Received"

    else:

        transaction_category = "Creator Earnings"


    connection = get_connection()
    cursor = connection.cursor()


    cursor.execute(
        """
        INSERT INTO wallet_transactions (
            user_id,
            transaction_type,
            amount,
            currency,
            description,
            reference,
            status,
            asset_type,
            asset_code,
            network
        )
        VALUES (
            ?, ?, ?, ?, ?, ?, 'Completed',
            'FIAT', ?, ''
        )
        """,
        (
            user_id,
            transaction_category,
            transaction_amount,
            wallet_currency,
            transaction_description.strip(),
            transaction_reference,
            wallet_currency,
        ),
    )


    cursor.execute(
        """
        UPDATE wallets
        SET
            balance = balance + ?,
            available_balance = available_balance + ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE user_id = ?
        """,
        (
            transaction_amount,
            transaction_amount,
            user_id,
        ),
    )


    connection.commit()
    connection.close()


    st.success(
        f"Development transaction added: "
        f"{wallet_currency} {transaction_amount:,.2f}"
    )

    st.rerun()


st.divider()


# =========================================================
# CRYPTO TEST BALANCE
# =========================================================

st.subheader("🧪 Add Development Crypto Balance")

st.info(
    "This creates test crypto balances only. "
    "No real cryptocurrency is purchased or received."
)


with st.form("crypto_test_balance_form"):

    test_crypto_asset = st.selectbox(
        "Crypto Asset",
        [
            "BTC",
            "ETH",
            "USDT",
            "USDC",
        ],
    )

    test_networks = {
        "BTC": ["Bitcoin"],
        "ETH": ["Ethereum"],
        "USDT": ["Ethereum", "Tron"],
        "USDC": ["Ethereum"],
    }

    test_crypto_network = st.selectbox(
        "Network",
        test_networks[test_crypto_asset],
    )

    test_crypto_amount = st.number_input(
        "Test Amount",
        min_value=0.00000001,
        value=0.001,
        step=0.001,
        format="%.8f",
    )

    add_crypto_balance = st.form_submit_button(
        "Add Development Crypto",
        type="primary",
    )


if add_crypto_balance:

    connection = get_connection()
    cursor = connection.cursor()


    cursor.execute(
        """
        SELECT id
        FROM wallet_assets
        WHERE user_id = ?
          AND asset_type = 'CRYPTO'
          AND asset_code = ?
          AND network = ?
        """,
        (
            user_id,
            test_crypto_asset,
            test_crypto_network,
        ),
    )

    asset_exists = cursor.fetchone()


    if not asset_exists:

        cursor.execute(
            """
            INSERT INTO wallet_assets (
                user_id,
                asset_type,
                asset_code,
                network,
                balance,
                available_balance,
                pending_balance,
                asset_status
            )
            VALUES (
                ?, 'CRYPTO', ?, ?, ?, ?, 0, 'Active'
            )
            """,
            (
                user_id,
                test_crypto_asset,
                test_crypto_network,
                test_crypto_amount,
                test_crypto_amount,
            ),
        )

    else:

        cursor.execute(
            """
            UPDATE wallet_assets
            SET
                balance = balance + ?,
                available_balance = available_balance + ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
              AND asset_type = 'CRYPTO'
              AND asset_code = ?
              AND network = ?
            """,
            (
                test_crypto_amount,
                test_crypto_amount,
                user_id,
                test_crypto_asset,
                test_crypto_network,
            ),
        )


    crypto_test_reference = (
        f"LGCRYPTOTEST-{uuid.uuid4().hex[:12].upper()}"
    )


    cursor.execute(
        """
        INSERT INTO crypto_transactions (
            user_id,
            transaction_type,
            asset_code,
            network,
            amount,
            description,
            status,
            reference
        )
        VALUES (
            ?,
            'Development Deposit',
            ?,
            ?,
            ?,
            ?,
            'Development',
            ?
        )
        """,
        (
            user_id,
            test_crypto_asset,
            test_crypto_network,
            test_crypto_amount,
            "Development crypto test balance",
            crypto_test_reference,
        ),
    )


    connection.commit()
    connection.close()


    st.success(
        f"Added {test_crypto_amount:.8f} "
        f"{test_crypto_asset} development balance."
    )

    st.rerun()


st.divider()


# =========================================================
# TRANSACTION HISTORY
# =========================================================

st.subheader("📒 Fiat Transaction History")


connection = get_connection()
cursor = connection.cursor()


cursor.execute(
    """
    SELECT
        transaction_type,
        amount,
        currency,
        description,
        reference,
        status,
        created_at
    FROM wallet_transactions
    WHERE user_id = ?
    ORDER BY id DESC
    """,
    (user_id,),
)


transactions = cursor.fetchall()

connection.close()


if not transactions:

    st.info(
        "No fiat wallet transactions yet."
    )

else:

    for transaction in transactions:

        (
            transaction_type,
            amount,
            currency,
            description,
            reference,
            status,
            created_at,
        ) = transaction


        with st.container(border=True):

            transaction_col1, transaction_col2 = st.columns(
                [3, 1]
            )


            with transaction_col1:

                st.markdown(
                    f"### {transaction_type}"
                )

                st.write(
                    description or "LifeGrid transaction"
                )

                st.caption(
                    f"Reference: {reference}"
                )

                st.caption(
                    f"Date: {created_at}"
                )


            with transaction_col2:

                st.markdown(
                    f"### {currency} {amount:,.2f}"
                )

                if status == "Completed":

                    st.success(
                        "Completed"
                    )

                elif status == "Pending":

                    st.warning(
                        "Pending"
                    )

                else:

                    st.error(
                        status
                    )


st.divider()


# =========================================================
# CRYPTO TRANSACTION HISTORY
# =========================================================

st.subheader("🪙 Crypto Transaction History")


connection = get_connection()
cursor = connection.cursor()


cursor.execute(
    """
    SELECT
        transaction_type,
        asset_code,
        network,
        amount,
        transaction_hash,
        description,
        status,
        reference,
        created_at
    FROM crypto_transactions
    WHERE user_id = ?
    ORDER BY id DESC
    """,
    (user_id,),
)


crypto_transactions = cursor.fetchall()

connection.close()


if not crypto_transactions:

    st.info(
        "No crypto development transactions yet."
    )

else:

    for transaction in crypto_transactions:

        (
            transaction_type,
            asset_code,
            network,
            amount,
            transaction_hash,
            description,
            status,
            reference,
            created_at,
        ) = transaction


        with st.container(border=True):

            crypto_history_col1, crypto_history_col2 = (
                st.columns([3, 1])
            )


            with crypto_history_col1:

                st.markdown(
                    f"### {transaction_type}"
                )

                st.write(
                    f"{amount:.8f} {asset_code}"
                )

                st.caption(
                    f"Network: {network}"
                )

                st.caption(
                    description or "LifeGrid crypto transaction"
                )

                st.caption(
                    f"Reference: {reference}"
                )

                if transaction_hash:

                    st.caption(
                        f"Development TX Hash: "
                        f"`{transaction_hash}`"
                    )

                st.caption(
                    f"Date: {created_at}"
                )


            with crypto_history_col2:

                if status == "Development":

                    st.warning(
                        "Development"
                    )

                elif status == "Completed":

                    st.success(
                        "Completed"
                    )

                else:

                    st.info(
                        status
                    )


st.divider()


# =========================================================
# WITHDRAWALS
# =========================================================

st.subheader("🏧 Withdrawals")

st.write(
    "Withdrawals will be connected after the LifeGrid "
    "payment, verification, and compliance system is implemented."
)

st.warning(
    "Real-money withdrawals and real cryptocurrency "
    "blockchain withdrawals are currently disabled."
)


st.divider()


# =========================================================
# FUTURE CRYPTO INFRASTRUCTURE
# =========================================================

st.subheader("🔐 Future Crypto Infrastructure")

st.write(
    "When real cryptocurrency support is introduced, "
    "LifeGrid will need to distinguish the asset from "
    "its blockchain network."
)

st.write(
    "For example:"
)

st.code(
    "USDT • Ethereum\n"
    "USDT • Tron\n"
    "USDC • Ethereum\n"
    "BTC • Bitcoin\n"
    "ETH • Ethereum"
)

st.warning(
    "Sending an asset through the wrong blockchain network "
    "can result in permanent loss. Real crypto transfers "
    "will therefore require network selection, wallet "
    "addresses, transaction verification, fees, limits, "
    "security controls, and appropriate compliance."
)


st.divider()


# =========================================================
# FOOTER
# =========================================================

st.caption(
    "LifeGrid Wallet • Receive • Give • Earn • Grow"
)

