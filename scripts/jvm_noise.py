"""Shared JVM invocation and stderr-noise filter for the scripts/test-*.py suites.

CI runs the shaded jar on GraalVM JDK 25. JDK 24+ prints restricted-native-access WARNING
lines to stderr when sqlite-jdbc (and other drivers) load JNI without --enable-native-access,
and JDK 23+ prints sun.misc.Unsafe deprecation WARNINGs for some clients. Local JDK 21 prints
neither, so strict stderr assertions pass here and fail in CI.

java_command(artifact) adds --enable-native-access=ALL-UNNAMED for jar runs (accepted since
JDK 17, verified on 21 and silences the native-access notice on 24+); strip_jvm_noise(text)
drops any remaining JDK runtime notices before a test asserts on stderr. Native binaries are
passed through unchanged.
"""
import re
import shutil
from pathlib import Path

NATIVE_ACCESS_FLAG = '--enable-native-access=ALL-UNNAMED'

_NOISE = re.compile(
    r'^(?:'
    r'WARNING: A restricted method in .* has been called'
    r'|WARNING: .* has been called by .*'
    r'|WARNING: Use --enable-native-access=.*'
    r'|WARNING: Restricted methods will be blocked in a future release.*'
    r'|WARNING: A terminally deprecated method in sun\.misc\.Unsafe has been called'
    r'|WARNING: Please consider reporting this to the maintainers of .*'
    r'|WARNING: sun\.misc\.Unsafe::.* will be removed in a future release'
    r'|WARNING: .*will be removed in a future release.*'
    r'|Picked up (?:JAVA_TOOL_OPTIONS|_JAVA_OPTIONS|JDK_JAVA_OPTIONS): .*'
    r')\s*$'
)

def java_command(artifact):
    """['java', flag, '-jar', path] for a .jar, else [path] for a native executable."""
    path = Path(artifact).resolve()
    if path.suffix == '.jar':
        # Absolute java path: some suites run lmclient under a restricted PATH (fake provider CLIs).
        return [shutil.which('java') or 'java', NATIVE_ACCESS_FLAG, '-jar', str(path)]
    return [str(path)]

def is_jvm_noise(line):
    return bool(_NOISE.match(line.strip()))

def strip_jvm_noise(text):
    """Return text without JDK runtime WARNING / 'Picked up ...' lines; other lines are untouched."""
    if not text:
        return text
    kept = [line for line in text.splitlines(keepends=True) if not is_jvm_noise(line)]
    return ''.join(kept)

if __name__ == '__main__':
    sample = ('WARNING: A restricted method in java.lang.System has been called\n'
              'WARNING: java.lang.System::load has been called by org.sqlite.SQLiteJDBCLoader in an unnamed module (file:/x/lmclient.jar)\n'
              'WARNING: Use --enable-native-access=ALL-UNNAMED to avoid a warning for callers in this module\n'
              'WARNING: Restricted methods will be blocked in a future release unless native access is enabled\n'
              'WARNING: A terminally deprecated method in sun.misc.Unsafe has been called\n'
              'WARNING: sun.misc.Unsafe::objectFieldOffset has been called by io.netty.util.internal.PlatformDependent0 (file:/x.jar)\n'
              'WARNING: Please consider reporting this to the maintainers of class io.netty.util.internal.PlatformDependent0\n'
              'WARNING: sun.misc.Unsafe::objectFieldOffset will be removed in a future release\n'
              'Picked up JAVA_TOOL_OPTIONS: -Dfile.encoding=UTF-8\n'
              'lmclient: real diagnostic line\n')
    assert strip_jvm_noise(sample) == 'lmclient: real diagnostic line\n', strip_jvm_noise(sample)
    assert strip_jvm_noise('') == '' and strip_jvm_noise('plain\n') == 'plain\n'
    print('jvm_noise self-test OK')
