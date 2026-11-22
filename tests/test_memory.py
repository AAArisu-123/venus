"""Tests for the independent Venus conversation-memory module."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from venus.memory import connect_database, history, save_turn


class MemoryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.db_path = self.tmp / 'nested' / 'data.sqlite3'
        self.db = connect_database(self.db_path)
        self.addCleanup(self.db.close)

    def reopen(self):
        return connect_database(self.db_path)

    def test_connect_creates_schema_and_parent_directories(self):
        self.assertTrue(self.db_path.is_file())
        objects = dict(self.db.execute(
            "SELECT name, type FROM sqlite_master WHERE type IN ('table', 'index')"
        ).fetchall())
        allowed = {'messages': 'table', 'idx_history': 'index'}
        for name, kind in allowed.items():
            self.assertEqual(objects.get(name), kind)
        columns = [row[1] for row in self.db.execute('PRAGMA table_info(messages)')]
        self.assertEqual(columns, ['id', 'persona', 'user_id', 'role', 'content'])

    def test_reopening_keeps_schema_and_data(self):
        with closing(self.reopen()) as other:
            save_turn(other, 'p', 'u', '你好', '在呢')
        self.assertEqual(history(self.db, 'p', 'u'), [('user', '你好'), ('assistant', '在呢')])

    def test_accepts_string_path(self):
        db_path = self.tmp / 'string_path.sqlite3'
        db = connect_database(str(db_path))
        self.addCleanup(db.close)
        save_turn(db, 'p', 'u', 'hi', 'hello')
        self.assertEqual(history(db, 'p', 'u'), [('user', 'hi'), ('assistant', 'hello')])

    def test_history_is_empty_initially(self):
        self.assertEqual(history(self.db, 'p', 'u'), [])

    def test_history_returns_chronological_role_content_pairs(self):
        save_turn(self.db, 'p', 'u', 'q1', 'a1')
        save_turn(self.db, 'p', 'u', 'q2', 'a2')
        self.assertEqual(
            history(self.db, 'p', 'u'),
            [('user', 'q1'), ('assistant', 'a1'), ('user', 'q2'), ('assistant', 'a2')],
        )

    def test_history_default_limit_is_twenty_most_recent_rows(self):
        for i in range(12):
            save_turn(self.db, 'p', 'u', f'u{i}', f'a{i}')
        expected = []
        for i in range(2, 12):
            expected.extend([('user', f'u{i}'), ('assistant', f'a{i}')])
        self.assertEqual(history(self.db, 'p', 'u'), expected)

    def test_history_explicit_limit_returns_most_recent_in_order(self):
        for i in range(6):
            save_turn(self.db, 'p', 'u', f'u{i}', f'a{i}')
        self.assertEqual(history(self.db, 'p', 'u', limit=3), [
            ('assistant', 'a4'), ('user', 'u5'), ('assistant', 'a5'),
        ])

    def test_history_limit_larger_than_stored_rows(self):
        save_turn(self.db, 'p', 'u', 'q', 'a')
        self.assertEqual(history(self.db, 'p', 'u', limit=100), [('user', 'q'), ('assistant', 'a')])

    def test_history_nonpositive_limit_returns_empty(self):
        save_turn(self.db, 'p', 'u', 'q', 'a')
        for limit in (0, -1):
            with self.subTest(limit=limit):
                self.assertEqual(history(self.db, 'p', 'u', limit=limit), [])

    def test_history_isolated_by_persona_and_user(self):
        save_turn(self.db, 'p1', 'u1', 'p1u1-q', 'p1u1-a')
        save_turn(self.db, 'p1', 'u2', 'p1u2-q', 'p1u2-a')
        save_turn(self.db, 'p2', 'u1', 'p2u1-q', 'p2u1-a')
        self.assertEqual(history(self.db, 'p1', 'u1'), [('user', 'p1u1-q'), ('assistant', 'p1u1-a')])
        self.assertEqual(history(self.db, 'p1', 'u2'), [('user', 'p1u2-q'), ('assistant', 'p1u2-a')])
        self.assertEqual(history(self.db, 'p2', 'u1'), [('user', 'p2u1-q'), ('assistant', 'p2u1-a')])
        self.assertEqual(history(self.db, 'p3', 'u1'), [])

    def test_save_turn_is_atomic(self):
        self.db.execute(
            "CREATE TRIGGER reject_assistant BEFORE INSERT ON messages "
            "WHEN NEW.role = 'assistant' BEGIN SELECT RAISE(ABORT, 'blocked'); END"
        )
        self.db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            save_turn(self.db, 'p', 'u', 'q', 'a')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM messages').fetchone()[0], 0)
        self.assertEqual(history(self.db, 'p', 'u'), [])

    def test_values_are_bound_not_interpolated(self):
        payload = "x'); DROP TABLE messages; --"
        save_turn(self.db, payload, payload, payload, payload)
        self.assertEqual(history(self.db, payload, payload), [('user', payload), ('assistant', payload)])
        self.assertEqual(
            self.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages'").fetchone(),
            ('messages',),
        )

    def test_unicode_roundtrip(self):
        save_turn(self.db, '人设', '用户', '你好', '世界')
        self.assertEqual(history(self.db, '人设', '用户'), [('user', '你好'), ('assistant', '世界')])


if __name__ == '__main__':
    unittest.main()
