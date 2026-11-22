import json
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from venus.__main__ import DEFAULT_PERSONA, answer
from venus import affect
from venus.affect_appraisal import make_appraisal, should_appraise
from venus.commands import handle_command
from venus.memory import connect_database, history

SCOPE = str(DEFAULT_PERSONA.resolve())
USER = 'test-qq'
ARGS = ('https://example.invalid/v1', 'fake-model', 'fake-key')


class AppraisalTests(unittest.TestCase):
    def test_only_known_finite_per_field_changes_are_applied(self):
        raw = ('{"emotion":{"happiness":2,"sadness":0.6,"anger":true,"anxiety":1e999},'
               '"relationship":{"affection":-8,"trust":"1","unknown":1},'
               '"self_state":{"self_presence":4},"unrecognized":{"x":1}}')
        self.assertEqual(affect.parse_delta(raw), {
            'emotion': {'happiness': 1, 'sadness': 0.6},
            'relationship': {'affection': -0.35}, 'self_state': {'self_presence': 0.35},
        })

    def test_unusable_json_is_ignored(self):
        for raw in ('[1]', 'null', '{', '```json\n{}\n```', ' ' * 5000 + '{}', '[' * 2000):
            with self.subTest(raw=raw[:15]):
                self.assertEqual(affect.parse_delta(raw), {})

    def test_appraisal_keeps_recent_input_bounded_and_out_of_system_role(self):
        captured = []
        make_appraisal(captured.extend, {'name': '维纳斯', 'description': '沉稳'}, '平静',
                       [('user', str(i) + '长' * 400) for i in range(8)], ['忆' * 300] * 7,
                       '用户文字' * 500)
        self.assertEqual([p['role'] for p in captured], ['system', 'user'])
        self.assertNotIn('用户文字', captured[0]['content'])
        data = json.loads(captured[1]['content'])
        self.assertEqual([v[:1] for _, v in data['recent']], list('234567'))
        self.assertEqual([len(v) for _, v in data['recent']], [350] * 6)
        self.assertEqual([len(v) for v in data['memories']], [250] * 5)
        self.assertEqual(len(data['current_text']), 1600)

    def test_appraisal_skips_short_neutral_turns(self):
        self.assertTrue(should_appraise('你好。', history_len=0))
        self.assertFalse(should_appraise('你好。', history_len=2))
        self.assertTrue(should_appraise('今天有点难过。', history_len=2))
        self.assertTrue(should_appraise('这是一段超过二十四个字符的普通聊天内容，用来触发评估。', history_len=2))
        self.assertFalse(should_appraise('', history_len=0))


@unittest.skipIf(affect.StateEngine is None, 'install requirements-affect.txt for AnimaFlux tests')
class AffectIntegrationTests(unittest.TestCase):
    def test_opt_in_and_reload_supply_prior_mood_to_next_turn(self):
        calls = []

        def complete(messages, *args, **kwargs):
            calls.append(messages)
            return ('{"emotion":{"happiness":0.9,"anxiety":0.5}}'
                    if len(calls) == 1 else '{}'
                    if len(calls) == 3 else '接着聊吧。')

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'venus.sqlite3'
            with closing(connect_database(path)) as db:
                self.assertIn('已开启', handle_command(db, SCOPE, USER, '/心情 开启'))
                with patch('venus.__main__._complete', side_effect=complete):
                    answer(db, DEFAULT_PERSONA, USER, '刚才那句话说得真好。', *ARGS)
            with closing(connect_database(path)) as db:
                with patch('venus.__main__._complete', side_effect=complete):
                    answer(db, DEFAULT_PERSONA, USER, '我回来了，今天有点累。', *ARGS)
                self.assertIn('愉快', handle_command(db, SCOPE, USER, '/心情'))
        self.assertEqual(len(calls), 4)
        self.assertIn('愉快', calls[3][0]['content'])
        self.assertIn('不安', calls[3][0]['content'])
        self.assertNotIn('愉快', calls[2][0]['content'].split('人设', 1)[0])
        self.assertIn('愉快', json.loads(calls[2][-1]['content'])['prior_tone'])

    def test_decay_preserves_durable_context_and_isolates_scope(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with closing(connect_database(':memory:')) as db:
            handle_command(db, SCOPE, USER, '/心情 开启')
            rev, state = affect.snapshot(db, SCOPE, USER, now)
            state = affect.preview(state, {'emotion': {'happiness': 1}, 'relationship': {'trust': 0.3}})
            self.assertTrue(affect.commit(db, SCOPE, USER, rev, state))
            _, later = affect.snapshot(db, SCOPE, USER, now + timedelta(hours=24))
            self.assertEqual(later['emotion']['happiness'], 5.5)
            self.assertEqual(later['relationship']['trust'], 5.3)
            other_scope = affect.snapshot(db, SCOPE, 'someone-else', now)
            other_persona = affect.snapshot(db, 'other-persona', USER, now)
            self.assertIsNotNone(other_scope)
            self.assertIsNotNone(other_persona)
            self.assertEqual(other_scope[1]['emotion']['happiness'], 5.0)
            self.assertEqual(other_persona[1]['emotion']['happiness'], 5.0)

    def test_reset_and_disable_invalidate_pending_updates(self):
        with closing(connect_database(':memory:')) as db:
            handle_command(db, SCOPE, USER, '/心情 开启')
            rev, state = affect.snapshot(db, SCOPE, USER)
            self.assertIn('已重置', handle_command(db, SCOPE, USER, '/心情 重置'))
            self.assertFalse(affect.commit(db, SCOPE, USER, rev, state))
            rev, state = affect.snapshot(db, SCOPE, USER)
            handle_command(db, SCOPE, USER, '/心情 关闭')
            self.assertIsNone(affect.snapshot(db, SCOPE, USER))
            handle_command(db, SCOPE, USER, '/心情 开启')
            self.assertFalse(affect.commit(db, SCOPE, USER, rev, state))

    def test_default_on_adds_one_appraisal_request(self):
        with closing(connect_database(':memory:')) as db:
            with patch('venus.__main__._complete', return_value='你好。') as complete:
                self.assertEqual(answer(db, DEFAULT_PERSONA, USER, '你好。', *ARGS), '你好。')
            self.assertEqual(complete.call_count, 2)
            self.assertIn('角色状态', complete.call_args_list[0].args[0][0]['content'])

    def test_failed_appraisal_still_returns_normal_reply(self):
        with closing(connect_database(':memory:')) as db:
            handle_command(db, SCOPE, USER, '/心情 开启')
            with patch('venus.__main__._complete', side_effect=[ValueError('评估失败'), '还在。']):
                self.assertEqual(answer(db, DEFAULT_PERSONA, USER, '在吗？', *ARGS), '还在。')
            self.assertEqual(affect.snapshot(db, SCOPE, USER)[0], 0)

    def test_failed_reply_has_no_state_change(self):
        with closing(connect_database(':memory:')) as db:
            handle_command(db, SCOPE, USER, '/心情 开启')
            with patch('venus.__main__._complete', side_effect=['{"emotion":{"happiness":1}}', ValueError('回复失败')]):
                with self.assertRaises(ValueError):
                    answer(db, DEFAULT_PERSONA, USER, '在吗？', *ARGS)
            self.assertEqual(affect.snapshot(db, SCOPE, USER)[0], 0)
            self.assertEqual(history(db, SCOPE, USER), [])
