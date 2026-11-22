"""Tests for the QQ access gate (allowlist or pairing-code approval)."""

import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from venus.pairing import approve_code, connect_database
from venus.qq_access import AccessGate


class AllowlistTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.pair_db = Path(self._tmp.name) / 'pairing.sqlite3'

    def gate(self, allowed=('open-a',), **kwargs):
        return AccessGate(allowed, self.pair_db, **kwargs)

    def test_allowlisted_user_is_allowed_without_pairing(self):
        self.assertEqual(self.gate().decide('open-a'), ('allow', None))

    def test_non_allowlisted_user_is_denied_and_never_prompted(self):
        self.assertEqual(self.gate().decide('stranger'), ('deny', None))

    def test_allowlist_takes_precedence_over_pairing_db(self):
        gate = self.gate()
        self.assertEqual(gate.decide('stranger'), ('deny', None))
        with closing(connect_database(self.pair_db)) as db:
            approve_code(db, 'A2B3C4', now=1000)  # nothing pending: no effect

    def test_blank_user_is_denied(self):
        for bad in ('', '   ', None, 42):
            with self.subTest(bad=bad):
                self.assertEqual(self.gate().decide(bad), ('deny', None))


class PairingModeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.pair_db = Path(self._tmp.name) / 'pairing.sqlite3'
        self.now = 1000

    def gate(self, code='A2B3C4'):
        return AccessGate(frozenset(), self.pair_db,
                          make_code=lambda: code, now=lambda: self.now)

    def test_unknown_user_gets_a_prompt_with_a_code_once(self):
        gate = self.gate()
        self.assertEqual(gate.decide('stranger'), ('prompt', 'A2B3C4'))
        self.assertEqual(gate.decide('stranger'), ('deny', None))

    def test_prompt_does_not_reach_the_model(self):
        gate = self.gate()
        kind, code = gate.decide('stranger')
        self.assertEqual(kind, 'prompt')
        self.assertEqual(code, 'A2B3C4')

    def test_approved_user_is_allowed_after_local_approval(self):
        gate = self.gate()
        gate.decide('stranger')
        with closing(connect_database(self.pair_db)) as db:
            self.assertEqual(approve_code(db, 'A2B3C4', now=self.now), 'stranger')
        self.assertEqual(gate.decide('stranger'), ('allow', None))

    def test_other_users_stay_blocked_after_someone_is_approved(self):
        gate = self.gate()
        gate.decide('stranger')
        with closing(connect_database(self.pair_db)) as db:
            approve_code(db, 'A2B3C4', now=self.now)
        self.assertEqual(gate.decide('someone-else'), ('prompt', 'A2B3C4'))

    def test_approval_expires_and_user_is_asked_again(self):
        gate = self.gate()
        gate.decide('stranger')
        with closing(connect_database(self.pair_db)) as db:
            approve_code(db, 'A2B3C4', now=self.now)
        self.now += 10 ** 9
        self.assertEqual(gate.decide('stranger'), ('allow', None))

    def test_blank_user_is_denied_in_pairing_mode(self):
        gate = self.gate()
        for bad in ('', '   ', None, 42):
            with self.subTest(bad=bad):
                self.assertEqual(gate.decide(bad), ('deny', None))

    def test_corrupt_pairing_db_fails_closed(self):
        self.pair_db.parent.mkdir(parents=True, exist_ok=True)
        self.pair_db.write_text('not a database', encoding='utf-8')
        self.assertEqual(self.gate().decide('stranger'), ('deny', None))


if __name__ == '__main__':
    unittest.main()
