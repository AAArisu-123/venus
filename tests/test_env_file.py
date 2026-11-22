"""Tests for the optional .env loader."""

import tempfile
import unittest
from pathlib import Path

from venus.env_file import load_env_file


class EnvFileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / '.env'

    def load(self, text, environ=None):
        self.path.write_text(text, encoding='utf-8')
        env = {} if environ is None else environ
        return load_env_file(self.path, env), env

    def test_missing_file_is_a_noop(self):
        env = {}
        self.assertEqual(load_env_file(Path(self._tmp.name) / 'nope', env), 0)
        self.assertEqual(env, {})

    def test_reads_simple_pairs(self):
        added, env = self.load('A=1\nB=two\n')
        self.assertEqual(added, 2)
        self.assertEqual(env, {'A': '1', 'B': 'two'})

    def test_ignores_blank_lines_comments_and_junk(self):
        added, env = self.load('\n# comment\nNOEQUALS\n=noname\nC=3\n')
        self.assertEqual(added, 1)
        self.assertEqual(env, {'C': '3'})

    def test_strips_quotes_and_spaces(self):
        _, env = self.load(' A = "x y" \nB=\'z\'\n')
        self.assertEqual(env, {'A': 'x y', 'B': 'z'})

    def test_does_not_override_existing_values(self):
        added, env = self.load('A=filed\n', {'A': 'existing'})
        self.assertEqual(added, 0)
        self.assertEqual(env['A'], 'existing')

    def test_value_may_contain_equals_signs(self):
        _, env = self.load('K=abc=def\n')
        self.assertEqual(env['K'], 'abc=def')

    def test_never_prints_values(self):
        import contextlib, io
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.load('SECRET=value\n')
        self.assertEqual(out.getvalue() + err.getvalue(), '')


if __name__ == '__main__':
    unittest.main()
