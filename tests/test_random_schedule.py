import sqlite3
import threading
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from datetime import datetime, timezone
from unittest.mock import patch
from venus.proactive import init_proactive, set_random_schedule, due_and_claim

class RandomScheduleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'db'
        self.db = sqlite3.connect(self.path); self.addCleanup(self.db.close)
        init_proactive(self.db)
        set_random_schedule(self.db, 'p', 'u', True, 'Asia/Shanghai')

    def time(self, day, hour, minute=0):
        from zoneinfo import ZoneInfo
        return datetime(2026,1,day,hour,minute,tzinfo=ZoneInfo('Asia/Shanghai')).astimezone(timezone.utc)

    def test_random_target_survives_reopen_and_claim_once(self):
        with patch('venus.proactive.secrets.randbelow', return_value=120) as rand:
            self.assertFalse(due_and_claim(self.db,'p','u',self.time(1,10)))
            with closing(sqlite3.connect(self.path)) as reopened:
                self.assertFalse(due_and_claim(reopened,'p','u',self.time(1,11,59)))
                self.assertTrue(due_and_claim(reopened,'p','u',self.time(1,12)))
            self.assertFalse(due_and_claim(self.db,'p','u',self.time(1,20,59)))
            self.assertEqual(rand.call_count,1)

    def test_outside_window_no_send_or_late_catchup(self):
        with patch('venus.proactive.secrets.randbelow', return_value=0):
            self.assertFalse(due_and_claim(self.db,'p','u',self.time(1,9,59)))
            self.assertFalse(due_and_claim(self.db,'p','u',self.time(1,21)))
            self.assertTrue(due_and_claim(self.db,'p','u',self.time(2,10)))

    def test_custom_target_window_is_respected(self):
        with patch('venus.proactive.secrets.randbelow', return_value=0):
            window = (18 * 60, 23 * 60 + 30)
            self.assertFalse(due_and_claim(
                self.db, 'p', 'u', self.time(1, 17, 59), target_window=window))
            self.assertTrue(due_and_claim(
                self.db, 'p', 'u', self.time(1, 18), target_window=window))
            self.assertFalse(due_and_claim(
                self.db, 'p', 'u', self.time(1, 23, 30), target_window=window))

    def test_concurrent_random_claims_single_winner(self):
        barrier = threading.Barrier(5)
        results, errors = [], []
        def run():
            try:
                with closing(sqlite3.connect(self.path, timeout=10)) as db:
                    barrier.wait(timeout=5)
                    results.append(due_and_claim(db, 'p', 'u', self.time(1,20,59)))
            except Exception as exc:
                errors.append(exc)
        threads = [threading.Thread(target=run) for _ in range(5)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(10)
        self.assertEqual(errors, [])
        self.assertEqual(results.count(True), 1)
        self.assertEqual(results.count(False), 4)

    def test_old_database_migrates_without_changing_existing_schedule(self):
        with closing(sqlite3.connect(':memory:')) as old:
            old.execute('CREATE TABLE proactive_schedule (persona TEXT NOT NULL, user_id TEXT NOT NULL, enabled INTEGER NOT NULL, hour INTEGER NOT NULL, minute INTEGER NOT NULL, timezone TEXT NOT NULL, PRIMARY KEY (persona,user_id))')
            old.execute("INSERT INTO proactive_schedule VALUES ('p','old',1,19,30,'Asia/Shanghai')")
            old.commit()
            init_proactive(old); init_proactive(old)
            self.assertEqual(old.execute('SELECT mode FROM proactive_schedule').fetchone(), ('fixed',))
            self.assertFalse(due_and_claim(old,'p','old',self.time(1,19,29)))
            self.assertTrue(due_and_claim(old,'p','old',self.time(1,19,30)))

    def test_scope_and_disabled(self):
        set_random_schedule(self.db,'p','v',False,'Asia/Shanghai')
        with patch('venus.proactive.secrets.randbelow', return_value=0):
            self.assertFalse(due_and_claim(self.db,'p','v',self.time(1,10)))
            self.assertFalse(due_and_claim(self.db,'other','u',self.time(1,10)))
            self.assertTrue(due_and_claim(self.db,'p','u',self.time(1,10)))
