"""Tests for the /修改记忆 command."""

import tempfile
import unittest
from pathlib import Path

from venus.commands import handle_command
from venus.long_memory import MAX_CONTENT_LEN, add_memory, init_memory, list_memories
from venus.memory import connect_database


PERSONA = "p"
USER = "alice"


class MemoryCorrectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "data.db"
        self.db = connect_database(self.db_path)
        self.addCleanup(self.db.close)
        init_memory(self.db)

    def _seed(self, content, persona=PERSONA, user=USER):
        """Store one memory directly on the temp DB and return its id."""
        return add_memory(self.db, persona, user, content)

    def _rows(self, persona=PERSONA, user=USER):
        return list_memories(self.db, persona, user)

    def _correct(self, command, persona=PERSONA, user=USER):
        return handle_command(self.db, persona, user, command)

    def test_correct_updates_own_memory_in_place_with_same_id(self):
        mid = self._seed("旧内容")
        reply = self._correct(f"/修改记忆 {mid} 新内容")
        self.assertIsInstance(reply, str)
        # One row, the very same id, with the new content: an in-place
        # UPDATE, never a delete + insert that would mint a fresh id.
        self.assertEqual(self._rows(), [(mid, "新内容")])

    def test_correct_survives_close_and_reopen(self):
        mid = self._seed("旧内容")
        self._correct(f"/修改记忆 {mid} 跨连接的新内容")
        # Closing without an explicit commit must not lose the correction:
        # the command has to persist it to the on-disk database.
        self.db.close()
        reopened = connect_database(self.db_path)
        self.addCleanup(reopened.close)
        self.assertEqual(
            list_memories(reopened, PERSONA, USER),
            [(mid, "跨连接的新内容")],
        )

    def test_other_user_and_other_persona_cannot_correct(self):
        mid = self._seed("原文")
        for persona, user in ((PERSONA, "bob"), ("q", USER)):
            with self.subTest(persona=persona, user=user):
                reply = self._correct(
                    f"/修改记忆 {mid} 被篡改", persona=persona, user=user
                )
                self.assertIsInstance(reply, str)
                # The owner's entry is untouched ...
                self.assertEqual(self._rows(), [(mid, "原文")])
                # ... and no new entry leaks into the intruder's scope.
                self.assertEqual(self._rows(persona, user), [])

    def test_rejects_missing_and_blank_content(self):
        mid = self._seed("保持原样")
        bad_commands = (
            "/修改记忆",                # no id and no content
            f"/修改记忆 {mid}",         # id but no content
            f"/修改记忆 {mid}   ",      # blank content (stripped to id-only)
            "/修改记忆 abc 新内容",      # non-numeric id
        )
        for command in bad_commands:
            with self.subTest(command=command):
                reply = self._correct(command)
                self.assertIsInstance(reply, str)
                self.assertEqual(self._rows(), [(mid, "保持原样")])

    def test_rejects_content_over_limit(self):
        mid = self._seed("未超限")
        too_long = "x" * (MAX_CONTENT_LEN + 1)
        reply = self._correct(f"/修改记忆 {mid} {too_long}")
        self.assertIsInstance(reply, str)
        self.assertEqual(self._rows(), [(mid, "未超限")])

    def test_accepts_content_at_limit(self):
        mid = self._seed("短")
        at_limit = "y" * MAX_CONTENT_LEN
        reply = self._correct(f"/修改记忆 {mid} {at_limit}")
        self.assertIsInstance(reply, str)
        self.assertEqual(self._rows(), [(mid, at_limit)])

    def test_help_mentions_correct_command(self):
        self.assertIn("/修改记忆", self._correct("/帮助"))

    def test_list_reflects_correction(self):
        mid = self._seed("错误内容")
        self._correct(f"/修改记忆 {mid} 正确内容")
        listing = self._correct("/记忆")
        self.assertIn("正确内容", listing)
        self.assertNotIn("错误内容", listing)


if __name__ == "__main__":
    unittest.main()
