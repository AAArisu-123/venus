"""Periodic driver for proactive openers and quiet-conversation follow-ups.

This module never reads credentials, environment variables or the system
clock for its decisions: every time decision is driven by the explicit
``now_utc`` argument of :func:`tick` / :func:`followup_tick`. Only
:func:`loop_forever` consults the wall clock, and solely to produce that
argument.

Two behaviours are available:

* :func:`tick` sends proactive openers. Schedules created by the modern random
  mode use one evening slot (:data:`venus.proactive.SLOT_WINDOWS`), so the
  companion reaches out at most once per day. Legacy fixed-time schedules keep
  their old once-a-day behaviour.
* :func:`followup_tick` can add one short message when the user has been quiet
  after the assistant spoke last. The bot does not wire it up by default;
  silence is better than a second unprompted message.

Generation is callback-based. A callback may return a plain string or a dict
``{'message': ..., 'life': ...}``; the life note is stored so later chat can
reference it. Failures are swallowed: no retry and no secret logging.
"""

import asyncio
import logging
from contextlib import closing
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .activity import (
    init_activity,
    allowed_today,
    minutes_since_activity,
    preferred_local_window,
)
from .life import add_life, init_life
from .memory import connect_database
from .presence import (
    claim_followup,
    followup_due,
    init_presence,
    note_assistant_message,
)
from .proactive import due_and_claim, init_slots, slot_due_and_claim


_LOG = logging.getLogger(__name__)
HELLO_CONTENT = '你好呀，今天也要开开心心！'
LATE_WINDOW_END = 23 * 60 + 30
# A live chat should never be interrupted by an opener, and a short lull is
# not an invitation either: wait at least six quiet hours.
MIN_ACTIVE_SILENCE_MINUTES = 6 * 60
# A user who has not written for a week is dormant: reaching out every evening
# would feel like spam, so the multi-slot path goes quiet until they write
# again (their next message re-enters the normal active window).
MAX_DORMANT_DAYS = 7


def _extend_window(window, local_minute):
    """Keep a usable evening window when the inferred one already passed.

    If a user becomes eligible for a proactive message after the activity-based
    window has ended, waiting until tomorrow would make the feature feel dead.
    Extend today's target to the evening instead, never starting before 18:00.
    """
    if window is None:
        return None
    start, end = window
    if local_minute >= end and local_minute < LATE_WINDOW_END:
        return max(local_minute, 18 * 60), LATE_WINDOW_END
    return window


def _unpack(result):
    """Normalise a generator result into ``(content, life)``.

    Older callbacks and tests return a bare string; a dict result may carry a
    life note that is stored for later chat continuity.
    """
    if isinstance(result, dict):
        content = result.get('message')
        life = result.get('life')
        return (
            content.strip() if isinstance(content, str) else '',
            life.strip() if isinstance(life, str) else '',
        )
    if isinstance(result, str):
        return result.strip(), ''
    return '', ''


def _local_day(now_utc, timezone_name):
    try:
        return now_utc.astimezone(ZoneInfo(timezone_name)).date().isoformat()
    except Exception:
        return now_utc.date().isoformat()


def _schedule_enabled(db, persona, user_id):
    row = db.execute(
        'SELECT enabled FROM proactive_schedule WHERE persona = ? AND user_id = ?',
        (persona, user_id),
    ).fetchone()
    return row is not None and bool(row[0])


def _persist_assistant(db, persona, user_id, content, now_utc):
    """Store the sent assistant turn and record the presence streak."""
    with db:
        db.execute(
            'INSERT INTO messages(persona, user_id, role, content) '
            'VALUES (?, ?, ?, ?)',
            (persona, user_id, 'assistant', content),
        )
    note_assistant_message(db, persona, user_id, now_utc)


async def tick(db_path, persona, send, now_utc, authorized=None, generate=None,
               timezone_name='Asia/Shanghai',
               min_active_silence_minutes=MIN_ACTIVE_SILENCE_MINUTES):
    """Claim and send this identity's proactive opener(s) that are due now.

    A fresh connection is opened for every tick. For modern random schedules,
    the current local minute must fall inside an unclaimed slot window and the
    user must have been quiet for at least ``min_active_silence_minutes``. For
    legacy fixed schedules the previous once-a-day path is unchanged. The claim
    is committed before generation, so whichever way generation or delivery
    turns out, that slot is never retried.
    """
    with closing(connect_database(db_path)) as db:
        init_activity(db)
        init_slots(db)
        init_life(db)
        init_presence(db)
        rows = db.execute(
            'SELECT user_id, mode FROM proactive_schedule '
            'WHERE persona = ? AND enabled = 1',
            (persona,),
        ).fetchall()
        for user_id, mode in rows:
            if authorized is not None and not authorized(user_id):
                continue

            if mode == 'random':
                silence = minutes_since_activity(db, persona, user_id, now_utc)
                if silence is None or silence < min_active_silence_minutes:
                    continue
                if silence > MAX_DORMANT_DAYS * 24 * 60:
                    continue
                if not slot_due_and_claim(db, persona, user_id, now_utc):
                    continue
            else:
                if not allowed_today(db, persona, user_id, now_utc):
                    continue
                try:
                    target_window = preferred_local_window(
                        db, persona, user_id, timezone_name, now_utc)
                    local = now_utc.astimezone(ZoneInfo(timezone_name))
                    target_window = _extend_window(
                        target_window, local.hour * 60 + local.minute)
                except Exception:
                    target_window = None
                if not due_and_claim(db, persona, user_id, now_utc,
                                     target_window=target_window):
                    continue

            content, life = HELLO_CONTENT, ''
            if generate is not None:
                try:
                    result = await generate(user_id)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    # Generation failed; the claim is already committed. Only
                    # the exception type is logged: no prompt, message text or
                    # credential may reach the status log.
                    _LOG.warning('status: proactive generation failed (%s)',
                                 type(exc).__name__)
                    continue
                content, life = _unpack(result)
                if not content:
                    _LOG.warning('status: proactive generation returned empty')
                    continue

            # Re-check opt-out state that may have changed during generation.
            if not _schedule_enabled(db, persona, user_id):
                continue
            if authorized is not None and not authorized(user_id):
                continue

            try:
                await send(openid=user_id, msg_type=0, content=content)
            except asyncio.CancelledError:
                # Cancellation must propagate so the loop can shut down.
                raise
            except Exception as exc:
                # Claim already committed and delivery outcome ambiguous:
                # do not persist, do not retry, never expose details.
                _LOG.warning('status: proactive send failed (%s)',
                             type(exc).__name__)
                continue

            _persist_assistant(db, persona, user_id, content, now_utc)
            if life:
                add_life(db, persona, user_id, _local_day(now_utc, timezone_name), life)


async def followup_tick(db_path, persona, send, now_utc, authorized=None,
                        generate=None, timezone_name='Asia/Shanghai'):
    """Send at most one short follow-up per identity when a chat goes quiet.

    Only identities with an enabled proactive schedule are considered, so an
    explicit ``/主动 关闭`` also silences follow-ups. The daily counter is
    claimed before generation, and the schedule/authorization state is
    re-checked before sending.
    """
    if generate is None:
        return
    with closing(connect_database(db_path)) as db:
        init_presence(db)
        init_life(db)
        rows = db.execute(
            'SELECT user_id FROM proactive_schedule '
            'WHERE persona = ? AND enabled = 1',
            (persona,),
        ).fetchall()
        for (user_id,) in rows:
            if authorized is not None and not authorized(user_id):
                continue
            if not followup_due(db, persona, user_id, now_utc,
                                timezone_name=timezone_name):
                continue
            if not claim_followup(db, persona, user_id, now_utc,
                                  timezone_name=timezone_name):
                continue
            if not _schedule_enabled(db, persona, user_id):
                continue

            try:
                result = await generate(user_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _LOG.warning('status: followup generation failed (%s)',
                             type(exc).__name__)
                continue
            content, life = _unpack(result)
            if not content:
                continue

            if not _schedule_enabled(db, persona, user_id):
                continue
            if authorized is not None and not authorized(user_id):
                continue

            try:
                await send(openid=user_id, msg_type=0, content=content)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _LOG.warning('status: followup send failed (%s)',
                             type(exc).__name__)
                continue

            _persist_assistant(db, persona, user_id, content, now_utc)
            if life:
                add_life(db, persona, user_id, _local_day(now_utc, timezone_name), life)


async def loop_forever(db_path, persona, send, interval=30, authorized=None,
                       generate=None, timezone_name='Asia/Shanghai',
                       followup_generate=None):
    """Run :func:`tick` and :func:`followup_tick` forever every ``interval``.

    The clock is read at the start of each iteration and passed explicitly to
    both ticks. ``asyncio.sleep`` yields to the event loop and lets an
    ``asyncio.CancelledError`` propagate, preserving cancellation. Follow-ups
    are only attempted when a ``followup_generate`` callback is supplied.
    """
    while True:
        now_utc = datetime.now(timezone.utc)
        try:
            await tick(db_path, persona, send, now_utc,
                       authorized=authorized, generate=generate,
                       timezone_name=timezone_name)
            if followup_generate is not None:
                await followup_tick(db_path, persona, send, now_utc,
                                    authorized=authorized,
                                    generate=followup_generate,
                                    timezone_name=timezone_name)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # A transient database or scheduling error must not kill the
            # background task permanently; the next interval retries.
            _LOG.debug('proactive tick failed: %s', type(exc).__name__)
        await asyncio.sleep(interval)
