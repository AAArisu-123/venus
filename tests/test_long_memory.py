"""Tests for long-term memory storage."""

import sqlite3
import unittest

from venus import long_memory

# Contract: list_memories must never grow without bound.
LIST_BOUND = 100

# Contract: content length limits (inclusive bounds).
MAX_CONTENT_LEN = 1000


def _connect(name):
    # isolation_level=None -> autocommit, so writes are visible to other
    # connections sharing the same in-memory database immediately.
    return sqlite3.connect(
        f"file:{name}?mode=memory&cache=shared",
        uri=True,
        isolation_level=None,
        check_same_thread=False,
    )


class LongMemoryTestCase(unittest.TestCase):
    """Base: fresh in-memory db with schema initialized per test."""

    db_name = "base"

    def setUp(self):
        self.db = _connect(self.db_name)
        long_memory.init_memory(self.db)

    def tearDown(self):
        self.db.close()


class TestSchemaAndReturnTypes(LongMemoryTestCase):
    db_name = "schema"

    def test_init_memory_is_idempotent(self):
        # Calling init again must not error or wipe data.
        mid = long_memory.add_memory(self.db, "venus", "alice", "hello")
        long_memory.init_memory(self.db)
        rows = long_memory.list_memories(self.db, "venus", "alice")
        self.assertIn((mid, "hello"), rows)

    def test_add_memory_returns_int_id(self):
        mid = long_memory.add_memory(self.db, "venus", "alice", "first note")
        self.assertIsInstance(mid, int)

    def test_list_memories_shape(self):
        long_memory.add_memory(self.db, "venus", "alice", "one")
        long_memory.add_memory(self.db, "venus", "alice", "two")
        rows = long_memory.list_memories(self.db, "venus", "alice")
        self.assertIsInstance(rows, list)
        for row in rows:
            self.assertIsInstance(row, tuple)
            self.assertEqual(len(row), 2)
            self.assertIsInstance(row[0], int)
            self.assertIsInstance(row[1], str)

    def test_delete_memory_returns_bool(self):
        mid = long_memory.add_memory(self.db, "venus", "alice", "doomed")
        self.assertIsInstance(
            long_memory.delete_memory(self.db, "venus", "alice", mid), bool
        )
        self.assertIsInstance(
            long_memory.delete_memory(self.db, "venus", "alice", 99999), bool
        )


class TestPersistenceAcrossReopen(LongMemoryTestCase):
    db_name = "persist"

    def test_memories_survive_connection_reopen(self):
        mid = long_memory.add_memory(self.db, "venus", "alice", "persisted fact")
        # Shared in-memory databases only persist while a connection remains.
        keeper = _connect(self.db_name)
        self.db.close()
        again = _connect(self.db_name)
        try:
            long_memory.init_memory(again)  # must be safe on existing data
            rows = long_memory.list_memories(again, "venus", "alice")
            self.assertIn((mid, "persisted fact"), rows)
        finally:
            again.close()
        self.db = _connect(self.db_name)
        keeper.close()


class TestIsolation(LongMemoryTestCase):
    db_name = "isolation"

    def test_user_isolation(self):
        long_memory.add_memory(self.db, "venus", "alice", "alice secret")
        long_memory.add_memory(self.db, "venus", "bob", "bob secret")

        alice = long_memory.list_memories(self.db, "venus", "alice")
        bob = long_memory.list_memories(self.db, "venus", "bob")

        self.assertEqual([c for _, c in alice], ["alice secret"])
        self.assertEqual([c for _, c in bob], ["bob secret"])

    def test_persona_isolation(self):
        long_memory.add_memory(self.db, "venus", "alice", "venus view")
        long_memory.add_memory(self.db, "mars", "alice", "mars view")

        venus = long_memory.list_memories(self.db, "venus", "alice")
        mars = long_memory.list_memories(self.db, "mars", "alice")

        self.assertEqual([c for _, c in venus], ["venus view"])
        self.assertEqual([c for _, c in mars], ["mars view"])

    def test_unknown_user_sees_empty_list(self):
        long_memory.add_memory(self.db, "venus", "alice", "only alice")
        self.assertEqual(long_memory.list_memories(self.db, "venus", "nobody"), [])


class TestDeleteScope(LongMemoryTestCase):
    db_name = "delete"

    def test_owner_can_delete_own_memory(self):
        mid = long_memory.add_memory(self.db, "venus", "alice", "temporary")
        self.assertTrue(long_memory.delete_memory(self.db, "venus", "alice", mid))
        self.assertEqual(
            [c for _, c in long_memory.list_memories(self.db, "venus", "alice")],
            [],
        )

    def test_delete_is_id_scoped_not_user_wide(self):
        keep_id = long_memory.add_memory(self.db, "venus", "alice", "keep me")
        drop_id = long_memory.add_memory(self.db, "venus", "alice", "drop me")
        self.assertTrue(long_memory.delete_memory(self.db, "venus", "alice", drop_id))
        remaining = [c for _, c in long_memory.list_memories(self.db, "venus", "alice")]
        self.assertEqual(remaining, ["keep me"])
        self.assertNotIn(keep_id, [drop_id])

    def test_other_user_cannot_delete(self):
        mid = long_memory.add_memory(self.db, "venus", "alice", "alice private")
        self.assertFalse(long_memory.delete_memory(self.db, "venus", "bob", mid))
        # Still there for alice.
        self.assertIn(
            (mid, "alice private"),
            long_memory.list_memories(self.db, "venus", "alice"),
        )

    def test_other_persona_cannot_delete(self):
        mid = long_memory.add_memory(self.db, "venus", "alice", "venus private")
        self.assertFalse(long_memory.delete_memory(self.db, "mars", "alice", mid))
        self.assertIn(
            (mid, "venus private"),
            long_memory.list_memories(self.db, "venus", "alice"),
        )

    def test_delete_unknown_id_returns_false(self):
        long_memory.add_memory(self.db, "venus", "alice", "anchor")
        self.assertFalse(long_memory.delete_memory(self.db, "venus", "alice", 123456))

    def test_double_delete_returns_false(self):
        mid = long_memory.add_memory(self.db, "venus", "alice", "once")
        self.assertTrue(long_memory.delete_memory(self.db, "venus", "alice", mid))
        self.assertFalse(long_memory.delete_memory(self.db, "venus", "alice", mid))


class TestValidation(LongMemoryTestCase):
    db_name = "validation"

    def test_blank_content_rejected(self):
        for blank in ("", "   ", "\t\n  \r"):
            with self.subTest(blank=repr(blank)):
                with self.assertRaises(ValueError):
                    long_memory.add_memory(self.db, "venus", "alice", blank)

    def test_over_max_length_rejected(self):
        with self.assertRaises(ValueError):
            long_memory.add_memory(self.db, "venus", "alice", "x" * (MAX_CONTENT_LEN + 1))

    def test_max_length_accepted(self):
        content = "x" * MAX_CONTENT_LEN
        mid = long_memory.add_memory(self.db, "venus", "alice", content)
        self.assertIn((mid, content), long_memory.list_memories(self.db, "venus", "alice"))

    def test_rejected_add_leaves_no_record(self):
        with self.assertRaises(ValueError):
            long_memory.add_memory(self.db, "venus", "alice", "")
        self.assertEqual(long_memory.list_memories(self.db, "venus", "alice"), [])


class TestHostileUnicodeAndInjection(LongMemoryTestCase):
    db_name = "hostile"

    HOSTILE_SAMPLES = [
        "'; DROP TABLE memories; --",
        "Robert'); DROP TABLE venus_memory;--",
        "\" OR 1=1 --",
        "%s %d {0} {{1}} $_{shell}",
        "‮ ⁦ crafted unicode control chars ⁩ ‪",
        "𠮷😀👨‍👩‍👧‍👦 combined emoji and astral plane",
        "адаптив Cyrillic lookalike of 'adaptive'",
        "　fullwidth spaces\ttab\nnewline\r\n",
        "\x00-ish: zero width \u200b\u200e\u202e mixed",
    ]

    def test_hostile_strings_stored_verbatim_not_executed(self):
        for sample in self.HOSTILE_SAMPLES:
            with self.subTest(sample=sample):
                mid = long_memory.add_memory(self.db, "venus", "alice", sample)
                rows = long_memory.list_memories(self.db, "venus", "alice")
                self.assertIn((mid, sample), rows)

        # Schema must still be intact after all hostile inputs.
        another = long_memory.add_memory(self.db, "venus", "carol", "still works")
        self.assertIsInstance(another, int)

    def test_hostile_strings_isolated_per_user(self):
        long_memory.add_memory(self.db, "venus", "alice", "'; DELETE FROM memories;--")
        long_memory.add_memory(self.db, "venus", "bob", "plain note")
        self.assertEqual(
            [c for _, c in long_memory.list_memories(self.db, "venus", "bob")],
            ["plain note"],
        )

    def test_injection_via_persona_and_user_id_fields(self):
        evil = "x' OR '1'='1"
        mid = long_memory.add_memory(self.db, evil, evil, "payload")
        self.assertIn((mid, "payload"), long_memory.list_memories(self.db, evil, evil))
        # Must not leak into a legitimate persona/user.
        self.assertEqual(long_memory.list_memories(self.db, "venus", "alice"), [])


class TestDuplicates(LongMemoryTestCase):
    db_name = "duplicates"

    def test_duplicate_content_allowed(self):
        id1 = long_memory.add_memory(self.db, "venus", "alice", "same note")
        id2 = long_memory.add_memory(self.db, "venus", "alice", "same note")
        self.assertNotEqual(id1, id2)
        contents = [c for _, c in long_memory.list_memories(self.db, "venus", "alice")]
        self.assertEqual(contents.count("same note"), 2)

    def test_duplicate_ids_never_reused_in_list(self):
        ids = [
            long_memory.add_memory(self.db, "venus", "alice", "dup") for _ in range(3)
        ]
        self.assertEqual(len(set(ids)), 3)


class TestBoundedList(LongMemoryTestCase):
    db_name = "bounded"

    def test_list_never_exceeds_bound(self):
        total = LIST_BOUND + 25
        for i in range(total):
            long_memory.add_memory(self.db, "venus", "alice", f"note {i}")
        rows = long_memory.list_memories(self.db, "venus", "alice")
        self.assertLessEqual(len(rows), LIST_BOUND)

    def test_bounded_list_keeps_recent(self):
        total = LIST_BOUND + 25
        ids = [
            long_memory.add_memory(self.db, "venus", "alice", f"note {i}")
            for i in range(total)
        ]
        rows = long_memory.list_memories(self.db, "venus", "alice")
        returned_ids = {mid for mid, _ in rows}
        # The newest entries must be present within the bound.
        for mid in ids[-LIST_BOUND // 2:]:
            self.assertIn(mid, returned_ids)

    def test_bound_applies_per_user_not_globally(self):
        for i in range(LIST_BOUND + 10):
            long_memory.add_memory(self.db, "venus", "alice", f"a {i}")
            long_memory.add_memory(self.db, "venus", "bob", f"b {i}")
        alice = long_memory.list_memories(self.db, "venus", "alice")
        bob = long_memory.list_memories(self.db, "venus", "bob")
        self.assertLessEqual(len(alice), LIST_BOUND)
        self.assertLessEqual(len(bob), LIST_BOUND)
        a_contents = {c for _, c in alice}
        b_contents = {c for _, c in bob}
        self.assertFalse(a_contents & b_contents)


class TestMetadata(LongMemoryTestCase):
    db_name = "metadata"

    def test_add_memory_stores_metadata(self):
        mid = long_memory.add_memory(
            self.db, "venus", "alice", "喜欢猫",
            category="preference", importance=5, source="auto",
        )
        row = self.db.execute(
            "SELECT category, importance, source, created_at, use_count, active "
            "FROM memories WHERE id = ?",
            (mid,),
        ).fetchone()
        self.assertEqual(row[0], "preference")
        self.assertEqual(row[1], 5)
        self.assertEqual(row[2], "auto")
        self.assertIsInstance(row[3], str)
        self.assertEqual(row[4], 0)
        self.assertEqual(row[5], 1)

    def test_invalid_metadata_is_rejected_before_insert(self):
        cases = (
            {"category": "unknown"},
            {"importance": 0},
            {"importance": 6},
            {"importance": True},
            {"source": ""},
            {"source": "x" * 33},
        )
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    long_memory.add_memory(
                        self.db, "venus", "alice", "content", **kwargs
                    )
        self.assertEqual(long_memory.list_memories(self.db, "venus", "alice"), [])

    def test_touch_is_scoped_and_increments_usage(self):
        mine = long_memory.add_memory(self.db, "venus", "alice", "我的记忆")
        other = long_memory.add_memory(self.db, "venus", "bob", "别人的记忆")
        self.assertEqual(
            long_memory.touch_memories(self.db, "venus", "alice", [mine, other]),
            1,
        )
        self.assertEqual(
            self.db.execute(
                "SELECT use_count FROM memories WHERE id = ?", (mine,)
            ).fetchone()[0],
            1,
        )
        self.assertEqual(
            self.db.execute(
                "SELECT use_count FROM memories WHERE id = ?", (other,)
            ).fetchone()[0],
            0,
        )

    def test_list_memories_skips_inactive_rows(self):
        mid = long_memory.add_memory(self.db, "venus", "alice", "旧记忆")
        self.db.execute("UPDATE memories SET active = 0 WHERE id = ?", (mid,))
        self.db.commit()
        self.assertEqual(long_memory.list_memories(self.db, "venus", "alice"), [])


if __name__ == "__main__":
    unittest.main()
