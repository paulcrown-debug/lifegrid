import os
import sqlite3
from pathlib import Path

# ============================================================
# DATABASE LOCATION & CONFIGURATION
# ============================================================

DATABASE_PATH = Path(__file__).parent / "data" / "lifegrid.db"

# Optional Cloud Database (Turso / libSQL) settings
TURSO_URL = os.environ.get("TURSO_DATABASE_URL")
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN")

try:
    import streamlit as st
    if not TURSO_URL and "TURSO_DATABASE_URL" in st.secrets:
        TURSO_URL = st.secrets["TURSO_DATABASE_URL"]
    if not TURSO_TOKEN and "TURSO_AUTH_TOKEN" in st.secrets:
        TURSO_TOKEN = st.secrets["TURSO_AUTH_TOKEN"]
except Exception:
    pass


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_connection():
    """Create a connection to either Turso (libSQL) or local SQLite."""
    if TURSO_URL and TURSO_TOKEN:
        try:
            import libsql_experimental as libsql
            return libsql.connect(database=TURSO_URL, auth_token=TURSO_TOKEN)
        except Exception as e:
            print(f"[LifeGrid DB Warning] Cloud DB connection failed, falling back to local SQLite: {e}")

    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DATABASE_PATH, check_same_thread=False)


# ============================================================
# SAFE COLUMN ADDITION
# ============================================================

def add_column_if_missing(cursor, table_name, column_name, column_definition):
    """Add a column to an existing table if the column does not already exist."""
    try:
        cursor.execute(f"PRAGMA table_info({table_name})")
        existing_columns = {row[1] for row in cursor.fetchall()}
        if column_name not in existing_columns:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")
    except Exception as e:
        print(f"[LifeGrid DB Migration Notice] Column check on {table_name}.{column_name}: {e}")


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def initialize_database():
    """Initialize all LifeGrid tables and run required schema migrations."""
    conn = get_connection()
    c = conn.cursor()

    try:
        # Users
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                email TEXT UNIQUE,
                password_hash TEXT,
                display_name TEXT,
                full_name TEXT,
                bio TEXT,
                avatar_url TEXT,
                phone TEXT,
                country TEXT DEFAULT 'Nigeria',
                currency TEXT DEFAULT 'NGN',
                role TEXT DEFAULT 'user',
                is_creator INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                failed_login_attempts INTEGER DEFAULT 0,
                last_failed_login_at TIMESTAMP,
                last_login_at TIMESTAMP,
                last_login TIMESTAMP,
                kyc_status TEXT DEFAULT 'unverified',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Password Resets
        c.execute("""
            CREATE TABLE IF NOT EXISTS password_resets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                reset_code TEXT,
                token TEXT,
                expires_at TIMESTAMP,
                used INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Wallets
        c.execute("""
            CREATE TABLE IF NOT EXISTS wallets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                balance REAL DEFAULT 0.0,
                pending_balance REAL DEFAULT 0.0,
                gift_credits INTEGER DEFAULT 0,
                currency TEXT DEFAULT 'USD',
                status TEXT DEFAULT 'Active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Creator Receiving Accounts
        c.execute("""
            CREATE TABLE IF NOT EXISTS receiving_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                payout_method TEXT DEFAULT 'bank',
                currency TEXT DEFAULT 'NGN',
                bank_name TEXT,
                account_number TEXT,
                account_name TEXT,
                bank_code TEXT,
                is_primary INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Creator Withdrawals
        c.execute("""
            CREATE TABLE IF NOT EXISTS creator_withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                currency TEXT DEFAULT 'NGN',
                fee REAL DEFAULT 0.0,
                net_amount REAL,
                status TEXT DEFAULT 'Pending',
                payout_method TEXT DEFAULT 'bank',
                bank_name TEXT,
                account_number TEXT,
                account_name TEXT,
                withdrawal_reference TEXT UNIQUE,
                transaction_reference TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP
            )
        """)

        # Transactions
        c.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                type TEXT,
                amount REAL,
                currency TEXT DEFAULT 'USD',
                status TEXT DEFAULT 'completed',
                reference TEXT UNIQUE,
                description TEXT,
                metadata TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Goals
        c.execute("""
            CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                title TEXT,
                description TEXT,
                target_amount REAL DEFAULT 0.0,
                current_amount REAL DEFAULT 0.0,
                currency TEXT DEFAULT 'USD',
                status TEXT DEFAULT 'active',
                category TEXT DEFAULT 'General',
                deadline DATE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Help Requests
        c.execute("""
            CREATE TABLE IF NOT EXISTS help_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                requester_id INTEGER,
                helper_id INTEGER,
                subject TEXT,
                message TEXT,
                status TEXT DEFAULT 'open',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Notifications
        c.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                title TEXT,
                message TEXT,
                type TEXT DEFAULT 'general',
                notification_type TEXT DEFAULT 'general',
                reference TEXT,
                reference_type TEXT,
                reference_id INTEGER,
                is_read INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Messages
        c.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER,
                receiver_id INTEGER,
                content TEXT,
                is_read INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Connections
        c.execute("""
            CREATE TABLE IF NOT EXISTS connections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                connected_user_id INTEGER,
                requester_id INTEGER,
                receiver_id INTEGER,
                status TEXT DEFAULT 'accepted',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Activity Logs
        c.execute("""
            CREATE TABLE IF NOT EXISTS activity_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                activity_type TEXT,
                activity_title TEXT,
                activity_description TEXT,
                action TEXT,
                details TEXT,
                ip_address TEXT,
                user_agent TEXT,
                location TEXT,
                reference_type TEXT,
                reference_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # --- Safe Column Migrations for Users ---
        add_column_if_missing(c, "users", "full_name", "TEXT")
        add_column_if_missing(c, "users", "is_active", "INTEGER DEFAULT 1")
        add_column_if_missing(c, "users", "failed_login_attempts", "INTEGER DEFAULT 0")
        add_column_if_missing(c, "users", "last_failed_login_at", "TIMESTAMP")
        add_column_if_missing(c, "users", "last_login_at", "TIMESTAMP")
        add_column_if_missing(c, "users", "last_login", "TIMESTAMP")

        # --- Safe Column Migrations for Password Resets ---
        add_column_if_missing(c, "password_resets", "reset_code", "TEXT")

        # --- Safe Column Migrations for Notifications ---
        add_column_if_missing(c, "notifications", "notification_type", "TEXT DEFAULT 'general'")
        add_column_if_missing(c, "notifications", "reference", "TEXT")
        add_column_if_missing(c, "notifications", "reference_type", "TEXT")
        add_column_if_missing(c, "notifications", "reference_id", "INTEGER")

        # --- Safe Column Migrations for Activity Logs ---
        add_column_if_missing(c, "activity_logs", "activity_type", "TEXT")
        add_column_if_missing(c, "activity_logs", "activity_title", "TEXT")
        add_column_if_missing(c, "activity_logs", "activity_description", "TEXT")
        add_column_if_missing(c, "activity_logs", "user_agent", "TEXT")
        add_column_if_missing(c, "activity_logs", "location", "TEXT")
        add_column_if_missing(c, "activity_logs", "reference_type", "TEXT")
        add_column_if_missing(c, "activity_logs", "reference_id", "INTEGER")

        # --- Safe Column Migrations for Help Requests & Connections ---
        add_column_if_missing(c, "help_requests", "requester_id", "INTEGER")
        add_column_if_missing(c, "help_requests", "helper_id", "INTEGER")
        add_column_if_missing(c, "connections", "requester_id", "INTEGER")
        add_column_if_missing(c, "connections", "receiver_id", "INTEGER")

        # --- Safe Column Migrations for Wallets & Withdrawals ---
        add_column_if_missing(c, "wallets", "pending_balance", "REAL DEFAULT 0.0")
        add_column_if_missing(c, "wallets", "status", "TEXT DEFAULT 'Active'")
        add_column_if_missing(c, "wallets", "gift_credits", "INTEGER DEFAULT 0")
        add_column_if_missing(c, "wallets", "currency", "TEXT DEFAULT 'USD'")
        add_column_if_missing(c, "creator_withdrawals", "fee", "REAL DEFAULT 0.0")
        add_column_if_missing(c, "creator_withdrawals", "net_amount", "REAL")
        add_column_if_missing(c, "creator_withdrawals", "payout_method", "TEXT DEFAULT 'bank'")
        add_column_if_missing(c, "creator_withdrawals", "transaction_reference", "TEXT")
        add_column_if_missing(c, "creator_withdrawals", "processed_at", "TIMESTAMP")

        conn.commit()
    except Exception as e:
        print(f"[LifeGrid DB Warning] Initialization notice: {e}")
    finally:
        conn.close()


# Auto-initialize database on import
try:
    initialize_database()
except Exception as e:
    print(f"[LifeGrid DB Warning] Auto-init failed: {e}")
