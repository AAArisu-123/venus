"""Tests for the Venus local QQ credential store (file based).

The QR onboarding flow writes the AppID/AppSecret obtained from Tencent into
a local file; the bot then reads it at startup instead of requiring the user
to copy secrets by hand. Nothing here prints, logs or echoes a secret.
"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from venus.credentials import load_credentials, save_credentials


class LoadTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / 'nested' / 'qq.json'

    def write(self, text):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(text, encoding='utf-8')

    def test_missing_file_returns_none(self):
        self.assertIsNone(load_credentials(self.path))

    def test_valid_file_returns_tuple(self):
        self.write(json.dumps({'app_id': '10001', 'app_secret': 's3cret'}))
        self.assertEqual(load_credentials(self.path), ('10001', 's3cret'))

    def test_invalid_json_raises(self):
        self.write('{not json')
        with self.assertRaises(ValueError):
            load_credentials(self.path)

    def test_non_dict_raises(self):
        self.write('[1, 2]')
        with self.assertRaises(ValueError):
            load_credentials(self.path)

    def test_missing_blank_or_non_string_fields_raise(self):
        for payload in ({}, {'app_id': '1'}, {'app_secret': 's'},
                        {'app_id': '', 'app_secret': 's'},
                        {'app_id': '1', 'app_secret': '   '},
                        {'app_id': 1, 'app_secret': 's'},
                        {'app_id': '1', 'app_secret': None}):
            with self.subTest(payload=payload):
                self.write(json.dumps(payload))
                with self.assertRaises(ValueError):
                    load_credentials(self.path)


class SaveTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / 'nested' / 'qq.json'

    def test_save_creates_directories_and_roundtrips(self):
        save_credentials(self.path, '10001', 's3cret')
        self.assertTrue(self.path.is_file())
        self.assertEqual(load_credentials(self.path), ('10001', 's3cret'))

    def test_saved_file_is_utf8_json_with_both_values(self):
        save_credentials(self.path, '10001', 's3cret')
        data = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(data, {'app_id': '10001', 'app_secret': 's3cret'})

    def test_no_temporary_files_left_behind(self):
        save_credentials(self.path, '10001', 's3cret')
        leftovers = [p.name for p in self.path.parent.iterdir() if p.name != 'qq.json']
        self.assertEqual(leftovers, [])

    def test_invalid_values_raise_and_write_nothing(self):
        for app_id, app_secret in (('', 's'), ('1', ''), ('  ', 's'), (None, 's'), ('1', 5)):
            with self.subTest(app_id=app_id, app_secret=app_secret):
                with self.assertRaises(ValueError):
                    save_credentials(self.path, app_id, app_secret)
                self.assertFalse(self.path.exists())

    def test_failed_validation_keeps_existing_file_intact(self):
        save_credentials(self.path, '10001', 's3cret')
        with self.assertRaises(ValueError):
            save_credentials(self.path, '', 'new')
        self.assertEqual(load_credentials(self.path), ('10001', 's3cret'))

    def test_never_prints_values(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            save_credentials(self.path, '10001', 's3cret')
            load_credentials(self.path)
        self.assertEqual(out.getvalue() + err.getvalue(), '')


if __name__ == '__main__':
    unittest.main()
