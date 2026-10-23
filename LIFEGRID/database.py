
import sqlite3
from pathlib import Path


# ============================================================
# DATABASE LOCATION
# ============================================================

DATABASE_PATH = Path(__file__).parent / "data" / "lifegrid.db"


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_connection():
    """Create a connection to the LifeGrid database."""

    DATABASE_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    connection = sqlite3.connect(
        DATABASE_PATH,
        check_same_thread=False,
    )

    return connection


# ============================================================
# SAFE COLUMN ADDITION
# ============================================================

def add_column_if_missing(
    cursor,
    table_name,
    column_name,
    column_definition,
):
    """
    Add a column to an existing table if the column
    does not already exist.
    """

    cursor.execute(
        f"PRAGMA table_info({table_name})"
    )

    existing_columns = {
        row[1]
        for row in cursor.fetchall()
    }

    if column_name not in existing_columns:

        cursor.execute(
            f"""
            ALTER TABLE {table_name}
            ADD COLUMN {column_name}
            {column_definition}
            """
        )


# ============================================================
# INITIALIZE DATABASE
# ============================================================

def initialize_database():
    """
    Create LifeGrid tables and safely upgrade existing
    database tables when new columns are required.
    """

    connection = get_connection()
    cursor = connection.cursor()

    # ========================================================
    # USERS
    # ========================================================

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT,
            country TEXT,
            currency TEXT DEFAULT 'NGN',
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    add_column_if_missing(
        cursor,
        "users",
        "full_name",
        "TEXT",
    )

    add_column_if_missing(
        cursor,
        "users",
        "country",
        "TEXT",
    )

    add_column_if_missing(
        cursor,
        "users",
        "currency",
        "TEXT DEFAULT 'NGN'",
    )

    add_column_if_missing(
        cursor,
        "users",
        "is_active",
        "INTEGER DEFAULT 1",
    )

    add_column_if_missing(
        cursor,
        "users",
        "created_at",
        "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    )

    # Security-related user fields.

    add_column_if_missing(
        cursor,
        "users",
        "last_login_at",
        "TIMESTAMP",
    )

    add_column_if_missing(
        cursor,
        "users",
        "failed_login_attempts",
        "INTEGER DEFAULT 0",
    )

    add_column_if_missing(
        cursor,
        "users",
        "last_failed_login_at",
        "TIMESTAMP",
    )

    # ========================================================
    # PASSWORD RESETS
    # ========================================================

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS password_resets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            reset_code TEXT NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            used INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )

    add_column_if_missing(
        cursor,
        "password_resets",
        "used",
        "INTEGER DEFAULT 0",
    )

    add_column_if_missing(
        cursor,
        "password_resets",
        "created_at",
        "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    )

    # ========================================================
    # GOALS
    # ========================================================

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            target_date TEXT,
            progress INTEGER DEFAULT 0,
            status TEXT DEFAULT 'Active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    add_column_if_missing(
        cursor,
        "goals",
        "description",
        "TEXT",
    )

    add_column_if_missing(
        cursor,
        "goals",
        "target_date",
        "TEXT",
    )

    add_column_if_missing(
        cursor,
        "goals",
        "progress",
        "INTEGER DEFAULT 0",
    )

    add_column_if_missing(
        cursor,
        "goals",
        "status",
        "TEXT DEFAULT 'Active'",
    )

    add_column_if_missing(
        cursor,
        "goals",
        "created_at",
        "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    )

    # ========================================================
    # HELP REQUESTS
    # ========================================================

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS help_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requester_id INTEGER NOT NULL,
            helper_id INTEGER,
            title TEXT NOT NULL,
            description TEXT,
            category TEXT,
            help_type TEXT,
            target_date TEXT,
            status TEXT DEFAULT 'Open',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            accepted_at TIMESTAMP,
            completed_at TIMESTAMP,
            confirmed_at TIMESTAMP
        )
        """
    )

    add_column_if_missing(
        cursor,
        "help_requests",
        "helper_id",
        "INTEGER",
    )

    add_column_if_missing(
        cursor,
        "help_requests",
        "description",
        "TEXT",
    )

    add_column_if_missing(
        cursor,
        "help_requests",
        "category",
        "TEXT",
    )

    add_column_if_missing(
        cursor,
        "help_requests",
        "help_type",
        "TEXT",
    )

    add_column_if_missing(
        cursor,
        "help_requests",
        "target_date",
        "TEXT",
    )

    add_column_if_missing(
        cursor,
        "help_requests",
        "status",
        "TEXT DEFAULT 'Open'",
    )

    add_column_if_missing(
        cursor,
        "help_requests",
        "created_at",
        "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    )

    add_column_if_missing(
        cursor,
        "help_requests",
        "accepted_at",
        "TIMESTAMP",
    )

    add_column_if_missing(
        cursor,
        "help_requests",
        "completed_at",
        "TIMESTAMP",
    )

    add_column_if_missing(
        cursor,
        "help_requests",
        "confirmed_at",
        "TIMESTAMP",
    )

    # ========================================================
    # WALLETS
    # ========================================================

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS wallets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            balance REAL DEFAULT 0,
            pending_balance REAL DEFAULT 0,
            currency TEXT DEFAULT 'NGN',
            status TEXT DEFAULT 'Active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    add_column_if_missing(
        cursor,
        "wallets",
        "balance",
        "REAL DEFAULT 0",
    )

    add_column_if_missing(
        cursor,
        "wallets",
        "pending_balance",
        "REAL DEFAULT 0",
    )

    add_column_if_missing(
        cursor,
        "wallets",
        "currency",
        "TEXT DEFAULT 'NGN'",
    )

    add_column_if_missing(
        cursor,
        "wallets",
        "status",
        "TEXT DEFAULT 'Active'",
    )

    add_column_if_missing(
        cursor,
        "wallets",
        "created_at",
        "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    )

    # ========================================================
    # RECEIVING ACCOUNTS
    # ========================================================

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS receiving_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            receiving_id TEXT UNIQUE NOT NULL,
            currency TEXT DEFAULT 'NGN',
            status TEXT DEFAULT 'Active',
            verification_status TEXT DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    add_column_if_missing(
        cursor,
        "receiving_accounts",
        "receiving_id",
        "TEXT",
    )

    add_column_if_missing(
        cursor,
        "receiving_accounts",
        "currency",
        "TEXT DEFAULT 'NGN'",
    )

    add_column_if_missing(
        cursor,
        "receiving_accounts",
        "status",
        "TEXT DEFAULT 'Active'",
    )

    add_column_if_missing(
        cursor,
        "receiving_accounts",
        "verification_status",
        "TEXT DEFAULT 'Pending'",
    )

    add_column_if_missing(
        cursor,
        "receiving_accounts",
        "created_at",
        "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    )

    # ========================================================
    # WALLET TRANSACTIONS
    # ========================================================

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS wallet_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            transaction_type TEXT NOT NULL,
            category TEXT,
            amount REAL NOT NULL DEFAULT 0,
            currency TEXT DEFAULT 'NGN',
            status TEXT DEFAULT 'Completed',
            description TEXT,
            reference TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    add_column_if_missing(
        cursor,
        "wallet_transactions",
        "transaction_type",
        "TEXT",
    )

    add_column_if_missing(
        cursor,
        "wallet_transactions",
        "category",
        "TEXT",
    )

    add_column_if_missing(
        cursor,
        "wallet_transactions",
        "amount",
        "REAL DEFAULT 0",
    )

    add_column_if_missing(
        cursor,
        "wallet_transactions",
        "currency",
        "TEXT DEFAULT 'NGN'",
    )

    add_column_if_missing(
        cursor,
        "wallet_transactions",
        "status",
        "TEXT DEFAULT 'Completed'",
    )

    add_column_if_missing(
        cursor,
        "wallet_transactions",
        "description",
        "TEXT",
    )

    add_column_if_missing(
        cursor,
        "wallet_transactions",
        "reference",
        "TEXT",
    )

    add_column_if_missing(
        cursor,
        "wallet_transactions",
        "created_at",
        "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    )

    # ========================================================
    # NOTIFICATIONS
    # ========================================================

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            notification_type TEXT,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            reference_type TEXT,
            reference_id INTEGER,
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    add_column_if_missing(
        cursor,
        "notifications",
        "notification_type",
        "TEXT",
    )

    add_column_if_missing(
        cursor,
        "notifications",
        "reference_type",
        "TEXT",
    )

    add_column_if_missing(
        cursor,
        "notifications",
        "reference_id",
        "INTEGER",
    )

    add_column_if_missing(
        cursor,
        "notifications",
        "is_read",
        "INTEGER DEFAULT 0",
    )

    add_column_if_missing(
        cursor,
        "notifications",
        "created_at",
        "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    )

    # ========================================================
    # MESSAGES
    # ========================================================

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    add_column_if_missing(
        cursor,
        "messages",
        "is_read",
        "INTEGER DEFAULT 0",
    )

    add_column_if_missing(
        cursor,
        "messages",
        "created_at",
        "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    )

    # ========================================================
    # CONNECTIONS
    # ========================================================

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS connections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requester_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            responded_at TIMESTAMP,
            UNIQUE(requester_id, receiver_id)
        )
        """
    )

    add_column_if_missing(
        cursor,
        "connections",
        "status",
        "TEXT DEFAULT 'Pending'",
    )

    add_column_if_missing(
        cursor,
        "connections",
        "created_at",
        "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    )

    add_column_if_missing(
        cursor,
        "connections",
        "responded_at",
        "TIMESTAMP",
    )

    # ========================================================
    # ACTIVITY & SECURITY LOG
    # ========================================================

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            activity_type TEXT NOT NULL,
            activity_title TEXT NOT NULL,
            activity_description TEXT,
            ip_address TEXT,
            user_agent TEXT,
            location TEXT,
            reference_type TEXT,
            reference_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )

    add_column_if_missing(
        cursor,
        "activity_logs",
        "activity_description",
        "TEXT",
    )

    add_column_if_missing(
        cursor,
        "activity_logs",
        "ip_address",
        "TEXT",
    )

    add_column_if_missing(
        cursor,
        "activity_logs",
        "user_agent",
        "TEXT",
    )

    add_column_if_missing(
        cursor,
        "activity_logs",
        "location",
        "TEXT",
    )

    add_column_if_missing(
        cursor,
        "activity_logs",
        "reference_type",
        "TEXT",
    )

    add_column_if_missing(
        cursor,
        "activity_logs",
        "reference_id",
        "INTEGER",
    )

    add_column_if_missing(
        cursor,
        "activity_logs",
        "created_at",
        "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    )

    # ========================================================
    # SECURITY INDEXES
    # ========================================================

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_activity_logs_user
        ON activity_logs(user_id)
        """
    )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_activity_logs_type
        ON activity_logs(activity_type)
        """
    )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_activity_logs_created
        ON activity_logs(created_at)
        """
    )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_notifications_user
        ON notifications(user_id)
        """
    )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_messages_receiver
        ON messages(receiver_id)
        """
    )

    # ========================================================
    # COMMIT CHANGES
    # ========================================================

    connection.commit()
    connection.close()


# ============================================================
# AUTOMATIC DATABASE INITIALIZATION
# ============================================================

initialize_database()

