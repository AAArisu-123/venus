"""Tests for the owner-facing self-check command (``python -m venus.doctor``)."""

import io
import json
import tempfile
import threading
import unittest
from contextlib import closing, contextmanager, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from venus import doctor
from venus.memory import connect_database
from venus.pairing import approve_code, connect_database as pairing_database
from venus.pairing import request_code


class _Handler(BaseHTTPRequestHandler):
    responses = {}
    records = []

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length).decode('utf-8'))
        type(self).records.append({
            'path': self.path,
            'body': body,
            'authorization': self.headers.get('Authorization'),
        })
        payload = type(self).responses.get(self.path)
        if payload is None:
            self.send_response(404)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        raw = json.dumps(payload).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


@contextmanager
def fake_server():
    _Handler.records = []
    _Handler.responses = {
        '/app/getAppAccessToken': {'access_token': 'TOKEN'},
        '/v2/users/openid%2F1/messages': {'id': 'message-1'},
    }
    server = ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_address[1]}'
    finally:
        server.shutdown()
        server.server_close()


class MaskTests(unittest.TestCase):
    def test_masks_the_middle_of_an_identifier(self):
        masked = doctor.mask('6E3F7EA08D0F94585872DA3659088641')
        self.assertTrue(masked.startswith('6E3F'))
        self.assertNotIn('7EA08D0F', masked)
        self.assertEqual(doctor.mask(''), '（空）')
        self.assertEqual(doctor.mask('abc'), '****')


class ResolveOpenidTests(unittest.TestCase):
    def test_the_allowlist_wins_and_is_sorted(self):
        config = {'allowed_openids': frozenset({'b', 'a'}), 'pairing_db': 'ignored'}
        self.assertEqual(doctor.resolve_openids(config), ['a', 'b'])

    def test_approved_pairings_are_used_when_the_allowlist_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'pairing.sqlite3')
            db = pairing_database(path)
            approve_code(db, request_code(db, 'openid-1', now=100), now=101)
            approve_code(db, request_code(db, 'openid-2', now=110), now=111)
            request_code(db, 'openid-3', now=120)
            db.close()
            self.assertEqual(
                doctor.resolve_openids({'pairing_db': path}),
                ['openid-1', 'openid-2'],
            )

    def test_a_missing_pairing_database_reports_no_users(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {'pairing_db': str(Path(tmp) / 'none.sqlite3')}
            self.assertEqual(doctor.resolve_openids(config), [])
            self.assertFalse((Path(tmp) / 'none.sqlite3').exists())


class LocalCheckTests(unittest.TestCase):
    def test_a_missing_database_is_reported_instead_of_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'none.sqlite3'
            ok, detail = doctor.check_database(path)
            self.assertFalse(ok)
            self.assertIn('尚未创建', detail)
            self.assertFalse(path.exists())

    def test_the_message_count_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'data.sqlite3'
            db = connect_database(str(path))
            with db:
                db.execute(
                    "INSERT INTO messages(persona, user_id, role, content)"
                    " VALUES ('p', 'u', 'user', 'hi')")
            db.close()
            ok, detail = doctor.check_database(path)
            self.assertTrue(ok)
            self.assertIn('1 条消息', detail)

    def test_the_schedule_is_summarised(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'data.sqlite3'
            db = connect_database(str(path))
            with db:
                db.execute(
                    "INSERT INTO proactive_schedule"
                    "(persona, user_id, enabled, hour, minute, timezone, mode)"
                    " VALUES ('p', 'u', 1, 9, 0, 'Asia/Shanghai', 'random')")
            db.close()
            ok, detail = doctor.check_schedule(path)
            self.assertTrue(ok)
            self.assertIn('1/1', detail)
            self.assertIn('随机', detail)

    def test_the_log_destination_is_writable(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok, detail = doctor.check_log(Path(tmp) / 'logs')
            self.assertTrue(ok)
            self.assertTrue(detail.endswith('qq-service.log'))
            self.assertTrue(Path(detail).parent.is_dir())

    def test_users_are_listed_masked(self):
        ok, detail = doctor.check_users(
            {'allowed_openids': frozenset({'6E3F7EA08D0F94585872DA3659088641'})})
        self.assertTrue(ok)
        self.assertIn('6E3F', detail)
        self.assertNotIn('7EA08D0F', detail)

    def test_collect_checks_reports_a_broken_persona_without_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = doctor.collect_checks(
                {'model': 'm', 'app_id': 'a',
                 'allowed_openids': frozenset({'u'})},
                db_path=Path(tmp) / 'data.sqlite3',
                persona_path=Path(tmp) / 'missing.json',
                log_folder=Path(tmp) / 'logs',
            )
        persona = dict((name, (ok, detail)) for name, ok, detail in results)['人设']
        self.assertFalse(persona[0])
        self.assertIn('检查失败', persona[1])


class ModelProbeTests(unittest.TestCase):
    def test_a_short_reply_is_reported(self):
        reply = doctor.probe_model(
            'https://api.deepseek.com', 'm', 'k',
            complete=lambda *args, **kwargs: '正常')
        self.assertEqual(reply, '正常')

    def test_an_empty_reply_fails(self):
        with self.assertRaises(RuntimeError):
            doctor.probe_model(
                'https://api.deepseek.com', 'm', 'k',
                complete=lambda *args, **kwargs: '   ')


class QqSendTests(unittest.TestCase):
    def test_a_token_is_requested_then_the_message_is_delivered(self):
        with fake_server() as base:
            with patch.object(doctor, 'TOKEN_URL', base + '/app/getAppAccessToken'), \
                 patch.object(doctor, 'API_BASE', base):
                doctor.send_test_message(
                    'appid-1', 'secret-1', 'openid/1', '测试内容')
        paths = [record['path'] for record in _Handler.records]
        self.assertEqual(
            paths, ['/app/getAppAccessToken', '/v2/users/openid%2F1/messages'])
        self.assertEqual(_Handler.records[0]['body'],
                         {'appId': 'appid-1', 'clientSecret': 'secret-1'})
        message = _Handler.records[1]
        self.assertEqual(message['body'], {'content': '测试内容', 'msg_type': 0})
        self.assertEqual(message['authorization'], 'QQBot TOKEN')

    def test_an_error_code_is_reported_without_echoing_the_body(self):
        with fake_server() as base:
            _Handler.responses['/app/getAppAccessToken'] = {
                'code': 10001, 'message': 'synthetic-body-text'}
            with patch.object(doctor, 'TOKEN_URL', base + '/app/getAppAccessToken'), \
                 patch.object(doctor, 'API_BASE', base):
                with self.assertRaises(RuntimeError) as raised:
                    doctor.request_access_token('appid-1', 'secret-1')
        self.assertIn('10001', str(raised.exception))
        self.assertNotIn('synthetic-body-text', str(raised.exception))

    def test_an_http_error_reports_the_status(self):
        with fake_server() as base:
            _Handler.responses = {}
            with patch.object(doctor, 'TOKEN_URL', base + '/missing'), \
                 patch.object(doctor, 'API_BASE', base):
                with self.assertRaises(RuntimeError) as raised:
                    doctor.request_access_token('appid-1', 'secret-1')
        self.assertIn('404', str(raised.exception))


class ArgumentTests(unittest.TestCase):
    def test_flags_and_values_are_parsed(self):
        parsed = doctor._parse(['--api', '--send-test', '--openid', 'u-1',
                                '--db', 'x.sqlite3'])
        self.assertTrue(parsed['api'])
        self.assertTrue(parsed['send_test'])
        self.assertEqual(parsed['openid'], 'u-1')
        self.assertEqual(parsed['db'], 'x.sqlite3')

    def test_unknown_or_incomplete_arguments_are_rejected(self):
        self.assertIsNone(doctor._parse(['--nope']))
        self.assertIsNone(doctor._parse(['--openid']))
        self.assertIsNone(doctor._parse(['--openid', '--api']))


class MainTests(unittest.TestCase):
    CONFIG = {
        'app_id': 'appid-1', 'app_secret': 'secret-1',
        'model': 'm', 'base_url': 'https://api.deepseek.com', 'api_key': 'k',
        'allowed_openids': frozenset({'openid-1'}), 'pairing_db': 'unused',
    }

    def test_local_run_reports_every_check_and_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = connect_database(str(Path(tmp) / 'data.sqlite3'))
            db.close()
            out = io.StringIO()
            with patch.object(doctor, 'load_env_file'), \
                 patch.object(doctor, 'load_config', return_value=dict(self.CONFIG)), \
                 redirect_stdout(out):
                code = doctor.main([
                    '--db', str(Path(tmp) / 'data.sqlite3'),
                    '--log-dir', str(Path(tmp) / 'logs'),
                ])
        text = out.getvalue()
        self.assertEqual(code, 0)
        for name in ('配置', '人设', '数据库', '主动计划', '日志', '用户'):
            self.assertIn(name, text)
        self.assertIn('--api', text)

    def test_a_broken_configuration_fails_closed(self):
        err = io.StringIO()
        with patch.object(doctor, 'load_env_file'), \
             patch.object(doctor, 'load_config', side_effect=ValueError('缺少必需的环境变量：X')), \
             redirect_stdout(io.StringIO()), patch('sys.stderr', err):
            code = doctor.main([])
        self.assertEqual(code, 1)
        self.assertIn('缺少必需的环境变量', err.getvalue())

    def test_send_test_uses_the_only_paired_user(self):
        with fake_server() as base, tempfile.TemporaryDirectory() as tmp:
            db = connect_database(str(Path(tmp) / 'data.sqlite3'))
            db.close()
            with patch.object(doctor, 'load_env_file'), \
                 patch.object(doctor, 'load_config', return_value=dict(self.CONFIG)), \
                 patch.object(doctor, 'TOKEN_URL', base + '/app/getAppAccessToken'), \
                 patch.object(doctor, 'API_BASE', base), \
                 patch.object(doctor, 'send_test_message') as send, \
                 redirect_stdout(io.StringIO()) as out:
                code = doctor.main([
                    '--send-test', '--db', str(Path(tmp) / 'data.sqlite3'),
                    '--log-dir', str(Path(tmp) / 'logs'),
                ])
        self.assertEqual(code, 0)
        send.assert_called_once()
        self.assertIn('[ok] QQ 发送', out.getvalue())


if __name__ == '__main__':
    unittest.main()
