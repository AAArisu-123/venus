"""Test-first specification for random proactive scheduling via commands.

These tests describe behaviour the command layer does not implement yet, so
they are expected to be RED until ``/主动 开启`` (no time argument) opts an
identity into random scheduling. Nothing here reads production data,
credentials, ``.env`` files or the network: configuration is observed only
through SQL on a real temporary SQLite database.
"""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from venus.commands import handle_command
from venus.memory import connect_database
from venus.proactive import due_and_claim


PERSONA = 'p'
SHANGHAI = 'Asia/Shanghai'


class RandomScheduleCommandTests(unittest.TestCase):
    """Behaviour of /主动 开启, /主动 关闭 and /帮助 for random mode."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = connect_database(Path(self.tmp.name) / 'data.sqlite3')
        self.addCleanup(self.db.close)

    # ---- helpers: everything is asserted through SQL ---------------------

    def command(self, user, text):
        return handle_command(self.db, PERSONA, user, text)

    def schedule(self, user):
        """Return (enabled, hour, minute, timezone, mode) straight from SQL."""
        return self.db.execute(
            'SELECT enabled, hour, minute, timezone, mode '
            'FROM proactive_schedule WHERE persona = ? AND user_id = ?',
            (PERSONA, user),
        ).fetchone()

    # ---- /主动 开启 with no time -> random --------------------------------

    def test_bare_enable_opts_into_random_mode_in_shanghai(self):
        reply = self.command('alice', '/主动 开启')

        row = self.schedule('alice')
        self.assertIsNotNone(row, 'bare /主动 开启 must persist a schedule')
        enabled, _hour, _minute, timezone_name, mode = row
        self.assertEqual(enabled, 1)
        self.assertEqual(mode, 'random')
        self.assertEqual(timezone_name, SHANGHAI)

        # The reply teaches the user what "random" means in concrete terms.
        for token in ('随机', '19:00', '21:00', '频率', '每天最多 1 次'):
            with self.subTest(token=token):
                self.assertIn(token, reply)

    # ---- /主动 关闭 disables ---------------------------------------------

    def test_disable_turns_the_random_schedule_off(self):
        self.command('alice', '/主动 开启')
        self.assertEqual(self.schedule('alice')[0], 1)

        reply = self.command('alice', '/主动 关闭')

        row = self.schedule('alice')
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 0)
        self.assertIn('关闭', reply)

    # ---- /帮助 advertises the no-time form -------------------------------

    def test_help_shows_bare_enable_without_required_time(self):
        help_text = self.command('alice', '/帮助')

        self.assertIn('/主动', help_text)
        open_lines = [line for line in help_text.splitlines() if '/主动 开启' in line]
        self.assertTrue(open_lines, 'help must mention /主动 开启')
        self.assertTrue(
            any('HH:MM' not in line for line in open_lines),
            'help must show /主动 开启 usable without a required time argument',
        )

    # ---- legacy fixed form stays backward compatible ---------------------

    def test_explicit_time_still_creates_a_fixed_schedule(self):
        reply = self.command('alice', '/主动 开启 19:30')

        row = self.schedule('alice')
        self.assertIsNotNone(row)
        enabled, hour, minute, timezone_name, mode = row
        self.assertEqual(enabled, 1)
        self.assertEqual((hour, minute), (19, 30))
        self.assertEqual(timezone_name, SHANGHAI)
        self.assertEqual(mode, 'fixed')
        self.assertIn('19:30', reply)

        # Backward compatibility also means the old fixed time still fires:
        # 19:30 Asia/Shanghai is 11:30 UTC.
        self.assertTrue(due_and_claim(
            self.db, PERSONA, 'alice',
            datetime(2026, 1, 1, 11, 30, tzinfo=timezone.utc),
        ))

    # ---- changes are scoped; disabling never enables ---------------------

    def test_random_enable_is_scoped_and_disable_does_not_enable_anyone(self):
        # Both identities start from the old fixed-schedule behaviour.
        self.command('alice', '/主动 开启 19:30')
        self.command('bob', '/主动 开启 08:15')
        bob_before = self.schedule('bob')
        self.assertEqual(bob_before[4], 'fixed')

        # Enabling random mode rewrites alice only.
        self.command('alice', '/主动 开启')
        alice_random = self.schedule('alice')
        self.assertEqual(alice_random[4], 'random')
        self.assertEqual(self.schedule('bob'), bob_before)

        # Disabling alice must not flip either identity back on.
        self.command('alice', '/主动 关闭')
        self.assertEqual(self.schedule('alice')[0], 0)
        self.assertEqual(self.schedule('bob'), bob_before)


if __name__ == '__main__':
    unittest.main()
