"""Tests for the companion's own small "life notes"."""

import tempfile
import unittest
from pathlib import Path

from venus.life import add_life, init_life, life_summary, recent_life
from venus.memory import connect_database


class LifeNoteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = connect_database(Path(self.tmp.name) / 'data.sqlite3')
        self.addCleanup(self.db.close)
        init_life(self.db)

    def test_blank_notes_are_ignored(self):
        self.assertFalse(add_life(self.db, 'p', 'u', '2026-01-01', '   '))
        self.assertEqual(recent_life(self.db, 'p', 'u'), [])

    def test_immediate_duplicates_are_skipped(self):
        self.assertTrue(add_life(self.db, 'p', 'u', '2026-01-01', '在家煮火锅'))
        self.assertFalse(add_life(self.db, 'p', 'u', '2026-01-01', '在家煮火锅'))
        self.assertEqual(len(recent_life(self.db, 'p', 'u')), 1)

    def test_notes_are_scoped_per_identity(self):
        add_life(self.db, 'p', 'u', '2026-01-01', '在家煮火锅')
        add_life(self.db, 'p', 'other', '2026-01-01', '别人的事')
        self.assertEqual([c for _, c in recent_life(self.db, 'p', 'u')], ['在家煮火锅'])

    def test_long_notes_are_clipped(self):
        add_life(self.db, 'p', 'u', '2026-01-01', '长' * 500)
        self.assertLessEqual(len(recent_life(self.db, 'p', 'u')[0][1]), 200)

    def test_recent_notes_are_newest_first(self):
        add_life(self.db, 'p', 'u', '2026-01-01', '昨天的小事')
        add_life(self.db, 'p', 'u', '2026-01-02', '今天的小事')
        self.assertEqual(
            [c for _, c in recent_life(self.db, 'p', 'u')],
            ['今天的小事', '昨天的小事'],
        )

    def test_summary_labels_today_and_yesterday(self):
        add_life(self.db, 'p', 'u', '2026-01-01', '昨晚熬夜看比赛')
        add_life(self.db, 'p', 'u', '2026-01-02', '今天在煮火锅')
        text = life_summary(self.db, 'p', 'u', today='2026-01-02')
        self.assertIn('今天：今天在煮火锅', text)
        self.assertIn('昨天：昨晚熬夜看比赛', text)

    def test_empty_summary_is_empty_string(self):
        self.assertEqual(life_summary(self.db, 'p', 'u', today='2026-01-02'), '')

    def test_notes_between_yesterday_and_a_week_are_labelled_recently(self):
        add_life(self.db, 'p', 'u', '2026-01-01', '看比赛')
        text = life_summary(self.db, 'p', 'u', today='2026-01-04')
        self.assertIn('前几天：看比赛', text)

    def test_stale_notes_are_left_out_of_the_summary(self):
        add_life(self.db, 'p', 'u', '2025-12-01', '上个月的事')
        self.assertEqual(life_summary(self.db, 'p', 'u', today='2026-01-04'), '')

    def test_unparseable_day_falls_back_to_the_raw_label(self):
        add_life(self.db, 'p', 'u', 'not-a-day', '手工写入的记录')
        text = life_summary(self.db, 'p', 'u', today='2026-01-04')
        self.assertIn('not-a-day：手工写入的记录', text)


if __name__ == '__main__':
    unittest.main()
