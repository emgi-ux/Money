"""Email/password accounts with opaque bearer tokens."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from .db import connect

SESSION_DAYS = 30
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,24}$")

# scrypt parameters: ~16 MB memory, fast enough for interactive logins.
_N, _R, _P = 2**14, 8, 1


class AuthError(ValueError):
    pass


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${salt.hex()}${h.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, hash_hex = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    h = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=_N, r=_R, p=_P, dklen=32)
    return hmac.compare_digest(h.hex(), hash_hex)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# Simple in-memory brute-force guard: 10 failed logins per key per 15 minutes.
_failures: dict[str, deque] = defaultdict(deque)
_WINDOW, _MAX_FAILURES = 900, 10


def _check_rate(key: str) -> None:
    q = _failures[key]
    now = time.time()
    while q and now - q[0] > _WINDOW:
        q.popleft()
    if len(q) >= _MAX_FAILURES:
        raise AuthError("Too many attempts. Try again in a few minutes.")


def register(email: str, password: str, display_name: str) -> dict:
    email = email.strip().lower()
    display_name = display_name.strip()
    if not EMAIL_RE.match(email):
        raise AuthError("Enter a valid email address")
    if len(password) < 8:
        raise AuthError("Password must be at least 8 characters")
    if not NAME_RE.match(display_name):
        raise AuthError("Display name must be 3-24 letters, numbers, dots, dashes or underscores")
    with connect() as c:
        try:
            cur = c.execute(
                "INSERT INTO users (email, password_hash, display_name) VALUES (?, ?, ?)",
                (email, hash_password(password), display_name),
            )
        except sqlite3.IntegrityError as e:
            field = "email" if "email" in str(e) else "display name"
            raise AuthError(f"That {field} is already taken") from e
        user_id = cur.lastrowid
    return {"token": create_session(user_id), "user": get_user(user_id)}


def login(email: str, password: str, client: str = "") -> dict:
    key = f"{email.strip().lower()}|{client}"
    _check_rate(key)
    with connect() as c:
        row = c.execute("SELECT id, password_hash FROM users WHERE email = ? AND is_bot = 0",
                        (email.strip().lower(),)).fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        _failures[key].append(time.time())
        raise AuthError("Incorrect email or password")
    _failures.pop(key, None)
    return {"token": create_session(row["id"]), "user": get_user(row["id"])}


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    with connect() as c:
        c.execute("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                  (_token_hash(token), user_id, expires.isoformat()))
    return token


def logout(token: str) -> None:
    with connect() as c:
        c.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


def user_for_token(token: str | None) -> dict | None:
    if not token:
        return None
    with connect() as c:
        row = c.execute("SELECT user_id, expires_at FROM sessions WHERE token_hash = ?",
                        (_token_hash(token),)).fetchone()
        if not row:
            return None
        if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
            c.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))
            return None
    return get_user(row["user_id"])


PUBLIC_FIELDS = ("id", "display_name", "bio", "is_public", "is_bot", "created_at")
PRIVATE_FIELDS = PUBLIC_FIELDS + ("email", "plan", "plan_interval", "plan_status", "plan_renews_at")


def get_user(user_id: int, private: bool = True) -> dict | None:
    with connect() as c:
        row = c.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        return None
    fields = PRIVATE_FIELDS if private else PUBLIC_FIELDS
    out = {k: row[k] for k in fields}
    if private:
        out["is_pro"] = is_pro(dict(row))
    return out


def is_pro(user: dict) -> bool:
    return user.get("plan") == "pro" and user.get("plan_status") in ("active", "trialing")


def update_profile(user_id: int, display_name: str | None = None, bio: str | None = None,
                   is_public: bool | None = None) -> dict:
    sets, args = [], []
    if display_name is not None:
        if not NAME_RE.match(display_name.strip()):
            raise AuthError("Display name must be 3-24 letters, numbers, dots, dashes or underscores")
        sets.append("display_name = ?")
        args.append(display_name.strip())
    if bio is not None:
        sets.append("bio = ?")
        args.append(bio.strip()[:280])
    if is_public is not None:
        sets.append("is_public = ?")
        args.append(int(is_public))
    if sets:
        with connect() as c:
            try:
                c.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = ?", (*args, user_id))
            except sqlite3.IntegrityError as e:
                raise AuthError("That display name is already taken") from e
    return get_user(user_id)


# ------------------------------------------------------------ password reset
RESET_MINUTES = 60


def request_password_reset(email: str, base_url: str) -> None:
    """Email a single-use reset link. Silent for unknown emails (no account enumeration)."""
    from .mailer import send_email

    email = email.strip().lower()
    _check_rate(f"reset|{email}")
    _failures[f"reset|{email}"].append(time.time())  # counts toward the throttle either way
    with connect() as c:
        row = c.execute("SELECT id FROM users WHERE email = ? AND is_bot = 0", (email,)).fetchone()
        if not row:
            return
        token = secrets.token_urlsafe(32)
        expires = datetime.now(timezone.utc) + timedelta(minutes=RESET_MINUTES)
        c.execute("INSERT INTO password_resets (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                  (_token_hash(token), row["id"], expires.isoformat()))
    link = f"{base_url}/#/reset?token={token}"
    send_email(email, "Reset your Money password",
               f"Someone asked to reset the password for this account.\n\n"
               f"Reset it here (valid for {RESET_MINUTES} minutes):\n{link}\n\n"
               f"If this wasn't you, you can ignore this email.")


def reset_password(token: str, new_password: str) -> dict:
    """Consume a reset token, set the password, and sign out every other session."""
    if len(new_password) < 8:
        raise AuthError("Password must be at least 8 characters")
    with connect() as c:
        row = c.execute("SELECT * FROM password_resets WHERE token_hash = ?", (_token_hash(token),)).fetchone()
        if (not row or row["used"]
                or datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc)):
            raise AuthError("This reset link is invalid or has expired")
        c.execute("UPDATE password_resets SET used = 1 WHERE token_hash = ?", (row["token_hash"],))
        c.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(new_password), row["user_id"]))
        c.execute("DELETE FROM sessions WHERE user_id = ?", (row["user_id"],))
        user_id = row["user_id"]
    return {"token": create_session(user_id), "user": get_user(user_id)}


def check_password(user_id: int, password: str) -> bool:
    with connect() as c:
        row = c.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
    return bool(row) and verify_password(password, row["password_hash"])


def delete_user(user_id: int) -> None:
    """Permanently delete a user; trades, sessions and copy links cascade."""
    with connect() as c:
        c.execute("DELETE FROM users WHERE id = ?", (user_id,))
