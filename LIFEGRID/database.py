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
    if not TURSO_URL and hasattr(st, "secrets") and "TURSO_DATABASE_URL" in st.secrets:
        TURSO_URL = st.secrets["TURSO_DATABASE_URL"]
    if not TURSO_TOKEN and hasattr(st, "secrets") and "TURSO_AUTH_TOKEN" in st.secrets:
        TURSO_TOKEN = st.secrets["TURSO_AUTH_TOKEN"]
except Exception:
    pass


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_connection():
    """Create a connection to either Turso (libSQL) or local SQLite."""
    if TURSO_URL or TURSO_TOKEN:
        if not TURSO_URL or not TURSO_TOKEN:
            raise RuntimeError(
                "Turso configuration is incomplete; both database URL and auth token are required."
            )
        try:
            import libsql_experimental as libsql
            return libsql.connect(database=TURSO_URL, auth_token=TURSO_TOKEN)
        except Exception as e:
            # Do not silently split production data into a separate local database.
            raise RuntimeError(
                "Configured Turso database connection failed; refusing to use a separate local SQLite database."
            ) from e

    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DATABASE_PATH, check_same_thread=False)


# ============================================================
# SAFE COLUMN ADDITION (NON-DESTRUCTIVE MIGRATION)
# ============================================================

def add_column_if_missing(cursor, table_name, column_name, column_definition):
    """Add a column to an existing table if the column does not already exist."""
    try:
        cursor.execute(f"PRAGMA table_info({table_name})")
        existing_columns = {row[1].lower() for row in cursor.fetchall()}
        if existing_columns and column_name.lower() not in existing_columns:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")
    except Exception as e:
        print(f"[LifeGrid DB Migration Notice] Column check on {table_name}.{column_name}: {e}")


def ensure_legacy_row_id(cursor, table_name):
    """Add a stable id to legacy rowid tables without rebuilding existing rows."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = {row[1].lower() for row in cursor.fetchall()}
    if not columns:
        raise RuntimeError(f"Required table {table_name} is missing")
    if "id" not in columns:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN id INTEGER")
    cursor.execute(f"UPDATE {table_name} SET id = rowid WHERE id IS NULL")
    trigger_name = f"trg_{table_name}_fill_legacy_id"
    cursor.execute(
        f"CREATE TRIGGER IF NOT EXISTS {trigger_name} "
        f"AFTER INSERT ON {table_name} WHEN NEW.id IS NULL "
        f"BEGIN UPDATE {table_name} SET id = NEW.rowid WHERE rowid = NEW.rowid; END"
    )


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def initialize_database():
    """Initialize all LifeGrid tables and run required schema migrations non-destructively."""
    conn = get_connection()
    c = conn.cursor()

    try:
        # 1. Users
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

        # 2. Password Resets
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

        # 3. Wallets
        c.execute("""
            CREATE TABLE IF NOT EXISTS wallets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                balance REAL DEFAULT 0.0,
                available_balance REAL DEFAULT 0.0,
                pending_balance REAL DEFAULT 0.0,
                gift_credits INTEGER DEFAULT 0,
                currency TEXT DEFAULT 'USD',
                status TEXT DEFAULT 'Active',
                wallet_status TEXT DEFAULT 'Active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 4. Receiving Accounts
        c.execute("""
            CREATE TABLE IF NOT EXISTS receiving_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                receiving_id TEXT UNIQUE,
                payout_method TEXT DEFAULT 'bank',
                currency TEXT DEFAULT 'NGN',
                bank_name TEXT,
                account_number TEXT,
                account_name TEXT,
                bank_code TEXT,
                is_primary INTEGER DEFAULT 1,
                account_status TEXT DEFAULT 'Active',
                account_type TEXT DEFAULT 'internal_wallet',
                verification_status TEXT DEFAULT 'Verified',
                status TEXT DEFAULT 'Active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 5. Creator Profiles
        c.execute("""
            CREATE TABLE IF NOT EXISTS creator_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                display_name TEXT,
                description TEXT DEFAULT '',
                creator_status TEXT DEFAULT 'active',
                currency TEXT DEFAULT 'NGN',
                total_earnings REAL DEFAULT 0.0,
                pending_balance REAL DEFAULT 0.0,
                kyc_tier INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT
            )
        """)

        # 6. Creator Withdrawals
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
                payment_method TEXT DEFAULT 'bank_transfer',
                bank_name TEXT,
                account_number TEXT,
                account_name TEXT,
                bank_code TEXT,
                receiving_account_id INTEGER,
                withdrawal_reference TEXT UNIQUE,
                transaction_reference TEXT,
                destination TEXT DEFAULT '',
                payout_details TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                requested_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP
            )
        """)

        # 7. Transactions
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

        # 8. Goals
        c.execute("""
            CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                title TEXT,
                description TEXT,
                category TEXT DEFAULT 'Personal',
                target_amount REAL DEFAULT 0.0,
                current_amount REAL DEFAULT 0.0,
                progress INTEGER DEFAULT 0,
                currency TEXT DEFAULT 'USD',
                target_date DATE,
                deadline DATE,
                status TEXT DEFAULT 'Active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 9. Help Requests
        c.execute("""
            CREATE TABLE IF NOT EXISTS help_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                requester_id INTEGER,
                helper_id INTEGER,
                target_helper_id INTEGER,
                title TEXT,
                category TEXT DEFAULT 'General',
                description TEXT,
                urgency TEXT DEFAULT 'Medium',
                subject TEXT,
                message TEXT,
                status TEXT DEFAULT 'Open',
                accepted_at TIMESTAMP,
                completed_at TIMESTAMP,
                confirmed_at TIMESTAMP,
                wallet_amount REAL DEFAULT 0.0,
                wallet_transfer_reference TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 10. Notifications
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
                reference_id TEXT,
                is_read INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 11. Messages
        c.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER,
                sender_id INTEGER,
                receiver_id INTEGER,
                content TEXT,
                message TEXT,
                is_read INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 12. Conversations
        c.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_one_id INTEGER NOT NULL,
                user_two_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 13. Connections
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

        # 14. Activity Logs
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

        # 15. Creator Earnings
        c.execute("""
            CREATE TABLE IF NOT EXISTS creator_earnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                creator_id INTEGER NOT NULL,
                supporter_id INTEGER,
                amount REAL DEFAULT 0,
                supporter_total REAL DEFAULT 0,
                currency TEXT DEFAULT 'NGN',
                platform_fee REAL DEFAULT 0,
                earning_reference TEXT UNIQUE,
                gift_name TEXT DEFAULT '',
                fan_name TEXT DEFAULT '',
                message TEXT DEFAULT '',
                status TEXT DEFAULT 'Completed',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 16. Creator Gift Earnings
        c.execute("""
            CREATE TABLE IF NOT EXISTS creator_gift_earnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                creator_user_id INTEGER,
                sender_user_id INTEGER,
                source_user_id INTEGER,
                gift_id INTEGER,
                gift_sent_id INTEGER,
                gift_code TEXT,
                credits INTEGER DEFAULT 0,
                creator_value INTEGER DEFAULT 0,
                gross_value REAL DEFAULT 0,
                platform_fee REAL DEFAULT 0,
                net_earnings REAL DEFAULT 0,
                currency_code TEXT DEFAULT 'USD',
                reference TEXT,
                transaction_reference TEXT,
                status TEXT DEFAULT 'Pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 17. Creator KYC
        c.execute("""
            CREATE TABLE IF NOT EXISTS creator_kyc (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                document_type TEXT,
                document_number TEXT,
                kyc_level INTEGER DEFAULT 1,
                verification_status TEXT DEFAULT 'Pending',
                rejection_reason TEXT,
                submitted_at TEXT,
                reviewed_at TEXT,
                reviewed_by TEXT
            )
        """)

        # 18. Creator Posts
        c.execute("""
            CREATE TABLE IF NOT EXISTS creator_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                creator_id INTEGER NOT NULL,
                creator_name TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                media_url TEXT DEFAULT '',
                post_type TEXT DEFAULT 'text',
                currency TEXT DEFAULT 'NGN',
                total_tips REAL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 19. Post Tips
        c.execute("""
            CREATE TABLE IF NOT EXISTS post_tips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id INTEGER NOT NULL,
                creator_id INTEGER NOT NULL,
                fan_name TEXT NOT NULL,
                amount REAL NOT NULL,
                currency TEXT DEFAULT 'NGN',
                gift_title TEXT NOT NULL,
                cheer_message TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 20. Crypto Transactions
        c.execute("""
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 21. Financial Audit Ledger
        c.execute("""
            CREATE TABLE IF NOT EXISTS financial_audit_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ledger_entry_id TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                transaction_ref TEXT NOT NULL,
                event_type TEXT NOT NULL,
                debit REAL DEFAULT 0.0,
                credit REAL DEFAULT 0.0,
                fee REAL DEFAULT 0.0,
                balance_after REAL NOT NULL,
                currency TEXT NOT NULL,
                entry_hash TEXT NOT NULL,
                prev_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 22. Gift Catalog
        c.execute("""
            CREATE TABLE IF NOT EXISTS gift_catalog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gift_name TEXT NOT NULL,
                gift_code TEXT UNIQUE NOT NULL,
                gift_icon TEXT NOT NULL,
                gift_emoji TEXT,
                credit_price INTEGER DEFAULT 0,
                credit_cost INTEGER DEFAULT 0,
                creator_value REAL DEFAULT 0,
                currency_code TEXT DEFAULT 'USD',
                is_active INTEGER DEFAULT 1,
                sort_order INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 23. Gift Credit Balances
        c.execute("""
            CREATE TABLE IF NOT EXISTS gift_credit_balances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                balance INTEGER DEFAULT 0,
                credit_balance INTEGER DEFAULT 0,
                lifetime_purchased INTEGER DEFAULT 0,
                lifetime_received INTEGER DEFAULT 0,
                lifetime_sent INTEGER DEFAULT 0,
                lifetime_spent INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 24. Gift Credit Payments
        c.execute("""
            CREATE TABLE IF NOT EXISTS gift_credit_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                transaction_reference TEXT UNIQUE NOT NULL,
                amount REAL NOT NULL,
                currency TEXT NOT NULL,
                credits INTEGER NOT NULL,
                provider TEXT DEFAULT 'Flutterwave',
                provider_transaction_id TEXT,
                status TEXT DEFAULT 'Pending',
                verification_note TEXT,
                checkout_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                verified_at TEXT,
                credited_at TEXT
            )
        """)

        # 25. Gift Credit Transactions
        c.execute("""
            CREATE TABLE IF NOT EXISTS gift_credit_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                transaction_type TEXT,
                credits INTEGER DEFAULT 0,
                balance_after INTEGER DEFAULT 0,
                wallet_amount REAL DEFAULT 0,
                wallet_currency TEXT,
                reference TEXT,
                transaction_reference TEXT,
                description TEXT,
                status TEXT DEFAULT 'Completed',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 26. Gift Wallet Debits
        c.execute("""
            CREATE TABLE IF NOT EXISTS gift_wallet_debits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL DEFAULT 0,
                wallet_currency TEXT,
                credits INTEGER DEFAULT 0,
                reference TEXT,
                transaction_reference TEXT,
                status TEXT DEFAULT 'Completed',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 27. Gifts
        c.execute("""
            CREATE TABLE IF NOT EXISTS gifts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                recipient_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                sender_total REAL NOT NULL,
                recipient_amount REAL NOT NULL,
                platform_fee REAL DEFAULT 0,
                currency TEXT NOT NULL,
                gift_type TEXT NOT NULL,
                message TEXT,
                gift_reference TEXT UNIQUE NOT NULL,
                wallet_reference TEXT,
                status TEXT DEFAULT 'Completed',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 28. Gifts Sent
        c.execute("""
            CREATE TABLE IF NOT EXISTS gifts_sent (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_user_id INTEGER,
                recipient_user_id INTEGER,
                receiver_user_id INTEGER,
                live_stream_id INTEGER,
                gift_id INTEGER,
                gift_name TEXT,
                gift_code TEXT,
                quantity INTEGER DEFAULT 1,
                credits INTEGER DEFAULT 0,
                total_credits INTEGER DEFAULT 0,
                creator_value REAL DEFAULT 0,
                currency_code TEXT DEFAULT 'USD',
                message TEXT,
                reference TEXT,
                transaction_reference TEXT,
                status TEXT DEFAULT 'Completed',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 29. Idempotency Keys
        c.execute("""
            CREATE TABLE IF NOT EXISTS idempotency_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                idempotency_key TEXT UNIQUE NOT NULL,
                request_hash TEXT NOT NULL,
                response_payload TEXT,
                status TEXT DEFAULT 'PROCESSING',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 30. LifeGrid Admins
        c.execute("""
            CREATE TABLE IF NOT EXISTS lifegrid_admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                admin_status TEXT DEFAULT 'Active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 31. LifeGrid KYC Verifications
        c.execute("""
            CREATE TABLE IF NOT EXISTS lifegrid_kyc_verifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                full_legal_name TEXT NOT NULL,
                date_of_birth TEXT,
                id_type TEXT NOT NULL,
                id_number TEXT NOT NULL,
                id_expiry_date TEXT,
                country_of_residence TEXT NOT NULL,
                state_province TEXT NOT NULL,
                city TEXT NOT NULL,
                residential_address TEXT NOT NULL,
                postal_code TEXT,
                proof_of_address_type TEXT,
                id_document_filename TEXT,
                proof_of_address_filename TEXT,
                facial_selfie_filename TEXT,
                verification_status TEXT DEFAULT 'Pending',
                aml_risk_level TEXT DEFAULT 'Low',
                rejection_reason TEXT,
                submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TIMESTAMP
            )
        """)

        # 32. Live Streams
        c.execute("""
            CREATE TABLE IF NOT EXISTS live_streams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                broadcaster_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                category TEXT,
                stream_key TEXT,
                status TEXT DEFAULT 'scheduled',
                viewer_count INTEGER DEFAULT 0,
                scheduled_at TEXT,
                started_at TEXT,
                ended_at TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 33. Live Chat
        c.execute("""
            CREATE TABLE IF NOT EXISTS live_chat (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stream_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 34. Live Creator Support
        c.execute("""
            CREATE TABLE IF NOT EXISTS live_creator_support (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                live_stream_id INTEGER NOT NULL,
                creator_id INTEGER NOT NULL,
                supporter_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                supporter_total REAL NOT NULL,
                platform_fee REAL NOT NULL,
                currency TEXT NOT NULL,
                earning_reference TEXT UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 35. Live Reactions
        c.execute("""
            CREATE TABLE IF NOT EXISTS live_reactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stream_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                reaction TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 36. Live Viewers
        c.execute("""
            CREATE TABLE IF NOT EXISTS live_viewers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stream_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                left_at TEXT
            )
        """)

        # 37. Platform Revenue
        c.execute("""
            CREATE TABLE IF NOT EXISTS platform_revenue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                amount REAL NOT NULL,
                currency TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_reference TEXT,
                revenue_reference TEXT UNIQUE NOT NULL,
                payer_id INTEGER,
                description TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 38. Platform Revenue Ledger
        c.execute("""
            CREATE TABLE IF NOT EXISTS platform_revenue_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                gross_amount REAL DEFAULT 0,
                creator_amount REAL DEFAULT 0,
                platform_amount REAL DEFAULT 0,
                platform_revenue INTEGER DEFAULT 0,
                currency_code TEXT DEFAULT 'USD',
                credits INTEGER DEFAULT 0,
                wallet_amount REAL DEFAULT 0,
                wallet_currency TEXT,
                source_type TEXT NOT NULL,
                source_reference TEXT,
                reference TEXT,
                transaction_reference TEXT,
                status TEXT DEFAULT 'Completed',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 39. Settlement Batches
        c.execute("""
            CREATE TABLE IF NOT EXISTS settlement_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_reference TEXT UNIQUE NOT NULL,
                period_label TEXT NOT NULL,
                total_transactions INTEGER DEFAULT 0,
                gross_amount REAL DEFAULT 0.0,
                fee_amount REAL DEFAULT 0.0,
                net_amount REAL DEFAULT 0.0,
                currency TEXT DEFAULT 'USD',
                status TEXT DEFAULT 'Closed',
                reconciled_by TEXT DEFAULT 'System',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 40. Wallet Assets
        c.execute("""
            CREATE TABLE IF NOT EXISTS wallet_assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                asset_type TEXT NOT NULL,
                asset_code TEXT NOT NULL,
                network TEXT DEFAULT '',
                balance REAL DEFAULT 0.0,
                available_balance REAL DEFAULT 0.0,
                pending_balance REAL DEFAULT 0.0,
                asset_status TEXT DEFAULT 'Active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, asset_type, asset_code, network)
            )
        """)

        # 41. Wallet Transactions
        c.execute("""
            CREATE TABLE IF NOT EXISTS wallet_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                transaction_type TEXT NOT NULL,
                amount REAL NOT NULL,
                currency TEXT NOT NULL,
                description TEXT,
                reference TEXT UNIQUE,
                status TEXT DEFAULT 'Completed',
                asset_type TEXT DEFAULT 'FIAT',
                asset_code TEXT,
                network TEXT,
                counterparty_user_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 42. Webhook Logs
        c.execute("""
            CREATE TABLE IF NOT EXISTS webhook_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                reference TEXT,
                status TEXT NOT NULL,
                received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 43. Withdrawal Notifications
        c.execute("""
            CREATE TABLE IF NOT EXISTS withdrawal_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                notification_type TEXT NOT NULL,
                withdrawal_reference TEXT NOT NULL,
                amount REAL DEFAULT 0.0,
                currency TEXT DEFAULT 'USD',
                is_read INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 44. Withdrawal Requests
        c.execute("""
            CREATE TABLE IF NOT EXISTS withdrawal_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                creator_id INTEGER NOT NULL,
                request_reference TEXT UNIQUE NOT NULL,
                gross_amount REAL NOT NULL,
                platform_charge REAL NOT NULL,
                net_disbursed REAL NOT NULL,
                currency TEXT DEFAULT 'NGN',
                payout_method TEXT,
                bank_name TEXT,
                account_number TEXT,
                account_name TEXT,
                status TEXT DEFAULT 'Pending',
                rejection_reason TEXT,
                processed_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP
            )
        """)

        # ====================================================
        # SAFE COLUMN MIGRATIONS FOR ALL EXISTING TABLES
        # ====================================================

        # --- Users ---
        add_column_if_missing(c, "users", "display_name", "TEXT")
        add_column_if_missing(c, "users", "full_name", "TEXT")
        add_column_if_missing(c, "users", "bio", "TEXT")
        add_column_if_missing(c, "users", "avatar_url", "TEXT")
        add_column_if_missing(c, "users", "phone", "TEXT")
        add_column_if_missing(c, "users", "country", "TEXT DEFAULT 'Nigeria'")
        add_column_if_missing(c, "users", "currency", "TEXT DEFAULT 'NGN'")
        add_column_if_missing(c, "users", "role", "TEXT DEFAULT 'user'")
        add_column_if_missing(c, "users", "is_creator", "INTEGER DEFAULT 0")
        add_column_if_missing(c, "users", "is_active", "INTEGER DEFAULT 1")
        add_column_if_missing(c, "users", "failed_login_attempts", "INTEGER DEFAULT 0")
        add_column_if_missing(c, "users", "last_failed_login_at", "TIMESTAMP")
        add_column_if_missing(c, "users", "last_login_at", "TIMESTAMP")
        add_column_if_missing(c, "users", "last_login", "TIMESTAMP")
        add_column_if_missing(c, "users", "kyc_status", "TEXT DEFAULT 'unverified'")
        add_column_if_missing(c, "users", "created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        add_column_if_missing(c, "users", "updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        add_column_if_missing(c, "users", "receiving_id", "TEXT")

        # --- Password Resets ---
        add_column_if_missing(c, "password_resets", "reset_code", "TEXT")
        add_column_if_missing(c, "password_resets", "token", "TEXT")
        add_column_if_missing(c, "password_resets", "expires_at", "TIMESTAMP")
        add_column_if_missing(c, "password_resets", "used", "INTEGER DEFAULT 0")

        # --- Wallets ---
        add_column_if_missing(c, "wallets", "available_balance", "REAL DEFAULT 0.0")
        add_column_if_missing(c, "wallets", "pending_balance", "REAL DEFAULT 0.0")
        add_column_if_missing(c, "wallets", "gift_credits", "INTEGER DEFAULT 0")
        add_column_if_missing(c, "wallets", "currency", "TEXT DEFAULT 'USD'")
        add_column_if_missing(c, "wallets", "status", "TEXT DEFAULT 'Active'")
        add_column_if_missing(c, "wallets", "wallet_status", "TEXT DEFAULT 'Active'")

        # --- Receiving Accounts ---
        add_column_if_missing(c, "receiving_accounts", "user_id", "INTEGER")
        add_column_if_missing(c, "receiving_accounts", "receiving_id", "TEXT")
        add_column_if_missing(c, "receiving_accounts", "payout_method", "TEXT DEFAULT 'bank'")
        add_column_if_missing(c, "receiving_accounts", "currency", "TEXT DEFAULT 'NGN'")
        add_column_if_missing(c, "receiving_accounts", "bank_name", "TEXT")
        add_column_if_missing(c, "receiving_accounts", "account_number", "TEXT")
        add_column_if_missing(c, "receiving_accounts", "account_name", "TEXT")
        add_column_if_missing(c, "receiving_accounts", "bank_code", "TEXT")
        add_column_if_missing(c, "receiving_accounts", "is_primary", "INTEGER DEFAULT 1")
        add_column_if_missing(c, "receiving_accounts", "account_status", "TEXT DEFAULT 'Active'")
        add_column_if_missing(c, "receiving_accounts", "account_type", "TEXT DEFAULT 'internal_wallet'")
        add_column_if_missing(c, "receiving_accounts", "verification_status", "TEXT DEFAULT 'Verified'")
        add_column_if_missing(c, "receiving_accounts", "status", "TEXT DEFAULT 'Active'")
        add_column_if_missing(c, "receiving_accounts", "created_at", "TIMESTAMP")
        add_column_if_missing(c, "receiving_accounts", "updated_at", "TIMESTAMP")
        ensure_legacy_row_id(c, "receiving_accounts")

        # --- Creator Profiles ---
        add_column_if_missing(c, "creator_profiles", "user_id", "INTEGER")
        add_column_if_missing(c, "creator_profiles", "display_name", "TEXT")
        add_column_if_missing(c, "creator_profiles", "description", "TEXT DEFAULT ''")
        add_column_if_missing(c, "creator_profiles", "creator_status", "TEXT DEFAULT 'active'")
        add_column_if_missing(c, "creator_profiles", "currency", "TEXT DEFAULT 'NGN'")
        add_column_if_missing(c, "creator_profiles", "total_earnings", "REAL DEFAULT 0.0")
        add_column_if_missing(c, "creator_profiles", "pending_balance", "REAL DEFAULT 0.0")
        add_column_if_missing(c, "creator_profiles", "kyc_tier", "INTEGER DEFAULT 1")
        add_column_if_missing(c, "creator_profiles", "created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        add_column_if_missing(c, "creator_profiles", "updated_at", "TEXT")
        ensure_legacy_row_id(c, "creator_profiles")

        # --- Creator Withdrawals ---
        add_column_if_missing(c, "creator_withdrawals", "fee", "REAL DEFAULT 0.0")
        add_column_if_missing(c, "creator_withdrawals", "net_amount", "REAL")
        add_column_if_missing(c, "creator_withdrawals", "status", "TEXT DEFAULT 'Pending'")
        add_column_if_missing(c, "creator_withdrawals", "payout_method", "TEXT DEFAULT 'bank'")
        add_column_if_missing(c, "creator_withdrawals", "payment_method", "TEXT DEFAULT 'bank_transfer'")
        add_column_if_missing(c, "creator_withdrawals", "bank_name", "TEXT")
        add_column_if_missing(c, "creator_withdrawals", "account_number", "TEXT")
        add_column_if_missing(c, "creator_withdrawals", "account_name", "TEXT")
        add_column_if_missing(c, "creator_withdrawals", "bank_code", "TEXT")
        add_column_if_missing(c, "creator_withdrawals", "receiving_account_id", "INTEGER")
        add_column_if_missing(c, "creator_withdrawals", "withdrawal_reference", "TEXT")
        add_column_if_missing(c, "creator_withdrawals", "transaction_reference", "TEXT")
        add_column_if_missing(c, "creator_withdrawals", "destination", "TEXT DEFAULT ''")
        add_column_if_missing(c, "creator_withdrawals", "payout_details", "TEXT DEFAULT ''")
        add_column_if_missing(c, "creator_withdrawals", "notes", "TEXT DEFAULT ''")
        add_column_if_missing(c, "creator_withdrawals", "requested_at", "TIMESTAMP")
        add_column_if_missing(c, "creator_withdrawals", "processed_at", "TIMESTAMP")

        # --- Goals ---
        add_column_if_missing(c, "goals", "category", "TEXT DEFAULT 'Personal'")
        add_column_if_missing(c, "goals", "target_amount", "REAL DEFAULT 0.0")
        add_column_if_missing(c, "goals", "current_amount", "REAL DEFAULT 0.0")
        add_column_if_missing(c, "goals", "progress", "INTEGER DEFAULT 0")
        add_column_if_missing(c, "goals", "currency", "TEXT DEFAULT 'USD'")
        add_column_if_missing(c, "goals", "target_date", "DATE")
        add_column_if_missing(c, "goals", "deadline", "DATE")
        add_column_if_missing(c, "goals", "status", "TEXT DEFAULT 'Active'")

        # --- Help Requests ---
        add_column_if_missing(c, "help_requests", "requester_id", "INTEGER")
        add_column_if_missing(c, "help_requests", "helper_id", "INTEGER")
        add_column_if_missing(c, "help_requests", "help_type", "TEXT DEFAULT 'Other'")
        add_column_if_missing(c, "help_requests", "target_date", "DATE")
        add_column_if_missing(c, "help_requests", "target_helper_id", "INTEGER")
        add_column_if_missing(c, "help_requests", "title", "TEXT")
        add_column_if_missing(c, "help_requests", "category", "TEXT DEFAULT 'General'")
        add_column_if_missing(c, "help_requests", "description", "TEXT")
        add_column_if_missing(c, "help_requests", "urgency", "TEXT DEFAULT 'Medium'")
        add_column_if_missing(c, "help_requests", "subject", "TEXT")
        add_column_if_missing(c, "help_requests", "message", "TEXT")
        add_column_if_missing(c, "help_requests", "status", "TEXT DEFAULT 'Open'")
        add_column_if_missing(c, "help_requests", "accepted_at", "TIMESTAMP")
        add_column_if_missing(c, "help_requests", "completed_at", "TIMESTAMP")
        add_column_if_missing(c, "help_requests", "confirmed_at", "TIMESTAMP")
        add_column_if_missing(c, "help_requests", "wallet_amount", "REAL DEFAULT 0.0")
        add_column_if_missing(c, "help_requests", "wallet_transfer_reference", "TEXT")

        # --- Notifications ---
        add_column_if_missing(c, "notifications", "type", "TEXT DEFAULT 'general'")
        add_column_if_missing(c, "notifications", "notification_type", "TEXT DEFAULT 'general'")
        add_column_if_missing(c, "notifications", "reference", "TEXT")
        add_column_if_missing(c, "notifications", "reference_type", "TEXT")
        add_column_if_missing(c, "notifications", "reference_id", "TEXT")

        # --- Messages ---
        add_column_if_missing(c, "messages", "conversation_id", "INTEGER")
        add_column_if_missing(c, "messages", "content", "TEXT")
        add_column_if_missing(c, "messages", "message", "TEXT")
        add_column_if_missing(c, "messages", "is_read", "INTEGER DEFAULT 0")

        # --- Connections ---
        add_column_if_missing(c, "connections", "connected_user_id", "INTEGER")
        add_column_if_missing(c, "connections", "requester_id", "INTEGER")
        add_column_if_missing(c, "connections", "receiver_id", "INTEGER")
        add_column_if_missing(c, "connections", "status", "TEXT DEFAULT 'accepted'")

        # --- Activity Logs ---
        add_column_if_missing(c, "activity_logs", "activity_type", "TEXT")
        add_column_if_missing(c, "activity_logs", "activity_title", "TEXT")
        add_column_if_missing(c, "activity_logs", "activity_description", "TEXT")
        add_column_if_missing(c, "activity_logs", "action", "TEXT")
        add_column_if_missing(c, "activity_logs", "details", "TEXT")
        add_column_if_missing(c, "activity_logs", "ip_address", "TEXT")
        add_column_if_missing(c, "activity_logs", "user_agent", "TEXT")
        add_column_if_missing(c, "activity_logs", "location", "TEXT")
        add_column_if_missing(c, "activity_logs", "reference_type", "TEXT")
        add_column_if_missing(c, "activity_logs", "reference_id", "INTEGER")

        # --- Creator Earnings ---
        add_column_if_missing(c, "creator_earnings", "supporter_id", "INTEGER")
        add_column_if_missing(c, "creator_earnings", "amount", "REAL DEFAULT 0")
        add_column_if_missing(c, "creator_earnings", "supporter_total", "REAL DEFAULT 0")
        add_column_if_missing(c, "creator_earnings", "currency", "TEXT DEFAULT 'NGN'")
        add_column_if_missing(c, "creator_earnings", "platform_fee", "REAL DEFAULT 0")
        add_column_if_missing(c, "creator_earnings", "earning_reference", "TEXT")
        add_column_if_missing(c, "creator_earnings", "gift_name", "TEXT DEFAULT ''")
        add_column_if_missing(c, "creator_earnings", "fan_name", "TEXT DEFAULT ''")
        add_column_if_missing(c, "creator_earnings", "message", "TEXT DEFAULT ''")
        add_column_if_missing(c, "creator_earnings", "status", "TEXT DEFAULT 'Completed'")
        add_column_if_missing(c, "creator_earnings", "asset_type", "TEXT DEFAULT 'FIAT'")

        # --- Creator Gift Earnings ---
        add_column_if_missing(c, "creator_gift_earnings", "creator_user_id", "INTEGER")
        add_column_if_missing(c, "creator_gift_earnings", "sender_user_id", "INTEGER")
        add_column_if_missing(c, "creator_gift_earnings", "source_user_id", "INTEGER")
        add_column_if_missing(c, "creator_gift_earnings", "gift_id", "INTEGER")
        add_column_if_missing(c, "creator_gift_earnings", "gift_sent_id", "INTEGER")
        add_column_if_missing(c, "creator_gift_earnings", "gift_code", "TEXT")
        add_column_if_missing(c, "creator_gift_earnings", "credits", "INTEGER DEFAULT 0")
        add_column_if_missing(c, "creator_gift_earnings", "creator_value", "INTEGER DEFAULT 0")
        add_column_if_missing(c, "creator_gift_earnings", "gross_value", "REAL DEFAULT 0")
        add_column_if_missing(c, "creator_gift_earnings", "platform_fee", "REAL DEFAULT 0")
        add_column_if_missing(c, "creator_gift_earnings", "net_earnings", "REAL DEFAULT 0")
        add_column_if_missing(c, "creator_gift_earnings", "currency_code", "TEXT DEFAULT 'USD'")
        add_column_if_missing(c, "creator_gift_earnings", "reference", "TEXT")
        add_column_if_missing(c, "creator_gift_earnings", "transaction_reference", "TEXT")
        add_column_if_missing(c, "creator_gift_earnings", "status", "TEXT DEFAULT 'Pending'")

        # --- Gift Credit Payments ---
        add_column_if_missing(c, "gift_credit_payments", "checkout_url", "TEXT")
        add_column_if_missing(c, "gift_credit_payments", "provider_transaction_id", "TEXT")
        add_column_if_missing(c, "gift_credit_payments", "verification_note", "TEXT")
        add_column_if_missing(c, "gift_credit_payments", "verified_at", "TEXT")
        add_column_if_missing(c, "gift_credit_payments", "credited_at", "TEXT")

        # --- Gift Credit Balances ---
        add_column_if_missing(c, "gift_credit_balances", "balance", "INTEGER DEFAULT 0")
        add_column_if_missing(c, "gift_credit_balances", "credit_balance", "INTEGER DEFAULT 0")
        add_column_if_missing(c, "gift_credit_balances", "lifetime_purchased", "INTEGER DEFAULT 0")
        add_column_if_missing(c, "gift_credit_balances", "lifetime_received", "INTEGER DEFAULT 0")
        add_column_if_missing(c, "gift_credit_balances", "lifetime_sent", "INTEGER DEFAULT 0")
        add_column_if_missing(c, "gift_credit_balances", "lifetime_spent", "INTEGER DEFAULT 0")

        # --- Gifts Sent ---
        add_column_if_missing(c, "gifts_sent", "sender_user_id", "INTEGER")
        add_column_if_missing(c, "gifts_sent", "recipient_user_id", "INTEGER")
        add_column_if_missing(c, "gifts_sent", "receiver_user_id", "INTEGER")
        add_column_if_missing(c, "gifts_sent", "live_stream_id", "INTEGER")
        add_column_if_missing(c, "gifts_sent", "gift_id", "INTEGER")
        add_column_if_missing(c, "gifts_sent", "gift_name", "TEXT")
        add_column_if_missing(c, "gifts_sent", "gift_code", "TEXT")
        add_column_if_missing(c, "gifts_sent", "quantity", "INTEGER DEFAULT 1")
        add_column_if_missing(c, "gifts_sent", "credits", "INTEGER DEFAULT 0")
        add_column_if_missing(c, "gifts_sent", "total_credits", "INTEGER DEFAULT 0")
        add_column_if_missing(c, "gifts_sent", "creator_value", "REAL DEFAULT 0")
        add_column_if_missing(c, "gifts_sent", "currency_code", "TEXT DEFAULT 'USD'")
        add_column_if_missing(c, "gifts_sent", "message", "TEXT")
        add_column_if_missing(c, "gifts_sent", "reference", "TEXT")
        add_column_if_missing(c, "gifts_sent", "transaction_reference", "TEXT")
        add_column_if_missing(c, "gifts_sent", "status", "TEXT DEFAULT 'Completed'")

        # --- Live Streams ---
        add_column_if_missing(c, "live_streams", "scheduled_at", "TEXT")
        add_column_if_missing(c, "live_streams", "started_at", "TEXT")
        add_column_if_missing(c, "live_streams", "ended_at", "TEXT")
        add_column_if_missing(c, "live_streams", "stream_key", "TEXT")
        add_column_if_missing(c, "live_streams", "viewer_count", "INTEGER DEFAULT 0")

        # --- Wallet Transactions ---
        add_column_if_missing(c, "wallet_transactions", "asset_type", "TEXT DEFAULT 'FIAT'")
        add_column_if_missing(c, "wallet_transactions", "asset_code", "TEXT")
        add_column_if_missing(c, "wallet_transactions", "network", "TEXT")
        add_column_if_missing(c, "wallet_transactions", "counterparty_user_id", "INTEGER")

        # --- Non-destructive safe balance and status synchronization ---
        try:
            # Sync available_balance from balance if NULL or 0 with positive balance
            c.execute("""
                UPDATE wallets
                SET available_balance = balance
                WHERE (available_balance IS NULL OR available_balance = 0.0)
                  AND balance > 0
            """)
        except Exception:
            pass

        try:
            # Sync status and wallet_status so both are always aligned
            c.execute("""
                UPDATE wallets
                SET wallet_status = status
                WHERE (wallet_status IS NULL OR wallet_status = '')
                  AND status IS NOT NULL AND status != ''
            """)
            c.execute("""
                UPDATE wallets
                SET status = wallet_status
                WHERE (status IS NULL OR status = '')
                  AND wallet_status IS NOT NULL AND wallet_status != ''
            """)
        except Exception:
            pass

        try:
            # Ensure each existing user has a corresponding wallet row
            c.execute("""
                INSERT OR IGNORE INTO wallets (
                    user_id, currency, balance, available_balance, pending_balance, status, wallet_status
                )
                SELECT id, COALESCE(currency, 'USD'), 0.0, 0.0, 0.0, 'Active', 'Active'
                FROM users
                WHERE id NOT IN (SELECT user_id FROM wallets WHERE user_id IS NOT NULL)
            """)
        except Exception:
            pass

        try:
            # Ensure each existing user has a corresponding creator profile
            c.execute("""
                INSERT OR IGNORE INTO creator_profiles (
                    user_id, display_name, description, creator_status, currency, total_earnings, pending_balance, kyc_tier
                )
                SELECT id, COALESCE(full_name, username, 'Creator'), '', 'active', COALESCE(currency, 'NGN'), 0.0, 0.0, 1
                FROM users
                WHERE id NOT IN (SELECT user_id FROM creator_profiles WHERE user_id IS NOT NULL)
            """)
        except Exception:
            pass

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

# ============================================================
# ALIASES & COMPATIBILITY HELPERS
# ============================================================

init_db = initialize_database

def table_exists(conn, table_name: str) -> bool:
    """Check if a table exists in the database."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    )
    return cursor.fetchone() is not None

def column_exists(conn, table_name: str, column_name: str) -> bool:
    """Check if a column exists in a given table."""
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    return any(row[1].lower() == column_name.lower() for row in cursor.fetchall())

