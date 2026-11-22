"""Tests for the intended generation-aware venus.proactive_runner.tick().

Contract under test (the "generation" addition):

``tick(path, persona, send, now, authorized=None, generate=None)`` is async.
``generate`` is an async callable that takes ONLY ``user_id`` and returns a
generated opener string. For each enabled persona/user whose schedule is due
and whose activity allows a message today, tick must:

* call ``await generate(user_id)`` and deliver the returned content via
  ``send``,
* after ``await send`` *succeeds*, persist ONLY an assistant row to the
  (persona, user_id)-scoped short-term history -- no fabricated user turn,
* deliver at most once per local day (a later tick that day neither generates
  nor sends again),
* on generation failure or blank output: send nothing, persist nothing and do
  not retry that day,
* on an ambiguous transport failure (e.g. timeout): persist nothing and do not
  retry that day,
* when the schedule is disabled or ``authorized`` rejects the identity: do
  neither generate nor send.

Only a real temporary SQLite database is used; no network, credentials, .env
or production data are touched. Tests run on the isolated asyncio test case
and use plain fake async callables.
"""

import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from venus.activity import init_activity, record_activity
from venus.memory import connect_database, history
from venus.proactive import init_proactive, set_schedule
from venus.proactive_runner import tick


PERSONA = 'persona'
USER = 'alice'
OTHER_USER = 'bob'
GENERATED = '今晚的月亮很好，你在忙什么呢'
OTHER_SCOPE_MARKER = 'OTHER_SCOPE_MARKER_不该变化'


class GeneratedRunnerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.now = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
        self._counter = 0
        self.path = self._fresh_db()

    def _fresh_db(self):
        """Create and seed a fresh on-disk SQLite db with schedule + activity."""
        path = Path(self._tmp.name) / ('data-%d.db' % self._counter)
        self._counter += 1
        with closing(connect_database(path)) as db:
            init_proactive(db)
            set_schedule(db, PERSONA, USER, True, 9, 0, 'UTC')
            # A marker in another user's scope; must never be touched.
            db.execute(
                'INSERT INTO messages(persona, user_id, role, content) '
                'VALUES (?, ?, ?, ?)',
                (PERSONA, OTHER_USER, 'assistant', OTHER_SCOPE_MARKER),
            )
            init_activity(db)
            # Four distinct active days, last message long enough ago.
            for i in range(4):
                record_activity(db, PERSONA, USER, 'act-%d' % i,
                                self.now - timedelta(days=i, hours=5))
        return path

    @staticmethod
    def _content_of(call):
        kwargs = call['kwargs']
        if 'content' in kwargs:
            return kwargs['content']
        args = call['args']
        return args[2] if len(args) >= 3 else None

    def make_send(self, error=None):
        calls = []

        async def send(*args, **kwargs):
            calls.append({'args': args, 'kwargs': kwargs})
            if error is not None:
                raise error
            return 'ok'

        return send, calls

    def make_generate(self, content=GENERATED, error=None):
        calls = []

        async def generate(user_id):
            calls.append(user_id)
            if error is not None:
                raise error
            return content

        return generate, calls

    def _messages(self, path):
        with closing(connect_database(path)) as db:
            return db.execute(
                'SELECT persona, user_id, role, content FROM messages'
            ).fetchall()

    def _history(self, path, persona=PERSONA, user=USER):
        with closing(connect_database(path)) as db:
            return history(db, persona, user)

    def _only_other_scope_message(self, path):
        return self._messages(path) == [
            (PERSONA, OTHER_USER, 'assistant', OTHER_SCOPE_MARKER)
        ]

    # -- generated content: delivered then saved assistant-only ----------
    async def test_generated_content_sent_then_saved_assistant_only(self):
        send, sent = self.make_send()
        generate, generated = self.make_generate()

        await tick(self.path, PERSONA, send, self.now, generate=generate)

        self.assertEqual(generated, [USER])
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]['kwargs'].get('openid'), USER)
        self.assertEqual(sent[0]['kwargs'].get('msg_type'), 0)
        self.assertEqual(self._content_of(sent[0]), GENERATED)

        # Scoped history holds exactly one assistant turn and no fake user text.
        self.assertEqual(self._history(self.path), [('assistant', GENERATED)])
        rows = self._messages(self.path)
        self.assertEqual([r for r in rows if r[1] == USER and r[2] == 'user'], [])
        self.assertEqual(
            [r for r in rows if r[1] == USER],
            [(PERSONA, USER, 'assistant', GENERATED)],
        )
        self.assertIn((PERSONA, OTHER_USER, 'assistant', OTHER_SCOPE_MARKER), rows)

    # -- a second tick the same day does nothing -------------------------
    async def test_duplicate_tick_does_not_generate_or_send_again(self):
        send, sent = self.make_send()
        generate, generated = self.make_generate()

        for _ in range(3):
            await tick(self.path, PERSONA, send, self.now, generate=generate)

        self.assertEqual(generated, [USER])
        self.assertEqual(len(sent), 1)
        self.assertEqual(self._history(self.path), [('assistant', GENERATED)])

    # -- generation failure: no send, no history, no same-day retry ------
    async def test_generation_failure_no_send_no_history_no_retry(self):
        send, sent = self.make_send()
        generate, generated = self.make_generate(
            error=RuntimeError('generation boom TOKEN=secret'))

        for _ in range(2):
            await tick(self.path, PERSONA, send, self.now, generate=generate)

        self.assertEqual(generated, [USER])
        self.assertEqual(sent, [])
        self.assertTrue(self._only_other_scope_message(self.path))

    # -- blank generation: no send, no history, no same-day retry --------
    async def test_blank_generation_no_send_no_history_no_retry(self):
        for blank in ('', '   \n ', '\t'):
            with self.subTest(blank=blank):
                path = self._fresh_db()
                send, sent = self.make_send()
                generate, generated = self.make_generate(content=blank)

                for _ in range(2):
                    await tick(path, PERSONA, send, self.now, generate=generate)

                self.assertEqual(generated, [USER])
                self.assertEqual(sent, [])
                self.assertTrue(self._only_other_scope_message(path))

    # -- ambiguous transport: no history, no retry -----------------------
    async def test_ambiguous_send_timeout_no_history_no_retry(self):
        send, sent = self.make_send(error=TimeoutError())
        generate, generated = self.make_generate()

        for _ in range(2):
            await tick(self.path, PERSONA, send, self.now, generate=generate)

        self.assertEqual(generated, [USER])
        self.assertEqual(len(sent), 1)
        self.assertEqual(self._history(self.path), [])
        self.assertTrue(self._only_other_scope_message(self.path))

    async def test_opt_out_during_generation_prevents_send(self):
        send, sent = self.make_send()
        async def generate(user_id):
            with closing(connect_database(self.path)) as db:
                set_schedule(db, PERSONA, USER, False, 9, 0, 'UTC')
            return GENERATED
        await tick(self.path, PERSONA, send, self.now, generate=generate)
        self.assertEqual(sent, [])
        self.assertEqual(self._history(self.path), [])

    # -- disabled schedule: no generation, no send -----------------------
    async def test_disabled_schedule_no_generation_or_send(self):
        with closing(connect_database(self.path)) as db:
            init_proactive(db)
            set_schedule(db, PERSONA, USER, False, 9, 0, 'UTC')
        send, sent = self.make_send()
        generate, generated = self.make_generate()

        await tick(self.path, PERSONA, send, self.now, generate=generate)

        self.assertEqual(generated, [])
        self.assertEqual(sent, [])
        self.assertTrue(self._only_other_scope_message(self.path))

    # -- unauthorized identity: no generation, no send -------------------
    async def test_unauthorized_no_generation_or_send(self):
        send, sent = self.make_send()
        generate, generated = self.make_generate()

        await tick(self.path, PERSONA, send, self.now,
                   authorized=lambda _: False, generate=generate)

        self.assertEqual(generated, [])
        self.assertEqual(sent, [])
        self.assertTrue(self._only_other_scope_message(self.path))

        # Once authorized, generation and delivery proceed normally.
        await tick(self.path, PERSONA, send, self.now,
                   authorized=lambda uid: uid == USER, generate=generate)

        self.assertEqual(generated, [USER])
        self.assertEqual(len(sent), 1)
        self.assertEqual(self._history(self.path), [('assistant', GENERATED)])


if __name__ == '__main__':
    unittest.main()
