"""Database-backed local accounts, sessions, invitations, and password resets."""

from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
import time
import uuid

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from paperpilot.database.connection import get_db
from paperpilot.security.identity import Identity


USERNAME_PATTERN = re.compile(r"^[a-z0-9_-]{3,32}$")
SESSION_ABSOLUTE_SECONDS = 7 * 24 * 3600
SESSION_IDLE_SECONDS = 12 * 3600
ONE_TIME_CODE_SECONDS = 24 * 3600


class LocalAuthError(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def normalize_username(value: object) -> str:
    if not isinstance(value, str):
        raise LocalAuthError("invalid_username")
    normalized = value.strip().lower()
    if not USERNAME_PATTERN.fullmatch(normalized):
        raise LocalAuthError("invalid_username")
    return normalized


def validate_password(value: object, *, temporary: bool = False) -> str:
    if not isinstance(value, str) or not 8 <= len(value) <= 128:
        raise LocalAuthError("invalid_password")
    return value


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class LocalAuthService:
    def __init__(self, *, now=time.time):
        self._now = now
        self._passwords = PasswordHasher(
            time_cost=3, memory_cost=65536, parallelism=2, hash_len=32, salt_len=16
        )

    @staticmethod
    def _public_user(row) -> dict:
        return {
            "id": row["id"],
            "username": row["username"],
            "role": row["role"],
            "status": row["status"],
            "must_change_password": bool(row["must_change_password"]),
        }

    def create_bootstrap_admin(self, username: str, password: str) -> dict:
        username_normalized = normalize_username(username)
        validate_password(password, temporary=True)
        now = int(self._now())
        database = get_db()
        try:
            database.execute(
                """INSERT INTO users
                   (id,username,username_normalized,password_hash,role,status,
                    must_change_password,created_at,updated_at)
                   VALUES (?,?,?,?,?,'active',1,?,?)""",
                (
                    str(uuid.uuid4()), username_normalized, username_normalized,
                    self._passwords.hash(password), "admin", now, now,
                ),
            )
            database.commit()
        except sqlite3.IntegrityError as exc:
            raise LocalAuthError("username_unavailable") from exc
        row = database.execute(
            "SELECT * FROM users WHERE username_normalized=?", (username_normalized,)
        ).fetchone()
        return self._public_user(row)

    def has_active_admin(self) -> bool:
        row = get_db().execute(
            "SELECT 1 FROM users WHERE role='admin' AND status='active' LIMIT 1"
        ).fetchone()
        return row is not None

    def first_active_admin(self) -> Identity | None:
        row = get_db().execute(
            """SELECT * FROM users WHERE role='admin' AND status='active'
               ORDER BY created_at,id LIMIT 1"""
        ).fetchone()
        if row is None:
            return None
        return Identity(row["id"], row["username"], row["role"], bool(row["must_change_password"]))

    def login(self, username: object, password: object) -> tuple[dict, str, str]:
        normalized = normalize_username(username)
        if not isinstance(password, str):
            raise LocalAuthError("invalid_credentials")
        database = get_db()
        row = database.execute(
            "SELECT * FROM users WHERE username_normalized=?", (normalized,)
        ).fetchone()
        if row is None or row["status"] != "active":
            raise LocalAuthError("invalid_credentials")
        try:
            self._passwords.verify(row["password_hash"], password)
        except (VerificationError, InvalidHashError):
            raise LocalAuthError("invalid_credentials") from None
        if self._passwords.check_needs_rehash(row["password_hash"]):
            database.execute(
                "UPDATE users SET password_hash=?,updated_at=? WHERE id=?",
                (self._passwords.hash(password), int(self._now()), row["id"]),
            )
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = int(self._now())
        database.execute(
            """INSERT INTO auth_sessions
               (token_hash,user_id,csrf_hash,created_at,last_seen_at,expires_at)
               VALUES (?,?,?,?,?,?)""",
            (_digest(token), row["id"], _digest(csrf), now, now, now + SESSION_ABSOLUTE_SECONDS),
        )
        database.commit()
        return self._public_user(row), token, csrf

    def authenticate(self, token: str | None) -> Identity | None:
        if not token:
            return None
        database = get_db()
        now = int(self._now())
        row = database.execute(
            """SELECT u.*,s.last_seen_at,s.expires_at,s.revoked_at
               FROM auth_sessions s JOIN users u ON u.id=s.user_id
               WHERE s.token_hash=?""",
            (_digest(token),),
        ).fetchone()
        if (
            row is None or row["status"] != "active" or row["revoked_at"] is not None
            or row["expires_at"] <= now or row["last_seen_at"] + SESSION_IDLE_SECONDS <= now
        ):
            return None
        database.execute(
            "UPDATE auth_sessions SET last_seen_at=? WHERE token_hash=?", (now, _digest(token))
        )
        database.commit()
        return Identity(
            row["id"], row["username"], row["role"], bool(row["must_change_password"])
        )

    def verify_csrf(self, token: str, csrf: str | None) -> bool:
        if not csrf:
            return False
        row = get_db().execute(
            "SELECT csrf_hash FROM auth_sessions WHERE token_hash=? AND revoked_at IS NULL",
            (_digest(token),),
        ).fetchone()
        return bool(row and secrets.compare_digest(row["csrf_hash"], _digest(csrf)))

    def logout(self, token: str | None) -> None:
        if token:
            database = get_db()
            database.execute(
                "UPDATE auth_sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL",
                (int(self._now()), _digest(token)),
            )
            database.commit()

    def change_password(
        self,
        user_id: str,
        current: object,
        replacement: object,
        *,
        current_session_token: str,
    ) -> tuple[str, str]:
        validate_password(replacement)
        if not isinstance(current, str):
            raise LocalAuthError("invalid_credentials")
        database = get_db()
        row = database.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        try:
            valid = row is not None and self._passwords.verify(row["password_hash"], current)
        except (VerificationError, InvalidHashError):
            valid = False
        if not valid:
            raise LocalAuthError("invalid_credentials")
        now = int(self._now())
        session = database.execute(
            """SELECT 1 FROM auth_sessions
               WHERE token_hash=? AND user_id=? AND revoked_at IS NULL""",
            (_digest(current_session_token), user_id),
        ).fetchone()
        if session is None:
            raise LocalAuthError("invalid_credentials")
        new_token = secrets.token_urlsafe(32)
        new_csrf = secrets.token_urlsafe(32)
        database.execute(
            """UPDATE users SET password_hash=?,must_change_password=0,
               password_changed_at=?,updated_at=? WHERE id=?""",
            (self._passwords.hash(replacement), now, now, user_id),
        )
        database.execute(
            "UPDATE auth_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
            (now, user_id),
        )
        database.execute(
            """INSERT INTO auth_sessions
               (token_hash,user_id,csrf_hash,created_at,last_seen_at,expires_at)
               VALUES (?,?,?,?,?,?)""",
            (
                _digest(new_token), user_id, _digest(new_csrf), now, now,
                now + SESSION_ABSOLUTE_SECONDS,
            ),
        )
        database.commit()
        return new_token, new_csrf

    def create_invite(self, admin_id: str) -> tuple[dict, str]:
        code = secrets.token_urlsafe(24)
        now = int(self._now())
        invite_id = str(uuid.uuid4())
        database = get_db()
        database.execute(
            """INSERT INTO invite_codes
               (id,token_hash,created_by,created_at,expires_at)
               VALUES (?,?,?,?,?)""",
            (invite_id, _digest(code), admin_id, now, now + ONE_TIME_CODE_SECONDS),
        )
        database.commit()
        return {"id": invite_id, "created_at": now, "expires_at": now + ONE_TIME_CODE_SECONDS}, code

    def list_invites(self) -> list[dict]:
        now = int(self._now())
        rows = get_db().execute(
            """SELECT id,created_at,expires_at,used_at,revoked_at
               FROM invite_codes ORDER BY created_at DESC"""
        ).fetchall()
        return [
            {
                **dict(row),
                "status": (
                    "used" if row["used_at"] else "revoked" if row["revoked_at"]
                    else "expired" if row["expires_at"] <= now else "active"
                ),
            }
            for row in rows
        ]

    def revoke_invite(self, invite_id: str) -> None:
        database = get_db()
        database.execute(
            "UPDATE invite_codes SET revoked_at=? WHERE id=? AND used_at IS NULL",
            (int(self._now()), invite_id),
        )
        database.commit()

    def list_users(self) -> list[dict]:
        rows = get_db().execute(
            "SELECT * FROM users ORDER BY created_at,username_normalized"
        ).fetchall()
        return [self._public_user(row) for row in rows]

    def update_user(self, actor_id: str, user_id: str, *, role=None, status=None) -> dict:
        if role not in {None, "admin", "user"} or status not in {None, "active", "disabled"}:
            raise LocalAuthError("invalid_user_update")
        database = get_db()
        target = database.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if target is None:
            raise LocalAuthError("user_not_found")
        next_role, next_status = role or target["role"], status or target["status"]
        removing_active_admin = (
            target["role"] == "admin" and target["status"] == "active"
            and (next_role != "admin" or next_status != "active")
        )
        if removing_active_admin:
            count = database.execute(
                "SELECT COUNT(*) FROM users WHERE role='admin' AND status='active'"
            ).fetchone()[0]
            if count <= 1:
                raise LocalAuthError("last_administrator_required")
        now = int(self._now())
        database.execute(
            "UPDATE users SET role=?,status=?,updated_at=? WHERE id=?",
            (next_role, next_status, now, user_id),
        )
        if next_status == "disabled" or next_role != target["role"]:
            database.execute(
                "UPDATE auth_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                (now, user_id),
            )
        database.commit()
        row = database.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return self._public_user(row)

    def create_password_reset(self, admin_id: str, user_id: str) -> tuple[dict, str]:
        database = get_db()
        if database.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone() is None:
            raise LocalAuthError("user_not_found")
        code, reset_id, now = secrets.token_urlsafe(24), str(uuid.uuid4()), int(self._now())
        database.execute(
            """INSERT INTO password_reset_codes
               (id,token_hash,user_id,created_by,created_at,expires_at)
               VALUES (?,?,?,?,?,?)""",
            (reset_id, _digest(code), user_id, admin_id, now, now + ONE_TIME_CODE_SECONDS),
        )
        database.commit()
        return {"id": reset_id, "expires_at": now + ONE_TIME_CODE_SECONDS}, code

    def offline_reset_password(self, username: str, temporary_password: str) -> None:
        """Reset a local account from the offline CLI and revoke every session."""
        normalized = normalize_username(username)
        validate_password(temporary_password, temporary=True)
        database = get_db()
        row = database.execute(
            "SELECT id FROM users WHERE username_normalized=?", (normalized,)
        ).fetchone()
        if row is None:
            raise LocalAuthError("user_not_found")
        now = int(self._now())
        database.execute(
            """UPDATE users SET password_hash=?,must_change_password=1,
               updated_at=? WHERE id=?""",
            (self._passwords.hash(temporary_password), now, row["id"]),
        )
        database.execute(
            "UPDATE auth_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
            (now, row["id"]),
        )
        database.commit()

    def reset_password(self, code: object, replacement: object) -> None:
        validate_password(replacement)
        if not isinstance(code, str) or not code:
            raise LocalAuthError("invalid_reset_code")
        database = get_db()
        now = int(self._now())
        row = database.execute(
            "SELECT * FROM password_reset_codes WHERE token_hash=?", (_digest(code),)
        ).fetchone()
        if (
            row is None or row["used_at"] is not None or row["revoked_at"] is not None
            or row["expires_at"] <= now
        ):
            raise LocalAuthError("invalid_reset_code")
        database.execute("BEGIN IMMEDIATE")
        database.execute(
            """UPDATE users SET password_hash=?,must_change_password=0,
               password_changed_at=?,updated_at=? WHERE id=?""",
            (self._passwords.hash(replacement), now, now, row["user_id"]),
        )
        changed = database.execute(
            "UPDATE password_reset_codes SET used_at=? WHERE id=? AND used_at IS NULL",
            (now, row["id"]),
        ).rowcount
        if changed != 1:
            database.rollback()
            raise LocalAuthError("invalid_reset_code")
        database.execute(
            "UPDATE auth_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
            (now, row["user_id"]),
        )
        database.commit()

    def register(self, username: object, password: object, invite_code: object) -> dict:
        normalized = normalize_username(username)
        validate_password(password)
        if not isinstance(invite_code, str) or not invite_code:
            raise LocalAuthError("invalid_invite")
        now = int(self._now())
        database = get_db()
        invite = database.execute(
            "SELECT * FROM invite_codes WHERE token_hash=?", (_digest(invite_code),)
        ).fetchone()
        if (
            invite is None or invite["used_at"] is not None or invite["revoked_at"] is not None
            or invite["expires_at"] <= now
        ):
            raise LocalAuthError("invalid_invite")
        user_id = str(uuid.uuid4())
        try:
            database.execute("BEGIN IMMEDIATE")
            database.execute(
                """INSERT INTO users
                   (id,username,username_normalized,password_hash,role,status,
                    must_change_password,created_at,updated_at)
                   VALUES (?,?,?,?, 'user','active',0,?,?)""",
                (user_id, normalized, normalized, self._passwords.hash(password), now, now),
            )
            changed = database.execute(
                """UPDATE invite_codes SET used_at=?,used_by=? WHERE id=?
                   AND used_at IS NULL AND revoked_at IS NULL AND expires_at>?""",
                (now, user_id, invite["id"], now),
            ).rowcount
            if changed != 1:
                raise LocalAuthError("invalid_invite")
            database.commit()
        except sqlite3.IntegrityError as exc:
            database.rollback()
            raise LocalAuthError("username_unavailable") from exc
        row = database.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return self._public_user(row)
