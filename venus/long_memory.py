"""Long-term memory, stored per persona and user in SQLite."""

import sqlite3
from datetime import datetime, timezone

__all__ = [
    "init_memory",
    "add_memory",
    "list_memories",
    "delete_memory",
    "touch_memories",
    "MAX_CONTENT_LEN",
    "LIST_BOUND",
    "CATEGORIES",
]

# Content length limit (inclusive): a string of exactly this length is valid.
MAX_CONTENT_LEN = 1000

# list_memories returns at most this many of the most recent entries.
LIST_BOUND = 100

# Stable categories keep retrieval and future UI understandable without an
# LLM deciding the schema on every write.
CATEGORIES = ("fact", "preference", "relationship", "boundary", "event")

DEFAULT_IMPORTANCE = 3
MAX_IMPORTANCE = 5

_TABLE = "memories"

# Columns added after the original prototype. Existing databases are
# migrated in place; no data is rewritten or dropped.
_EXTRA_COLUMNS = {
    "category": "TEXT NOT NULL DEFAULT 'fact'",
    "importance": "INTEGER NOT NULL DEFAULT 3",
    "source": "TEXT NOT NULL DEFAULT 'explicit'",
    "created_at": "TEXT",
    "last_used_at": "TEXT",
    "use_count": "INTEGER NOT NULL DEFAULT 0",
    "active": "INTEGER NOT NULL DEFAULT 1",
}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ensure_columns(db: sqlite3.Connection) -> None:
    existing = {row[1] for row in db.execute(f"PRAGMA table_info({_TABLE})")}
    for name, declaration in _EXTRA_COLUMNS.items():
        if name not in existing:
            db.execute(f"ALTER TABLE {_TABLE} ADD COLUMN {name} {declaration}")
    # Legacy rows have no timestamp; backfill once so recency scoring is
    # deterministic instead of treating them as infinitely old.
    db.execute(
        f"UPDATE {_TABLE} SET created_at = ? WHERE created_at IS NULL",
        (_now(),),
    )


def init_memory(db: sqlite3.Connection) -> None:
    """Create or migrate the memory schema. Safe to call repeatedly."""
    db.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            persona TEXT NOT NULL,
            user_id TEXT NOT NULL,
            content TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'fact',
            importance INTEGER NOT NULL DEFAULT 3,
            source TEXT NOT NULL DEFAULT 'explicit',
            created_at TEXT,
            last_used_at TEXT,
            use_count INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    _ensure_columns(db)
    db.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{_TABLE}_scope "
        f"ON {_TABLE} (persona, user_id, id)"
    )
    db.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{_TABLE}_live "
        f"ON {_TABLE} (persona, user_id, active, id)"
    )


def add_memory(db: sqlite3.Connection, persona: str, user_id: str, content: str,
               *, category: str = "fact", importance: int = DEFAULT_IMPORTANCE,
               source: str = "explicit", created_at: str | None = None) -> int:
    """Validate and store one memory, returning its new integer id.

    Raises ValueError when content is blank (empty or whitespace-only),
    exceeds MAX_CONTENT_LEN, or when metadata is outside the allowed range.
    A rejected add leaves no record behind.
    """
    if not isinstance(content, str):
        raise ValueError("content must be a string")
    if content.strip() == "":
        raise ValueError("content must not be blank")
    if len(content) > MAX_CONTENT_LEN:
        raise ValueError(f"content exceeds MAX_CONTENT_LEN ({MAX_CONTENT_LEN})")
    if category not in CATEGORIES:
        raise ValueError("unknown memory category")
    if isinstance(importance, bool) or not isinstance(importance, int) or not (
        1 <= importance <= MAX_IMPORTANCE
    ):
        raise ValueError("importance must be an integer between 1 and 5")
    if not isinstance(source, str) or not source.strip() or len(source) > 32:
        raise ValueError("source must be a short non-blank string")

    cur = db.execute(
        f"INSERT INTO {_TABLE} "
        "(persona, user_id, content, category, importance, source, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (persona, user_id, content, category, importance, source,
         created_at or _now()),
    )
    return int(cur.lastrowid)


def list_memories(db: sqlite3.Connection, persona: str, user_id: str) -> list[tuple[int, str]]:
    """Return up to LIST_BOUND active (id, content) pairs, oldest first.

    The bound keeps the most recent entries and is applied per (persona,
    user_id), never globally.
    """
    cur = db.execute(
        f"SELECT id, content FROM {_TABLE} "
        f"WHERE persona = ? AND user_id = ? AND active = 1 "
        f"ORDER BY id DESC LIMIT ?",
        (persona, user_id, LIST_BOUND),
    )
    return [(int(mid), content) for mid, content in cur.fetchall()][::-1]


def touch_memories(db: sqlite3.Connection, persona: str, user_id: str,
                   memory_ids, *, now: str | None = None) -> int:
    """Record that these memories were retrieved for a reply.

    Only rows in the exact scope are updated. The write is committed so the
    frequency signal survives restarts.
    """
    ids = [int(mid) for mid in memory_ids]
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    with db:
        cur = db.execute(
            f"UPDATE {_TABLE} SET last_used_at = ?, use_count = use_count + 1 "
            f"WHERE persona = ? AND user_id = ? AND active = 1 AND id IN ({placeholders})",
            (now or _now(), persona, user_id, *ids),
        )
    return cur.rowcount


def delete_memory(db: sqlite3.Connection, persona: str, user_id: str, memory_id: int) -> bool:
    """Delete one memory by id, only if it belongs to this (persona, user_id).

    Returns True when a row was removed, False otherwise (unknown id, wrong
    owner/persona, or already deleted).
    """
    cur = db.execute(
        f"DELETE FROM {_TABLE} WHERE id = ? AND persona = ? AND user_id = ?",
        (memory_id, persona, user_id),
    )
    return cur.rowcount > 0
