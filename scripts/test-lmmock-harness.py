#!/usr/bin/env python3
"""Offline regression checks for PATH selection and lmmock fallback policy."""
import contextlib
import importlib.util
import io
import os
import sys
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
        for key in ('LMMOCK_BIN', 'LMMOCK_VERSION', 'LMMOCK_REQUIRED', 'LMMOCK_LMSCRIPT_JS', 'LMSCRIPT_BIN'):
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


    def fake_compiler(self, body):
        # Python stands in for Node so these process tests need no installed compiler.
        compiler = self.directory / 'compiler with spaces.js'
        compiler.write_text(body, encoding='utf-8')
        self.stack.enter_context(patch.dict(os.environ, {'LMMOCK_LMSCRIPT_JS': str(compiler)}))
        self.stack.enter_context(patch.object(harness.shutil, 'which', return_value=sys.executable))

    def test_failing_compiler_reports_stderr_without_starting_server(self):
        self.fake_compiler("import sys; sys.stderr.write('fixture compiler syntax error'); sys.exit(7)")
        (self.directory / 'source.lms').write_text('fixture source', encoding='utf-8')
        with patch.object(harness, 'export_schema'), \
             patch.object(harness, 'locate_lmmock', return_value='lmmock'), \
             patch.object(harness, '_server') as server:
            with self.assertRaisesRegex(RuntimeError, 'compiler exited 7: fixture compiler syntax error'):
                with harness.lmmock_serve(self.directory / 'source.lms'):
                    self.fail('failing compiler yielded a server')
            server.assert_not_called()

    def test_source_compiles_before_serve_and_bytecode_is_cleaned(self):
        shim = self.directory / 'broken lmscript.cmd'
        shim.write_text('@echo off\nexit /b 99\n', encoding='utf-8')
        self.stack.enter_context(patch.dict(os.environ, {'LMSCRIPT_BIN': str(shim)}))
        self.fake_compiler("import sys; from pathlib import Path; Path(sys.argv[-1]).write_bytes(b'fixture-bytecode')")
        source = self.directory / 'source with spaces.lms'
        source.write_text('fixture source', encoding='utf-8')
        paths = []
        @contextlib.contextmanager
        def server(arguments, config, *, binary):
            self.assertEqual(binary, 'lmmock')
            self.assertEqual(arguments[:2], ['serve', '--lmcode'])
            bytecode = Path(arguments[2])
            self.assertEqual(bytecode.read_bytes(), b'fixture-bytecode')
            self.assertEqual(config, {'fixture': True})
            paths.append(bytecode)
            yield 'http://127.0.0.1:1234'
        with patch.object(harness, 'export_schema'), \
             patch.object(harness, 'locate_lmmock', return_value='lmmock'), \
             patch.object(harness, '_server', server):
            with harness.lmmock_serve(self.directory / 'source with spaces.lms', {'fixture': True}) as url:
                self.assertEqual(url, 'http://127.0.0.1:1234')
        self.assertFalse(paths[0].exists())

    def test_failed_server_includes_stderr(self):
        with patch.object(harness, 'locate_lmmock', return_value=sys.executable):
            with self.assertRaisesRegex(RuntimeError, r'before readiness \(exit 1\): fixture server error'):
                with harness._server(['-c', "import sys; sys.stderr.write('fixture server error'); sys.exit(1)"]):
                    self.fail('failed server became ready')


    def test_compile_uses_exact_serving_schema_not_source_schema(self):
        source = self.directory / 'fixture.lms'
        source.write_bytes(b'p = _lmcode_ schema="schema.json";\n')
        stale = b'{"schema":"stale"}\r\n'
        (self.directory / 'schema.json').write_bytes(stale)
        canonical = b'{"schema":"serving binary"}\n'
        self.fake_compiler(
            "import sys; from pathlib import Path; "
            "source = Path(sys.argv[-2]); "
            f"assert source.with_name('schema.json').read_bytes() == {canonical!r}; "
            "Path(sys.argv[-1]).write_bytes(b'checked-schema')")
        real_run = harness.subprocess.run
        def run(args, **kwargs):
            if args == ['selected-lmmock', 'schema']:
                self.assertNotIn('text', kwargs)
                return harness.subprocess.CompletedProcess(args, 0, canonical, b'')
            return real_run(args, **kwargs)
        @contextlib.contextmanager
        def server(arguments, config, *, binary):
            self.assertEqual(binary, 'selected-lmmock')
            self.assertEqual(Path(arguments[2]).read_bytes(), b'checked-schema')
            yield 'http://127.0.0.1:1234'
        with patch.object(harness, 'locate_lmmock', side_effect=['selected-lmmock', 'wrong-binary']) as locate, \
             patch.object(harness.subprocess, 'run', side_effect=run), \
             patch.object(harness, '_server', server):
            with harness.lmmock_serve(source):
                pass
            locate.assert_called_once_with()
        self.assertEqual((self.directory / 'schema.json').read_bytes(), stale)

    def test_schema_export_failure_stops_before_compilation(self):
        source = self.directory / 'fixture.lms'
        source.write_bytes(b'fixture')
        failed = harness.subprocess.CompletedProcess([], 2, b'', b'fixture schema export error')
        with patch.object(harness, 'locate_lmmock', return_value='selected-lmmock'), \
             patch.object(harness.subprocess, 'run', return_value=failed), \
             patch.object(harness, 'compile_script') as compile_script:
            with self.assertRaisesRegex(RuntimeError, 'schema export exited 2: fixture schema export error'):
                with harness.lmmock_serve(source):
                    self.fail('failed export became ready')
            compile_script.assert_not_called()


if __name__ == '__main__':
    unittest.main()
