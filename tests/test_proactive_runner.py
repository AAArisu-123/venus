import asyncio
import unittest
from datetime import datetime, timezone, timedelta
from venus.activity import init_activity, record_activity
from unittest.mock import AsyncMock, patch
from contextlib import closing
import tempfile
from pathlib import Path

from venus.memory import connect_database
from venus.proactive import init_proactive, set_schedule
from venus.proactive_runner import _extend_window, loop_forever, tick


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'data.db'
        with closing(connect_database(self.path)) as db:
            init_proactive(db)
            set_schedule(db, 'persona', 'alice', True, 9, 0, 'UTC')
        self.now = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
        with closing(connect_database(self.path)) as db:
            init_activity(db)
            for i in range(4):
                record_activity(
                    db, 'persona', 'alice', str(i),
                    self.now - timedelta(days=i, hours=5),
                )

    def test_passed_window_moves_to_evening(self):
        self.assertEqual(
            _extend_window((14 * 60 + 31, 17 * 60 + 31), 17 * 60 + 45),
            (18 * 60, 23 * 60 + 30),
        )
        self.assertEqual(
            _extend_window((14 * 60 + 31, 17 * 60 + 31), 15 * 60),
            (14 * 60 + 31, 17 * 60 + 31),
        )

    async def test_due_send_once(self):
        send = AsyncMock()
        await tick(self.path, 'persona', send, self.now)
        await tick(self.path, 'persona', send, self.now)
        self.assertEqual(send.await_count, 1)
        args, kwargs = send.await_args
        self.assertEqual(kwargs['openid'], 'alice')
        self.assertEqual(kwargs['msg_type'], 0)
        self.assertTrue(kwargs['content'])
        self.assertNotIn('msg_id', kwargs)

    async def test_loop_survives_a_tick_error(self):
        calls = []

        async def fake_tick(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError('boom')
            raise asyncio.CancelledError()

        with patch('venus.proactive_runner.tick', side_effect=fake_tick):
            with self.assertRaises(asyncio.CancelledError):
                await loop_forever('x', 'persona', AsyncMock(), interval=0)
        self.assertEqual(len(calls), 2)

    async def test_no_retry_after_ambiguous_send(self):
        send = AsyncMock(side_effect=TimeoutError())
        await tick(self.path, 'persona', send, self.now)
        await tick(self.path, 'persona', send, self.now)
        self.assertEqual(send.await_count, 1)

    async def test_unauthorized_recipient_is_not_claimed_or_sent(self):
        send = AsyncMock()
        await tick(self.path, 'persona', send, self.now, authorized=lambda _: False)
        send.assert_not_awaited()
        await tick(self.path, 'persona', send, self.now, authorized=lambda _: True)
        self.assertEqual(send.await_count, 1)

    async def test_disabled_not_sent(self):
        with closing(connect_database(self.path)) as db:
            set_schedule(db, 'persona', 'alice', False, 9, 0, 'UTC')
        send = AsyncMock()
        await tick(self.path, 'persona', send, self.now)
        send.assert_not_awaited()
