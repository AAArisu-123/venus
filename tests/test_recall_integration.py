import json
import tempfile
import threading
import unittest
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from venus.memory import connect_database
from venus.long_memory import init_memory, add_memory
from venus.__main__ import answer

class RecallIntegration(unittest.TestCase):
    def test_old_relevant_memory_sent_to_model(self):
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                body=b'{"choices":[{"message":{"content":"ok"}}]}'
                self.send_response(200); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
            def log_message(self, *args): pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'p.json'; p.write_text('{"name":"V","description":"friendly"}',encoding='utf-8')
            with closing(connect_database(Path(tmp)/'db')) as db:
                init_memory(db); scope=str(p.resolve())
                add_memory(db,scope,'u','独特的摄影偏好'); add_memory(db,scope,'other','摄影私人数据')
                for i in range(105): add_memory(db,scope,'u',f'不相关{i}')
                db.commit()
                answer(db,p,'u','聊聊摄影',f'http://127.0.0.1:{server.server_port}/v1','test','test')
        text=json.dumps(requests,ensure_ascii=False)
        self.assertIn('独特的摄影偏好',text)
        self.assertNotIn('摄影私人数据',text)
        # Relevant recall should not also drag in the newest unrelated notes.
        self.assertNotIn('不相关104',text)
