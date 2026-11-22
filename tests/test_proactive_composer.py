"""Tests for compose(), using a local fake model endpoint."""

import json
import tempfile
import threading
import unittest
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from venus.long_memory import add_memory, init_memory, list_memories
from venus.memory import connect_database, history, save_turn
from venus.proactive_composer import compose, compose_opener


PERSONA_NAME = 'V测试人设'
PERSONA_DESC = '温柔、安静、喜欢深夜聊天的伙伴'
DESCRIPTION_MARKER = 'DESC_MARKER_' + PERSONA_DESC
SELF_USER = 'p/user'
SELF_TURN_MARKER = 'SELF_HISTORY_MARKER_自已有话'
SELF_REPLY_MARKER = 'SELF_REPLY_MARKER_自有回复'
SELF_MEMORY_MARKER = 'SELF_MEMORY_MARKER_自有长期记忆'
OTHER_USER = 'other/user'
OTHER_PERSONA = 'otherpersona'
OTHER_SCOPE_MARKER = 'OTHER_SCOPE_MARKER_绝不该出现'
GENERATED = '今晚的月亮很好，你在忙什么呢'
API_KEY = 'sk-fake-secret-key-123'


def _openai_body(content):
    return json.dumps(
        {'choices': [{'message': {'role': 'assistant', 'content': content}}]},
        ensure_ascii=False,
    ).encode('utf-8')


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        raw = self.rfile.read(length)
        self.server.captured.append(
            {'path': self.path, 'headers': dict(self.headers), 'raw': raw}
        )
        payload = _openai_body(self.server.response_content)
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args, **kwargs):
        pass


class ComposerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)

        # Fake persona file (JSON {name, description}).
        self.persona_path = root / 'persona.json'
        self.persona_path.write_text(
            json.dumps(
                {'name': PERSONA_NAME, 'description': DESCRIPTION_MARKER},
                ensure_ascii=False,
            ),
            encoding='utf-8',
        )

        PERSONA_SCOPE = str(self.persona_path.resolve())
        self.persona_scope = PERSONA_SCOPE
        # Seed the DB: own scope vs. two unrelated other-scope variants.
        self.db_path = root / 'data.db'
        with closing(connect_database(self.db_path)) as db:
            init_memory(db)
            save_turn(
                db, PERSONA_SCOPE, SELF_USER,
                SELF_TURN_MARKER, SELF_REPLY_MARKER,
            )
            add_memory(db, PERSONA_SCOPE, SELF_USER, SELF_MEMORY_MARKER)
            # Same persona, different user -> must be excluded.
            save_turn(db, PERSONA_SCOPE, OTHER_USER, OTHER_SCOPE_MARKER, 'x')
            add_memory(db, PERSONA_SCOPE, OTHER_USER, OTHER_SCOPE_MARKER)
            # Same user, different persona -> must be excluded.
            save_turn(db, OTHER_PERSONA, SELF_USER, OTHER_SCOPE_MARKER, 'y')
            add_memory(db, OTHER_PERSONA, SELF_USER, OTHER_SCOPE_MARKER)
            db.commit()
            self.msg_count_before = db.execute(
                'SELECT COUNT(*) FROM messages'
            ).fetchone()[0]
            self.mem_count_before = db.execute(
                'SELECT COUNT(*) FROM memories'
            ).fetchone()[0]

        # Local fake OpenAI server.
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
        self.server.captured = []
        self.server.response_content = GENERATED
        self.base_url = 'http://127.0.0.1:%d/v1' % self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._shutdown)

    def _shutdown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _call(self, api_key=API_KEY):
        with closing(connect_database(self.db_path)) as db:
            init_memory(db)
            return compose(
                db, str(self.persona_path), SELF_USER,
                self.base_url, 'gpt-fake', api_key,
            )

    def _call_opener(self, mode='proactive'):
        with closing(connect_database(self.db_path)) as db:
            init_memory(db)
            return compose_opener(
                db, str(self.persona_path), SELF_USER,
                self.base_url, 'gpt-fake', API_KEY, mode=mode,
            )

    def _payload_text(self):
        entry = self.server.captured[-1]
        body = json.loads(entry['raw'].decode('utf-8'))
        # Serialize back with Chinese preserved so substring checks are stable.
        return entry, body, json.dumps(body, ensure_ascii=False)

    def test_returns_generated_string(self):
        self.assertEqual(self._call().strip(), GENERATED)

    def test_json_answer_is_split_into_message_and_life(self):
        self.server.response_content = json.dumps(
            {'life': '今晚在家煮火锅', 'message': '在煮火锅，来蹭一口？'},
            ensure_ascii=False,
        )
        result = self._call_opener()
        self.assertEqual(result['message'], '在煮火锅，来蹭一口？')
        self.assertEqual(result['life'], '今晚在家煮火锅')

    def test_plain_text_answer_has_no_life_note(self):
        result = self._call_opener()
        self.assertEqual(result['message'], GENERATED)
        self.assertEqual(result['life'], '')

    def test_followup_mode_asks_for_one_catch_up_message(self):
        self._call_opener(mode='followup')
        _, _, text = self._payload_text()
        self.assertIn('补一条', text)
        self.assertIn('压力', text)
        self.assertIn('数据', text)

    def test_sends_request_to_base_url_with_model_and_key(self):
        self._call()
        entry, body, _ = self._payload_text()
        self.assertIn('chat/completions', entry['path'])
        self.assertEqual(body.get('model'), 'gpt-fake')
        joined_headers = ' '.join(
            '%s:%s' % (k, v) for k, v in entry['headers'].items()
        ).lower()
        self.assertIn(API_KEY.lower(), joined_headers)

    def test_payload_includes_own_history_and_memory_and_persona(self):
        self._call()
        _, _, text = self._payload_text()
        self.assertIn(SELF_TURN_MARKER, text)
        self.assertIn(SELF_REPLY_MARKER, text)
        self.assertIn(SELF_MEMORY_MARKER, text)
        self.assertIn(DESCRIPTION_MARKER, text)

    def test_payload_excludes_other_scope(self):
        self._call()
        _, _, text = self._payload_text()
        self.assertNotIn(OTHER_SCOPE_MARKER, text)

    def test_payload_carries_explicit_chinese_instruction(self):
        self._call()
        _, _, text = self._payload_text()
        # Must be a Chinese-language instruction, not bare English boilerplate.
        self.assertTrue(any('\u4e00' <= c <= '\u9fff' for c in text))
        # A single, natural, short, proactive opener.
        self.assertIn('主动', text)
        self.assertIn('开场', text)
        self.assertIn('自然', text)
        self.assertTrue('一句' in text or '一条' in text or '简短' in text)
        # Grounded in the supplied context.
        self.assertTrue(
            '历史' in text or '记忆' in text or '上下文' in text or '根据' in text
        )
        # Treat history/memory strictly as data, never as instructions.
        self.assertIn('数据', text)
        self.assertIn('指令', text)
        # Do not invent shared experiences.
        self.assertIn('虚构', text)
        # Do not pressure the user.
        self.assertIn('压力', text)

    def test_does_not_persist_and_invents_no_user_turn(self):
        self._call()
        with closing(connect_database(self.db_path)) as db:
            init_memory(db)
            self.assertEqual(
                db.execute('SELECT COUNT(*) FROM messages').fetchone()[0],
                self.msg_count_before,
            )
            self.assertEqual(
                db.execute('SELECT COUNT(*) FROM memories').fetchone()[0],
                self.mem_count_before,
            )
            # Own history is exactly what was seeded (one user + one reply).
            turns = history(db, self.persona_scope, SELF_USER)
            self.assertEqual(len(turns), 2)
            self.assertNotIn(OTHER_SCOPE_MARKER, [c for _, c in turns])
            # Own long memory untouched.
            self.assertEqual(
                [c for _, c in list_memories(db, self.persona_scope, SELF_USER)],
                [SELF_MEMORY_MARKER],
            )

    def test_empty_response_raises_value_error(self):
        self.server.response_content = ''
        with self.assertRaises(ValueError):
            self._call()

    def test_whitespace_response_raises_value_error(self):
        self.server.response_content = '   \n  '
        with self.assertRaises(ValueError):
            self._call()


if __name__ == '__main__':
    unittest.main()
