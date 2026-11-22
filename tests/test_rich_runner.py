"""End-to-end tests for multi-slot openers and quiet-conversation follow-ups."""

import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

from venus.activity import init_activity, record_activity
from venus.life import init_life
from venus.memory import connect_database
from venus.presence import (
    init_presence,
    note_assistant_message,
    note_user_message,
    presence_snapshot,
)
from venus.proactive import init_proactive, init_slots, set_random_schedule
from venus.proactive_runner import followup_tick, tick

# 20:00 Beijing time: inside the evening slot (19:00-21:00) and the waking
# window.
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
LOCAL_DAY = '2026-01-01'


class RichRunnerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'data.sqlite3'
        with closing(connect_database(self.path)) as db:
            init_proactive(db)
            init_slots(db)
            init_activity(db)
            init_presence(db)
            init_life(db)
            set_random_schedule(db, 'p', 'u', True, 'Asia/Shanghai')
            # The user chatted seven hours ago, so an opener is not interruptive.
            record_activity(db, 'p', 'u', 'e1', NOW - timedelta(hours=7))
            db.execute(
                'INSERT OR REPLACE INTO proactive_slot_target '
                '(persona, user_id, local_day, slot, minute_of_day) '
                'VALUES (?, ?, ?, ?, ?)',
                ('p', 'u', LOCAL_DAY, 0, 19 * 60),
            )
            db.commit()

    async def test_opener_sends_once_and_stores_the_life_note(self):
        send = AsyncMock()
        generate = AsyncMock(return_value={
            'message': '在煮火锅，你要不要来蹭一口',
            'life': '晚上在家煮火锅',
        })
        await tick(self.path, 'p', send, NOW, generate=generate)
        await tick(self.path, 'p', send, NOW, generate=generate)
        self.assertEqual(send.await_count, 1)
        self.assertEqual(send.await_args.kwargs['content'],
                         '在煮火锅，你要不要来蹭一口')
        with closing(connect_database(self.path)) as db:
            init_life(db)
            self.assertEqual(
                [c for _, c in db.execute('SELECT local_day, content FROM life_log')],
                ['晚上在家煮火锅'],
            )
            row = db.execute(
                "SELECT content FROM messages WHERE role = 'assistant'").fetchone()
            self.assertEqual(row[0], '在煮火锅，你要不要来蹭一口')
            self.assertEqual(presence_snapshot(db, 'p', 'u')['assistant_streak'], 1)

    async def test_plain_string_generator_still_works(self):
        send = AsyncMock()
        await tick(self.path, 'p', send, NOW, generate=AsyncMock(return_value='嗨'))
        self.assertEqual(send.await_count, 1)
        with closing(connect_database(self.path)) as db:
            self.assertEqual(
                db.execute('SELECT COUNT(*) FROM life_log').fetchone()[0], 0)

    async def test_live_chat_is_not_interrupted(self):
        with closing(connect_database(self.path)) as db:
            record_activity(db, 'p', 'u', 'e2', NOW - timedelta(minutes=5))
            db.commit()
        send = AsyncMock()
        await tick(self.path, 'p', send, NOW,
                   generate=AsyncMock(return_value='在吗'))
        send.assert_not_awaited()

    async def test_generation_failure_is_logged_without_leaking_details(self):
        send = AsyncMock()

        def boom(_user_id):
            raise RuntimeError('secret-prompt-text')

        with self.assertLogs('venus.proactive_runner', level='WARNING') as logs:
            await tick(self.path, 'p', send, NOW,
                       generate=AsyncMock(side_effect=boom))
        send.assert_not_awaited()
        text = '\n'.join(logs.output)
        self.assertIn('generation failed', text)
        self.assertIn('RuntimeError', text)
        self.assertNotIn('secret-prompt-text', text)

    async def test_send_failure_is_logged_and_nothing_is_persisted(self):
        send = AsyncMock(side_effect=RuntimeError('qq rejected'))
        with self.assertLogs('venus.proactive_runner', level='WARNING') as logs:
            await tick(self.path, 'p', send, NOW,
                       generate=AsyncMock(return_value='在吗'))
        self.assertIn('send failed', '\n'.join(logs.output))
        with closing(connect_database(self.path)) as db:
            self.assertEqual(
                db.execute('SELECT COUNT(*) FROM messages').fetchone()[0], 0)

    async def test_followup_is_sent_once_after_a_quiet_gap(self):
        with closing(connect_database(self.path)) as db:
            note_user_message(db, 'p', 'u', NOW - timedelta(minutes=60))
            note_assistant_message(db, 'p', 'u', NOW - timedelta(minutes=50))
        send = AsyncMock()
        generate = AsyncMock(return_value={'message': '还在吗', 'life': ''})
        await followup_tick(self.path, 'p', send, NOW, generate=generate)
        self.assertEqual(send.await_count, 1)
        with closing(connect_database(self.path)) as db:
            self.assertEqual(
                presence_snapshot(db, 'p', 'u')['assistant_streak'], 2)
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM messages WHERE role = 'assistant'"
                ).fetchone()[0], 1)
        # Two unanswered assistant turns are the limit: no third message.
        await followup_tick(self.path, 'p', send, NOW, generate=generate)
        self.assertEqual(send.await_count, 1)

    async def test_followup_without_a_generator_does_nothing(self):
        with closing(connect_database(self.path)) as db:
            note_user_message(db, 'p', 'u', NOW - timedelta(minutes=60))
            note_assistant_message(db, 'p', 'u', NOW - timedelta(minutes=50))
        send = AsyncMock()
        await followup_tick(self.path, 'p', send, NOW)
        send.assert_not_awaited()

    async def test_followup_respects_a_disabled_schedule(self):
        with closing(connect_database(self.path)) as db:
            set_random_schedule(db, 'p', 'u', False, 'Asia/Shanghai')
            note_user_message(db, 'p', 'u', NOW - timedelta(minutes=60))
            note_assistant_message(db, 'p', 'u', NOW - timedelta(minutes=50))
        send = AsyncMock()
        await followup_tick(self.path, 'p', send, NOW,
                            generate=AsyncMock(return_value='在吗'))
        send.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
