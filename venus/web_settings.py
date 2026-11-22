"""Durable, per-(persona, user) opt-in for public/web search in Venus.

The consent flag lives in a scope-owned SQLite table inside the caller's
connection. Like auto-memory consent, web access is *off by default*: an
identity with no stored row is never considered opted in. Persona and user
identifiers are opaque caller-supplied strings; every statement is
parameterized, so hostile input is treated strictly as data, never executed.
This module never reads credentials, environment variables or the production
``data`` directory, and it makes no network calls.
"""

__all__ = ["init_web_settings", "set_enabled", "is_enabled"]

_TABLE = "web_settings"


def init_web_settings(db):
    """Create the consent schema on first use. Safe to call repeatedly."""
    db.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            persona TEXT NOT NULL,
            user_id TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (persona, user_id)
        )
        """
    )


def set_enabled(db, persona, user_id, enabled):
    """Persist the web-search consent flag for this (persona, user_id).

    The flag is stored as 1/0 and the mutation is committed before returning.
    A row is inserted on first set and updated thereafter; all reads and
    writes are restricted to the exact scope, so other personas/users are
    untouched. The schema is created lazily on first use.
    """
    init_web_settings(db)
    value = 1 if enabled else 0
    db.execute(
        f"INSERT INTO {_TABLE} (persona, user_id, enabled) VALUES (?, ?, ?) "
        "ON CONFLICT(persona, user_id) DO UPDATE SET enabled = excluded.enabled",
        (persona, user_id, value),
    )
    db.commit()


def is_enabled(db, persona, user_id):
    """Return the web-search consent flag for this (persona, user_id).

    Returns False when no flag has been stored for the scope (default off).
    The schema is created lazily on first use.
    """
    init_web_settings(db)
    cur = db.execute(
        f"SELECT enabled FROM {_TABLE} WHERE persona = ? AND user_id = ?",
        (persona, user_id),
    )
    row = cur.fetchone()
    return bool(row[0]) if row is not None else False
