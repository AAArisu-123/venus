"""TDD tests for venus.auto_memory (tests only; module not yet implemented).

API under test:
    extract_candidates(text) -> list[str]
        Deterministic, regex-based extraction of explicit first-person
        Chinese preference statements. No model is involved, so nothing can
        be "hallucinated": text without an explicit 我+喜欢-style statement
        yields []. Text containing sensitive terms (passwords, codes, bank,
        medical), long digit runs, third-party or negated statements, or
        longer than 200 chars yields [] wholesale.

    remember_candidates(db, persona, user_id, text) -> list[int]
        Runs extract_candidates and stores each candidate into the existing
        venus.long_memory schema via that module, returning the new row ids.
        Successive equivalent candidates within one call are deduplicated,
        and candidates already stored for this exact (persona, user_id)
        scope are suppressed (exact-string match). Other scopes are
        unaffected. Persistence is ordinary SQLite (survives reopen).

All storage tests use a tempfile-backed SQLite file with the schema created
by venus.long_memory.init_memory.
"""

import os
import sqlite3
import tempfile
import unittest

from venus import auto_memory, long_memory

# Contract: wholesale text rejection above this length.
MAX_TEXT_LEN = 200

PERSONA = "venus"
USER = "alice"


def _rows(db, persona=PERSONA, user_id=USER):
    return [c for _, c in long_memory.list_memories(db, persona, user_id)]


class ExtractTestCase(unittest.TestCase):
    """Pure-function behavior of extract_candidates (no db, no files)."""

    def test_explicit_preference_extracted_verbatim(self):
        self.assertEqual(auto_memory.extract_candidates("我喜欢红茶"), ["我喜欢红茶"])

    def test_trailing_punctuation_stripped(self):
        self.assertEqual(auto_memory.extract_candidates("我喜欢红茶。"), ["我喜欢红茶"])

    def test_preference_embedded_in_conversation(self):
        # The candidate is the statement itself, not the whole chat line.
        self.assertEqual(
            auto_memory.extract_candidates("嗯嗯好的，我喜欢红茶，谢谢啦"),
            ["我喜欢红茶"],
        )

    def test_multiple_distinct_candidates(self):
        result = auto_memory.extract_candidates("我喜欢红茶。我喜欢散步。")
        self.assertEqual(result, ["我喜欢红茶", "我喜欢散步"])

    def test_generic_greeting_yields_nothing(self):
        for text in (
            "你好！",
            "很高兴认识你",
            "今天天气不错",
            "I like black tea",
            "",
            "   ",
        ):
            with self.subTest(text=text):
                self.assertEqual(auto_memory.extract_candidates(text), [])

    def test_vague_or_hypothetical_statements_yields_nothing(self):
        # Only explicit concrete statements count; nothing is invented.
        for text in (
            "我可能喜欢喝点什么呢",
            "随便，都行，看你们安排",
            "我说不清自己喜欢啥",
        ):
            with self.subTest(text=text):
                self.assertEqual(auto_memory.extract_candidates(text), [])

    def test_extraction_is_deterministic(self):
        text = "我喜欢红茶。"
        self.assertEqual(
            auto_memory.extract_candidates(text),
            auto_memory.extract_candidates(text),
        )


class ExtractRejectionTestCase(unittest.TestCase):
    """Sensitive / third-party / negated / overlong inputs reject wholesale."""

    def test_password_and_code_terms_rejected(self):
        for text in (
            "我喜欢密码是abc123的账号",
            "我的密码是 hunter2，我喜欢安静",
            "我喜欢验证码123456",
        ):
            with self.subTest(text=text):
                self.assertEqual(auto_memory.extract_candidates(text), [])

    def test_bank_terms_rejected(self):
        self.assertEqual(
            auto_memory.extract_candidates("我喜欢银行卡余额变多"), []
        )

    def test_medical_terms_rejected(self):
        for text in (
            "我在医院附近住，我喜欢安静",
            "我确诊了糖尿病，我喜欢清淡饮食",
        ):
            with self.subTest(text=text):
                self.assertEqual(auto_memory.extract_candidates(text), [])

    def test_long_digit_runs_rejected(self):
        for text in (
            "我喜欢手机号13800138000归属地的风景",
            "我喜欢卡号6222021234567890的银行",  # also bank, digit run alone:
        ):
            with self.subTest(text=text):
                self.assertEqual(auto_memory.extract_candidates(text), [])
        self.assertEqual(
            auto_memory.extract_candidates("我喜欢编号9876543210的产品"), []
        )

    def test_third_party_statements_rejected(self):
        for text in (
            "他喜欢红茶",
            "她喜欢喝咖啡",
            "你喜欢红茶吗",
        ):
            with self.subTest(text=text):
                self.assertEqual(auto_memory.extract_candidates(text), [])

    def test_negated_statements_rejected(self):
        for text in (
            "我不喜欢红茶",
            "我并不是很喜欢咖啡",
        ):
            with self.subTest(text=text):
                self.assertEqual(auto_memory.extract_candidates(text), [])

    def test_overlong_text_rejected(self):
        filler = "聊" * (MAX_TEXT_LEN - len("我喜欢红茶"))
        too_long = "我喜欢红茶。" + filler
        self.assertGreater(len(too_long), MAX_TEXT_LEN)
        self.assertEqual(auto_memory.extract_candidates(too_long), [])

    def test_at_length_limit_not_rejected_for_length(self):
        text = ("我喜欢红茶。" + "聊" * MAX_TEXT_LEN)[:MAX_TEXT_LEN]
        self.assertEqual(len(text), MAX_TEXT_LEN)
        # Exactly at the limit must not trip the >200 rejection; whether a
        # truncated statement still matches is the module's business, but it
        # must not raise.
        auto_memory.extract_candidates(text)


class RememberCandidatesTestCase(unittest.TestCase):
    """remember_candidates against the existing long_memory schema on disk."""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(fd)
        self.db = sqlite3.connect(self.db_path, isolation_level=None)
        long_memory.init_memory(self.db)

    def tearDown(self):
        self.db.close()
        os.unlink(self.db_path)

    def test_stores_candidate_into_long_memory_table(self):
        ids = auto_memory.remember_candidates(self.db, PERSONA, USER, "我喜欢红茶。")
        self.assertEqual(len(ids), 1)
        self.assertIsInstance(ids[0], int)
        self.assertEqual(_rows(self.db), ["我喜欢红茶"])

    def test_stores_multiple_candidates(self):
        ids = auto_memory.remember_candidates(
            self.db, PERSONA, USER, "我喜欢红茶。我喜欢散步。"
        )
        self.assertEqual(len(ids), 2)
        self.assertEqual(_rows(self.db), ["我喜欢红茶", "我喜欢散步"])

    def test_successive_equivalent_candidates_deduplicated(self):
        # Two equivalent statements in one call -> one stored memory.
        auto_memory.remember_candidates(
            self.db, PERSONA, USER, "我喜欢红茶。我喜欢红茶。"
        )
        self.assertEqual(_rows(self.db), ["我喜欢红茶"])

    def test_exact_duplicate_across_calls_suppressed(self):
        auto_memory.remember_candidates(self.db, PERSONA, USER, "我喜欢红茶。")
        again = auto_memory.remember_candidates(self.db, PERSONA, USER, "我喜欢红茶。")
        self.assertEqual(again, [])
        self.assertEqual(_rows(self.db), ["我喜欢红茶"])

    def test_non_matching_text_stores_nothing(self):
        ids = auto_memory.remember_candidates(self.db, PERSONA, USER, "你好呀，今天天气不错")
        self.assertEqual(ids, [])
        self.assertEqual(_rows(self.db), [])

    def test_sensitive_text_stores_nothing(self):
        auto_memory.remember_candidates(
            self.db, PERSONA, USER, "我的密码是abc123，我喜欢红茶"
        )
        self.assertEqual(_rows(self.db), [])

    def test_scoped_per_user(self):
        auto_memory.remember_candidates(self.db, PERSONA, "alice", "我喜欢红茶。")
        # bob's identical statement is new for his scope, not suppressed.
        ids = auto_memory.remember_candidates(self.db, PERSONA, "bob", "我喜欢红茶。")
        self.assertEqual(len(ids), 1)
        self.assertEqual(_rows(self.db, user_id="bob"), ["我喜欢红茶"])
        # alice's view unchanged; scopes never cross.
        self.assertEqual(_rows(self.db, user_id="alice"), ["我喜欢红茶"])
        auto_memory.remember_candidates(self.db, PERSONA, "bob", "我喜欢游泳。")
        self.assertEqual(_rows(self.db, user_id="alice"), ["我喜欢红茶"])

    def test_scoped_per_persona(self):
        auto_memory.remember_candidates(self.db, "venus", USER, "我喜欢红茶。")
        ids = auto_memory.remember_candidates(self.db, "mars", USER, "我喜欢红茶。")
        self.assertEqual(len(ids), 1)
        self.assertEqual(_rows(self.db, persona="mars"), ["我喜欢红茶"])
        self.assertEqual(_rows(self.db, persona="venus"), ["我喜欢红茶"])

    def test_persistence_survives_reopen(self):
        auto_memory.remember_candidates(self.db, PERSONA, USER, "我喜欢红茶。")
        self.db.close()
        again = sqlite3.connect(self.db_path, isolation_level=None)
        try:
            long_memory.init_memory(again)  # must be safe on existing data
            self.assertEqual(_rows(again), ["我喜欢红茶"])
            # Suppression consultates persisted state, not process memory.
            self.assertEqual(
                auto_memory.remember_candidates(again, PERSONA, USER, "我喜欢红茶。"),
                [],
            )
        finally:
            again.close()
        self.db = sqlite3.connect(self.db_path, isolation_level=None)


if __name__ == "__main__":
    unittest.main()
