import io
import contextlib
import tempfile
import time
import unittest

from venus import pair_cli
from venus import pairing


def run_cli(argv):
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = pair_cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


class MaskTests(unittest.TestCase):
    def test_mask_keeps_first_four_and_last_two(self):
        masked = pair_cli.mask_openid('OPENID_1234567890abcdef')
        self.assertEqual(masked, 'OPEN****ef')

    def test_mask_short_openid_shows_nothing(self):
        self.assertEqual(pair_cli.mask_openid('abc123'), '****')


class ListTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.db_path = self._dir.name + '/pairing.sqlite3'
        self.now = time.time()
        db = pairing.connect_database(self.db_path)
        try:
            pairing.request_code(
                db, 'USERAAA_0123456789xyz',
                now=self.now, make_code=lambda: 'AAAAAA',
            )
            pairing.request_code(
                db, 'USERBBB_9876543210qpr',
                now=self.now, make_code=lambda: 'ZZZZZZ',
            )
            pairing.request_code(
                db, 'OLDDONE_5555555555abc',
                now=self.now - pairing.CODE_TTL_SECONDS - 1,
                make_code=lambda: 'BBBBBB',
            )
        finally:
            db.close()

    def test_list_prints_exact_masked_lines(self):
        rc, out, err = run_cli(['--list', '--db', self.db_path])
        self.assertEqual(rc, 0)
        self.assertEqual(out, 'AAAAAA USER****yz\nZZZZZZ USER****pr\n')
        self.assertEqual(err, '')

    def test_list_never_leaks_full_openid(self):
        rc, out, err = run_cli(['--list', '--db', self.db_path])
        for secret in ('USERAAA_0123456789xyz', 'USERBBB_9876543210qpr'):
            self.assertNotIn(secret, out)
            self.assertNotIn(secret, err)

    def test_list_empty_prints_nothing(self):
        empty_path = self._dir.name + '/empty.sqlite3'
        rc, out, err = run_cli(['--list', '--db', empty_path])
        self.assertEqual(rc, 0)
        self.assertEqual(out, '')


class ApproveTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.db_path = self._dir.name + '/pairing.sqlite3'
        self.now = time.time()
        db = pairing.connect_database(self.db_path)
        try:
            pairing.request_code(
                db, 'USERAAA_0123456789xyz',
                now=self.now, make_code=lambda: 'ABCDEF',
            )
            pairing.request_code(
                db, 'EXPIRED_0123456789zzz',
                now=self.now - pairing.CODE_TTL_SECONDS - 1,
                make_code=lambda: 'FEDCBA',
            )
        finally:
            db.close()

    def test_approve_prints_masked_paired_user(self):
        rc, out, err = run_cli(['--approve', 'ABCDEF', '--db', self.db_path])
        self.assertEqual(rc, 0)
        self.assertEqual(out, 'paired user USER****yz\n')
        self.assertNotIn('USERAAA_0123456789xyz', out)

    def test_approve_marks_user_allowed(self):
        run_cli(['--approve', 'ABCDEF', '--db', self.db_path])
        db = pairing.connect_database(self.db_path)
        try:
            self.assertTrue(pairing.is_allowed(db, 'USERAAA_0123456789xyz'))
        finally:
            db.close()

    def test_approve_expired_code_prints_nothing(self):
        rc, out, err = run_cli(['--approve', 'FEDCBA', '--db', self.db_path])
        self.assertEqual(rc, 0)
        self.assertEqual(out, '')

    def test_approve_unknown_code_prints_nothing(self):
        rc, out, err = run_cli(['--approve', 'QQQQQQ', '--db', self.db_path])
        self.assertEqual(rc, 0)
        self.assertEqual(out, '')
        self.assertNotIn('QQQQQQ', out)

    def test_approve_twice_prints_nothing_the_second_time(self):
        run_cli(['--approve', 'ABCDEF', '--db', self.db_path])
        rc, out, err = run_cli(['--approve', 'ABCDEF', '--db', self.db_path])
        self.assertEqual(rc, 0)
        self.assertEqual(out, '')


class RevokeTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.db_path = self._dir.name + '/pairing.sqlite3'
        self.now = time.time()
        db = pairing.connect_database(self.db_path)
        try:
            pairing.request_code(
                db, 'USERAAA_0123456789xyz',
                now=self.now, make_code=lambda: 'ABCDEF',
            )
            pairing.approve_code(db, 'ABCDEF', now=self.now)
        finally:
            db.close()

    def test_revoke_paired_user(self):
        rc, out, err = run_cli(['--revoke', 'USERAAA_0123456789xyz',
                                '--db', self.db_path])
        self.assertEqual(rc, 0)
        self.assertEqual(out, 'revoked USER****yz\n')
        self.assertNotIn('USERAAA_0123456789xyz', out)
        db = pairing.connect_database(self.db_path)
        try:
            self.assertFalse(pairing.is_allowed(db, 'USERAAA_0123456789xyz'))
        finally:
            db.close()

    def test_revoke_unknown_user_reports_not_revoked(self):
        rc, out, err = run_cli(['--revoke', 'NOBODY_0123456789abc',
                                '--db', self.db_path])
        self.assertEqual(rc, 0)
        self.assertEqual(out, 'not revoked NOBO****bc\n')


class UsageErrorTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.db_path = self._dir.name + '/pairing.sqlite3'

    def assert_usage_error(self, argv):
        rc, out, err = run_cli(argv)
        self.assertEqual(rc, 2)
        self.assertEqual(out, '')
        self.assertTrue(err.startswith('usage:'), err)
        return err

    def test_no_action(self):
        self.assert_usage_error([])

    def test_unknown_flag(self):
        self.assert_usage_error(['--zap'])

    def test_bare_argument(self):
        self.assert_usage_error(['ABCDEF'])

    def test_approve_without_code(self):
        self.assert_usage_error(['--approve'])

    def test_db_without_path(self):
        self.assert_usage_error(['--db'])

    def test_duplicate_db(self):
        self.assert_usage_error(['--db', self.db_path, '--db', self.db_path])

    def test_duplicate_list(self):
        self.assert_usage_error(['--list', '--list'])

    def test_multiple_actions(self):
        self.assert_usage_error(
            ['--list', '--approve', 'ABCDEF', '--db', self.db_path])

    def test_flag_as_option_value_is_rejected(self):
        err = self.assert_usage_error(['--revoke', '--list'])
        self.assertNotIn('usage:usage', err)

    def test_usage_error_never_echoes_openid(self):
        secret = 'USERAAA_0123456789xyz'
        rc, out, err = run_cli(['--revoke', secret, '--bogus'])
        self.assertEqual(rc, 2)
        self.assertNotIn(secret, out)
        self.assertNotIn(secret, err)


if __name__ == '__main__':
    unittest.main()
