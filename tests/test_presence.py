"""Tests for presence tracking and quiet-conversation follow-ups."""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from venus.memory import connect_database
from venus.presence import (
    claim_followup,
    followup_due,
    init_presence,
    note_assistant_message,
    note_user_message,
    presence_snapshot,
)

# 20:00 in Shanghai, inside the default wake window.
BASE = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


class PresenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = connect_database(Path(self.tmp.name) / 'data.sqlite3')
        self.addCleanup(self.db.close)
        init_presence(self.db)

    # -- helpers ---------------------------------------------------------
    def conversation(self, user='u'):
        note_user_message(self.db, 'p', user, BASE)
        note_assistant_message(self.db, 'p', user, BASE + timedelta(minutes=1))

    def later(self, minutes):
        return BASE + timedelta(minutes=minutes)

    # -- recording -------------------------------------------------------
    def test_user_message_resets_the_unanswered_streak(self):
        self.conversation()
        note_assistant_message(self.db, 'p', 'u', BASE + timedelta(minutes=2))
        self.assertEqual(presence_snapshot(self.db, 'p', 'u')['assistant_streak'], 2)
        note_user_message(self.db, 'p', 'u', BASE + timedelta(minutes=3))
        self.assertEqual(presence_snapshot(self.db, 'p', 'u')['assistant_streak'], 0)

    def test_identities_are_isolated(self):
        self.conversation()
        self.assertIsNone(presence_snapshot(self.db, 'p', 'other'))

    # -- follow-up timing ------------------------------------------------
    def test_no_followup_before_the_minimum_silence(self):
        self.conversation()
        self.assertFalse(followup_due(self.db, 'p', 'u', self.later(20)))
        self.assertTrue(followup_due(self.db, 'p', 'u', self.later(40)))

    def test_no_followup_when_the_user_spoke_last(self):
        self.conversation()
        note_user_message(self.db, 'p', 'u', BASE + timedelta(minutes=2))
        self.assertFalse(followup_due(self.db, 'p', 'u', self.later(60)))

    def test_two_unanswered_assistant_turns_stop_followups(self):
        self.conversation()
        note_assistant_message(self.db, 'p', 'u', BASE + timedelta(minutes=2))
        self.assertFalse(followup_due(self.db, 'p', 'u', self.later(60)))

    def test_no_followup_outside_the_wake_window(self):
        # 03:00 Shanghai is outside the human waking window.
        night = datetime(2025, 12, 31, 19, 0, tzinfo=timezone.utc)
        note_user_message(self.db, 'p', 'u', night)
        note_assistant_message(self.db, 'p', 'u', night + timedelta(minutes=1))
        self.assertFalse(followup_due(
            self.db, 'p', 'u', night + timedelta(minutes=40)))

    def test_unknown_identity_is_never_due(self):
        self.assertFalse(followup_due(self.db, 'p', 'nobody', self.later(120)))

    # -- claiming and caps ----------------------------------------------
    def test_claim_records_the_day_and_counter(self):
        self.conversation()
        self.assertTrue(claim_followup(self.db, 'p', 'u', self.later(40)))
        snapshot = presence_snapshot(self.db, 'p', 'u')
        self.assertEqual(snapshot['follows_today'], 1)
        self.assertEqual(snapshot['follows_day'], '2026-01-01')

    def test_second_claim_in_the_same_minute_is_blocked_by_the_gap(self):
        self.conversation()
        self.assertTrue(claim_followup(self.db, 'p', 'u', self.later(40)))
        self.assertFalse(claim_followup(self.db, 'p', 'u', self.later(41)))

    def test_followups_are_capped_per_day(self):
        self.conversation()
        self.assertTrue(claim_followup(self.db, 'p', 'u', self.later(40)))
        self.assertTrue(claim_followup(self.db, 'p', 'u', self.later(80)))
        self.assertTrue(claim_followup(self.db, 'p', 'u', self.later(120)))
        self.assertFalse(claim_followup(self.db, 'p', 'u', self.later(160)))

    def test_cap_is_reset_on_a_new_local_day(self):
        self.conversation()
        for minutes in (40, 80, 120):
            self.assertTrue(claim_followup(self.db, 'p', 'u', self.later(minutes)))
        next_day = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)
        self.assertTrue(claim_followup(self.db, 'p', 'u', next_day + timedelta(minutes=40)))


if __name__ == '__main__':
    unittest.main()
