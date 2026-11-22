"""Pull explicit "I like ..." preferences out of new messages.

This is regex-based, not a model call. Anything ambiguous, negated,
third-party or too long is skipped.
"""

import re

from venus import long_memory
from venus.privacy import detect

__all__ = [
    "extract_candidates",
    "remember_candidates",
    "MAX_TEXT_LEN",
    "set_auto_enabled",
    "is_auto_enabled",
]

# Wholesale text rejection above this length.
MAX_TEXT_LEN = 200

# Terms that mark the text as touching credentials, finance, or health.
_SENSITIVE_TERMS = (
    "密码",
    "验证码",
    "银行",
    "账号",
    "卡号",
    "医院",
    "诊所",
    "确诊",
    "病史",
    "手术",
)

# Phone-number-like or card-number-like digit runs.
_DIGIT_RUN = re.compile(r"\d{7,}")

# Third-party preference statements.
_THIRD_PARTY = re.compile(r"[他她它您你]喜欢")

# Negated preference statements, including hedged forms (并不是很喜欢).
_NEGATED = re.compile(r"不[^，。！？、；\s]{0,3}喜欢")

# The explicit first-person statement itself; stops at any boundary
# punctuation or whitespace so the candidate is the clause, not the line.
_STATEMENT = re.compile(r"我喜欢[^，。！？、；,.!?;:：\s]+")


def extract_candidates(text):
    """Return explicit first-person preference statements found in text.

    Returns [] when the text is not a string, exceeds MAX_TEXT_LEN, contains
    sensitive terms or long digit runs, or contains third-party or negated
    preference language. Otherwise returns the 我喜欢... clauses in order of
    appearance, trailing punctuation excluded, with exact duplicates removed.
    """
    if not isinstance(text, str) or len(text) > MAX_TEXT_LEN:
        return []
    if _DIGIT_RUN.search(text):
        return []
    if any(term in text for term in _SENSITIVE_TERMS):
        return []
    if _THIRD_PARTY.search(text):
        return []
    if _NEGATED.search(text):
        return []
    return list(dict.fromkeys(m.group(0) for m in _STATEMENT.finditer(text)))


def remember_candidates(db, persona, user_id, text):
    """Extract candidates from text and store the unseen ones via long_memory.

    Returns the new row ids in candidate order. Candidates equal to content
    already stored for this exact (persona, user_id) scope are suppressed;
    other scopes are untouched.
    """
    if detect(text):
        return []
    candidates = extract_candidates(text)
    if not candidates:
        return []

    cur = db.execute(
        "SELECT content FROM memories WHERE persona = ? AND user_id = ?",
        (persona, user_id),
    )
    existing = {content for content, in cur.fetchall()}

    ids = []
    for candidate in candidates:
        if candidate in existing:
            continue
        ids.append(long_memory.add_memory(
            db, persona, user_id, candidate,
            category="preference", importance=3, source="auto",
        ))
        existing.add(candidate)
    return ids


# Separate scope-owned table for the auto-memory consent flag. Kept distinct
# from long_memory.memories so consent state is independent of stored memories.
_CONSENT_TABLE = "auto_consent"


def _init_consent(db):
    """Create the consent schema on first use. Safe to call repeatedly."""
    db.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_CONSENT_TABLE} (
            persona TEXT NOT NULL,
            user_id TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (persona, user_id)
        )
        """
    )


def set_auto_enabled(db, persona, user_id, enabled):
    """Persist the auto-memory consent flag for this (persona, user_id).

    The flag is stored as 1/0 and the mutation is committed. A row is
    inserted on first set and updated thereafter; other scopes are untouched.
    The schema is created lazily on first use.
    """
    _init_consent(db)
    value = 1 if enabled else 0
    cur = db.execute(
        f"SELECT 1 FROM {_CONSENT_TABLE} WHERE persona = ? AND user_id = ?",
        (persona, user_id),
    )
    if cur.fetchone() is None:
        db.execute(
            f"INSERT INTO {_CONSENT_TABLE} (persona, user_id, enabled) "
            f"VALUES (?, ?, ?)",
            (persona, user_id, value),
        )
    else:
        db.execute(
            f"UPDATE {_CONSENT_TABLE} SET enabled = ? "
            f"WHERE persona = ? AND user_id = ?",
            (value, persona, user_id),
        )
    db.commit()


def is_auto_enabled(db, persona, user_id):
    """Return the auto-memory consent flag for this (persona, user_id).

    Auto-memory is on by default: a missing row means enabled. An explicit
    ``/自动记忆 关闭`` stores 0 and is preserved on later reads. The schema is
    created lazily on first use.
    """
    _init_consent(db)
    cur = db.execute(
        f"SELECT enabled FROM {_CONSENT_TABLE} "
        f"WHERE persona = ? AND user_id = ?",
        (persona, user_id),
    )
    row = cur.fetchone()
    return True if row is None else bool(row[0])
