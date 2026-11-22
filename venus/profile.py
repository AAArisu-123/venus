"""Explicit, user-editable profile layered on top of long-term memory.

Venus already stores what happened in the conversation; this module stores
who the user wants the companion to be for them. The profile is deliberately
small and explicit: a preferred name, a communication style, and boundaries.
It is scoped by the same opaque ``(persona, user_id)`` pair as other storage,
and every statement is parameterized.

Nothing here reads the environment, credentials, or the network.
"""

import sqlite3
from datetime import datetime, timezone

__all__ = [
    "init_profile",
    "get_profile",
    "peek_profile",
    "set_field",
    "clear_profile",
    "describe_profile",
    "FIELD_LIMITS",
]

_TABLE = "user_profile"

FIELD_LIMITS = {
    "display_name": 40,
    "style": 500,
    "boundaries": 500,
}

_COLUMNS = ("display_name", "style", "boundaries")


def init_profile(db):
    """Create the profile schema if absent. Safe to call repeatedly."""
    db.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            persona TEXT NOT NULL,
            user_id TEXT NOT NULL,
            display_name TEXT NOT NULL DEFAULT '',
            style TEXT NOT NULL DEFAULT '',
            boundaries TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            PRIMARY KEY (persona, user_id)
        )
        """
    )


def _blank_profile():
    return {
        "display_name": "",
        "style": "",
        "boundaries": "",
        "updated_at": None,
    }


def peek_profile(db, persona, user_id):
    """Read a profile without creating schema; blank when the table is absent.

    Proactive composition is documented as read-only, so it uses this instead
    of :func:`get_profile`.
    """
    try:
        row = db.execute(
            f"SELECT display_name, style, boundaries, updated_at FROM {_TABLE} "
            "WHERE persona = ? AND user_id = ?",
            (persona, user_id),
        ).fetchone()
    except sqlite3.OperationalError:
        return _blank_profile()
    if row is None:
        return _blank_profile()
    return {
        "display_name": row[0],
        "style": row[1],
        "boundaries": row[2],
        "updated_at": row[3],
    }


def get_profile(db, persona, user_id):
    """Return the profile for this exact scope, or a blank profile."""
    init_profile(db)
    return peek_profile(db, persona, user_id)


def set_field(db, persona, user_id, field, value):
    """Set one profile field, creating the row on first use.

    Blank values clear the field. A value over the configured limit raises
    ``ValueError`` before anything is written. The change is committed.
    """
    if field not in FIELD_LIMITS:
        raise ValueError("unknown profile field")
    if not isinstance(value, str):
        raise ValueError("profile value must be a string")
    cleaned = value.strip()
    if len(cleaned) > FIELD_LIMITS[field]:
        raise ValueError(f"profile field {field} is too long")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    init_profile(db)
    # ``field`` is chosen from FIELD_LIMITS above, never from raw input.
    with db:
        db.execute(
            f"INSERT INTO {_TABLE} (persona, user_id, {field}, updated_at) "
            "VALUES (?, ?, ?, ?) "
            f"ON CONFLICT(persona, user_id) DO UPDATE SET "
            f"{field} = excluded.{field}, updated_at = excluded.updated_at",
            (persona, user_id, cleaned, now),
        )


def clear_profile(db, persona, user_id):
    """Remove every profile field for this scope. Returns the deleted rows."""
    init_profile(db)
    with db:
        cur = db.execute(
            f"DELETE FROM {_TABLE} WHERE persona = ? AND user_id = ?",
            (persona, user_id),
        )
    return cur.rowcount


def describe_profile(profile):
    """Render a profile as compact context, or ``''`` when it is empty.

    The result is data for the model, not an instruction. Callers wrap it in
    a system message that says so.
    """
    lines = []
    if profile.get("display_name"):
        lines.append(f"对方希望你称呼其为「{_flat(profile['display_name'])}」。")
    if profile.get("style"):
        lines.append(f"对方的交流偏好：{_flat(profile['style'])}")
    if profile.get("boundaries"):
        lines.append(f"对方希望避开的边界：{_flat(profile['boundaries'])}")
    return "\n".join(lines)


def _flat(value):
    """Collapse whitespace so a profile field cannot smuggle a new layer."""
    return " ".join(str(value).split())
