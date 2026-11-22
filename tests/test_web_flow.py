import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from venus.memory import connect_database
from venus.long_memory import init_memory
from venus.web_settings import set_enabled
from venus.__main__ import answer
from venus.proactive_composer import compose, compose_opener

NATURAL = {'message': '刚收拾完桌子，准备开一局', 'life': '在收拾桌子'}


class WebFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.p=Path(self.tmp.name)/'p.json'; self.p.write_text('{"name":"V","description":"友善"}',encoding='utf-8')
        self.db=connect_database(Path(self.tmp.name)/'db'); self.addCleanup(self.db.close)
        init_memory(self.db); self.db.commit()
        self.scope=str(self.p.resolve())

    def test_enabled_chat_uses_web_tool_and_returns_attributed_source(self):
        set_enabled(self.db,self.scope,'u',True)
        with patch('venus.__main__._complete', return_value='{}'), \
             patch('venus.__main__.complete_web',return_value=('我找到一则消息',[{'url':'https://example.org/news','title':'新闻'}])):
            result=answer(self.db,self.p,'u','最近的消息','https://api.deepseek.com','x','fake')
        self.assertIn('https://example.org/news',result)

    def test_enabled_proactive_searches_and_shares_sourced_result(self):
        set_enabled(self.db,self.scope,'u',True)
        with patch('venus.proactive_composer.complete_web',return_value=('看到一个有趣的新闻',[{'url':'https://example.org/story','title':'来源'}])) as call:
            result=compose(self.db,self.p,'u','https://api.deepseek.com','x','fake')
        self.assertIn('https://example.org/story',result)
        self.assertEqual(call.call_count,1)

    def test_web_share_parses_json_answer_and_keeps_the_source(self):
        set_enabled(self.db,self.scope,'u',True)
        content = '{"life": "下午看了一集新番", "message": "刚看到个新情报"}'
        with patch('venus.proactive_composer.complete_web',
                   return_value=(content,[{'url':'https://example.org/story','title':'来源'}])):
            result = compose_opener(self.db,self.p,'u','https://api.deepseek.com','x','fake')
        self.assertEqual(result['message'],
                         '刚看到个新情报\n来源：https://example.org/story')
        self.assertEqual(result['life'], '下午看了一集新番')

    def test_proactive_disabled_during_generation_does_not_share(self):
        set_enabled(self.db,self.scope,'u',True)
        def revoke(*args):
            set_enabled(self.db,self.scope,'u',False)
            return ('新闻',[{'url':'https://example.org/story','title':'来源'}])
        with patch('venus.proactive_composer.complete_web',side_effect=revoke), \
             patch('venus.proactive_composer._compose_natural', return_value=NATURAL):
            result=compose(self.db,self.p,'u','https://api.deepseek.com','x','fake')
        self.assertEqual(result, NATURAL['message'])
        self.assertNotIn('example.org', result)

    def test_enabled_proactive_does_not_share_unsourced_live_claim(self):
        set_enabled(self.db,self.scope,'u',True)
        with patch('venus.proactive_composer.complete_web',return_value=('编造的新闻',[])), \
             patch('venus.proactive_composer._compose_natural', return_value=NATURAL):
            result=compose(self.db,self.p,'u','https://api.deepseek.com','x','fake')
        self.assertEqual(result, NATURAL['message'])

    def test_web_failure_still_sends_a_natural_opener(self):
        set_enabled(self.db,self.scope,'u',True)
        from venus.web_tool import WebToolError
        with patch('venus.proactive_composer.complete_web',
                   side_effect=WebToolError('down')), \
             patch('venus.proactive_composer._compose_natural', return_value=NATURAL) as natural:
            result=compose(self.db,self.p,'u','https://api.deepseek.com','x','fake')
        self.assertEqual(result, NATURAL['message'])
        self.assertEqual(natural.call_count, 1)

    def test_web_unsupported_host_falls_back_to_natural(self):
        set_enabled(self.db,self.scope,'u',True)
        with patch('venus.proactive_composer.complete_web') as web, \
             patch('venus.proactive_composer._compose_natural', return_value=NATURAL):
            result=compose(self.db,self.p,'u','https://example.com/v1','x','fake')
        self.assertEqual(result, NATURAL['message'])
        web.assert_not_called()


if __name__ == '__main__':
    unittest.main()
