"""TDD tests for :mod:`venus.proactive`.

These tests define the behavioural contract of the proactive daily-message
scheduler. Every call injects an explicit *aware* UTC datetime, so the suite is
deterministic and never reads the system clock, ``.env`` files or the
production ``data`` directory.

Module under test is expected to expose::

    init_proactive(db)
    set_schedule(db, persona, user_id, enabled, hour, minute, timezone) -> None
    due_and_claim(db, persona, user_id, now_utc) -> bool
"""

import os
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timezone as dt_timezone
from contextlib import closing
from zoneinfo import ZoneInfo

from venus.proactive import (
    disable_schedule,
    due_and_claim,
    ensure_default_schedule,
    init_proactive,
    set_schedule,
)


class ProactiveTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = os.path.join(self._tmp.name, 'proactive.sqlite3')
        self.db = self.new_db()
        self.addCleanup(self.db.close)
        init_proactive(self.db)
        self.db.commit()

    # -- helpers ---------------------------------------------------------
    def new_db(self):
        """Open an independent connection to the same on-disk database."""
        return sqlite3.connect(self.db_path, timeout=10)

    def set(self, persona, user_id, enabled=True, hour=9, minute=0,
            tz='UTC', db=None):
        db = db if db is not None else self.db
        result = set_schedule(db, persona, user_id, bool(enabled), hour,
                              minute, tz)
        db.commit()
        return result

    def due(self, persona, user_id, now_utc, db=None):
        db = db if db is not None else self.db
        return due_and_claim(db, persona, user_id, now_utc)

    @staticmethod
    def utc(year, month, day, hour=0, minute=0):
        return datetime(year, month, day, hour, minute,
                        tzinfo=dt_timezone.utc)

    # -- set_schedule validation -----------------------------------------
    def test_set_schedule_returns_none(self):
        self.assertIsNone(self.set('p', 'u'))

    def test_set_schedule_accepts_valid_boundaries(self):
        for hour, minute in ((0, 0), (0, 59), (23, 0), (23, 59)):
            for tz in ('UTC', 'Asia/Shanghai', 'America/New_York'):
                with self.subTest(hour=hour, minute=minute, tz=tz):
                    self.assertIsNone(self.set('p', 'u', True, hour, minute, tz))

    def test_set_schedule_rejects_hour_below_zero(self):
        with self.assertRaises(ValueError):
            self.set('p', 'u', True, -1, 0)

    def test_set_schedule_rejects_hour_above_23(self):
        with self.assertRaises(ValueError):
            self.set('p', 'u', True, 24, 0)

    def test_set_schedule_rejects_minute_below_zero(self):
        with self.assertRaises(ValueError):
            self.set('p', 'u', True, 9, -1)

    def test_set_schedule_rejects_minute_above_59(self):
        with self.assertRaises(ValueError):
            self.set('p', 'u', True, 9, 60)

    def test_set_schedule_rejects_invalid_timezone(self):
        for tz in ('', 'Not/AZone', 'UTC+8', 'Mars/Olympus', None):
            with self.subTest(tz=tz):
                with self.assertRaises(ValueError):
                    self.set('p', 'u', True, 9, 0, tz)

    def test_set_schedule_rejects_non_integer_time_components(self):
        for hour, minute in ((9.5, 0), ('9', 0), (9, 0.5), (9, '0')):
            with self.subTest(hour=hour, minute=minute):
                with self.assertRaises(ValueError):
                    self.set('p', 'u', True, hour, minute)

    # -- init_proactive ---------------------------------------------------
    def test_init_proactive_is_idempotent_and_preserves_schedule(self):
        self.set('p', 'u', True, 9, 0)
        init_proactive(self.db)  # re-initialise must not wipe existing rows
        self.db.commit()
        self.assertIs(self.due('p', 'u', self.utc(2026, 1, 1, 9, 0)), True)

    # -- defaults / safety ------------------------------------------------
    def test_unknown_persona_user_returns_false(self):
        self.assertIs(self.due('nobody', 'nobody', self.utc(2026, 1, 1, 23, 0)),
                      False)

    def test_disabled_schedule_returns_false_even_when_due(self):
        self.set('p', 'u', enabled=False, hour=9, minute=0)
        self.assertIs(self.due('p', 'u', self.utc(2026, 1, 1, 12, 0)), False)

    # -- due-time boundary ------------------------------------------------
    def test_returns_false_before_scheduled_local_time(self):
        self.set('p', 'u', True, 9, 0)
        self.assertIs(self.due('p', 'u', self.utc(2026, 1, 1, 8, 59)), False)

    def test_returns_true_exactly_at_scheduled_local_time(self):
        self.set('p', 'u', True, 9, 0)
        self.assertIs(self.due('p', 'u', self.utc(2026, 1, 1, 9, 0)), True)

    def test_returns_true_after_scheduled_local_time(self):
        self.set('p', 'u', True, 9, 0)
        self.assertIs(self.due('p', 'u', self.utc(2026, 1, 1, 18, 30)), True)

    # -- timezone handling ------------------------------------------------
    def test_uses_local_time_for_non_utc_timezone(self):
        # Asia/Shanghai is UTC+8; 09:00 local == 01:00 UTC.
        self.set('p', 'u', True, 9, 0, 'Asia/Shanghai')
        self.assertIs(self.due('p', 'u', self.utc(2026, 1, 1, 0, 30)), False)
        self.assertIs(self.due('p', 'u', self.utc(2026, 1, 1, 1, 30)), True)

    def test_uses_local_time_for_negative_offset_timezone(self):
        # America/New_York is UTC-5 in January; 08:00 local == 13:00 UTC.
        self.set('p', 'u', True, 8, 0, 'America/New_York')
        self.assertIs(self.due('p', 'u', self.utc(2026, 1, 15, 12, 59)), False)
        self.assertIs(self.due('p', 'u', self.utc(2026, 1, 15, 13, 1)), True)

    def test_accepts_aware_datetime_in_non_utc_timezone(self):
        # An aware datetime carrying a non-UTC tzinfo must be converted to UTC
        # by the callee rather than compared wall-clock-style.
        self.set('p', 'u', True, 9, 0, 'Asia/Shanghai')
        local_now = datetime(2026, 1, 1, 8, 30, tzinfo=ZoneInfo('Asia/Shanghai'))
        self.assertIs(self.due('p', 'u', local_now), False)
        local_now = datetime(2026, 1, 1, 9, 30, tzinfo=ZoneInfo('Asia/Shanghai'))
        self.assertIs(self.due('p', 'u', local_now), True)

    # -- claim semantics: one per day, persisted, claim-before-send -------
    def test_claim_is_one_shot_within_the_same_day(self):
        self.set('p', 'u', True, 9, 0)
        self.assertIs(self.due('p', 'u', self.utc(2026, 1, 1, 9, 0)), True)
        self.assertIs(self.due('p', 'u', self.utc(2026, 1, 1, 9, 1)), False)
        self.assertIs(self.due('p', 'u', self.utc(2026, 1, 1, 23, 59)), False)

    def test_no_duplicate_after_sqlite_reconnect(self):
        self.set('p', 'u', True, 9, 0)
        self.assertIs(self.due('p', 'u', self.utc(2026, 1, 1, 9, 30)), True)

        with closing(self.new_db()) as reopened:
            self.assertIs(self.due('p', 'u', self.utc(2026, 1, 1, 9, 31),
                                   db=reopened), False)
        # The claim must be visible from the original connection as well.
        self.assertIs(self.due('p', 'u', self.utc(2026, 1, 1, 9, 32)), False)

    def test_claim_before_send_prevents_duplicate_on_ambiguous_delivery(self):
        # The claim is recorded atomically by due_and_claim, before any send
        # attempt. If delivery is ambiguous and the caller simply asks again,
        # the second request must not produce another message.
        self.set('p', 'u', True, 9, 0)
        now = self.utc(2026, 1, 1, 9, 30)
        first = self.due('p', 'u', now)
        # Simulate a failed/uncertain send: no acknowledgement is fed back.
        second = self.due('p', 'u', now)
        self.assertIs(first, True)
        self.assertIs(second, False)

    # -- day rollover / no catch-up ---------------------------------------
    def test_day_rollover_allows_one_new_claim_per_local_day(self):
        self.set('p', 'u', True, 9, 0)
        self.assertIs(self.due('p', 'u', self.utc(2026, 1, 1, 9, 30)), True)
        self.assertIs(self.due('p', 'u', self.utc(2026, 1, 1, 10, 0)), False)

        # Next local day, before and then after the scheduled time.
        self.assertIs(self.due('p', 'u', self.utc(2026, 1, 2, 8, 59)), False)
        self.assertIs(self.due('p', 'u', self.utc(2026, 1, 2, 9, 0)), True)
        self.assertIs(self.due('p', 'u', self.utc(2026, 1, 2, 9, 1)), False)

    def test_no_catch_up_for_skipped_days(self):
        self.set('p', 'u', True, 9, 0)
        # A long gap must yield only a single claim for the current day, never
        # a backlog of one claim per missed day.
        self.assertIs(self.due('p', 'u', self.utc(2026, 1, 10, 9, 30)), True)
        self.assertIs(self.due('p', 'u', self.utc(2026, 1, 10, 9, 31)), False)
        self.assertIs(self.due('p', 'u', self.utc(2026, 2, 1, 23, 0)), True)
        self.assertIs(self.due('p', 'u', self.utc(2026, 2, 1, 23, 1)), False)

    def test_missed_first_day_does_not_accumulate(self):
        self.set('p', 'u', True, 9, 0)
        # Missed the window on day 1 entirely.
        self.assertIs(self.due('p', 'u', self.utc(2026, 1, 1, 8, 0)), False)
        # Days later: exactly one claim for the current day, no catch-up.
        self.assertIs(self.due('p', 'u', self.utc(2026, 1, 5, 10, 0)), True)
        self.assertIs(self.due('p', 'u', self.utc(2026, 1, 5, 11, 0)), False)

    # -- isolation --------------------------------------------------------
    def test_schedule_and_claims_are_isolated_by_persona_and_user(self):
        self.set('p1', 'u1', True, 9, 0)
        self.set('p1', 'u2', True, 9, 0)
        self.set('p2', 'u1', True, 9, 0)
        now = self.utc(2026, 1, 1, 9, 30)

        self.assertIs(self.due('p1', 'u1', now), True)
        self.assertIs(self.due('p1', 'u1', now), False)  # only p1/u1 claimed
        # Other identities are unaffected by p1/u1's claim.
        self.assertIs(self.due('p1', 'u2', now), True)
        self.assertIs(self.due('p2', 'u1', now), True)
        self.assertIs(self.due('p3', 'u1', now), False)  # unknown identity

    def test_disabled_for_one_identity_does_not_affect_another(self):
        self.set('p1', 'u1', True, 9, 0)
        self.set('p1', 'u2', False, 9, 0)
        now = self.utc(2026, 1, 1, 9, 30)
        self.assertIs(self.due('p1', 'u1', now), True)
        self.assertIs(self.due('p1', 'u2', now), False)

    def test_reconfiguring_schedule_takes_effect(self):
        self.set('p', 'u', True, 9, 0)
        self.set('p', 'u', False, 9, 0)
        self.assertIs(self.due('p', 'u', self.utc(2026, 1, 1, 9, 30)), False)
        self.set('p', 'u', True, 10, 0)
        self.assertIs(self.due('p', 'u', self.utc(2026, 1, 1, 9, 30)), False)
        self.assertIs(self.due('p', 'u', self.utc(2026, 1, 1, 10, 30)), True)

    # -- concurrency ------------------------------------------------------
    def test_concurrent_claims_exactly_one_wins(self):
        self.set('p', 'u', True, 9, 0)
        now = self.utc(2026, 1, 1, 9, 30)
        workers = 6
        barrier = threading.Barrier(workers)
        results = [None] * workers
        errors = []

        def attempt(index):
            try:
                conn = self.new_db()
                try:
                    barrier.wait(timeout=10)
                    results[index] = self.due('p', 'u', now, db=conn)
                finally:
                    conn.close()
            except Exception as exc:  # surface failures in the main thread
                errors.append(exc)

        threads = [threading.Thread(target=attempt, args=(i,))
                   for i in range(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)

        self.assertEqual(errors, [])
        self.assertEqual(sum(1 for value in results if value is True), 1)
        # The single claim is committed: later callers still see no due message.
        self.assertIs(self.due('p', 'u', now), False)


    # -- default-on scheduling -------------------------------------------
    def test_default_schedule_is_enabled_random(self):
        ensure_default_schedule(self.db, "p", "u", "Asia/Shanghai")
        row = self.db.execute(
            "SELECT enabled, mode, timezone FROM proactive_schedule "
            "WHERE persona = ? AND user_id = ?",
            ("p", "u"),
        ).fetchone()
        self.assertEqual(row, (1, "random", "Asia/Shanghai"))

    def test_explicit_disable_survives_default_creation(self):
        disable_schedule(self.db, "p", "u", "Asia/Shanghai")
        ensure_default_schedule(self.db, "p", "u", "Asia/Shanghai")
        row = self.db.execute(
            "SELECT enabled FROM proactive_schedule "
            "WHERE persona = ? AND user_id = ?",
            ("p", "u"),
        ).fetchone()
        self.assertEqual(row[0], 0)

    def test_default_schedule_does_not_override_existing_fixed_time(self):
        self.set("p", "u", True, 19, 30)
        ensure_default_schedule(self.db, "p", "u", "UTC")
        row = self.db.execute(
            "SELECT enabled, hour, minute, mode FROM proactive_schedule "
            "WHERE persona = ? AND user_id = ?",
            ("p", "u"),
        ).fetchone()
        self.assertEqual(row, (1, 19, 30, "fixed"))


if __name__ == '__main__':
    unittest.main()
