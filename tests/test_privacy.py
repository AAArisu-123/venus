import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from venus.__main__ import answer
from venus.commands import handle_command
from venus.long_memory import add_memory, init_memory, list_memories
from venus.memory import connect_database, history
from venus.privacy import detect, redact, safe_reply
from venus.prompt import build_messages
from venus.profile import get_profile, init_profile


class DetectTests(unittest.TestCase):
    def test_detects_high_confidence_secrets(self):
        cases = {
            "sk-" + "a" * 24: "API 密钥",
            "AIza" + "a" * 35: "API 密钥",
            "Bearer " + "a" * 24: "访问令牌",
            "我的密码是 abc123": "密码",
            "验证码 123456": "验证码",
            "11010519491231002X": "身份证号",
            "6222021234567890123": "银行卡号",
            "我的手机号是13800138000": "手机号",
            "someone@example.com": "邮箱",
            "-----BEGIN RSA PRIVATE KEY-----": "私钥",
        }
        for text, label in cases.items():
            with self.subTest(text=text[:20]):
                self.assertIn(label, detect(text))

    def test_ordinary_conversation_is_not_blocked(self):
        for text in (
            "我喜欢红茶，今天很开心",
            "我在写一个密码管理器",
            "今天验证码还没到",
            "我们聊聊摄影吧",
        ):
            with self.subTest(text=text):
                self.assertEqual(detect(text), [])

    def test_redact_removes_values_and_keeps_context(self):
        text = "我的手机号是13800138000，晚点联系"
        result = redact(text)
        self.assertNotIn("13800138000", result)
        self.assertIn("[已隐藏]", result)
        self.assertIn("晚点联系", result)

    def test_safe_reply_does_not_echo_the_value(self):
        reply = safe_reply(["手机号"])
        self.assertIn("手机号", reply)
        self.assertIn("没有发送", reply)
        self.assertNotIn("13800138000", reply)


class PrivacyIntegrationTests(unittest.TestCase):
    def test_answer_blocks_sensitive_message_before_model_and_history(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            persona = root / "persona.json"
            persona.write_text(
                json.dumps({"name": "V", "description": "友善"}, ensure_ascii=False),
                encoding="utf-8",
            )
            with closing(connect_database(root / "data.db")) as db:
                with patch("venus.__main__._complete") as complete:
                    result = answer(
                        db, persona, "u", "我的手机号是13800138000",
                        "http://127.0.0.1:1/v1", "m", "k",
                    )
                complete.assert_not_called()
                self.assertIn("没有发送", result)
                self.assertEqual(history(db, str(persona.resolve()), "u"), [])

    def test_remember_and_profile_commands_reject_sensitive_values(self):
        with closing(sqlite3.connect(":memory:")) as db:
            init_memory(db)
            init_profile(db)
            result = handle_command(db, "p", "u", "/记住 我的密码是 abc123")
            self.assertIn("没有发送", result)
            self.assertEqual(list_memories(db, "p", "u"), [])
            result = handle_command(db, "p", "u", "/称呼 13800138000")
            self.assertIn("没有发送", result)
            self.assertEqual(get_profile(db, "p", "u")["display_name"], "")
            mid = add_memory(db, "p", "u", "旧内容")
            result = handle_command(db, "p", "u", f"/修改记忆 {mid} 我的密码是 abc123")
            self.assertIn("没有发送", result)
            self.assertEqual(list_memories(db, "p", "u"), [(mid, "旧内容")])

    def test_old_history_and_memory_are_redacted_before_model(self):
        persona = {"name": "V", "description": "友善"}
        profile = {}
        memories = [(1, "我的手机号是13800138000")]
        rows = [("user", "我的银行卡6222021234567890123")]
        messages = build_messages(persona, profile, memories, rows, "你好")
        text = json.dumps(messages, ensure_ascii=False)
        self.assertNotIn("13800138000", text)
        self.assertNotIn("6222021234567890123", text)
        self.assertIn("[已隐藏]", text)


if __name__ == "__main__":
    unittest.main()
