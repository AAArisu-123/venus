"""Offline tests for the Windows scheduled QQ entry point."""
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from venus.qq_service import GatewayStatusOnly, open_status_handler, run


class ServiceTests(unittest.TestCase):
    def test_return_is_failure_so_scheduler_restarts(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(run(lambda: 0, Path(tmp)), 1)

    def test_exception_details_are_not_written(self):
        def fail():
            raise RuntimeError('synthetic-credential')

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self.assertEqual(run(fail, folder), 1)
            text = (folder / 'qq-service.log').read_text(encoding='utf-8')
            self.assertIn('RuntimeError', text)
            self.assertNotIn('synthetic-credential', text)

    def test_sdk_logs_are_reduced_to_known_status_events(self):
        filt = GatewayStatusOnly()
        record = logging.LogRecord('botpy', logging.INFO, 'gateway.py', 1,
                                   '[botpy] 机器人「%s」启动成功！', ('private-name',), None)
        self.assertTrue(filt.filter(record))
        self.assertEqual(record.getMessage(), 'QQ gateway READY')
        record = logging.LogRecord('botpy', logging.ERROR, 'http.py', 1,
                                   'request headers: synthetic-token', (), None)
        self.assertFalse(filt.filter(record))

    def test_runner_status_events_are_kept_but_free_text_is_not(self):
        filt = GatewayStatusOnly()
        record = logging.LogRecord(
            'venus.proactive_runner', logging.WARNING, 'proactive_runner.py', 1,
            'status: proactive send failed (%s)', ('TimeoutError',), None)
        self.assertTrue(filt.filter(record))
        self.assertEqual(record.getMessage(),
                         'status: proactive send failed (TimeoutError)')
        record = logging.LogRecord(
            'venus.proactive_runner', logging.WARNING, 'proactive_runner.py', 1,
            'chat text: synthetic-message', (), None)
        self.assertFalse(filt.filter(record))

    def test_log_falls_back_when_the_primary_folder_is_unusable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            blocker = root / 'blocked'
            blocker.write_text('not a directory', encoding='utf-8')
            temp_dir = root / 'temp'
            temp_dir.mkdir()
            with patch.dict(os.environ, {'TEMP': str(temp_dir)}):
                handler = open_status_handler(blocker)
                try:
                    self.assertIn(
                        str(temp_dir / 'Venus' / 'logs'), handler.baseFilename)
                    handler.emit(logging.LogRecord(
                        'venus.qq_service', logging.INFO, 'x', 1, 'ok', (), None))
                finally:
                    handler.close()
            self.assertTrue((temp_dir / 'Venus' / 'logs' / 'qq-service.log').exists())

