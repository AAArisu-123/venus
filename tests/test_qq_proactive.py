import asyncio
import json
import tempfile
import threading
import unittest
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock
from venus.memory import connect_database, save_turn
from venus.long_memory import init_memory, add_memory
import venus.qq_bot as qq_bot

class QQProactiveWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_ready_wires_generated_content_to_runner(self):
        generator = AsyncMock()
        c = SimpleNamespace(handler=object(), _proactive_task=None,
            _proactive_db='db', _proactive_persona='p',
            _proactive_generate=generator, api=SimpleNamespace(post_c2c_message=AsyncMock()),
            _authorized_for_proactive=lambda user: True)
        with patch.object(qq_bot, 'loop_forever', new_callable=AsyncMock) as loop:
            await qq_bot.Client.on_ready(c)
            await c._proactive_task
            self.assertIs(loop.await_args.kwargs.get('generate'), generator)

    async def test_qq_generator_uses_scoped_history_and_memory(self):
        received = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                body = json.dumps({'choices':[{'message':{'content':'红茶喝得怎么样？'}}]}, ensure_ascii=False).encode()
                self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'persona.json'
            p.write_text('{"name":"V","description":"友善"}',encoding='utf-8')
            path = Path(tmp) / 'db.sqlite3'
            with closing(connect_database(path)) as db:
                save_turn(db, str(p.resolve()), 'alice', '我喜欢红茶', '我也喜欢')
                init_memory(db); add_memory(db,str(p.resolve()),'alice','爱喝红茶'); db.commit()
            config = {'base_url':f'http://127.0.0.1:{server.server_port}/v1','model':'fake','api_key':'fake'}
            generate = qq_bot.build_proactive_generator(config, path, p)
            result = await generate('alice')
            self.assertEqual(result['message'], '红茶喝得怎么样？')
            self.assertIsInstance(result.get('life'), str)
            data = json.dumps(received, ensure_ascii=False)
            self.assertIn('我喜欢红茶', data); self.assertIn('爱喝红茶', data)
