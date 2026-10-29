#!/usr/bin/env python3
"""Offline cleanup regression checks, including simulated Windows sharing errors."""
import os
import unittest
from unittest.mock import patch
from temp_cleanup import temporary_directory


class CleanupTests(unittest.TestCase):
    def test_removes_directory_on_body_failure(self):
        with self.assertRaisesRegex(RuntimeError, 'body failed'):
            with temporary_directory(prefix='lmclient-cleanup-') as directory:
                with open(os.path.join(directory, 'fixture'), 'w') as output:
                    output.write('dummy')
                raise RuntimeError('body failed')
        self.assertFalse(os.path.exists(directory))

    @patch('temp_cleanup.time.sleep')
    @patch('temp_cleanup.shutil.rmtree', side_effect=[PermissionError(), PermissionError(), None])
    @patch('temp_cleanup.tempfile.mkdtemp', return_value='fixture-directory')
    def test_retries_transient_sharing_error(self, mkdir, remove, sleep):
        with temporary_directory() as directory:
            self.assertEqual(directory, 'fixture-directory')
        self.assertEqual(remove.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        sleep.assert_called_with(0.5)

    @patch('temp_cleanup.time.sleep')
    @patch('temp_cleanup.shutil.rmtree', side_effect=PermissionError('still locked'))
    @patch('temp_cleanup.tempfile.mkdtemp', return_value='fixture-directory')
    def test_persistent_lock_fails_after_ten_retries(self, mkdir, remove, sleep):
        with self.assertRaisesRegex(PermissionError, 'still locked'):
            with temporary_directory():
                pass
        self.assertEqual(remove.call_count, 11)
        self.assertEqual(sleep.call_count, 10)

    @patch('temp_cleanup.time.sleep')
    @patch('temp_cleanup.shutil.rmtree', side_effect=OSError('not a sharing error'))
    @patch('temp_cleanup.tempfile.mkdtemp', return_value='fixture-directory')
    def test_other_errors_are_not_retried(self, mkdir, remove, sleep):
        with self.assertRaisesRegex(OSError, 'not a sharing error'):
            with temporary_directory():
                pass
        self.assertEqual(remove.call_count, 1)
        sleep.assert_not_called()


if __name__ == '__main__':
    unittest.main()
