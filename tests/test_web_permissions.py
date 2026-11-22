"""Tests for per-(persona, user) web permissions and their QQ commands.

Test-first specification: ``venus.web_settings`` and the ``/联网`` commands in
``venus.commands`` are the intended implementation; these tests describe the
contract they must satisfy. Only a throwaway SQLite database in a temporary
directory is used -- no network access, credentials or real user data.
"""

import tempfile
import unittest
from pathlib import Path

from venus import web_settings
from venus.commands import handle_command
from venus.memory import connect_database


class WebSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / 'data.db'
        self.db = connect_database(self.db_path)
        self.addCleanup(self.db.close)

    def test_is_enabled_defaults_to_false(self):
        for persona, user in (('p', 'alice'), ('p', 'bob'), ('other', 'alice')):
            with self.subTest(persona=persona, user=user):
                self.assertFalse(web_settings.is_enabled(self.db, persona, user))

    def test_set_enabled_toggles_and_is_read_back(self):
        web_settings.set_enabled(self.db, 'p', 'alice', True)
        self.assertTrue(web_settings.is_enabled(self.db, 'p', 'alice'))
        web_settings.set_enabled(self.db, 'p', 'alice', False)
        self.assertFalse(web_settings.is_enabled(self.db, 'p', 'alice'))

    def test_no_cross_user_or_persona_leakage(self):
        web_settings.set_enabled(self.db, 'p', 'alice', True)
        self.assertTrue(web_settings.is_enabled(self.db, 'p', 'alice'))
        self.assertFalse(web_settings.is_enabled(self.db, 'p', 'bob'))
        self.assertFalse(web_settings.is_enabled(self.db, 'other', 'alice'))

        web_settings.set_enabled(self.db, 'p', 'bob', True)
        web_settings.set_enabled(self.db, 'other', 'alice', True)
        self.assertTrue(web_settings.is_enabled(self.db, 'p', 'alice'))
        self.assertTrue(web_settings.is_enabled(self.db, 'p', 'bob'))
        self.assertTrue(web_settings.is_enabled(self.db, 'other', 'alice'))

        web_settings.set_enabled(self.db, 'p', 'bob', False)
        self.assertTrue(web_settings.is_enabled(self.db, 'p', 'alice'))
        self.assertFalse(web_settings.is_enabled(self.db, 'p', 'bob'))
        self.assertTrue(web_settings.is_enabled(self.db, 'other', 'alice'))

    def test_enabled_flag_is_committed_and_survives_reopen(self):
        web_settings.set_enabled(self.db, 'p', 'alice', True)
        self.db.close()

        reopened = connect_database(self.db_path)
        self.addCleanup(reopened.close)
        self.assertTrue(web_settings.is_enabled(reopened, 'p', 'alice'))
        self.assertFalse(web_settings.is_enabled(reopened, 'p', 'bob'))
        self.assertFalse(web_settings.is_enabled(reopened, 'other', 'alice'))


class WebCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = connect_database(Path(self.tmp.name) / 'data.db')
        self.addCleanup(self.db.close)

    def _assert_discloses_provider_sharing(self, reply):
        """Public/web search must warn that terms go to a provider."""
        self.assertIn('发送', reply)
        term_words = ('搜索词', '搜索关键词', '查询词', '检索词')
        self.assertTrue(
            any(word in reply for word in term_words),
            f'回复未提到搜索词：{reply!r}',
        )
        provider_words = ('服务商', '提供方', '服务方', '第三方', 'provider')
        self.assertTrue(
            any(word in reply for word in provider_words),
            f'回复未说明搜索词会发送给搜索服务商：{reply!r}',
        )

    def test_enable_and_disable_commands_toggle_the_setting(self):
        self.assertFalse(web_settings.is_enabled(self.db, 'p', 'alice'))

        enable_reply = handle_command(self.db, 'p', 'alice', '/联网 开启')
        self.assertIsInstance(enable_reply, str)
        self.assertTrue(enable_reply.strip())
        self.assertTrue(web_settings.is_enabled(self.db, 'p', 'alice'))

        disable_reply = handle_command(self.db, 'p', 'alice', '/联网 关闭')
        self.assertIsInstance(disable_reply, str)
        self.assertTrue(disable_reply.strip())
        self.assertFalse(web_settings.is_enabled(self.db, 'p', 'alice'))

    def test_web_command_does_not_affect_other_scopes(self):
        handle_command(self.db, 'p', 'alice', '/联网 开启')
        self.assertTrue(web_settings.is_enabled(self.db, 'p', 'alice'))
        self.assertFalse(web_settings.is_enabled(self.db, 'p', 'bob'))
        self.assertFalse(web_settings.is_enabled(self.db, 'other', 'alice'))

    def test_help_lists_both_web_commands(self):
        help_text = handle_command(self.db, 'p', 'alice', '/帮助')
        self.assertIn('/联网 开启', help_text)
        self.assertIn('/联网 关闭', help_text)

    def test_enable_reply_discloses_provider_sharing(self):
        reply = handle_command(self.db, 'p', 'alice', '/联网 开启')
        self._assert_discloses_provider_sharing(reply)


if __name__ == '__main__':
    unittest.main()
