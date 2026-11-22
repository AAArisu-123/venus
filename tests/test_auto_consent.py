import unittest
import sqlite3
from venus.auto_memory import remember_candidates, set_auto_enabled, is_auto_enabled
from venus.long_memory import init_memory, list_memories

class AutoConsentTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        init_memory(self.db)

    def test_default_on_and_explicit_off_is_isolated(self):
        self.assertTrue(is_auto_enabled(self.db, 'p', 'a'))
        self.assertTrue(is_auto_enabled(self.db, 'p', 'b'))
        set_auto_enabled(self.db, 'p', 'a', False)
        self.assertFalse(is_auto_enabled(self.db, 'p', 'a'))
        self.assertTrue(is_auto_enabled(self.db, 'p', 'b'))
        set_auto_enabled(self.db, 'p', 'a', True)
        self.assertTrue(is_auto_enabled(self.db, 'p', 'a'))
