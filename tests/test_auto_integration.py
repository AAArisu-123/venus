import json
import tempfile
import threading
import unittest
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from venus.__main__ import answer
from venus.commands import handle_command
from venus.long_memory import list_memories
from venus.memory import connect_database

class AutoIntegrationTests(unittest.TestCase):
    def test_default_extract_disable_enable_delete_and_scope(self):
        payloads = []
        class Server(BaseHTTPRequestHandler):
            def do_POST(self):
                payloads.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                data = b'{"choices":[{"message":{"content":"ok"}}]}'
                self.send_response(200)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Server)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with tempfile.TemporaryDirectory() as tmp:
            persona = Path(tmp) / 'p.json'
            persona.write_text('{"name":"V","description":"friendly"}', encoding='utf-8')
            scope = str(persona.resolve())
            with closing(connect_database(Path(tmp)/'db')) as db:
                base = f'http://127.0.0.1:{server.server_port}/v1'
                answer(db, persona, 'u', '我喜欢咖啡', base, 'test', 'test')
                rows = list_memories(db, scope, 'u')
                self.assertEqual([r[1] for r in rows], ['我喜欢咖啡'])
                self.assertIn('关闭', handle_command(db, scope, 'u', '/自动记忆 关闭'))
                answer(db, persona, 'u', '我喜欢红茶', base, 'test', 'test')
                self.assertEqual(
                    [r[1] for r in list_memories(db, scope, 'u')],
                    ['我喜欢咖啡'],
                )
                self.assertIn('开启', handle_command(db, scope, 'u', '/自动记忆 开启'))
                answer(db, persona, 'u', '我喜欢青茶', base, 'test', 'test')
                self.assertEqual(
                    [r[1] for r in list_memories(db, scope, 'u')],
                    ['我喜欢咖啡', '我喜欢青茶'],
                )
                self.assertEqual(list_memories(db, scope, 'other'), [])
                answer(db, persona, 'u', '继续', base, 'test', 'test')
                self.assertIn('我喜欢咖啡', json.dumps(payloads[-1], ensure_ascii=False))
                handle_command(db, scope, 'u', '/忘记 '+str(rows[0][0]))
                self.assertEqual(
                    [r[1] for r in list_memories(db, scope, 'u')],
                    ['我喜欢青茶'],
                )
