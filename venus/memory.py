"""Independent conversation-memory storage for Venus.

Uses a local SQLite database. Persona and user identifiers are opaque
strings supplied by the caller; this module never reads credentials or
environment variables.
"""

import sqlite3
from pathlib import Path

from .long_memory import init_memory


def connect_database(path):
    """Open (or create) a conversation database and return the connection.

    Creates the parent directories, the ``messages`` table and an index for
    persona/user history lookups. Calling this again on an existing database
    is harmless. The schema is committed before returning.
    """
    db_path = Path(path).expanduser()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(db_path), timeout=10)
    from venus.proactive import init_proactive
    init_proactive(db)
    with db:
        init_memory(db)
        db.execute(
            'CREATE TABLE IF NOT EXISTS messages ('
            'id INTEGER PRIMARY KEY, '
            'persona TEXT NOT NULL, '
            'user_id TEXT NOT NULL, '
            'role TEXT NOT NULL, '
            'content TEXT NOT NULL)'
        )
        db.execute(
            'CREATE INDEX IF NOT EXISTS idx_history '
            'ON messages(persona, user_id, id)'
        )
    return db


def history(db, persona, user_id, limit=20):
    """Return the most recent ``limit`` turns as ``(role, content)`` tuples.

    Only rows matching both ``persona`` and ``user_id`` are considered. The
    result is ordered oldest to newest, ready to be passed to a model as
    conversation context. Nonpositive limits return an empty list.
    """
    if limit <= 0:
        return []
    rows = db.execute(
        'SELECT role, content FROM ('
        'SELECT id, role, content FROM messages '
        'WHERE persona = ? AND user_id = ? '
        'ORDER BY id DESC LIMIT ?'
        ') ORDER BY id',
        (persona, user_id, limit),
    ).fetchall()
    return rows


def save_turn(db, persona, user_id, user_text, assistant_text):
    """Save one user message and its assistant reply atomically.

    Both rows share the same persona and user identifier. If either insert
    fails, the whole turn is rolled back.
    """
    with db:
        db.executemany(
            'INSERT INTO messages(persona, user_id, role, content) '
            'VALUES (?, ?, ?, ?)',
            (
                (persona, user_id, 'user', user_text),
                (persona, user_id, 'assistant', assistant_text),
            ),
        )
