import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from venus.memory import connect_database
from venus.long_memory import add_memory, delete_memory, init_memory, touch_memories
from venus.memory_recall import recall

class RecallTests(unittest.TestCase):
    def test_recall_relevance_and_isolation_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            with closing(connect_database(Path(tmp)/'db')) as db:
                init_memory(db)
                tea = add_memory(db,'p','a','我喜欢红茶')
                add_memory(db,'p','a','喜欢小猫')
                add_memory(db,'p','b','红茶秘密')
                db.commit()
                self.assertEqual(recall(db,'p','a','红茶怎么样',limit=5),[(tea,'我喜欢红茶')])
                self.assertEqual(recall(db,'p','b','小猫',limit=5),[])
                self.assertEqual(recall(db,'p','a','',limit=5),[])
                delete_memory(db,'p','a',tea)
                self.assertEqual(recall(db,'p','a','红茶',limit=5),[])

    def test_old_relevant_memory_is_not_excluded_by_recent_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            with closing(connect_database(Path(tmp)/'db')) as db:
                init_memory(db)
                ident = add_memory(db,'p','u','过去喜欢摄影')
                for i in range(120): add_memory(db,'p','u',f'记录 {i}')
                self.assertEqual(recall(db,'p','u','摄影',limit=5),[(ident,'过去喜欢摄影')])

    def test_importance_breaks_equal_relevance_ties(self):
        with closing(sqlite3.connect(':memory:')) as db:
            init_memory(db)
            now = datetime.now(timezone.utc).isoformat(timespec='seconds')
            low = add_memory(db, 'p', 'u', '红茶低重要', importance=1, created_at=now)
            high = add_memory(db, 'p', 'u', '红茶高重要', importance=5, created_at=now)
            self.assertEqual(
                [mid for mid, _ in recall(db, 'p', 'u', '红茶', limit=5)],
                [high, low],
            )

    def test_recency_breaks_equal_importance_ties(self):
        with closing(sqlite3.connect(':memory:')) as db:
            init_memory(db)
            now = datetime.now(timezone.utc)
            old = add_memory(
                db, 'p', 'u', '红茶旧事', created_at=(now - timedelta(days=90)).isoformat(),
            )
            new = add_memory(db, 'p', 'u', '红茶新事', created_at=now.isoformat())
            self.assertEqual(
                [mid for mid, _ in recall(db, 'p', 'u', '红茶', limit=5)],
                [new, old],
            )

    def test_usage_breaks_remaining_ties(self):
        with closing(sqlite3.connect(':memory:')) as db:
            init_memory(db)
            now = datetime.now(timezone.utc).isoformat(timespec='seconds')
            first = add_memory(db, 'p', 'u', '红茶一', created_at=now)
            second = add_memory(db, 'p', 'u', '红茶二', created_at=now)
            touch_memories(db, 'p', 'u', [first], now=now)
            self.assertEqual(
                [mid for mid, _ in recall(db, 'p', 'u', '红茶', limit=5)],
                [first, second],
            )

    def test_inactive_memory_is_not_recalled(self):
        with closing(sqlite3.connect(':memory:')) as db:
            init_memory(db)
            ident = add_memory(db, 'p', 'u', '我喜欢红茶')
            db.execute('UPDATE memories SET active = 0 WHERE id = ?', (ident,))
            db.commit()
            self.assertEqual(recall(db, 'p', 'u', '红茶', limit=5), [])

    def test_legacy_schema_is_migrated_without_losing_rows(self):
        with closing(sqlite3.connect(':memory:')) as db:
            db.execute(
                'CREATE TABLE memories ('
                'id INTEGER PRIMARY KEY AUTOINCREMENT, '
                'persona TEXT NOT NULL, '
                'user_id TEXT NOT NULL, '
                'content TEXT NOT NULL)'
            )
            db.execute(
                "INSERT INTO memories(persona, user_id, content) "
                "VALUES ('p', 'u', '旧记忆红茶')"
            )
            db.commit()
            init_memory(db)
            columns = {row[1] for row in db.execute('PRAGMA table_info(memories)')}
            self.assertTrue({
                'category', 'importance', 'source', 'created_at',
                'last_used_at', 'use_count', 'active',
            } <= columns)
            self.assertEqual(
                [content for _, content in recall(db, 'p', 'u', '红茶', limit=5)],
                ['旧记忆红茶'],
            )
