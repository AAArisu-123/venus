"""Tests for the Venus pairing-code access module.

Pairing is the owner-approval flow that replaces a static allowlist: an
unknown user is given a short code, the owner approves that code locally,
and only then may the user be served. These tests pin the security
properties that matter — codes are short-lived, single-use, never leak
through the pending list once approved, and access is denied by default.
"""

import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from venus.pairing import (
    CODE_ALPHABET,
    CODE_LENGTH,
    CODE_TTL_SECONDS,
    approve_code,
    approved_openids,
    connect_database,
    is_allowed,
    pending_codes,
    request_code,
    revoke_openid,
)


AMBIGUOUS = set('01OI')


class PairingTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / 'nested' / 'pairing.sqlite3'
        self.db = connect_database(self.db_path)
        self.addCleanup(self.db.close)
        self.now = 1_000_000

    def reopen(self):
        return connect_database(self.db_path)

    def request(self, openid, make_code=None, now=None):
        return request_code(self.db, openid,
                            now=self.now if now is None else now,
                            make_code=make_code or (lambda: 'A2B3C4'))

    def approve(self, code, now=None):
        return approve_code(self.db, code,
                            now=self.now if now is None else now)

    def test_connect_creates_schema_and_parent_directories(self):
        self.assertTrue(self.db_path.is_file())
        objects = dict(self.db.execute(
            "SELECT name, type FROM sqlite_master WHERE type IN ('table', 'index')"
        ).fetchall())
        self.assertEqual(objects.get('pairings'), 'table')
        columns = [row[1] for row in self.db.execute('PRAGMA table_info(pairings)')]
        self.assertEqual(
            columns,
            ['code', 'openid', 'created_at', 'approved_at'],
        )

    def test_reopening_is_idempotent_and_keeps_data(self):
        self.request('user-1')
        self.approve('A2B3C4')
        with closing(self.reopen()) as other:
            self.assertTrue(is_allowed(other, 'user-1'))
        self.assertTrue(is_allowed(self.db, 'user-1'))

    def test_request_returns_code_from_alphabet(self):
        codes = []
        for index in range(20):
            openid = f'user-{index}'
            code = request_code(self.db, openid, now=self.now)
            self.assertIsInstance(code, str)
            self.assertEqual(len(code), CODE_LENGTH)
            self.assertEqual(set(code), set(code.upper()))
            self.assertTrue(set(code) <= set(CODE_ALPHABET))
            self.assertFalse(set(code) & AMBIGUOUS)
            codes.append(code)
        self.assertEqual(len(set(codes)), len(codes))

    def test_code_format_constants(self):
        self.assertEqual(CODE_LENGTH, 6)
        self.assertEqual(CODE_TTL_SECONDS, 600)
        self.assertTrue(set(CODE_ALPHABET) <= set('ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'))

    def test_is_denied_before_approval(self):
        code = self.request('user-1')
        self.assertEqual(code, 'A2B3C4')
        self.assertFalse(is_allowed(self.db, 'user-1'))

    def test_approval_allows_the_openid(self):
        self.request('user-1')
        self.assertEqual(self.approve('A2B3C4'), 'user-1')
        self.assertTrue(is_allowed(self.db, 'user-1'))

    def test_is_allowed_denies_unknown_openid(self):
        self.assertFalse(is_allowed(self.db, 'nobody'))
        self.assertFalse(is_allowed(self.db, ''))
        self.assertFalse(is_allowed(self.db, None))

    def test_unknown_code_approves_nothing(self):
        self.request('user-1')
        self.assertIsNone(self.approve('ZZZZZZ'))
        self.assertFalse(is_allowed(self.db, 'user-1'))

    def test_approval_is_single_use(self):
        self.request('user-1')
        self.request('user-2', make_code=lambda: 'D4E5F6')
        self.assertEqual(self.approve('A2B3C4'), 'user-1')
        self.assertIsNone(self.approve('A2B3C4'))
        self.assertFalse(is_allowed(self.db, 'user-2'))

    def test_code_match_ignores_case_and_surrounding_space(self):
        self.request('user-1')
        self.assertEqual(self.approve('  a2b3c4 \t'), 'user-1')
        self.assertTrue(is_allowed(self.db, 'user-1'))

    def test_blank_or_badly_typed_code_approves_nothing(self):
        self.request('user-1')
        for bad in ('', '   ', None, 42, 'A2B3C4A', '??????'):
            with self.subTest(code=bad):
                self.assertIsNone(approve_code(self.db, bad, now=self.now))
        self.assertFalse(is_allowed(self.db, 'user-1'))

    def test_code_expires_at_ttl(self):
        self.request('user-1')
        self.assertIsNone(self.approve('A2B3C4', now=self.now + CODE_TTL_SECONDS))
        self.assertFalse(is_allowed(self.db, 'user-1'))

    def test_code_is_valid_one_second_before_expiry(self):
        self.request('user-1')
        self.assertEqual(self.approve('A2B3C4', now=self.now + CODE_TTL_SECONDS - 1),
                         'user-1')

    def test_approval_is_not_time_limited(self):
        self.request('user-1')
        self.assertEqual(self.approve('A2B3C4'), 'user-1')
        self.assertTrue(is_allowed(self.db, 'user-1'))
        self.request('user-1', make_code=lambda: 'G7H5J6')
        self.assertTrue(is_allowed(self.db, 'user-1'))

    def test_rerequest_replaces_the_pending_code(self):
        first = self.request('user-1')
        second = self.request('user-1', make_code=lambda: 'K2M3N4')
        self.assertEqual(second, 'K2M3N4')
        self.assertIsNone(self.approve(first))
        self.assertEqual(self.approve(second), 'user-1')

    def test_request_for_allowed_openid_issues_nothing(self):
        self.request('user-1')
        self.approve('A2B3C4')
        self.assertIsNone(self.request('user-1', make_code=lambda: 'K2M3N4'))
        self.assertEqual([item for item in pending_codes(self.db, now=self.now)
                          if item[1] == 'user-1'], [])

    def test_pending_lists_only_unexpired_unapproved_codes(self):
        self.request('user-1')
        self.request('user-2', make_code=lambda: 'D4E5F6')
        self.request('user-3', make_code=lambda: 'P7Q6R5', now=self.now - CODE_TTL_SECONDS - 1)
        self.approve('D4E5F6')
        later = self.request('user-4', make_code=lambda: 'S2T3U4')
        self.assertEqual(pending_codes(self.db, now=self.now),
                         [('A2B3C4', 'user-1'), (later, 'user-4')])

    def test_pending_is_empty_by_default(self):
        self.assertEqual(pending_codes(self.db, now=self.now), [])

    def test_revoke_blocks_access(self):
        self.request('user-1')
        self.approve('A2B3C4')
        self.assertTrue(revoke_openid(self.db, 'user-1'))
        self.assertFalse(is_allowed(self.db, 'user-1'))

    def test_revoke_can_be_granted_again(self):
        self.request('user-1')
        self.approve('A2B3C4')
        revoke_openid(self.db, 'user-1')
        self.request('user-1', make_code=lambda: 'K2M3N4')
        self.assertEqual(self.approve('K2M3N4'), 'user-1')
        self.assertTrue(is_allowed(self.db, 'user-1'))

    def test_revoke_unknown_openid_returns_false(self):
        self.assertFalse(revoke_openid(self.db, 'nobody'))

    def test_request_rejects_invalid_openid(self):
        for bad in ('', '   ', None, 42, ['user']):
            with self.subTest(openid=bad):
                with self.assertRaises((TypeError, ValueError)):
                    request_code(self.db, bad, now=self.now)
        self.assertEqual(pending_codes(self.db, now=self.now), [])

    def test_openids_are_matched_exactly(self):
        self.request('user-1')
        self.approve('A2B3C4')
        for near in ('user-11', 'user-', 'User-1', ' user-1'):
            with self.subTest(openid=near):
                self.assertFalse(is_allowed(self.db, near))

    def test_values_are_bound_not_interpolated(self):
        payload = "A'); DROP TABLE pairings; --"
        self.request(payload, make_code=lambda: 'A2B3C4')
        self.assertEqual(self.approve('A2B3C4'), payload)
        self.assertTrue(is_allowed(self.db, payload))
        self.assertEqual(
            self.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='pairings'"
            ).fetchone(),
            ('pairings',),
        )

    def test_distinct_openids_do_not_share_access(self):
        self.request('user-1')
        self.request('user-2', make_code=lambda: 'D4E5F6')
        self.approve('A2B3C4')
        self.assertTrue(is_allowed(self.db, 'user-1'))
        self.assertFalse(is_allowed(self.db, 'user-2'))

    def test_approved_openids_lists_only_approved_users_in_approval_order(self):
        self.request('user-1', make_code=lambda: 'A2B3C4')
        self.request('user-2', make_code=lambda: 'D4E5F6')
        self.request('user-3', make_code=lambda: 'G7H5J6')
        self.approve('A2B3C4')
        self.approve('G7H5J6', now=self.now + 5)
        self.assertEqual(approved_openids(self.db), ['user-1', 'user-3'])

    def test_approved_openids_is_empty_by_default(self):
        self.assertEqual(approved_openids(self.db), [])

    def test_revoked_user_disappears_from_the_approved_list(self):
        self.request('user-1')
        self.approve('A2B3C4')
        self.assertEqual(approved_openids(self.db), ['user-1'])
        revoke_openid(self.db, 'user-1')
        self.assertEqual(approved_openids(self.db), [])

    def test_bad_make_code_is_not_stored(self):
        for bad in (lambda: 'short', lambda: 'aaaaaaaa', lambda: 'a2b3c4',
                    lambda: 'A2B3C0', lambda: None, lambda: 42):
            with self.subTest(make_code=bad):
                with self.assertRaises((TypeError, ValueError)):
                    request_code(self.db, 'user-1', now=self.now, make_code=bad)
        self.assertEqual(pending_codes(self.db, now=self.now), [])
        self.assertFalse(is_allowed(self.db, 'user-1'))


if __name__ == '__main__':
    unittest.main()


