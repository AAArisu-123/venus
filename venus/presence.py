"""Track the last speaker and unanswered messages.

Used by the optional follow-up path; the bot leaves it off by default.
"""

from datetime import datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo

_TS_FORMAT = '%Y-%m-%dT%H:%M:%SZ'

# One extra message after a silence, then stop: two unanswered assistant turns
# in a row is already the limit of what feels natural in a chat.
DEFAULT_MIN_SILENCE_MINUTES = 35
DEFAULT_MAX_STREAK = 2
DEFAULT_DAILY_CAP = 3
DEFAULT_MIN_GAP_MINUTES = 30
# Follow-ups are chat behaviour, so they respect a humane waking window.
DEFAULT_WAKE_WINDOW = (8 * 60 + 30, 23 * 60 + 59)


def _as_utc(value, name='when'):
    """Return ``value`` normalised to UTC, rejecting naive timestamps."""
    if not isinstance(value, datetime):
        raise ValueError('%s must be a datetime' % name)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('%s must be an aware datetime' % name)
    return value.astimezone(dt_timezone.utc)


def _parse(value):
    """Parse one stored UTC timestamp, returning ``None`` when malformed."""
    try:
        return datetime.strptime(value, _TS_FORMAT).replace(
            tzinfo=dt_timezone.utc)
    except (TypeError, ValueError):
        return None


def init_presence(db):
    """Create the presence table if absent. Safe to call repeatedly."""
    with db:
        db.execute(
            'CREATE TABLE IF NOT EXISTS presence ('
            'persona TEXT NOT NULL, '
            'user_id TEXT NOT NULL, '
            'last_user_at TEXT, '
            'last_assistant_at TEXT, '
            'assistant_streak INTEGER NOT NULL DEFAULT 0, '
            'follows_day TEXT, '
            'follows_today INTEGER NOT NULL DEFAULT 0, '
            'last_follow_at TEXT, '
            'PRIMARY KEY (persona, user_id))'
        )


def note_user_message(db, persona, user_id, when):
    """Record an incoming user message and reset the unanswered streak."""
    when_utc = _as_utc(when)
    with db:
        db.execute(
            'INSERT OR IGNORE INTO presence (persona, user_id, assistant_streak) '
            'VALUES (?, ?, 0)',
            (persona, user_id),
        )
        db.execute(
            'UPDATE presence SET last_user_at = ?, assistant_streak = 0 '
            'WHERE persona = ? AND user_id = ?',
            (when_utc.strftime(_TS_FORMAT), persona, user_id),
        )


def note_assistant_message(db, persona, user_id, when):
    """Record an assistant message and extend the unanswered streak."""
    when_utc = _as_utc(when)
    with db:
        db.execute(
            'INSERT OR IGNORE INTO presence (persona, user_id, assistant_streak) '
            'VALUES (?, ?, 0)',
            (persona, user_id),
        )
        db.execute(
            'UPDATE presence '
            'SET last_assistant_at = ?, assistant_streak = assistant_streak + 1 '
            'WHERE persona = ? AND user_id = ?',
            (when_utc.strftime(_TS_FORMAT), persona, user_id),
        )


def presence_snapshot(db, persona, user_id):
    """Return the stored presence row as a dict, or ``None``."""
    row = db.execute(
        'SELECT last_user_at, last_assistant_at, assistant_streak, '
        'follows_day, follows_today, last_follow_at '
        'FROM presence WHERE persona = ? AND user_id = ?',
        (persona, user_id),
    ).fetchone()
    if row is None:
        return None
    return {
        'last_user_at': row[0],
        'last_assistant_at': row[1],
        'assistant_streak': row[2],
        'follows_day': row[3],
        'follows_today': row[4],
        'last_follow_at': row[5],
    }


def _local_day(now_utc, tz_name):
    try:
        local = now_utc.astimezone(ZoneInfo(tz_name))
    except Exception:
        local = now_utc
    return local, local.date().isoformat()


def followup_due(db, persona, user_id, now_utc, *,
                 timezone_name='Asia/Shanghai',
                 min_silence_minutes=DEFAULT_MIN_SILENCE_MINUTES,
                 max_streak=DEFAULT_MAX_STREAK,
                 daily_cap=DEFAULT_DAILY_CAP,
                 wake_window=DEFAULT_WAKE_WINDOW,
                 min_gap_minutes=DEFAULT_MIN_GAP_MINUTES):
    """Return whether one more short follow-up message is appropriate now.

    Conditions, all scoped to this identity: the assistant spoke last, the user
    has been silent since then for at least ``min_silence_minutes``, fewer than
    ``max_streak`` assistant messages are unanswered, the daily follow-up cap
    is not reached, the local time is inside ``wake_window``, and the previous
    follow-up is at least ``min_gap_minutes`` old.
    """
    now_utc = _as_utc(now_utc, 'now')
    snapshot = presence_snapshot(db, persona, user_id)
    if snapshot is None:
        return False
    if not snapshot['last_user_at'] or not snapshot['last_assistant_at']:
        return False

    last_user = _parse(snapshot['last_user_at'])
    last_assistant = _parse(snapshot['last_assistant_at'])
    if last_user is None or last_assistant is None:
        return False
    # The user already answered her last message; nothing to follow up on.
    if last_user > last_assistant:
        return False

    streak = snapshot['assistant_streak']
    if streak < 1 or streak >= max_streak:
        return False

    local, today = _local_day(now_utc, timezone_name)
    minute_of_day = local.hour * 60 + local.minute
    if not wake_window[0] <= minute_of_day < wake_window[1]:
        return False

    silence = (now_utc - last_assistant).total_seconds() / 60.0
    if silence < min_silence_minutes:
        return False

    used = snapshot['follows_today'] if snapshot['follows_day'] == today else 0
    if used >= daily_cap:
        return False

    if snapshot['last_follow_at']:
        last_follow = _parse(snapshot['last_follow_at'])
        if last_follow is not None:
            gap = (now_utc - last_follow).total_seconds() / 60.0
            if gap < min_gap_minutes:
                return False
    return True


def claim_followup(db, persona, user_id, now_utc, **kwargs):
    """Atomically verify and record today's follow-up slot.

    Returns ``True`` only when the follow-up is due *and* the daily counter was
    written, so a caller can never send two follow-ups for one counted slot.
    """
    now_utc = _as_utc(now_utc, 'now')
    if not followup_due(db, persona, user_id, now_utc, **kwargs):
        return False
    timezone_name = kwargs.get('timezone_name', 'Asia/Shanghai')
    _local, today = _local_day(now_utc, timezone_name)
    snapshot = presence_snapshot(db, persona, user_id)
    used = snapshot['follows_today'] if snapshot['follows_day'] == today else 0
    with db:
        db.execute(
            'UPDATE presence SET follows_day = ?, follows_today = ?, '
            'last_follow_at = ? WHERE persona = ? AND user_id = ?',
            (today, used + 1, now_utc.strftime(_TS_FORMAT), persona, user_id),
        )
    return True
