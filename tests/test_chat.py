import json
from contextlib import closing
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class ConversationTest(unittest.TestCase):
    def test_custom_persona_and_history_reach_model(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                data = json.dumps({'choices': [{'message': {'content': '你好，狸花猫！'}}]}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with tempfile.TemporaryDirectory() as tmp:
            persona = Path(tmp) / 'persona.json'
            persona.write_text(json.dumps({'name': '星星', 'description': '你是一位爱读书的AI伴侣。'}, ensure_ascii=False), encoding='utf-8')
            env = os.environ.copy()
            env.update({'VENUS_API_KEY': 'test-key', 'VENUS_BASE_URL': f'http://127.0.0.1:{server.server_port}/v1', 'VENUS_MODEL': 'test-model', 'PYTHONIOENCODING': 'utf-8'})
            cmd = [sys.executable, '-m', 'venus', '--persona', str(persona), '--db', str(Path(tmp) / 'data.db'), '--user', 'cat', '--message']
            for text in ('你好', '你记得我吗？'):
                result = subprocess.run(cmd + [text], env=env, capture_output=True, text=True, encoding='utf-8', timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('你好，狸花猫！', result.stdout)
            # Default-on mood adds a non-streaming appraisal request before
            # the main reply; keep only the main chat requests here.
            def without_turn_hints(messages):
                return [
                    m['content'] for m in messages
                    if not m['content'].startswith(
                        ('【本轮长度】', '【本轮接话】', '【避免重复】'))
                ]

            main_requests = [r for r in requests if 'response_format' not in r]
            self.assertIn('爱读书', main_requests[1]['messages'][0]['content'])
            self.assertEqual(
                without_turn_hints(main_requests[1]['messages'][1:]),
                ['你好', '你好，狸花猫！', '你记得我吗？'],
            )
            self.assertEqual(main_requests[1]['model'], 'test-model')
            result = subprocess.run(cmd[:-3] + ['--user', 'another-user', '--message', '初次见面'], env=env, capture_output=True, text=True, encoding='utf-8', timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            main_requests = [r for r in requests if 'response_format' not in r]
            self.assertEqual(
                without_turn_hints(main_requests[2]['messages'][1:]),
                ['初次见面'],
            )

    def test_failed_request_does_not_save_message(self):
        from venus.__main__ import answer, connect_database
        with tempfile.TemporaryDirectory() as tmp:
            persona = Path(tmp) / 'persona.json'
            persona.write_text('{"name":"V","description":"Friendly"}', encoding='utf-8')
            with closing(connect_database(Path(tmp) / 'data.db')) as db:
                with self.assertRaises(ValueError):
                    answer(db, persona, 'cat', 'hello', 'http://127.0.0.1:1/v1', 'test', 'test-key')
                self.assertEqual(db.execute('SELECT COUNT(*) FROM messages').fetchone()[0], 0)

    def test_persona_rejects_blank_description(self):
        from venus.__main__ import load_persona
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bad.json'
            path.write_text('{"name":"V","description":" "}', encoding='utf-8')
            with self.assertRaises(ValueError):
                load_persona(path)

    def test_unsafe_redirect_does_not_send_token(self):
        from venus.__main__ import answer, connect_database
        received = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(302)
                self.send_header('Location', f'http://localhost:{self.server.server_port}/capture')
                self.end_headers()
            def do_GET(self):
                received.append(self.headers.get('Authorization'))
                self.send_response(200)
                self.end_headers()
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with tempfile.TemporaryDirectory() as tmp:
            persona = Path(tmp) / 'p.json'
            persona.write_text('{"name":"V","description":"Friendly"}', encoding='utf-8')
            with closing(connect_database(Path(tmp) / 'data.db')) as db:
                with self.assertRaises(ValueError):
                    answer(db, persona, 'cat', 'hello', f'http://127.0.0.1:{server.server_port}/v1', 'test', 'secret')
            self.assertEqual(received, [])


if __name__ == '__main__':
    unittest.main()
