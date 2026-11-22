"""Tests for the multi-slot proactive scheduler in :mod:`venus.proactive`."""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from venus.memory import connect_database
from venus.proactive import (
    SLOT_WINDOWS,
    claimed_slots_today,
    init_proactive,
    init_slots,
    set_random_schedule,
    slot_due_and_claim,
)

SHANGHAI = ZoneInfo('Asia/Shanghai')
MORNING_SLOTS = ((9 * 60, 10 * 60),)


class SlotSchedulerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = connect_database(Path(self.tmp.name) / 'data.sqlite3')
        self.addCleanup(self.db.close)
        init_proactive(self.db)
        init_slots(self.db)
        set_random_schedule(self.db, 'p', 'u', True, 'Asia/Shanghai')
        self.day = '2026-01-01'

    # -- helpers ---------------------------------------------------------
    def at(self, hour, minute, day=1):
        return datetime(2026, 1, day, hour, minute,
                        tzinfo=SHANGHAI).astimezone(timezone.utc)

    def pin_target(self, slot, minute, persona='p', user_id='u', day=None):
        self.db.execute(
            'INSERT OR REPLACE INTO proactive_slot_target '
            '(persona, user_id, local_day, slot, minute_of_day) '
            'VALUES (?, ?, ?, ?, ?)',
            (persona, user_id, day or self.day, slot, minute),
        )
        self.db.commit()

    def claimed(self):
        return claimed_slots_today(self.db, 'p', 'u', self.day)

    # -- behaviour -------------------------------------------------------
    def test_claims_once_after_the_slot_target(self):
        self.pin_target(0, 9 * 60 + 10)
        self.assertFalse(slot_due_and_claim(
            self.db, 'p', 'u', self.at(9, 5), slots=MORNING_SLOTS))
        self.assertTrue(slot_due_and_claim(
            self.db, 'p', 'u', self.at(9, 10), slots=MORNING_SLOTS))
        self.assertFalse(slot_due_and_claim(
            self.db, 'p', 'u', self.at(9, 20), slots=MORNING_SLOTS))
        self.assertEqual(self.claimed(), [0])

    def test_outside_every_window_is_never_due(self):
        # 10:45 local falls outside the production evening window.
        self.assertFalse(slot_due_and_claim(self.db, 'p', 'u', self.at(10, 45)))

    def test_disabled_schedule_is_never_due(self):
        set_random_schedule(self.db, 'p', 'u', False, 'Asia/Shanghai')
        self.pin_target(0, 9 * 60)
        self.assertFalse(slot_due_and_claim(
            self.db, 'p', 'u', self.at(9, 10), slots=MORNING_SLOTS))

    def test_daily_cap_stops_extra_slots(self):
        slots = (
            (8 * 60 + 30, 10 * 60 + 30),
            (11 * 60 + 30, 13 * 60 + 30),
            (15 * 60, 17 * 60),
        )
        for slot, minute in ((0, 8 * 60 + 30), (1, 11 * 60 + 30), (2, 15 * 60)):
            self.pin_target(slot, minute)
        self.assertTrue(slot_due_and_claim(
            self.db, 'p', 'u', self.at(8, 40), slots=slots, max_per_day=2))
        self.assertTrue(slot_due_and_claim(
            self.db, 'p', 'u', self.at(11, 40), slots=slots, max_per_day=2))
        self.assertFalse(slot_due_and_claim(
            self.db, 'p', 'u', self.at(15, 10), slots=slots, max_per_day=2))

    def test_min_gap_blocks_two_close_claims(self):
        slots = ((8 * 60, 8 * 60 + 30), (8 * 60 + 35, 9 * 60))
        self.pin_target(0, 8 * 60)
        self.pin_target(1, 8 * 60 + 35)
        self.assertTrue(slot_due_and_claim(
            self.db, 'p', 'u', self.at(8, 20), slots=slots))
        # 20 minutes later the second slot is due by target but too close.
        self.assertFalse(slot_due_and_claim(
            self.db, 'p', 'u', self.at(8, 40), slots=slots))

    def test_other_identity_is_not_affected(self):
        self.pin_target(0, 9 * 60)
        self.assertFalse(slot_due_and_claim(
            self.db, 'p', 'other', self.at(9, 10), slots=MORNING_SLOTS))
        self.assertEqual(claimed_slots_today(self.db, 'p', 'other', self.day), [])

    def test_requires_an_existing_schedule(self):
        self.assertFalse(slot_due_and_claim(self.db, 'p', 'nobody', self.at(9, 10)))

    def test_default_schedule_is_one_evening_slot(self):
        self.assertEqual(SLOT_WINDOWS, ((19 * 60, 21 * 60),))
        self.assertFalse(slot_due_and_claim(self.db, 'p', 'u', self.at(18, 59)))
        self.assertTrue(slot_due_and_claim(self.db, 'p', 'u', self.at(20, 59)))
        self.assertFalse(slot_due_and_claim(self.db, 'p', 'u', self.at(21, 0)))

    def test_each_window_can_claim_before_it_closes(self):
        # One minute before a window closes, any random target chosen for that
        # window has already passed, so the slot must be claimable.
        slots = (
            (8 * 60 + 30, 10 * 60 + 30),
            (11 * 60 + 30, 13 * 60 + 30),
            (15 * 60, 17 * 60),
        )
        for end_hour, end_minute in ((10, 29), (13, 29), (16, 59)):
            with self.subTest(end_hour=end_hour, end_minute=end_minute):
                self.db.execute('DELETE FROM proactive_slot_target')
                self.db.execute('DELETE FROM proactive_slot_claim')
                self.db.commit()
                self.assertTrue(slot_due_and_claim(
                    self.db, 'p', 'u', self.at(end_hour, end_minute),
                    slots=slots))


if __name__ == '__main__':
    unittest.main()
