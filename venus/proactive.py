"""Proactive-message schedules and claims.

Every decision takes an explicit `now_utc`, and a claim is written before
sending so a retry cannot double-send.
"""

import secrets
from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

RANDOM_WINDOW_START = 10 * 60
RANDOM_WINDOW_SPAN = 660  # 10:00 (inclusive) .. 20:59 (21:00 exclusive)

# One evening window, one opener per day, and only after a quiet stretch.
SLOT_WINDOWS = (
    (19 * 60, 21 * 60),
)
SLOT_MIN_GAP_MINUTES = 25


def _schedule_has_mode(db):
    return any(
        row[1] == 'mode'
        for row in db.execute('PRAGMA table_info(proactive_schedule)')
    )


def init_proactive(db):
    """Create the schedule, random-target and claim tables if missing.

    Idempotent: calling this again on an existing database preserves all rows.
    Databases created before random scheduling existed are migrated by adding
    a ``mode TEXT NOT NULL DEFAULT 'fixed'`` column, so legacy schedules keep
    their exact behaviour.  The caller owns ``db`` and may commit/close it as
    it wishes.
    """
    with db:
        db.execute(
            'CREATE TABLE IF NOT EXISTS proactive_schedule ('
            'persona TEXT NOT NULL, '
            'user_id TEXT NOT NULL, '
            'enabled INTEGER NOT NULL, '
            'hour INTEGER NOT NULL, '
            'minute INTEGER NOT NULL, '
            'timezone TEXT NOT NULL, '
            "mode TEXT NOT NULL DEFAULT 'fixed', "
            'PRIMARY KEY (persona, user_id))'
        )
        if not _schedule_has_mode(db):
            db.execute(
                "ALTER TABLE proactive_schedule "
                "ADD COLUMN mode TEXT NOT NULL DEFAULT 'fixed'"
            )
        db.execute(
            'CREATE TABLE IF NOT EXISTS proactive_random_target ('
            'persona TEXT NOT NULL, '
            'user_id TEXT NOT NULL, '
            'local_day TEXT NOT NULL, '
            'minute_of_day INTEGER NOT NULL, '
            'PRIMARY KEY (persona, user_id, local_day))'
        )
        db.execute(
            'CREATE TABLE IF NOT EXISTS proactive_claim ('
            'persona TEXT NOT NULL, '
            'user_id TEXT NOT NULL, '
            'local_day TEXT NOT NULL, '
            'PRIMARY KEY (persona, user_id, local_day))'
        )


def _validate_component(value, name, high):
    """Require ``value`` to be a plain integer within ``[0, high]``."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError('%s must be an integer' % name)
    if value < 0 or value > high:
        raise ValueError('%s must be between 0 and %d' % (name, high))


def _validate_timezone(value):
    """Require ``value`` to be a loadable IANA timezone name."""
    if not isinstance(value, str):
        raise ValueError('timezone must be an IANA time zone name')
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError('invalid timezone: %r' % (value,)) from exc
    return value


def set_schedule(db, persona, user_id, enabled, hour, minute, timezone):
    """Create or replace the daily schedule for ``(persona, user_id)``.

    The schedule is stored with ``mode = 'fixed'``, so it overrides any
    previous random schedule for the same identity.  Returns ``None``.
    Raises :class:`ValueError` for a non-integer or out-of-range
    ``hour``/``minute`` and for an unknown ``timezone``.  The change is
    committed before returning.
    """
    _validate_component(hour, 'hour', 23)
    _validate_component(minute, 'minute', 59)
    _validate_timezone(timezone)
    with db:
        db.execute(
            'INSERT OR REPLACE INTO proactive_schedule '
            '(persona, user_id, enabled, hour, minute, timezone, mode) '
            "VALUES (?, ?, ?, ?, ?, ?, 'fixed')",
            (persona, user_id, 1 if enabled else 0, hour, minute, timezone),
        )


def set_random_schedule(db, persona, user_id, enabled, timezone):
    """Create or replace a ``mode = 'random'`` daily schedule.

    The actual local send minute is not chosen here; it is generated lazily
    once per local day by :func:`due_and_claim` and stored in the random
    target table.  ``hour``/``minute`` are kept at 0 because random schedules
    ignore them.  The change is committed before returning.
    """
    _validate_timezone(timezone)
    with db:
        db.execute(
            'INSERT OR REPLACE INTO proactive_schedule '
            '(persona, user_id, enabled, hour, minute, timezone, mode) '
            "VALUES (?, ?, ?, 0, 0, ?, 'random')",
            (persona, user_id, 1 if enabled else 0, timezone),
        )


def ensure_default_schedule(db, persona, user_id, timezone):
    """Create an enabled random schedule when this identity has no row.

    Proactive messages are on by default for new identities. The activity
    threshold in :mod:`venus.activity` still decides whether a greeting is
    appropriate, and an explicit ``/主动 关闭`` row is preserved.
    """
    _validate_timezone(timezone)
    init_proactive(db)
    with db:
        db.execute(
            'INSERT OR IGNORE INTO proactive_schedule '
            '(persona, user_id, enabled, hour, minute, timezone, mode) '
            "VALUES (?, ?, 1, 0, 0, ?, 'random')",
            (persona, user_id, timezone),
        )


def disable_schedule(db, persona, user_id, timezone):
    """Disable proactive messages, creating a durable opt-out if needed.

    Unlike a bare UPDATE, this writes a disabled row when the identity has
    never had a schedule, so a later :func:`ensure_default_schedule` cannot
    silently turn the feature back on.
    """
    _validate_timezone(timezone)
    init_proactive(db)
    with db:
        db.execute(
            'INSERT OR IGNORE INTO proactive_schedule '
            '(persona, user_id, enabled, hour, minute, timezone, mode) '
            "VALUES (?, ?, 0, 0, 0, ?, 'random')",
            (persona, user_id, timezone),
        )
        db.execute(
            'UPDATE proactive_schedule SET enabled = 0 '
            'WHERE persona = ? AND user_id = ?',
            (persona, user_id),
        )


def _local_now(now_utc, tz_name):
    """Return ``now_utc`` expressed in ``tz_name``.

    An aware datetime is converted to UTC first so that a non-UTC tzinfo on
    the input cannot be mistaken for wall-clock time.  Naive input is treated
    as UTC for robustness; the test suite always supplies aware datetimes.
    """
    if now_utc.tzinfo is None or now_utc.utcoffset() is None:
        now_utc = now_utc.replace(tzinfo=dt_timezone.utc)
    return now_utc.astimezone(ZoneInfo(tz_name))


def _random_target_minute(db, persona, user_id, local_day,
                          start=RANDOM_WINDOW_START, span=RANDOM_WINDOW_SPAN):
    """Return this identity's stored random minute-of-day for ``local_day``.

    Generates it with ``secrets.randbelow`` only on first use; the PRIMARY
    KEY on (persona, user_id, local_day) plus INSERT OR IGNORE makes racing
    connections converge on the row that was written first, and the re-read
    guarantees every caller observes that same persisted value. ``start`` and
    ``span`` define the local-time window used for today's target.
    """
    row = db.execute(
        'SELECT minute_of_day FROM proactive_random_target '
        'WHERE persona = ? AND user_id = ? AND local_day = ?',
        (persona, user_id, local_day),
    ).fetchone()
    if row is None:
        db.execute(
            'INSERT OR IGNORE INTO proactive_random_target '
            '(persona, user_id, local_day, minute_of_day) VALUES (?, ?, ?, ?)',
            (persona, user_id, local_day, start + secrets.randbelow(span)),
        )
        row = db.execute(
            'SELECT minute_of_day FROM proactive_random_target '
            'WHERE persona = ? AND user_id = ? AND local_day = ?',
            (persona, user_id, local_day),
        ).fetchone()
    return row[0]


def due_and_claim(db, persona, user_id, now_utc, target_window=None):
    """Claim this user's next message if it is due now.

    Returns False when the schedule is off, early, or already claimed today.
    The claim is committed before returning, so a crash cannot cause a resend.
    """
    if target_window is None:
        window_start, window_end = (
            RANDOM_WINDOW_START, RANDOM_WINDOW_START + RANDOM_WINDOW_SPAN
        )
    else:
        try:
            window_start, window_end = target_window
        except (TypeError, ValueError) as exc:
            raise ValueError('target_window must be a (start, end) pair') from exc
        if (not isinstance(window_start, int) or not isinstance(window_end, int)
                or isinstance(window_start, bool) or isinstance(window_end, bool)
                or not 0 <= window_start < window_end <= 24 * 60):
            raise ValueError('target_window must be within 0..1440')
    span = window_end - window_start

    with db:
        row = db.execute(
            'SELECT enabled, hour, minute, timezone, mode FROM proactive_schedule '
            'WHERE persona = ? AND user_id = ?',
            (persona, user_id),
        ).fetchone()
        if row is None or not row[0]:
            return False

        _enabled, hour, minute, tz_name, mode = row
        local_now = _local_now(now_utc, tz_name)
        local_day = local_now.date().isoformat()

        if mode == 'random':
            minute_of_day = local_now.hour * 60 + local_now.minute
            if not window_start <= minute_of_day < window_end:
                return False
            if minute_of_day < _random_target_minute(
                db, persona, user_id, local_day, window_start, span
            ):
                return False
        elif (local_now.hour, local_now.minute) < (hour, minute):
            return False

        cur = db.execute(
            'INSERT OR IGNORE INTO proactive_claim '
            '(persona, user_id, local_day) VALUES (?, ?, ?)',
            (persona, user_id, local_day),
        )
        # sqlite3_changes()/rowcount is 1 for an inserted row and 0 when the
        # PRIMARY KEY conflict caused the INSERT OR IGNORE to be skipped.
        return cur.rowcount == 1


def init_slots(db):
    """Create the per-slot target and claim tables if missing.

    Idempotent. Targets store the one randomly chosen minute per slot per local
    day so every poll, reconnect and restart reuses the same moment instead of
    silently rescheduling. Claims make each slot fire at most once.
    """
    with db:
        db.execute(
            'CREATE TABLE IF NOT EXISTS proactive_slot_target ('
            'persona TEXT NOT NULL, '
            'user_id TEXT NOT NULL, '
            'local_day TEXT NOT NULL, '
            'slot INTEGER NOT NULL, '
            'minute_of_day INTEGER NOT NULL, '
            'PRIMARY KEY (persona, user_id, local_day, slot))'
        )
        db.execute(
            'CREATE TABLE IF NOT EXISTS proactive_slot_claim ('
            'persona TEXT NOT NULL, '
            'user_id TEXT NOT NULL, '
            'local_day TEXT NOT NULL, '
            'slot INTEGER NOT NULL, '
            'claimed_minute INTEGER NOT NULL, '
            'PRIMARY KEY (persona, user_id, local_day, slot))'
        )


def _slot_target_minute(db, persona, user_id, local_day, slot, start, end):
    """Return the stored random minute for one slot, generating it once."""
    row = db.execute(
        'SELECT minute_of_day FROM proactive_slot_target '
        'WHERE persona = ? AND user_id = ? AND local_day = ? AND slot = ?',
        (persona, user_id, local_day, slot),
    ).fetchone()
    if row is None:
        db.execute(
            'INSERT OR IGNORE INTO proactive_slot_target '
            '(persona, user_id, local_day, slot, minute_of_day) '
            'VALUES (?, ?, ?, ?, ?)',
            (persona, user_id, local_day, slot, start + secrets.randbelow(end - start)),
        )
        row = db.execute(
            'SELECT minute_of_day FROM proactive_slot_target '
            'WHERE persona = ? AND user_id = ? AND local_day = ? AND slot = ?',
            (persona, user_id, local_day, slot),
        ).fetchone()
    return row[0]


def claimed_slots_today(db, persona, user_id, local_day):
    """Return the slot numbers already claimed for ``local_day``, ascending."""
    return [
        row[0]
        for row in db.execute(
            'SELECT slot FROM proactive_slot_claim '
            'WHERE persona = ? AND user_id = ? AND local_day = ? ORDER BY slot',
            (persona, user_id, local_day),
        )
    ]


def slot_due_and_claim(db, persona, user_id, now_utc, *, slots=SLOT_WINDOWS,
                       max_per_day=None, min_gap_minutes=SLOT_MIN_GAP_MINUTES):
    """Claim one slot for this user if it is open and due.

    The check and the insert share a transaction, so two ticks cannot both win.
    """
    if max_per_day is None:
        max_per_day = len(slots)
    if (not isinstance(max_per_day, int) or isinstance(max_per_day, bool)
            or max_per_day < 1):
        raise ValueError('max_per_day must be a positive integer')
    if (not isinstance(min_gap_minutes, int) or isinstance(min_gap_minutes, bool)
            or min_gap_minutes < 0):
        raise ValueError('min_gap_minutes must be a non-negative integer')

    with db:
        row = db.execute(
            'SELECT enabled, timezone FROM proactive_schedule '
            'WHERE persona = ? AND user_id = ?',
            (persona, user_id),
        ).fetchone()
        if row is None or not row[0]:
            return False

        local_now = _local_now(now_utc, row[1])
        minute_of_day = local_now.hour * 60 + local_now.minute
        local_day = local_now.date().isoformat()

        slot = None
        for index, (start, end) in enumerate(slots):
            if start <= minute_of_day < end:
                slot = index
                break
        if slot is None:
            return False

        start, end = slots[slot]
        if minute_of_day < _slot_target_minute(
            db, persona, user_id, local_day, slot, start, end
        ):
            return False

        claims = db.execute(
            'SELECT slot, claimed_minute FROM proactive_slot_claim '
            'WHERE persona = ? AND user_id = ? AND local_day = ?',
            (persona, user_id, local_day),
        ).fetchall()
        if any(claimed_slot == slot for claimed_slot, _ in claims):
            return False
        if len(claims) >= max_per_day:
            return False
        if claims and min_gap_minutes:
            newest = max(claimed for _, claimed in claims)
            if minute_of_day - newest < min_gap_minutes:
                return False

        cur = db.execute(
            'INSERT OR IGNORE INTO proactive_slot_claim '
            '(persona, user_id, local_day, slot, claimed_minute) '
            'VALUES (?, ?, ?, ?, ?)',
            (persona, user_id, local_day, slot, minute_of_day),
        )
        return cur.rowcount == 1
