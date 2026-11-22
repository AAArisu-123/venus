"""Read-only recall over long-term memories.

Candidates are matched lexically, then ranked by relevance, importance,
recency and past use.
"""

import math
import re
from datetime import datetime, timezone

__all__ = ["recall"]

_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_WORD = re.compile(r"[a-z0-9]+")
_RECENCY_DAYS = 30.0


def _recency_score(value, now):
    if not isinstance(value, str):
        return 0.0
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return 0.0
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    age_days = (now - timestamp.astimezone(timezone.utc)).total_seconds() / 86400
    if age_days < 0:
        age_days = 0
    return math.exp(-age_days / _RECENCY_DAYS)


def _query_tokens(query):
    tokens = set()
    for run in _CJK_RUN.findall(query):
        for i in range(len(run) - 1):
            tokens.add(run[i : i + 2])
    tokens.update(_WORD.findall(query.lower()))
    return tokens


def recall(db, persona, user_id, query, limit=5):
    """Return up to ``limit`` (id, content) memories matching ``query``.

    A memory must share at least one query token to be eligible. Eligible
    memories are ranked by lexical matches first (weight 3), then stored
    importance, recency and usage as small tie-breakers. Ties fall back to
    the newest id. A blank query, a query with no matching tokens, or a
    nonpositive limit yields an empty list.
    """
    if limit <= 0:
        return []
    tokens = _query_tokens(query)
    if not tokens:
        return []
    rows = db.execute(
        "SELECT id, content, importance, created_at, last_used_at, use_count "
        "FROM memories WHERE persona = ? AND user_id = ? AND active = 1",
        (persona, user_id),
    ).fetchall()
    now = datetime.now(timezone.utc)
    scored = []
    for memory_id, content, importance, created_at, last_used_at, use_count in rows:
        lowered = content.lower()
        matches = sum(1 for token in tokens if token in lowered)
        if not matches:
            continue
        try:
            importance_score = max(1, min(5, int(importance))) / 5
        except (TypeError, ValueError):
            importance_score = 3 / 5
        recency = _recency_score(last_used_at or created_at, now)
        try:
            usage = min(max(int(use_count), 0), 5) / 5
        except (TypeError, ValueError):
            usage = 0.0
        score = matches * 3.0 + importance_score + recency + usage
        scored.append((-score, -int(memory_id), int(memory_id), content))
    scored.sort()
    return [(memory_id, content) for _, _, memory_id, content in scored[:limit]]
