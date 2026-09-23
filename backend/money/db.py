"""SQLite persistence for users, sessions, subscriptions and paper trading.

SQLite keeps deployment to a single file; the schema is plain SQL so moving
to Postgres later is mechanical.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    bio TEXT NOT NULL DEFAULT '',
    is_public INTEGER NOT NULL DEFAULT 0,
    is_bot INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    -- subscription
    plan TEXT NOT NULL DEFAULT 'free',
    plan_interval TEXT,
    plan_status TEXT,
    plan_renews_at TEXT,
    stripe_customer_id TEXT UNIQUE,
    stripe_subscription_id TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_accounts (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    starting_cash REAL NOT NULL,
    cash REAL NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    qty REAL NOT NULL CHECK (qty > 0),
    price REAL NOT NULL CHECK (price > 0),
    ts TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    leader_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    leader_trade_id INTEGER
);
CREATE INDEX IF NOT EXISTS trades_user ON trades(user_id, ts);

CREATE TABLE IF NOT EXISTS copies (
    follower_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    leader_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    allocation REAL NOT NULL CHECK (allocation > 0),
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (follower_id, leader_id)
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS password_resets (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS stripe_events (
    id TEXT PRIMARY KEY,
    received_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_lock = threading.RLock()
_initialized: set[str] = set()


def db_path() -> Path:
    default = Path.home() / ".local" / "share" / "money" / "money.db"
    return Path(os.environ.get("MONEY_DB", default))


@contextmanager
def connect():
    """Connection with foreign keys on; commits on success, rolls back on error.

    Writes are serialised with a process-wide lock, which keeps multi-statement
    operations (an order and its copy-trades) atomic under SQLite.
    """
    path = db_path()
    with _lock:
        if str(path) not in _initialized:
            path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(path) as c:
                c.executescript(SCHEMA)
            _initialized.add(str(path))
        conn = sqlite3.connect(path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
