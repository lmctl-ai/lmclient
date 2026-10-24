#!/usr/bin/env python3
"""Eight regression tests for check-linux-linkage.py."""
import importlib.util
import subprocess
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).with_name("check-linux-linkage.py")
SPEC = importlib.util.spec_from_file_location("check_linux_linkage", SCRIPT)
assert SPEC and SPEC.loader
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)

READ_ELF_DYNAMIC = """
Dynamic section at offset 0x1000 contains 4 entries:
 0x0000000000000001 (NEEDED) Shared library: [libc.so.6]
 0x0000000000000001 (NEEDED) Shared library: [libm.so.6]
 0x0000000000000001 (NEEDED) Shared library: [ld-linux-x86-64.so.2]
"""
VERSION_235 = "Name: GLIBC_2.35  Flags: none  Version: 1\n"

def completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)

class LinuxLinkageTests(unittest.TestCase):
    def readelf_runner(self, command, **kwargs):
        self.assertEqual(kwargs["timeout"], 30)
        self.assertEqual(kwargs["env"]["LC_ALL"], "C")
        return completed(VERSION_235 if "--version-info" in command else READ_ELF_DYNAMIC)

    @mock.patch.object(checker.subprocess, "run")
    @mock.patch.object(checker.shutil, "which", return_value="/usr/bin/readelf")
    def test_allowed_dynamic_dependencies(self, which, run):
        run.side_effect = self.readelf_runner
        checker.check("host")
        self.assertEqual(run.call_count, 2)

    @mock.patch.object(checker.subprocess, "run")
    @mock.patch.object(checker.shutil, "which", return_value="/usr/bin/readelf")
    def test_static_or_missing_libc_rejected(self, which, run):
        run.side_effect = [completed("There is no dynamic section in this file."), completed(VERSION_235)]
        with self.assertRaisesRegex(checker.LinkageError, "libc.so.6"):
            checker.check("host")

    @mock.patch.object(checker.subprocess, "run")
    @mock.patch.object(checker.shutil, "which", return_value="/usr/bin/readelf")
    def test_other_shared_library_rejected(self, which, run):
        run.side_effect = [completed(READ_ELF_DYNAMIC.replace("libm.so.6", "libstdc++.so.6") +
                                      " (NEEDED) Shared library: [libother.so.1]\n")]
        with self.assertRaisesRegex(checker.LinkageError, "libstdc\\+\\+.so.6"):
            checker.check("host")

    @mock.patch.object(checker.subprocess, "run")
    @mock.patch.object(checker.shutil, "which", return_value="/usr/bin/readelf")
    def test_too_new_glibc_rejected(self, which, run):
        run.side_effect = [completed(READ_ELF_DYNAMIC), completed("Name: GLIBC_2.36")]
        with self.assertRaisesRegex(checker.LinkageError, "newer than 2.35"):
            checker.check("host")

    @mock.patch.object(checker.subprocess, "run")
    @mock.patch.object(checker.shutil, "which", side_effect=lambda name: None if name == "readelf" else "/usr/bin/ldd")
    def test_ldd_fallback(self, which, run):
        run.return_value = completed("linux-vdso.so.1 (0x0)\nlibc.so.6 => /lib/libc.so.6 (0x0)\n/lib64/ld-linux-x86-64.so.2 (0x0)\n")
        checker.check("host")
        run.assert_called_once()

    @mock.patch.object(checker.subprocess, "run")
    @mock.patch.object(checker.shutil, "which", return_value="/usr/bin/readelf")
    def test_absolute_needed_loader_rejected(self, which, run):
        run.return_value = completed(READ_ELF_DYNAMIC.replace("ld-linux-x86-64.so.2", "/tmp/ld-linux-other.so.2"))
        with self.assertRaisesRegex(checker.LinkageError, "disallowed"):
            checker.check("host")

    @mock.patch.object(checker.subprocess, "run")
    @mock.patch.object(checker.shutil, "which", side_effect=lambda name: None if name == "readelf" else "/usr/bin/ldd")
    def test_ldd_unresolved_dependency_rejected(self, which, run):
        run.return_value = completed("libc.so.6 => /lib/libc.so.6 (0x1)\nlibm.so.6 => not found\n")
        with self.assertRaisesRegex(checker.LinkageError, "could not resolve"):
            checker.check("host")

    @mock.patch.object(checker.subprocess, "run")
    @mock.patch.object(checker.shutil, "which", side_effect=lambda name: None if name == "readelf" else "/usr/bin/ldd")
    def test_ldd_failure_rejected_even_with_partial_output(self, which, run):
        run.return_value = completed("libc.so.6 => /lib/libc.so.6 (0x1)\n", returncode=1)
        with self.assertRaisesRegex(checker.LinkageError, "could not resolve"):
            checker.check("host")

if __name__ == "__main__":
    unittest.main()
