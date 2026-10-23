
import bcrypt
import secrets
from datetime import datetime, timedelta

from database import get_connection


# ============================================================
# ACTIVITY LOGGING
# ============================================================

def log_activity(
    user_id,
    activity_type,
    activity_title,
    activity_description=None,
    ip_address=None,
    user_agent=None,
    location=None,
    reference_type=None,
    reference_id=None,
):
    """Record a LifeGrid activity or security event."""

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT INTO activity_logs (
            user_id,
            activity_type,
            activity_title,
            activity_description,
            ip_address,
            user_agent,
            location,
            reference_type,
            reference_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            activity_type,
            activity_title,
            activity_description,
            ip_address,
            user_agent,
            location,
            reference_type,
            reference_id,
        ),
    )

    connection.commit()
    connection.close()


# ============================================================
# PASSWORD HASHING
# ============================================================

def hash_password(password: str) -> str:
    """Securely hash a user's password."""

    password_bytes = password.encode("utf-8")

    hashed = bcrypt.hashpw(
        password_bytes,
        bcrypt.gensalt(),
    )

    return hashed.decode("utf-8")


def verify_password(
    password: str,
    password_hash: str,
) -> bool:
    """Check a password against its stored hash."""

    password_bytes = password.encode("utf-8")
    hash_bytes = password_hash.encode("utf-8")

    return bcrypt.checkpw(
        password_bytes,
        hash_bytes,
    )


# ============================================================
# REGISTER USER
# ============================================================

def register_user(
    username: str,
    email: str,
    password: str,
    full_name: str = "",
    country: str = "",
    currency: str = "NGN",
):
    """Register a new LifeGrid user and create a welcome notification."""

    username = username.strip()
    email = email.strip().lower()
    full_name = full_name.strip()
    country = country.strip()

    if not username or not email or not password:
        return False, "Username, email, and password are required."

    password_hash = hash_password(password)

    connection = get_connection()
    cursor = connection.cursor()

    try:
        # --------------------------------------------------------
        # CREATE USER ACCOUNT
        # --------------------------------------------------------

        cursor.execute(
            """
            INSERT INTO users (
                username,
                email,
                password_hash,
                full_name,
                country,
                currency
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                username,
                email,
                password_hash,
                full_name,
                country,
                currency,
            ),
        )

        user_id = cursor.lastrowid

        # --------------------------------------------------------
        # CREATE AUTOMATIC WELCOME NOTIFICATION
        # --------------------------------------------------------

        display_name = full_name if full_name else username

        welcome_title = "Welcome to LifeGrid 🌍"

        welcome_message = (
            f"Welcome to LifeGrid, {display_name}! "
            "Your account has been created successfully. "
            "Start by completing your profile, setting your goals, "
            "connecting with people, and exploring the LifeGrid community."
        )

        cursor.execute(
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
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                user_id,
                "system",
                welcome_title,
                welcome_message,
                "account",
                user_id,
                0,
            ),
        )

        # --------------------------------------------------------
        # COMMIT ACCOUNT + WELCOME NOTIFICATION
        # --------------------------------------------------------

        connection.commit()

        # --------------------------------------------------------
        # RECORD ACCOUNT CREATION ACTIVITY
        # --------------------------------------------------------

        log_activity(
            user_id,
            "Account",
            "Account created",
            "A new LifeGrid account was created.",
            reference_type="account",
            reference_id=user_id,
        )

        return True, "Account created successfully."

    except Exception as error:

        connection.rollback()

        if "UNIQUE constraint failed" in str(error):
            return False, "Username or email already exists."

        return False, "Unable to create the account."

    finally:

        connection.close()


# ============================================================
# LOGIN USER
# ============================================================

def login_user(
    identifier: str,
    password: str,
):
    """Authenticate a LifeGrid user."""

    identifier = identifier.strip()

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT
            id,
            username,
            email,
            password_hash,
            full_name,
            country,
            currency,
            is_active,
            failed_login_attempts
        FROM users
        WHERE username = ? OR email = ?
        """,
        (
            identifier,
            identifier.lower(),
        ),
    )

    user = cursor.fetchone()

    if not user:

        connection.close()

        log_activity(
            None,
            "Security",
            "Failed login attempt",
            "A login attempt was made using an unknown username or email.",
        )

        return None

    (
        user_id,
        username,
        email,
        password_hash,
        full_name,
        country,
        currency,
        is_active,
        failed_login_attempts,
    ) = user

    if not is_active:

        connection.close()

        log_activity(
            user_id,
            "Security",
            "Login blocked",
            "A login attempt was made on an inactive account.",
        )

        return None

    if not verify_password(
        password,
        password_hash,
    ):

        cursor.execute(
            """
            UPDATE users
            SET
                failed_login_attempts =
                    COALESCE(failed_login_attempts, 0) + 1,
                last_failed_login_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (user_id,),
        )

        connection.commit()
        connection.close()

        log_activity(
            user_id,
            "Security",
            "Failed login attempt",
            "An incorrect password was entered.",
        )

        return None

    cursor.execute(
        """
        UPDATE users
        SET
            last_login_at = CURRENT_TIMESTAMP,
            failed_login_attempts = 0
        WHERE id = ?
        """,
        (user_id,),
    )

    connection.commit()
    connection.close()

    log_activity(
        user_id,
        "Security",
        "Successful login",
        "The user successfully logged into LifeGrid.",
    )

    return {
        "id": user_id,
        "username": username,
        "email": email,
        "full_name": full_name,
        "country": country,
        "currency": currency,
    }


# ============================================================
# LOGOUT
# ============================================================

def log_logout(user_id):
    """Record a user logout event."""

    if not user_id:
        return

    log_activity(
        user_id,
        "Security",
        "User logged out",
        "The user logged out of LifeGrid.",
    )


# ============================================================
# CREATE PASSWORD RESET CODE
# ============================================================

def create_password_reset_code(email: str):
    """
    Create a temporary password recovery code.

    Returns:
        False, message
        OR
        True, reset information dictionary
    """

    email = email.strip().lower()

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT id
        FROM users
        WHERE email = ?
          AND is_active = 1
        """,
        (email,),
    )

    user = cursor.fetchone()

    if not user:

        connection.close()

        log_activity(
            None,
            "Security",
            "Password reset request",
            "A password recovery request was made for an unknown account.",
        )

        return (
            False,
            "No active LifeGrid account was found with that email.",
        )

    user_id = user[0]

    # --------------------------------------------------------
    # INVALIDATE PREVIOUS RESET CODES
    # --------------------------------------------------------

    cursor.execute(
        """
        UPDATE password_resets
        SET used = 1
        WHERE user_id = ?
          AND used = 0
        """,
        (user_id,),
    )

    # --------------------------------------------------------
    # GENERATE SIX-DIGIT CODE
    # --------------------------------------------------------

    reset_code = f"{secrets.randbelow(1_000_000):06d}"

    expires_at = (
        datetime.now()
        + timedelta(minutes=15)
    )

    cursor.execute(
        """
        INSERT INTO password_resets (
            user_id,
            reset_code,
            expires_at
        )
        VALUES (?, ?, ?)
        """,
        (
            user_id,
            reset_code,
            expires_at,
        ),
    )

    reset_id = cursor.lastrowid

    connection.commit()
    connection.close()

    log_activity(
        user_id,
        "Security",
        "Password reset requested",
        "A password recovery code was generated.",
        reference_type="password_reset",
        reference_id=reset_id,
    )

    # IMPORTANT:
    # app.py expects result["user_id"].
    return (
        True,
        {
            "user_id": user_id,
            "reset_id": reset_id,
            "reset_code": reset_code,
            "expires_at": expires_at,
        },
    )


# ============================================================
# VERIFY PASSWORD RESET CODE
# ============================================================

def verify_password_reset_code(
    email: str,
    reset_code: str,
):
    """Verify a password recovery code."""

    email = email.strip().lower()
    reset_code = reset_code.strip()

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT
            password_resets.id,
            password_resets.user_id,
            password_resets.expires_at
        FROM password_resets
        JOIN users
            ON users.id = password_resets.user_id
        WHERE users.email = ?
          AND password_resets.reset_code = ?
          AND password_resets.used = 0
        ORDER BY password_resets.id DESC
        LIMIT 1
        """,
        (
            email,
            reset_code,
        ),
    )

    reset_record = cursor.fetchone()

    if not reset_record:

        connection.close()

        return False, None

    (
        reset_id,
        user_id,
        expires_at,
    ) = reset_record

    try:

        expiry_time = datetime.fromisoformat(
            str(expires_at)
        )

    except ValueError:

        connection.close()

        return False, None

    if datetime.now() > expiry_time:

        cursor.execute(
            """
            UPDATE password_resets
            SET used = 1
            WHERE id = ?
            """,
            (reset_id,),
        )

        connection.commit()
        connection.close()

        log_activity(
            user_id,
            "Security",
            "Expired password reset code",
            "An expired password recovery code was submitted.",
            reference_type="password_reset",
            reference_id=reset_id,
        )

        return False, None

    connection.close()

    log_activity(
        user_id,
        "Security",
        "Password reset code verified",
        "A password recovery code was successfully verified.",
        reference_type="password_reset",
        reference_id=reset_id,
    )

    return True, {
        "reset_id": reset_id,
        "user_id": user_id,
    }


# ============================================================
# RESET PASSWORD
# ============================================================

def reset_password(
    email: str,
    reset_code: str,
    new_password: str,
):
    """Reset a user's password."""

    if len(new_password) < 8:

        return (
            False,
            "Password must contain at least 8 characters.",
        )

    valid, reset_data = verify_password_reset_code(
        email,
        reset_code,
    )

    if not valid:

        return (
            False,
            "Invalid or expired recovery code.",
        )

    new_password_hash = hash_password(
        new_password
    )

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        UPDATE users
        SET
            password_hash = ?,
            failed_login_attempts = 0
        WHERE id = ?
        """,
        (
            new_password_hash,
            reset_data["user_id"],
        ),
    )

    cursor.execute(
        """
        UPDATE password_resets
        SET used = 1
        WHERE id = ?
        """,
        (reset_data["reset_id"],),
    )

    connection.commit()
    connection.close()

    log_activity(
        reset_data["user_id"],
        "Security",
        "Password changed",
        "The user's password was successfully changed.",
        reference_type="password_reset",
        reference_id=reset_data["reset_id"],
    )

    return (
        True,
        "Your password has been changed successfully.",
    )

