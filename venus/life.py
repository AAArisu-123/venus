"""Small "what I've been up to" notes used by proactive openers."""

_MAX_CONTENT = 200
_MAX_SUMMARY_CHARS = 400
# A note about last week's dinner is no longer "what she is up to"; stale rows
# stay on disk for the record but never reach the prompt.
_MAX_AGE_DAYS = 7


def init_life(db):
    """Create the life-note table if absent. Safe to call repeatedly."""
    with db:
        db.execute(
            'CREATE TABLE IF NOT EXISTS life_log ('
            'id INTEGER PRIMARY KEY AUTOINCREMENT, '
            'persona TEXT NOT NULL, '
            'user_id TEXT NOT NULL, '
            'local_day TEXT NOT NULL, '
            'content TEXT NOT NULL)'
        )
        db.execute(
            'CREATE INDEX IF NOT EXISTS idx_life_scope '
            'ON life_log(persona, user_id, id)'
        )


def add_life(db, persona, user_id, local_day, content):
    """Store one life note, skipping blanks and immediate duplicates.

    Returns ``True`` when a row was written. Content is clipped so a runaway
    model answer cannot grow the database without bound.
    """
    if not isinstance(content, str) or not content.strip():
        return False
    text = ' '.join(content.split())[:_MAX_CONTENT]
    last = db.execute(
        'SELECT content FROM life_log WHERE persona = ? AND user_id = ? '
        'ORDER BY id DESC LIMIT 1',
        (persona, user_id),
    ).fetchone()
    if last is not None and last[0] == text:
        return False
    with db:
        db.execute(
            'INSERT INTO life_log (persona, user_id, local_day, content) '
            'VALUES (?, ?, ?, ?)',
            (persona, user_id, str(local_day), text),
        )
    return True


def recent_life(db, persona, user_id, limit=3):
    """Return up to ``limit`` recent life notes as ``(local_day, content)``.

    Newest first, scoped to this identity only.
    """
    if limit <= 0:
        return []
    return db.execute(
        'SELECT local_day, content FROM life_log '
        'WHERE persona = ? AND user_id = ? ORDER BY id DESC LIMIT ?',
        (persona, user_id, limit),
    ).fetchall()


def life_summary(db, persona, user_id, *, today=None, limit=3):
    """Render recent life notes as a short labelled block, or ``''``.

    ``today`` is an ISO date string supplied by the caller so the labels can be
    relative (今天 / 昨天) without this module reading the clock.
    """
    rows = recent_life(db, persona, user_id, limit=limit)
    if not rows:
        return ''
    lines = []
    total = 0
    for local_day, content in rows:
        age = _days_before(today, local_day) if today else None
        if age is not None and age > _MAX_AGE_DAYS:
            continue
        if age == 0:
            label = '今天'
        elif age == 1:
            label = '昨天'
        elif age is not None:
            label = '前几天'
        else:
            label = str(local_day)
        line = '%s：%s' % (label, content)
        if total + len(line) > _MAX_SUMMARY_CHARS:
            break
        lines.append(line)
        total += len(line)
    return '\n'.join(lines)


def _days_before(iso_day, earlier_iso_day):
    """Return how many days ``earlier_iso_day`` precedes ``iso_day``, or None."""
    try:
        later = _parse_day(iso_day)
        earlier = _parse_day(earlier_iso_day)
    except (AttributeError, TypeError, ValueError):
        return None
    if later is None or earlier is None:
        return None
    return (later - earlier).days


def _parse_day(iso_day):
    from datetime import date

    year, month, day = (int(part) for part in iso_day.split('-'))
    return date(year, month, day)


def _previous_day(iso_day):
    """Return the ISO date before ``iso_day``; ``''`` when unparseable."""
    from datetime import timedelta

    try:
        return (_parse_day(iso_day) - timedelta(days=1)).isoformat()
    except (AttributeError, TypeError, ValueError):
        return ''
