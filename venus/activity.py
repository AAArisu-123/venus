"""Per-identity activity tracking for Venus proactive messaging.

Events are stored in a caller-supplied SQLite connection and keyed by
``(persona, user_id, event_id)``, so replaying the same event cannot inflate
activity. Every time decision uses the explicit *aware* UTC datetime supplied
by the caller; this module never reads the system clock, environment
variables, credentials or the production ``data`` directory.
"""

from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

_WINDOW_DAYS = 7
_TS_FORMAT = '%Y-%m-%dT%H:%M:%S.%fZ'
_DEFAULT_WINDOW = (18 * 60, 23 * 60 + 30)


def _as_utc(value, name):
    """Return ``value`` normalised to UTC, rejecting naive/non-datetime input."""
    if not isinstance(value, datetime):
        raise ValueError('%s must be a datetime' % name)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('%s must be an aware datetime' % name)
    return value.astimezone(dt_timezone.utc)


def init_activity(db):
    """Create the activity schema if absent. Safe to call repeatedly."""
    with db:
        db.execute(
            'CREATE TABLE IF NOT EXISTS activity ('
            'persona TEXT NOT NULL, '
            'user_id TEXT NOT NULL, '
            'event_id TEXT NOT NULL, '
            'occurred_at TEXT NOT NULL, '
            'occurred_date TEXT NOT NULL, '
            'PRIMARY KEY (persona, user_id, event_id))'
        )
        db.execute(
            'CREATE INDEX IF NOT EXISTS idx_activity_window '
            'ON activity (persona, user_id, occurred_at)'
        )


def record_activity(db, persona, user_id, event_id, when):
    """Record one activity event, deduplicated per ``(persona, user, event_id)``.

    ``when`` must be an aware datetime and is normalised to UTC before being
    stored. Recording the same event id again is a no-op. The write is
    committed before returning.
    """
    when_utc = _as_utc(when, 'when')
    with db:
        db.execute(
            'INSERT OR IGNORE INTO activity '
            '(persona, user_id, event_id, occurred_at, occurred_date) '
            'VALUES (?, ?, ?, ?, ?)',
            (
                persona,
                user_id,
                event_id,
                when_utc.strftime(_TS_FORMAT),
                when_utc.date().isoformat(),
            ),
        )


def _parse_ts(value):
    """Parse one stored UTC timestamp, returning ``None`` if malformed."""
    try:
        return datetime.strptime(value, _TS_FORMAT).replace(
            tzinfo=dt_timezone.utc)
    except (TypeError, ValueError):
        return None


def allowed_today(db, persona, user_id, now):
    """Return whether a proactive message is allowed for this identity today.

    Counts distinct UTC active dates in the rolling seven-day window ending at
    ``now``; future-dated events are excluded. A recent conversation suppresses
    the proactive message so it does not interrupt an active chat:

    * no activity: ``False``
    * one to three active days: ``True`` after six hours of silence
    * four or more active days: ``True`` after four hours of silence

    The caller still enforces its own minimum interval between proactive
    messages. ``now`` must be an aware datetime.
    """
    now_utc = _as_utc(now, 'now')
    row = db.execute(
        'SELECT COUNT(DISTINCT occurred_date), MAX(occurred_at) FROM activity '
        'WHERE persona = ? AND user_id = ? '
        'AND occurred_at >= ? AND occurred_at <= ?',
        (
            persona,
            user_id,
            (now_utc - timedelta(days=_WINDOW_DAYS)).strftime(_TS_FORMAT),
            now_utc.strftime(_TS_FORMAT),
        ),
    ).fetchone()
    active_days, last_at = row
    if not active_days or not last_at:
        return False
    last = _parse_ts(last_at)
    if last is None:
        return False
    if active_days <= 3:
        minimum_silence = timedelta(hours=6)
    else:
        minimum_silence = timedelta(hours=4)
    return now_utc - last >= minimum_silence


def minutes_since_activity(db, persona, user_id, now):
    """Return minutes since this identity's most recent activity, or ``None``.

    Used by the richer multi-slot scheduler to avoid interrupting a live chat:
    an opener is only worth sending when the user has actually been away for a
    while. ``None`` means there is no recorded activity in the future-filtered
    window, so the caller should treat the identity as not yet engaged.
    """
    now_utc = _as_utc(now, 'now')
    row = db.execute(
        'SELECT MAX(occurred_at) FROM activity '
        'WHERE persona = ? AND user_id = ? AND occurred_at <= ?',
        (persona, user_id, now_utc.strftime(_TS_FORMAT)),
    ).fetchone()
    last = _parse_ts(row[0]) if row else None
    if last is None:
        return None
    return (now_utc - last).total_seconds() / 60.0


def preferred_local_window(db, persona, user_id, tz_name, now,
                           days=14, radius_minutes=90):
    """Return a likely active local-time window as ``(start, end)`` minutes.

    The median local minute-of-day from recent activity is used as the centre;
    the returned window is centred on it and clamped to a humane 08:00-23:30.
    A narrow window makes the daily proactive message feel timed to the user's
    routine instead of landing at a random hour. If there is no usable
    activity, the default is 18:00-23:30. ``now`` must be an aware datetime.
    """
    now_utc = _as_utc(now, 'now')
    try:
        tz = ZoneInfo(tz_name)
    except (KeyError, ValueError):
        return _DEFAULT_WINDOW
    rows = db.execute(
        'SELECT occurred_at FROM activity '
        'WHERE persona = ? AND user_id = ? '
        'AND occurred_at >= ? AND occurred_at <= ? '
        'ORDER BY occurred_at DESC LIMIT 200',
        (
            persona,
            user_id,
            (now_utc - timedelta(days=days)).strftime(_TS_FORMAT),
            now_utc.strftime(_TS_FORMAT),
        ),
    ).fetchall()
    minutes = []
    for (stored,) in rows:
        parsed = _parse_ts(stored)
        if parsed is None:
            continue
        local = parsed.astimezone(tz)
        minutes.append(local.hour * 60 + local.minute)
    if not minutes:
        return _DEFAULT_WINDOW

    minutes.sort()
    centre = minutes[len(minutes) // 2]
    # A median after midnight means a night owl; keep the window late rather
    # than moving it to the morning.
    if centre < 8 * 60:
        centre = 22 * 60
    centre = min(max(centre, 9 * 60), 22 * 60)
    start = max(8 * 60, centre - radius_minutes)
    end = min(23 * 60 + 30, centre + radius_minutes)
    if end - start < 60:
        start = max(8 * 60, end - 60)
        end = min(23 * 60 + 30, start + 60)
    return start, end
