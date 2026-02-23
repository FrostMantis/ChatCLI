import string
import re
import bcrypt
from datetime import datetime, timedelta, timezone
import secrets
import hashlib
import random
from flask import current_app
import os

from app.errors import BadRequest, Unauthorized, Forbidden, NotFound, Conflict, APIError
from app.database.db_helper import fetch_records, insert_record, update_records
from app.services.base_services import authenticate_token
from app.services.mail_services import (
    send_verification_email,
    send_password_reset_email,
    send_email_change_verification,
)

# Character set for tokens
alphabet = string.ascii_letters + string.digits


def register(data: dict) -> dict:
    """
    Registers a new user and sends a verification code.
    """
    username = (data.get("username") or "").strip()
    password = data.get("password")
    email    = (data.get("email") or "").strip()

    # 400: missing/invalid input
    if not username or not password:
        raise BadRequest("Username and password are required.")
    invalid_chars = set(r'"%\'()*+,/:;<=>?@[\]^{|}~` ')
    if any(ch in invalid_chars for ch in username):
        raise BadRequest("Username includes invalid characters.")
    if not email:
        raise BadRequest("Email is required.")
    if not re.match(r'^[\w\.\+-]+@[\w-]+\.[\w\.-]+$', email):
        raise BadRequest("Invalid email address.")
    if (
        len(password) < 8 or
        not any(ch.isupper() for ch in password) or
        not any(ch.islower() for ch in password) or
        not any(ch.isdigit() for ch in password) or
        not any(ch in string.punctuation for ch in password)
    ):
        raise BadRequest(
            "Password must be ≥8 chars, include upper, lower, digit & special."
        )

    try:
        # hash password (store as utf-8 string for DB portability)
        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

        # check existing user
        users = fetch_records(
            table="users",
            where_clause="LOWER(username) = LOWER(%s)",
            params=(username,),
            fetch_all=True
        )

        if users:
            user = users[0]
            if user["email_verified"]:
                raise Conflict(f"User '{username}' already exists.")
            userID = user["userID"]
            # update unverified user
            update_records(
                table="users",
                data={
                    "password": hashed,
                    "email": email,
                    "created_at": datetime.now(timezone.utc)
                },
                where_clause="userID = %s",
                where_params=(userID,)
            )
            # revoke any recent tokens
            update_records(
                table="email_tokens",
                data={"revoked": True},
                where_clause="userID = %s AND expires_at > %s",
                where_params=(userID, datetime.now(timezone.utc))
            )
        else:
            # insert new user
            userID = insert_record(
                "users",
                {
                    "username": username,
                    "password": hashed,
                    "email": email,
                    "email_verified": False
                }
            )

        # create verification token
        email_token = f"{random.randint(100000, 999999):06d}"
        expiry      = datetime.now(timezone.utc) + timedelta(minutes=5)
        insert_record(
            "email_tokens",
            {
                "userID":      userID,
                "email_token": email_token,
                "expires_at":  expiry,
                "revoked":     False
            }
        )
    except Conflict:
        raise
    except Exception as e:
        current_app.logger.error("Error during user registration", exc_info=e)
        raise APIError()

    # send verification email
    if os.getenv("FLASK_ENV") == "dev" and os.getenv("IGNORE_EMAIL_VERIF") == "true":
        verify_email(data={"username":username,"email_token":email_token})
        return {"message": "Email Verification skipped!"}
    else:
        send_verification_email(username, email_token, email)
        return {"message": "Verification email sent!"}


def verify_email(data: dict) -> dict:
    """
    Consumes a verification token and marks the user verified.
    """
    username    = (data.get("username") or "").strip().lower()
    client_code = (data.get("email_token") or "").strip()

    if not username or not client_code:
        raise BadRequest("Username and email_token are required.")

    try:
        # fetch the latest valid token
        row = fetch_records(
            table="email_tokens",
            where_clause=(
                "userID = (SELECT userID FROM users WHERE LOWER(username) = LOWER(%s)) "
                "AND revoked = FALSE AND expires_at > %s"
            ),
            params=(username, datetime.now(timezone.utc)),
            order_by="created_at DESC",
            limit=1,
            fetch_all=False
        )
        if not row or str(row["email_token"]) != client_code:
            raise BadRequest("Invalid or expired code.")

        # revoke token & mark user verified
        update_records(
            table="email_tokens",
            data={"revoked": True},
            where_clause="tokenID = %s",
            where_params=(row["tokenID"],)
        )
        update_records(
            table="users",
            data={"email_verified": True},
            where_clause="userID = %s",
            where_params=(row["userID"],)
        )

    except APIError:
        # re-raise known API errors
        raise
    except Exception as e:
        current_app.logger.error("Error during email verification", exc_info=e)
        raise APIError()

    return {"message": "Email verified!"}


def resend_verification(data: dict) -> dict:
    """
    Resends a verification code to the user's email.
    """
    username = (data.get("username") or "").strip().lower()

    if not username:
        raise BadRequest("Username is required.")

    try:
        users = fetch_records(
            table="users",
            where_clause="LOWER(username) = LOWER(%s)",
            params=(username,),
            fetch_all=True
        )
        if not users:
            raise NotFound("User not found.")
        user = users[0]
        if user["email_verified"]:
            raise BadRequest("Email is already verified.")

        # revoke all tokens
        update_records(
            table="email_tokens",
            data={"revoked": True},
            where_clause="userID = %s AND expires_at > %s",
            where_params=(user["userID"], datetime.now(timezone.utc))
        )

        # create new token
        email_token = f"{random.randint(100000, 999999):06d}"
        expiry      = datetime.now(timezone.utc) + timedelta(minutes=5)
        insert_record(
            "email_tokens",
            {
                "userID":      user["userID"],
                "email_token": email_token,
                "expires_at":  expiry,
                "revoked":     False
            }
        )
    except APIError:
        raise
    except Exception as e:
        current_app.logger.error("Error during resend verification", exc_info=e)
        raise APIError()

    # send verification email
    send_verification_email(user["username"], email_token, user["email"])

    return {"message": "Verification email resent!"}


def login(data: dict) -> dict:
    """
    Authenticates credentials and issues tokens.
    """
    username = (data.get("username") or "").strip().lower()
    password = data.get("password")

    if not username or not password:
        raise BadRequest("Username and password required.")

    try:
        users = fetch_records(
            table="users",
            where_clause="username = %s AND email_verified = 1 AND disabled = 0",
            params=(username,),
            fetch_all=True
        )
        if not users:
            raise BadRequest("Username or password is incorrect.")
        user = users[0]
        # Normalize stored password to bytes for bcrypt
        stored = user.get("password")
        if isinstance(stored, (bytes, bytearray, memoryview)):
            stored_bytes = bytes(stored)
        elif isinstance(stored, str):
            stored_bytes = stored.encode("utf-8")
        else:
            current_app.logger.error("Unexpected password type for user %s: %s", username, type(stored))
            raise APIError()

        try:
            if not bcrypt.checkpw(password.encode("utf-8"), stored_bytes):
                raise BadRequest("Username or password is incorrect.")
        except ValueError as e:
            current_app.logger.error("Invalid password hash for user %s: %r", username, stored, exc_info=e)
            raise APIError()

        now = datetime.now(timezone.utc)
        # generate access token
        access_plain  = secrets.token_urlsafe(48)
        access_hash   = hashlib.sha256(access_plain.encode()).hexdigest()
        access_expiry = now + timedelta(days=1)
        update_records(
            table="session_tokens",
            data={"revoked": True},
            where_clause="userID = %s",
            where_params=(user["userID"],)
        )
        insert_record(
            "session_tokens",
            {
                "userID":        user["userID"],
                "session_token": access_hash,
                "expires_at":    access_expiry,
                "revoked":       False,
                "ip_address":    None
            }
        )
        # generate refresh token
        refresh_plain  = secrets.token_urlsafe(64)
        refresh_hash   = hashlib.sha256(refresh_plain.encode()).hexdigest()
        refresh_expiry = now + timedelta(days=60)
        insert_record(
            "refresh_tokens",
            {
                "userID": user["userID"],
                "token":   refresh_hash,
                "expires_at": refresh_expiry,
                "revoked": False
            }
        )

    except APIError:
        raise
    except Exception as e:
        current_app.logger.error("Error during login", exc_info=e)
        raise APIError()

    return {
        "message": "Login successful",
        "access_token":  access_plain,
        "refresh_token": refresh_plain
    }

def _to_aware_utc(dt):
    # Accept datetime or string from DB and return tz-aware UTC datetime
    if isinstance(dt, str):
        # Try ISO first; fall back to common format without tz
        try:
            parsed = datetime.fromisoformat(dt)
        except ValueError:
            parsed = datetime.strptime(dt, "%Y-%m-%d %H:%M:%S")
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    elif isinstance(dt, datetime):
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    else:
        return None

def refresh_token(data: dict) -> dict:
    """
    Rotates a valid refresh token and issues new tokens.
    """
    refresh_plain = data.get("refresh_token")
    if not refresh_plain:
        raise BadRequest("Refresh token required.")

    try:
        now = datetime.now(timezone.utc)  # aware
        refresh_hash = hashlib.sha256(refresh_plain.encode()).hexdigest()
        rows = fetch_records(
            table="refresh_tokens",
            where_clause="token = %s",
            params=(refresh_hash,),
            fetch_all=True
        )
        if not rows:
            raise Unauthorized("Invalid refresh token.")
        row = rows[0]

        expires_at = _to_aware_utc(row["expires_at"])  # ← normalize
        if expires_at is None:
            current_app.logger.error("expires_at is None or invalid for row id=%s", row.get("id"))
            raise Unauthorized("Refresh token expired or revoked.")

        if row["revoked"] or expires_at < now:         # ← safe compare
            raise Unauthorized("Refresh token expired or revoked.")

        userID = row["userID"]

        # Revoke old refresh token
        update_records(
            table="refresh_tokens",
            data={"revoked": True},
            where_clause="id = %s",
            where_params=(row["id"],)
        )

        # Issue new refresh token (aware UTC expiry)
        new_refresh_plain = secrets.token_urlsafe(64)
        new_refresh_hash  = hashlib.sha256(new_refresh_plain.encode()).hexdigest()
        insert_record(
            "refresh_tokens",
            {
                "userID":    userID,
                "token":      new_refresh_hash,
                "expires_at": now + timedelta(days=30),
                "revoked":    False
            }
        )

        # Issue new access token (aware UTC expiry)
        new_access_plain = secrets.token_urlsafe(48)
        new_access_hash  = hashlib.sha256(new_access_plain.encode()).hexdigest()
        insert_record(
            "session_tokens",
            {
                "userID":        userID,            # see note (2) below
                "session_token": new_access_hash,
                "expires_at":    now + timedelta(days=1),
                "revoked":       False,
                "ip_address":    None
            }
        )

    except APIError:
        raise
    except Exception as e:
        current_app.logger.error("Error during token refresh", exc_info=e)
        raise APIError()

    return {
        "ok": True,                       # ← add this for the frontend
        "message": "Token refreshed",
        "access_token":  new_access_plain,
        "refresh_token": new_refresh_plain
    }

def reset_password_request(data: dict) -> dict:
    """
    Generates a reset token and emails a reset link.
    """
    username = (data.get("username") or "").strip()
    if not username:
        raise BadRequest("Username is required.")

    try:
        users = fetch_records(
            table="users",
            where_clause="LOWER(username) = LOWER(%s)",
            params=(username,),
            fetch_all=True
        )
        if not users:
            raise NotFound("User not found.")
        user = users[0]
        userID = user["userID"]
        reset_plain = secrets.token_urlsafe(32)
        hashed_tok = hashlib.sha256(reset_plain.encode()).hexdigest()
        expiry     = datetime.now(timezone.utc) + timedelta(hours=1)
        insert_record(
            "pass_reset_tokens",
            {
                "userID":      userID,
                "reset_token": hashed_tok,
                "expires_at":  expiry,
                "revoked":     False
            }
        )
    except APIError:
        raise
    except Exception as e:
        current_app.logger.error("Error during password-reset request", exc_info=e)
        raise APIError()

    if not send_password_reset_email(user["username"], reset_plain, user["email"]):
        raise APIError("Failed to send password reset email.")

    return {"message": "Password reset email sent!"}


def reset_password(data: dict) -> dict:
    """
    Applies new password, revoking the reset token.
    """
    token    = data.get("token")
    username = data.get("username")
    new_pass = data.get("password")
    confirm  = data.get("confirm_password")

    if not (username and token):
        raise BadRequest("Username and token are required.")
    if new_pass is None or confirm is None:
        raise BadRequest("New password and confirmation are required.")
    if new_pass != confirm:
        raise BadRequest("Passwords do not match.")
    if (
        len(new_pass) < 8 or
        not any(ch.isupper() for ch in new_pass) or
        not any(ch.islower() for ch in new_pass) or
        not any(ch.isdigit() for ch in new_pass) or
        not any(ch in string.punctuation for ch in new_pass)
    ):
        raise BadRequest("Password must be ≥8 chars, include upper, lower, digit & special.")

    try:
        hashed_token = hashlib.sha256(token.encode()).hexdigest()
        # verify reset token
        row = fetch_records(
            table="pass_reset_tokens",
            where_clause="reset_token = %s AND revoked = FALSE AND expires_at > %s",
            params=(hashed_token, datetime.now(timezone.utc)),
            order_by="created_at DESC",
            limit=1,
            fetch_all=False
        )
        if not row:
            raise BadRequest("Invalid or expired reset link.")
        # verify user match
        users = fetch_records(
            table="users",
            where_clause="userID = %s AND LOWER(username) = LOWER(%s)",
            params=(row["userID"], username),
            fetch_all=True
        )
        if not users:
            raise BadRequest("Username does not match.")

        # update password & revoke token (store as utf-8 string)
        new_hashed = bcrypt.hashpw(new_pass.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        update_records(
            table="users",
            data={"password": new_hashed},
            where_clause="userID = %s",
            where_params=(row["userID"],)
        )
        update_records(
            table="pass_reset_tokens",
            data={"revoked": True},
            where_clause="tokenID = %s",
            where_params=(row["tokenID"],)
        )
    except APIError:
        raise
    except Exception as e:
        current_app.logger.error("Error during password reset", exc_info=e)
        raise APIError()

    return {"message": "Password reset successfully"}


def profile(data: dict) -> dict:
    """
    Returns user profile for valid session token.
    """
    token = (data.get("session_token") or "").strip()
    if not token:
        raise BadRequest("Session token is required.")

    username = authenticate_token(token)
    if not username:
        raise Unauthorized("Invalid or expired session token.")

    try:
        user = fetch_records(
            table="users",
            where_clause="username = %s",
            params=(username,),
            fetch_all=False
        )
        if not user:
            raise NotFound("User not found.")
    except APIError:
        raise
    except Exception as e:
        current_app.logger.error("Error fetching profile", exc_info=e)
        raise APIError()

    return {"username": user["username"], "email": user.get("email", "")}  


def submit_profile(data: dict) -> dict:
    """
    Updates or disables/deletes user profile.
    """
    token      = (data.get("session_token") or "").strip()
    new_u      = (data.get("username") or "").strip()
    new_e      = (data.get("email") or "").strip()
    disable    = bool(data.get("disable"))
    delete_acc = bool(data.get("delete"))

    if not token:
        raise BadRequest("Session token is required.")

    username = authenticate_token(token)
    if not username:
        raise Unauthorized("Invalid or expired session token.")

    try:
        user = fetch_records(
            table="users",
            where_clause="username = %s",
            params=(username,),
            fetch_all=False
        )
        if not user:
            raise NotFound("User not found.")
        userID   = user["userID"]
        old_email = user.get("email", "")

        # handle delete
        if delete_acc:
            # 1) Scrub all messages by this user
            update_records(
                table="messages",
                data={"message": "[deleted]"},
                where_clause="userID = %s",
                where_params=(userID,),
            )

            # 2) Revoke all session + refresh tokens
            update_records(
                table="session_tokens",
                data={"revoked": True},
                where_clause="userID = %s",
                where_params=(userID,),
            )
            update_records(
                table="refresh_tokens",
                data={"revoked": True},
                where_clause="userID = %s",
                where_params=(userID,),
            )

            # revoke any other tokens
            update_records(
                table="email_tokens",
                data={"revoked": True},
                where_clause="userID = %s",
                where_params=(userID,),
            )
            update_records(
                table="pass_reset_tokens",
                data={"revoked": True},
                where_clause="userID = %s",
                where_params=(userID,),
            )

            # 3) Anonymise & flag the user
            anon_username = f"deleted_{userID}"

            update_records(
                table="users",
                data={
                    "username":       anon_username,
                    "password":       "0",
                    "email":          "deleted@deleted.deleted",
                    "email_verified": False,
                    "disabled":       True,
                    "deleted":        True,
                },
                where_clause="userID = %s",
                where_params=(userID,),
            )

            return {"disable": False, "delete": True, "message": "Account deleted."}

        # handle disable
        if disable:
            # Flag as disabled
            update_records(
                table="users",
                data={"disabled": True},
                where_clause="userID = %s",
                where_params=(userID,),
            )

            # Revoke all session + refresh tokens
            update_records(
                table="session_tokens",
                data={"revoked": True},
                where_clause="userID = %s",
                where_params=(userID,),
            )
            update_records(
                table="refresh_tokens",
                data={"revoked": True},
                where_clause="userID = %s",
                where_params=(userID,),
            )

            return {"disable": True, "delete": False, "message": "Account disabled."}

        # handle update
        update_data = {}
        if new_u and new_u != username:
            update_data["username"] = new_u
        if new_e and new_e != old_email:
            update_data["email"] = new_e
            update_data["email_verified"] = False

        if update_data:
            update_records(
                table="users",
                data=update_data,
                where_clause="userID = %s",
                where_params=(userID,)
            )
            if "email" in update_data:
                code = f"{random.randint(100000, 999999):06d}"
                expiry = datetime.now(timezone.utc) + timedelta(minutes=5)
                insert_record(
                    "email_tokens",
                    {"userID": userID, "email_token": code, "expires_at": expiry, "revoked": False}
                )
                send_email_change_verification(new_u or username, code, new_e)
            resp = {"username": update_data.get("username", username),
                    "email": update_data.get("email", old_email),
                    "verificationSent": "email" in update_data}
            return {**resp, "message": "Profile updated."}

        raise BadRequest("No changes requested.")

    except APIError:
        raise
    except Exception as e:
        current_app.logger.error("Error in submit-profile", exc_info=e)
        raise APIError()


def change_password(data: dict) -> dict:
    """
    Changes the user's password.
    """
    token        = (data.get("session_token") or "").strip()
    old_password = (data.get("current_password") or "").strip()
    new_password = (data.get("new_password") or "").strip()

    if not token:
        raise BadRequest("Session token is required.")
    if not old_password:
        raise BadRequest("Old password is required.")
    if not new_password:
        raise BadRequest("New password is required.")
    if new_password == old_password:
        raise BadRequest("New password cannot be the same as old password.")

    username = authenticate_token(token)
    if not username:
        raise Unauthorized("Invalid or expired session token.")

    try:
        user = fetch_records(
            table="users",
            where_clause="username = %s",
            params=(username,),
            fetch_all=False
        )
        if not user:
            raise NotFound("User not found.")
        # Normalize stored password to bytes for bcrypt
        stored = user.get("password")
        if isinstance(stored, (bytes, bytearray, memoryview)):
            stored_bytes = bytes(stored)
        elif isinstance(stored, str):
            stored_bytes = stored.encode("utf-8")
        else:
            current_app.logger.error("Unexpected password type for user %s: %s", username, type(stored))
            raise APIError()

        try:
            if not bcrypt.checkpw(old_password.encode("utf-8"), stored_bytes):
                raise Forbidden("Incorrect current password.")
        except ValueError as e:
            current_app.logger.error("Invalid password hash for user %s during change_password: %r", username, stored, exc_info=e)
            raise APIError()
        if (
            len(new_password) < 8 or
            not any(ch.isupper() for ch in new_password) or
            not any(ch.islower() for ch in new_password) or
            not any(ch.isdigit() for ch in new_password) or
            not any(ch in string.punctuation for ch in new_password)
        ):
            raise BadRequest("Password must be ≥8 chars, include upper, lower, digit & special.")

        hashed = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        update_records(
            table="users",
            data={"password": hashed},
            where_clause="userID = %s",
            where_params=(user["userID"],)
        )
        update_records(
            table="session_tokens",
            data={"revoked": True},
            where_clause="userID = %s",
            where_params=(user["userID"],)
        )
        update_records(
            table="refresh_tokens",
            data={"revoked": True},
            where_clause="userID = %s",
            where_params=(user["userID"],)
        )

    except APIError:
        raise
    except Exception as e:
        current_app.logger.error("Error changing password", exc_info=e)
        raise APIError()

    return {"message": "Password changed successfully."}

def logout(data: dict) -> dict:
    """
    Revokes all tokens for the user.
    """
    session_token = (data.get("session_token") or "").strip()
    refresh_token = (data.get("refresh_token") or "").strip()
    if not session_token: raise BadRequest("Session token is required.")
    if not refresh_token: raise BadRequest("Refresh token is required.")
    session_hash = hashlib.sha256(session_token.encode()).hexdigest()
    refresh_hash = hashlib.sha256(refresh_token.encode()).hexdigest()

    username = authenticate_token(session_token)
    if not username:
        raise Unauthorized("Invalid or expired session token.")

    try:
        user = fetch_records(
            table="users",
            where_clause="username = %s",
            params=(username,),
            fetch_all=False
        )
        if not user:
            raise NotFound("User not found.")
        userID = user["userID"]

        update_records(
            table="session_tokens",
            data={"revoked": True},
            where_clause="session_token = %s",
            where_params=(session_hash,)
        )
        update_records(
            table="refresh_tokens",
            data={"revoked": True},
            where_clause="token = %s AND userID = %s",
            where_params=(refresh_hash, userID)
        )

    except APIError:
        raise
    except Exception as e:
        current_app.logger.error("Error during logout", exc_info=e)
        raise APIError()

    return {"message": "Logged out successfully."}

def logout_all(data: dict) -> dict:
    """
    Revokes all tokens for the user across all sessions.
    """
    session_token = (data.get("session_token") or "").strip()
    if not session_token:
        raise BadRequest("Session token is required.")

    username = authenticate_token(session_token)
    if not username:
        raise Unauthorized("Invalid or expired session token.")

    try:
        user = fetch_records(
            table="users",
            where_clause="username = %s",
            params=(username,),
            fetch_all=False
        )
        if not user:
            raise NotFound("User not found.")
        userID = user["userID"]

        update_records(
            table="session_tokens",
            data={"revoked": True},
            where_clause="userID = %s",
            where_params=(userID,)
        )
        update_records(
            table="refresh_tokens",
            data={"revoked": True},
            where_clause="userID = %s",
            where_params=(userID,)
        )

    except APIError:
        raise
    except Exception as e:
        current_app.logger.error("Error during logout-all", exc_info=e)
        raise APIError()

    return {"message": "Logged out from all sessions successfully."}