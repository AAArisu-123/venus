import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from venus.commands import handle_command
from venus.memory import connect_database
from venus.long_memory import list_memories
from venus.proactive import due_and_claim
from datetime import datetime, timezone


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = connect_database(Path(self.tmp.name) / 'data.db')
        self.addCleanup(self.db.close)
        from venus.long_memory import init_memory
        from venus.proactive import init_proactive
        init_memory(self.db)
        init_proactive(self.db)

    def test_remember_list_delete_scoped_to_user(self):
        result = handle_command(self.db, 'p', 'alice', '/记住 我喜欢猫')
        self.assertIn('记住', result)
        result = handle_command(self.db, 'p', 'alice', '/记忆')
        self.assertIn('我喜欢猫', result)
        mid = list_memories(self.db, 'p', 'alice')[0][0]
        self.assertNotIn('我喜欢猫', handle_command(self.db, 'p', 'bob', '/记忆'))
        self.assertIn('没有', handle_command(self.db, 'p', 'bob', f'/忘记 {mid}'))
        self.assertIn('删除', handle_command(self.db, 'p', 'alice', f'/忘记 {mid}'))
        self.assertEqual(list_memories(self.db, 'p', 'alice'), [])

    def test_only_explicit_commands_change_memory(self):
        self.assertIsNone(handle_command(self.db, 'p', 'alice', '请记住我喜欢猫'))
        self.assertEqual(list_memories(self.db, 'p', 'alice'), [])

    def test_schedule_commands_are_opt_in(self):
        now = datetime(2026, 1, 1, 11, 29, tzinfo=timezone.utc)
        self.assertFalse(due_and_claim(self.db, 'p', 'alice', now))
        self.assertIn('开启', handle_command(self.db, 'p', 'alice', '/主动 开启 19:30'))
        self.assertFalse(due_and_claim(self.db, 'p', 'alice', now))
        self.assertTrue(due_and_claim(self.db, 'p', 'alice', datetime(2026, 1, 1, 11, 30, tzinfo=timezone.utc)))
        self.assertIn('关闭', handle_command(self.db, 'p', 'alice', '/主动 关闭'))
        self.assertFalse(due_and_claim(self.db, 'p', 'alice', datetime(2026, 1, 2, 12, tzinfo=timezone.utc)))

    def test_proactive_disable_is_durable_without_prior_schedule(self):
        self.assertIn('关闭', handle_command(self.db, 'p', 'alice', '/主动 关闭'))
        row = self.db.execute(
            'SELECT enabled FROM proactive_schedule '
            'WHERE persona = ? AND user_id = ?',
            ('p', 'alice'),
        ).fetchone()
        self.assertEqual(row[0], 0)

    def test_long_memory_goes_to_model_but_is_removed_after_forget(self):
        from venus.commands import handle_command
        from venus.__main__ import answer
        payloads = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                payloads.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                data = b'{"choices":[{"message":{"content":"OK"}}]}'
                self.send_response(200)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with tempfile.TemporaryDirectory() as tmp:
            persona = Path(tmp) / 'p.json'
            persona.write_text('{"name":"V","description":"Friendly"}', encoding='utf-8')
            scope = str(persona.resolve())
            with closing(connect_database(Path(tmp) / 'db.sqlite3')) as db:
                handle_command(db, scope, 'cat', '/记住 我喜欢红茶')
                endpoint = f'http://127.0.0.1:{server.server_port}/v1'
                answer(db, persona, 'cat', '你好吗', endpoint, 'fake', 'fake')
                mid = list_memories(db, scope, 'cat')[0][0]
                handle_command(db, scope, 'cat', f'/忘记 {mid}')
                answer(db, persona, 'cat', '再见', endpoint, 'fake', 'fake')
        # Default-on mood adds an appraisal request before each main reply.
        main_payloads = [p for p in payloads if 'response_format' not in p]
        self.assertIn('我喜欢红茶', json.dumps(main_payloads[0], ensure_ascii=False))
        self.assertNotIn('我喜欢红茶', json.dumps(main_payloads[1], ensure_ascii=False))

    def test_help_and_invalid_command(self):
        self.assertIn('/记住', handle_command(self.db, 'p', 'alice', '/帮助'))
        self.assertIn('格式', handle_command(self.db, 'p', 'alice', '/主动 开启 25:00'))
        self.assertIsNone(handle_command(self.db, 'p', 'alice', '普通对话'))
