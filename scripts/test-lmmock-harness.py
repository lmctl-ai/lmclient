#!/usr/bin/env python3
"""Offline regression checks for PATH selection and lmmock fallback policy."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import urllib.error
from temp_cleanup import temporary_directory

spec = importlib.util.spec_from_file_location('lmmock_helpers', Path(__file__).with_name('lmmock-helpers.py'))
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = Path(self.stack.enter_context(temporary_directory(prefix='lmclient-harness-')))
        env = dict(os.environ)
        for key in ('LMMOCK_BIN', 'LMMOCK_VERSION', 'LMMOCK_REQUIRED'):
            env.pop(key, None)
        env['PATH'] = str(self.directory)
        self.stack.enter_context(patch.dict(os.environ, env, clear=True))
        self.stack.enter_context(patch.object(harness, 'ROOT', self.directory))

    def fake(self, version=None, proto_exit=0):
        version = version or harness.PINNED_VERSION
        if os.name == 'nt':
            path = self.directory / 'lmmock.cmd'
            source = (f'@echo off\nif "%1"=="--version" (\n'
                      f'echo lmmock {version}\nexit /b 0\n)\n'
                      f'if "%1 %2"=="proto --list" exit /b {proto_exit}\nexit /b 2\n')
        else:
            path = self.directory / 'lmmock'
            source = (f'#!/bin/sh\nif [ "$1" = "--version" ]; then\n'
                      f'echo "lmmock {version}"\nexit 0\nfi\n'
                      f'if [ "$1 $2" = "proto --list" ]; then exit {proto_exit}; fi\nexit 2\n')
        path.write_text(source, encoding='utf-8')
        path.chmod(0o755)
        return str(path.resolve())

    def test_stale_proto_falls_back_even_with_matching_version(self):
        self.fake(proto_exit=2)
        with patch.object(harness, 'download_lmmock', return_value='verified-download') as download:
            self.assertEqual(harness.locate_lmmock(), 'verified-download')
            download.assert_called_once_with()

    def test_different_version_falls_back(self):
        for version in ('0.1.4', '99.0.0'):
            with self.subTest(version=version):
                self.fake(version=version)
                with patch.object(harness, 'download_lmmock', return_value='verified-download'):
                    self.assertEqual(harness.locate_lmmock(), 'verified-download')

    def test_matching_version_and_proto_use_path(self):
        binary = self.fake()
        with patch.object(harness, 'download_lmmock') as download:
            self.assertEqual(harness.locate_lmmock(), binary)
            download.assert_not_called()

    def test_version_override_is_the_effective_pin(self):
        binary = self.fake(version='0.1.99')
        with patch.dict(os.environ, {'LMMOCK_VERSION': 'v0.1.99'}):
            self.assertEqual(harness.locate_lmmock(), binary)

    def test_explicit_binary_remains_an_override(self):
        binary = self.fake(version='0.1.4', proto_exit=2)
        with patch.dict(os.environ, {'LMMOCK_BIN': binary}), patch.object(harness.subprocess, 'run') as run:
            self.assertEqual(harness.locate_lmmock(), binary)
            run.assert_not_called()

    def test_failed_probe_falls_back(self):
        self.fake()
        for failure in (OSError('cannot execute'), harness.subprocess.TimeoutExpired('lmmock', 5)):
            with self.subTest(failure=type(failure).__name__), \
                 patch.object(harness.subprocess, 'run', side_effect=failure), \
                 patch.object(harness, 'download_lmmock', return_value='verified-download'):
                self.assertEqual(harness.locate_lmmock(), 'verified-download')

    def test_unavailable_download_skips_or_fails_when_required(self):
        self.fake(proto_exit=2)
        with patch.object(harness.urllib.request, 'urlopen', side_effect=urllib.error.URLError('offline')):
            output = io.StringIO()
            with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as skipped:
                harness.locate_lmmock()
            self.assertEqual(skipped.exception.code, 0)
            self.assertIn('SKIP lmmock: cannot download', output.getvalue())
            with patch.dict(os.environ, {'LMMOCK_REQUIRED': '1'}), self.assertRaisesRegex(RuntimeError, 'lmmock required:'):
                harness.locate_lmmock()


if __name__ == '__main__':
    unittest.main()
