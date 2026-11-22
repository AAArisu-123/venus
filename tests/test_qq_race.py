"""Race tests for duplicate QQ message ids.

Scenario: two concurrent events share one message id. The first request is
blocked inside the model call while the second one starts and is then either
completed or cancelled. The first reply must still be delivered exactly once,
through the api object belonging to the request that produced it.

Only observable behaviour is asserted: which api objects received
``post_c2c_message`` calls, what was sent, and how many times the model was
asked. No internal bookkeeping of the client is inspected.

A fake ``botpy`` is injected into ``sys.modules`` before importing
``venus.qq_bot``. Fakes follow tests/test_qq_bot.py. Nothing here touches the
network or real credentials.
"""

import asyncio
import contextlib
import importlib
import sys
import threading
import types
import unittest
from unittest import mock


class FakeIntents:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeClientBase:
    def __init__(self, *args, **kwargs):
        self.init_args = args
        self.init_kwargs = kwargs

    def run(self, **kwargs):
        self.run_calls.append(kwargs)


def _install_fake_botpy():
    module = types.ModuleType('botpy')
    module.Client = FakeClientBase
    module.Intents = FakeIntents
    sys.modules['botpy'] = module
    return module


_install_fake_botpy()
qq_bot = importlib.import_module('venus.qq_bot')


FULL_ENV = {
    'QQ_APP_ID': 'app-id-value',
    'QQ_APP_SECRET': 'app-secret-value',
    'QQ_ALLOWED_OPENIDS': 'open-a, open-b',
    'VENUS_API_KEY': 'venus-api-key-value',
    'VENUS_BASE_URL': 'https://example.invalid/v1',
    'VENUS_MODEL': 'venus-test-model',
}


class FakeAuthor:
    def __init__(self, user_openid):
        self.user_openid = user_openid


class FakeApi:
    def __init__(self):
        self.calls = []

    async def post_c2c_message(self, **kwargs):
        self.calls.append(kwargs)


class FakeMessage:
    def __init__(self, message_id='m1', openid='open-a', content='hi', api=None):
        self.id = message_id
        self.author = FakeAuthor(openid)
        self.content = content
        self._api = FakeApi() if api is None else api


class FakeDB:
    def __init__(self, path):
        self.path = path

    def close(self):
        pass


class DuplicateMessageIdRaceTests(unittest.IsolatedAsyncioTestCase):
    """First reply must survive a concurrent same-id second request."""

    def setUp(self):
        self.answer_calls = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.addCleanup(self.release.set)

        def fake_answer(db, persona_path, user_id, text, base_url, model, api_key):
            self.answer_calls.append(text)
            if text == 'first':
                self.started.set()
                self.assertTrue(self.release.wait(5), 'model call was never released')
            return '回答:' + text

        connect_patcher = mock.patch.object(
            qq_bot, 'connect_database', lambda path: FakeDB(path)
        )
        answer_patcher = mock.patch.object(qq_bot, 'answer', fake_answer)
        connect_patcher.start()
        answer_patcher.start()
        self.addCleanup(connect_patcher.stop)
        self.addCleanup(answer_patcher.stop)
        for name in ('init_activity', 'record_activity', 'ensure_default_schedule'):
            patcher = mock.patch.object(qq_bot, name)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.client = qq_bot.Client(intents=FakeIntents(public_messages=True))
        self.client.configure(
            qq_bot.load_config(dict(FULL_ENV)),
            db_path='tmp/venus.db',
            persona_path='tmp/persona.json',
        )

    async def wait_for_model_call(self):
        """Block until the first request is parked inside the model call."""
        started_in_thread = asyncio.to_thread(self.started.wait, 2)
        try:
            reached = await asyncio.wait_for(started_in_thread, timeout=3)
        except asyncio.TimeoutError:
            reached = False
        if not reached or not self.started.is_set():
            self.fail('first request never reached the model call')

    async def let_event_run(self, task):
        """Give ``task`` enough loop turns to reach its first blocking await."""
        for _ in range(20):
            if task.done():
                return
            await asyncio.sleep(0.005)

    async def run_concurrent_second_request(self, api1, api2):
        """Start request 1 (blocked in model) then request 2 with the same id."""
        task1 = asyncio.create_task(self.client.on_c2c_message_create(FakeMessage(
            message_id='m1', openid='open-a', content='first', api=api1,
        )))
        await self.wait_for_model_call()
        task2 = asyncio.create_task(self.client.on_c2c_message_create(FakeMessage(
            message_id='m1', openid='open-a', content='dup', api=api2,
        )))
        await self.let_event_run(task2)
        return task1, task2

    def total_posts(self, *apis):
        return [call for api in apis for call in api.calls]

    async def test_second_request_completes_and_first_reply_is_still_sent(self):
        api1, api2 = FakeApi(), FakeApi()
        task1, task2 = await self.run_concurrent_second_request(api1, api2)

        self.release.set()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.gather(task1, task2), timeout=5)

        # The first request's answer must be delivered once, by the api that
        # the first request came with.
        self.assertEqual(
            [p['msg_id'] for p in api1.calls], ['m1'],
            'first reply was not delivered through its own message api',
        )
        self.assertEqual(api1.calls[0]['content'], '回答:first')
        self.assertEqual(api2.calls, [])
        # The duplicate must not have been answered a second time.
        self.assertEqual(self.answer_calls, ['first'])

    async def test_second_request_cancelled_after_start_does_not_lose_reply(self):
        api1, api2 = FakeApi(), FakeApi()
        task1, task2 = await self.run_concurrent_second_request(api1, api2)

        task2.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task2
        self.assertTrue(task2.cancelled())

        self.release.set()
        await asyncio.wait_for(task1, timeout=5)

        posts = self.total_posts(api1, api2)
        self.assertEqual(
            [p['msg_id'] for p in posts], ['m1'],
            'cancelling the concurrent request deleted the api needed by the '
            'first reply',
        )
        self.assertEqual(posts[0]['content'], '回答:first')
        self.assertEqual(api2.calls, [])
        self.assertEqual(self.answer_calls, ['first'])

    async def test_repeated_second_requests_keep_first_reply_deliverable(self):
        """Several concurrent same-id requests, ending in cancellation, must
        not strand request 1."""
        api1 = FakeApi()
        task1 = asyncio.create_task(self.client.on_c2c_message_create(FakeMessage(
            message_id='m1', openid='open-a', content='first', api=api1,
        )))
        await self.wait_for_model_call()

        second_tasks = []
        for i in range(3):
            api = FakeApi()
            task = asyncio.create_task(self.client.on_c2c_message_create(FakeMessage(
                message_id='m1', openid='open-a', content=f'dup{i}', api=api,
            )))
            await self.let_event_run(task)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            second_tasks.append(api)

        self.release.set()
        await asyncio.wait_for(task1, timeout=5)

        posts = self.total_posts(api1, *second_tasks)
        self.assertEqual(
            [p['msg_id'] for p in posts], ['m1'],
            'first reply was lost after repeated concurrent cancellations',
        )
        self.assertEqual(posts[0]['content'], '回答:first')
        self.assertEqual(self.answer_calls, ['first'])


if __name__ == '__main__':
    unittest.main()
