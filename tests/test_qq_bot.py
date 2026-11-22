"""Tests for the official botpy QQ integration.

A fake ``botpy`` is injected into ``sys.modules`` before importing
``venus.qq_bot``. Tests never use real credentials and never touch the
network: model calls and SQLite connections are replaced with fakes.
"""

import asyncio
import contextlib
import importlib
import io
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock


class FakeIntents:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeClientBase:
    def __init__(self, *args, **kwargs):
        self.init_args = args
        self.init_kwargs = kwargs
        self.run_calls = []

    def run(self, **kwargs):
        self.run_calls.append(kwargs)


def _install_fake_botpy():
    module = types.ModuleType('botpy')
    module.Client = FakeClientBase
    module.Intents = FakeIntents
    sys.modules['botpy'] = module
    return module


FAKE_BOTPY = _install_fake_botpy()
# Another test module (loaded earlier by alphabetical discovery) may already
# have imported venus.qq_bot with the real botpy client. Drop that module so
# this suite always binds the fake client, independent of import order.
sys.modules.pop('venus.qq_bot', None)
qq_bot = importlib.import_module('venus.qq_bot')


FULL_ENV = {
    'QQ_APP_ID': 'app-id-value',
    'QQ_APP_SECRET': 'app-secret-value',
    'QQ_ALLOWED_OPENIDS': 'open-a, open-b ,open-c',
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


_UNSET = object()


class FakeMessage:
    def __init__(self, message_id='m1', openid='open-a', content='hi', api=None,
                 author=_UNSET):
        self.id = message_id
        self.author = FakeAuthor(openid) if author is _UNSET else author
        self.content = content
        self._api = FakeApi() if api is None else api


class FakeDB:
    def __init__(self, path):
        self.path = path
        self.closed = False

    def close(self):
        self.closed = True


class ConfigTests(unittest.TestCase):
    def load(self, **overrides):
        env = dict(FULL_ENV)
        removed = overrides.pop('_remove', ())
        env.update(overrides)
        # Keep tests hermetic: never read the developer's real credentials file.
        env.setdefault('QQ_CREDENTIALS_FILE', str(Path(tempfile.gettempdir()) / 'venus-absent-creds.json'))
        for name in removed:
            env.pop(name, None)
        return qq_bot.load_config(env)

    def test_load_config_returns_expected_values(self):
        config = self.load()
        self.assertEqual(config['app_id'], 'app-id-value')
        self.assertEqual(config['app_secret'], 'app-secret-value')
        self.assertEqual(config['api_key'], 'venus-api-key-value')
        self.assertEqual(config['base_url'], 'https://example.invalid/v1')
        self.assertEqual(config['model'], 'venus-test-model')
        self.assertEqual(
            config['allowed_openids'], frozenset({'open-a', 'open-b', 'open-c'})
        )

    def test_missing_required_variable_fails(self):
        for name in qq_bot.REQUIRED_ENV_NAMES:
            with self.subTest(name=name):
                env = dict(FULL_ENV)
                env.pop(name)
                with self.assertRaises(ValueError):
                    qq_bot.load_config(env)

    def test_blank_required_variable_fails(self):
        for name in qq_bot.REQUIRED_ENV_NAMES:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    self.load(**{name: '   '})

    def test_empty_allowlist_switches_to_pairing_mode(self):
        for value in ('', '   ', ',', ' , , '):
            with self.subTest(value=value):
                config = self.load(QQ_ALLOWED_OPENIDS=value)
                self.assertEqual(config['allowed_openids'], frozenset())
                self.assertTrue(config['pairing_db'])

    def test_load_config_does_not_print_secrets(self):
        env = dict(FULL_ENV)
        env.pop('QQ_APP_SECRET', None)
        env['QQ_CREDENTIALS_FILE'] = str(Path(tempfile.gettempdir()) / 'venus-absent-creds.json')
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(ValueError):
                qq_bot.load_config(env)
        text = out.getvalue() + err.getvalue()
        self.assertNotIn('app-secret-value', text)
        self.assertNotIn('venus-api-key-value', text)


class ParseMessageTests(unittest.TestCase):
    def test_valid_message_returns_triple(self):
        message = FakeMessage(message_id='m1', openid='open-a', content='hi')
        self.assertEqual(qq_bot._parse_message(message), ('m1', 'open-a', 'hi'))

    def test_text_is_stripped(self):
        message = FakeMessage(content='\n  hello \t')
        self.assertEqual(qq_bot._parse_message(message)[2], 'hello')

    def test_blank_or_non_string_fields_are_rejected(self):
        bad_ids = (None, '', '   ', 1, 1.5, True, [], {})
        for value in bad_ids:
            with self.subTest(field='id', value=value):
                self.assertIsNone(qq_bot._parse_message(
                    FakeMessage(message_id=value)))
        bad_openids = (None, '', '  ', 1, [], {})
        for value in bad_openids:
            with self.subTest(field='user_openid', value=value):
                self.assertIsNone(qq_bot._parse_message(
                    FakeMessage(author=FakeAuthor(value))))
        bad_contents = (None, '', '  \n ', 1, [], {}, b'bytes')
        for value in bad_contents:
            with self.subTest(field='content', value=value):
                self.assertIsNone(qq_bot._parse_message(
                    FakeMessage(content=value)))

    def test_missing_or_bad_author_is_rejected(self):
        for author in (None, 'open-a', 42, []):
            with self.subTest(author=author):
                self.assertIsNone(qq_bot._parse_message(
                    FakeMessage(author=author)))

    def test_non_message_input_is_rejected(self):
        for value in (None, 'text', 42, [], {}):
            with self.subTest(value=value):
                self.assertIsNone(qq_bot._parse_message(value))

    def test_unicode_fields_are_preserved(self):
        message = FakeMessage(message_id='消息-①', openid='用户_😀', content='  你好，世界！  ')
        self.assertEqual(
            qq_bot._parse_message(message), ('消息-①', '用户_😀', '你好，世界！')
        )


class BuildHandlerTests(unittest.TestCase):
    def test_requires_callable_api_for(self):
        config = qq_bot.load_config(dict(FULL_ENV))
        with self.assertRaises(TypeError):
            qq_bot.build_handler(config, None)


class HandlerTestBase(unittest.IsolatedAsyncioTestCase):
    def make_answer(self, failure=False, hook=None):
        def fake(db, persona_path, user_id, text, base_url, model, api_key):
            self.answer_calls.append({
                'db': db,
                'persona_path': persona_path,
                'user_id': user_id,
                'text': text,
                'base_url': base_url,
                'model': model,
                'api_key': api_key,
                'thread': threading.get_ident(),
            })
            if hook is not None:
                hook(user_id, text)
            if failure:
                raise ValueError('模型请求失败 TOKEN=should-not-leak')
            return '回答:' + text
        return fake

    def patch_answer(self, failure=False, hook=None):
        patcher = mock.patch.object(
            qq_bot, 'answer', self.make_answer(failure=failure, hook=hook)
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def setUp(self):
        self.answer_calls = []
        self.db_paths = []
        self.dbs = []
        self.main_thread = threading.get_ident()

        def fake_connect(path):
            self.db_paths.append(path)
            db = FakeDB(path)
            self.dbs.append(db)
            return db

        connect_patcher = mock.patch.object(
            qq_bot, 'connect_database', fake_connect
        )
        answer_patcher = mock.patch.object(qq_bot, 'answer', self.make_answer())
        for patcher in (connect_patcher, answer_patcher):
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in ('init_activity', 'record_activity', 'ensure_default_schedule'):
            patcher = mock.patch.object(qq_bot, name)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.config = qq_bot.load_config(dict(FULL_ENV))
        self.apis = {}

        def api_for(message_id):
            return self.apis.pop(message_id, None)

        self.handler = qq_bot.build_handler(
            self.config, api_for,
            db_path='tmp/venus.db', persona_path='tmp/persona.json',
        )


class ReplyTests(HandlerTestBase):
    async def test_reply_runs_in_worker_thread_with_fresh_connection(self):
        api = FakeApi()
        self.apis['m1'] = api
        await self.handler.handle('m1', 'open-a', '你好')

        self.assertEqual(len(self.answer_calls), 1)
        call = self.answer_calls[0]
        self.assertNotEqual(call['thread'], self.main_thread)
        self.assertEqual(call['user_id'], 'open-a')
        self.assertEqual(call['text'], '你好')
        self.assertEqual(call['base_url'], FULL_ENV['VENUS_BASE_URL'])
        self.assertEqual(call['model'], FULL_ENV['VENUS_MODEL'])
        self.assertEqual(call['api_key'], FULL_ENV['VENUS_API_KEY'])
        self.assertEqual(call['persona_path'], 'tmp/persona.json')
        self.assertEqual(self.db_paths, ['tmp/venus.db'])
        self.assertEqual(len(self.dbs), 1)
        self.assertIs(self.dbs[0], call['db'])
        self.assertTrue(self.dbs[0].closed)
        self.assertEqual(api.calls, [{
            'openid': 'open-a',
            'msg_type': 0,
            'msg_id': 'm1',
            'content': '回答:你好',
        }])

    async def test_each_request_opens_and_closes_its_own_connection(self):
        api = FakeApi()
        for i in range(3):
            self.apis[f'm{i}'] = api
            await self.handler.handle(f'm{i}', 'open-a', f't{i}')
        self.assertEqual(self.db_paths, ['tmp/venus.db'] * 3)
        self.assertEqual(len({id(db) for db in self.dbs}), 3)
        self.assertTrue(all(db.closed for db in self.dbs))
        self.assertEqual(len(api.calls), 3)

    async def test_model_failure_sends_a_short_fallback(self):
        self.patch_answer(failure=True)
        api = FakeApi()
        self.apis['m1'] = api
        await self.handler.handle('m1', 'open-a', 'hi')
        self.assertEqual(len(self.answer_calls), 1)
        self.assertEqual(len(api.calls), 1)
        self.assertEqual(api.calls[0]['content'], qq_bot.FALLBACK_REPLY)

    async def test_no_secret_or_message_text_is_printed(self):
        self.patch_answer(failure=True)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.apis['m1'] = FakeApi()
            await self.handler.handle('m1', 'open-a', 'MESSAGE_SENTINEL')
        text = out.getvalue() + err.getvalue()
        self.assertEqual(text, '')
        self.assertNotIn('should-not-leak', text)
        self.assertNotIn('MESSAGE_SENTINEL', text)
        self.assertNotIn(FULL_ENV['VENUS_API_KEY'], text)

    async def test_same_user_messages_are_serialized(self):
        order = []

        def hook(user_id, text):
            order.append(('start', text))
            time.sleep(0.02)
            order.append(('end', text))

        self.patch_answer(hook=hook)
        apis = [FakeApi() for _ in range(2)]
        for i, api in enumerate(apis):
            self.apis[f'm{i}'] = api
        await asyncio.gather(*[
            self.handler.handle(f'm{i}', 'open-a', f't{i}') for i in range(2)
        ])
        self.assertEqual(order, [
            ('start', 't0'), ('end', 't0'), ('start', 't1'), ('end', 't1'),
        ])
        self.assertEqual([len(api.calls) for api in apis], [1, 1])

    async def test_different_users_are_not_serialized(self):
        order = []

        def hook(user_id, text):
            if user_id == 'open-a':
                time.sleep(0.05)
                order.append('slow')
            else:
                order.append('fast')

        self.patch_answer(hook=hook)
        self.apis['m1'] = FakeApi()
        self.apis['m2'] = FakeApi()
        await asyncio.wait_for(asyncio.gather(
            self.handler.handle('m1', 'open-a', 'a'),
            self.handler.handle('m2', 'open-b', 'b'),
        ), timeout=2)
        self.assertEqual(order, ['fast', 'slow'])

    async def test_duplicate_message_id_is_answered_once(self):
        api = FakeApi()
        self.apis['m1'] = api
        await asyncio.gather(*[
            self.handler.handle('m1', 'open-a', 'hi') for _ in range(5)
        ])
        self.assertEqual(len(self.answer_calls), 1)
        self.assertEqual(len(api.calls), 1)


class ClientEventTests(HandlerTestBase):
    def make_client(self):
        client = qq_bot.Client(intents=FakeIntents(public_messages=True))
        client.configure(
            self.config, db_path='tmp/venus.db', persona_path='tmp/persona.json'
        )
        return client

    async def test_allowed_message_is_answered_and_replied(self):
        client = self.make_client()
        api = FakeApi()
        await client.on_c2c_message_create(FakeMessage(
            message_id='m1', openid='open-a', content='  你好  ', api=api,
        ))
        self.assertEqual(len(self.answer_calls), 1)
        self.assertEqual(self.answer_calls[0]['text'], '你好')
        self.assertEqual(api.calls, [{
            'openid': 'open-a',
            'msg_type': 0,
            'msg_id': 'm1',
            'content': '回答:你好',
        }])
        self.assertEqual(client._apis, {})

    async def test_openid_not_in_allowlist_is_ignored(self):
        client = self.make_client()
        api = FakeApi()
        await client.on_c2c_message_create(FakeMessage(
            message_id='m1', openid='stranger', content='hi', api=api,
        ))
        self.assertEqual(self.answer_calls, [])
        self.assertEqual(api.calls, [])
        self.assertEqual(client._apis, {})

    async def test_malformed_messages_are_ignored(self):
        client = self.make_client()
        messages = [
            None,
            FakeMessage(message_id='', openid='open-a', content='hi'),
            FakeMessage(message_id='m1', openid='  ', content='hi'),
            FakeMessage(message_id='m1', openid='open-a', content='  '),
            FakeMessage(message_id='m1', openid='open-a', content=None),
            FakeMessage(message_id=123, openid='open-a', content='hi'),
            FakeMessage(message_id='m1', openid='open-a', content='hi', author=None),
        ]
        for message in messages:
            with self.subTest(message=type(message).__name__):
                await client.on_c2c_message_create(message)
        self.assertEqual(self.answer_calls, [])
        self.assertEqual(client._apis, {})

    async def test_missing_api_is_ignored(self):
        client = self.make_client()
        message = FakeMessage(message_id='m1', openid='open-a', content='hi')
        message._api = None
        await client.on_c2c_message_create(message)
        self.assertEqual(self.answer_calls, [])
        self.assertEqual(client._apis, {})

    async def test_stranger_in_pairing_mode_gets_a_code_not_a_model_reply(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            config = qq_bot.load_config(dict(FULL_ENV, QQ_ALLOWED_OPENIDS='',
                                             QQ_PAIRING_DB=str(Path(tmp) / 'p.sqlite3')))
            client = qq_bot.Client(intents=FakeIntents(public_messages=True))
            client.configure(config, db_path='tmp/venus.db',
                             persona_path='tmp/persona.json')
            api = FakeApi()
            await client.on_c2c_message_create(FakeMessage(
                message_id='m1', openid='stranger', content='在吗', api=api,
            ))
            self.assertEqual(self.answer_calls, [])
            self.assertEqual(len(api.calls), 1)
            self.assertIn('配对码：', api.calls[0]['content'])
            self.assertEqual(api.calls[0]['msg_id'], 'm1')

    async def test_api_registry_is_cleaned_after_model_failure(self):
        client = self.make_client()
        self.patch_answer(failure=True)
        await client.on_c2c_message_create(FakeMessage(
            message_id='m1', openid='open-a', content='hi',
        ))
        self.assertEqual(client._apis, {})


    async def test_long_reply_is_sent_as_two_bubbles(self):
        api = FakeApi()
        self.apis['m1'] = api
        long_reply = '第一句。' * 80
        with mock.patch.object(qq_bot, 'answer', return_value=long_reply), \
             mock.patch.object(qq_bot.asyncio, 'sleep', new=mock.AsyncMock()):
            await self.handler.handle('m1', 'open-a', '你好')
        self.assertEqual(len(api.calls), 2)
        self.assertEqual([call['msg_seq'] for call in api.calls], [1, 2])
        self.assertEqual(''.join(call['content'] for call in api.calls), long_reply)

    async def test_schedule_failure_does_not_block_reply(self):
        client = self.make_client()
        api = FakeApi()
        with mock.patch.object(
            qq_bot, 'ensure_default_schedule', side_effect=RuntimeError('locked')
        ):
            await client.on_c2c_message_create(FakeMessage(
                message_id='m1', openid='open-a', content='你好', api=api,
            ))
        self.assertEqual(len(api.calls), 1)
        self.assertEqual(api.calls[0]['content'], '回答:你好')

    async def test_blank_model_reply_returns_fallback(self):
        api = FakeApi()
        self.apis['m1'] = api
        with mock.patch.object(qq_bot, 'answer', return_value='   '):
            await self.handler.handle('m1', 'open-a', '你好')
        self.assertEqual(len(api.calls), 1)
        self.assertEqual(api.calls[0]['content'], qq_bot.FALLBACK_REPLY)


class CleanReplyTests(unittest.TestCase):
    def test_strips_visible_markdown(self):
        text = '**你好**\n# 标题\n- 第一条\n- 第二条\n```python\nprint(1)\n```'
        cleaned = qq_bot.clean_reply(text)
        self.assertNotIn('**', cleaned)
        self.assertNotIn('# 标题', cleaned)
        self.assertNotIn('- 第一条', cleaned)
        self.assertNotIn('```', cleaned)
        self.assertIn('你好', cleaned)
        self.assertIn('第一条', cleaned)

    def test_caps_long_reply_at_sentence_boundary(self):
        cleaned = qq_bot.clean_reply('好' * 2000)
        self.assertLessEqual(len(cleaned), qq_bot.MAX_QQ_CHARS + 1)

    def test_normal_text_is_unchanged(self):
        self.assertEqual(qq_bot.clean_reply('在呢，今天怎么样？'), '在呢，今天怎么样？')

    def test_preserves_kaomoji(self):
        text = '想你了。(￣▽￣)'
        self.assertEqual(qq_bot.clean_reply(text), text)

    def test_split_reply_at_sentence_boundary(self):
        text = '第一句。第二句。第三句。' * 12
        parts = qq_bot.split_reply(text)
        self.assertEqual(len(parts), 2)
        self.assertTrue(parts[0].endswith('。'))
        self.assertEqual(''.join(parts), text)

    def test_short_reply_stays_in_one_bubble(self):
        self.assertEqual(qq_bot.split_reply('好的。'), ['好的。'])


class MainTests(unittest.TestCase):
    def test_missing_config_fails_closed_before_start(self):
        env = dict(FULL_ENV, QQ_CREDENTIALS_FILE=str(Path(tempfile.gettempdir()) / 'venus-absent-creds.json'))
        env.pop('QQ_APP_SECRET', None)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(qq_bot, 'load_env_file', lambda *a, **k: 0):
                with mock.patch.object(qq_bot, 'Client') as client_cls:
                    with mock.patch.object(qq_bot.botpy, 'Intents') as intents_cls:
                        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                            result = qq_bot.main()
        self.assertEqual(result, 2)
        intents_cls.assert_not_called()
        client_cls.assert_not_called()
        self.assertNotIn('app-secret-value', out.getvalue() + err.getvalue())

    def test_start_uses_official_sample_shape(self):
        with mock.patch.dict(os.environ, FULL_ENV, clear=True):
            with mock.patch.object(qq_bot, 'Client') as client_cls:
                with mock.patch.object(qq_bot.botpy, 'Intents') as intents_cls:
                    result = qq_bot.main()
        self.assertEqual(result, 0)
        intents_cls.assert_called_once_with(public_messages=True)
        # The SDK file handler is disabled so chat text never lands in
        # botpy.log; the scheduled entry point installs its own status log.
        client_cls.assert_called_once_with(
            intents=intents_cls.return_value, ext_handlers=False
        )
        client = client_cls.return_value
        client.configure.assert_called_once()
        config = client.configure.call_args[0][0]
        self.assertEqual(
            config['allowed_openids'], frozenset({'open-a', 'open-b', 'open-c'})
        )
        client.run.assert_called_once_with(
            appid='app-id-value', secret='app-secret-value'
        )

    def test_main_does_not_print_secrets(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, FULL_ENV, clear=True):
            with mock.patch.object(qq_bot, 'Client'):
                with mock.patch.object(qq_bot.botpy, 'Intents'):
                    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                        qq_bot.main()
        text = out.getvalue() + err.getvalue()
        self.assertNotIn('app-secret-value', text)
        self.assertNotIn('venus-api-key-value', text)


if __name__ == '__main__':
    unittest.main()
