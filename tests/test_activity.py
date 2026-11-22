import sqlite3
import unittest
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from venus.activity import (
    allowed_today,
    init_activity,
    preferred_local_window,
    record_activity,
)


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        init_activity(self.db)
        self.now = datetime(2026, 1, 6, 12, tzinfo=timezone.utc)

    def test_no_activity_means_no_proactive_message(self):
        self.assertFalse(allowed_today(self.db, 'p', 'u', self.now))

    def test_active_days_enable_daily_and_scope_isolation(self):
        for days in range(4):
            record_activity(
                self.db, 'p', 'u', str(days),
                self.now - timedelta(days=days, hours=5),
            )
        self.assertTrue(allowed_today(self.db, 'p', 'u', self.now))
        self.assertFalse(allowed_today(self.db, 'p', 'other', self.now))
        self.assertFalse(allowed_today(self.db, 'other', 'u', self.now))

    def test_duplicate_event_does_not_inflate_activity(self):
        for _ in range(8):
            record_activity(self.db, 'p', 'u', 'same', self.now)
        self.assertFalse(allowed_today(self.db, 'p', 'u', self.now))

    def test_old_activity_not_counted(self):
        for days in range(8, 13):
            record_activity(self.db, 'p', 'u', str(days),
                            self.now - timedelta(days=days))
        self.assertFalse(allowed_today(self.db, 'p', 'u', self.now))

    def test_single_active_day_waits_six_hours(self):
        record_activity(self.db, 'p', 'u', 'first',
                        self.now - timedelta(hours=6))
        self.assertTrue(allowed_today(self.db, 'p', 'u', self.now))
        record_activity(self.db, 'p', 'u', 'recent',
                        self.now - timedelta(hours=2))
        self.assertFalse(allowed_today(self.db, 'p', 'u', self.now))

    def test_two_active_days_wait_six_hours(self):
        record_activity(self.db, 'p', 'u', 'today',
                        self.now - timedelta(hours=6))
        record_activity(self.db, 'p', 'u', 'yesterday',
                        self.now - timedelta(days=1, hours=6))
        self.assertTrue(allowed_today(self.db, 'p', 'u', self.now))
        record_activity(self.db, 'p', 'u', 'recent',
                        self.now - timedelta(hours=1))
        self.assertFalse(allowed_today(self.db, 'p', 'u', self.now))

    def test_recent_activity_suppresses_daily_message(self):
        for days in range(1, 5):
            record_activity(self.db, 'p', 'u', 'prior-%d' % days,
                            self.now - timedelta(days=days, hours=2))
        self.assertTrue(allowed_today(self.db, 'p', 'u', self.now))
        record_activity(self.db, 'p', 'u', 'now', self.now)
        self.assertFalse(allowed_today(self.db, 'p', 'u', self.now))

    def test_preferred_local_window_is_centred_on_evening_activity(self):
        for days in range(3):
            record_activity(self.db, 'p', 'u', 'evening-%d' % days,
                            self.now - timedelta(days=days))
        start, end = preferred_local_window(
            self.db, 'p', 'u', 'Asia/Shanghai', self.now)
        local = self.now.astimezone(ZoneInfo('Asia/Shanghai'))
        minute = local.hour * 60 + local.minute
        self.assertLessEqual(start, minute)
        self.assertGreater(end, minute)

    def test_preferred_local_window_defaults_without_activity(self):
        self.assertEqual(
            preferred_local_window(
                self.db, 'p', 'u', 'Asia/Shanghai', self.now),
            (18 * 60, 23 * 60 + 30),
        )

    def test_naive_time_rejected(self):
        with self.assertRaises(ValueError):
            record_activity(self.db, 'p', 'u', 'id', datetime(2026, 1, 1))
        with self.assertRaises(ValueError):
            allowed_today(self.db, 'p', 'u', datetime(2026, 1, 1))


if __name__ == '__main__':
    unittest.main()
