#!/usr/bin/env python3
"""Shared lmmock lifecycle and verified release acquisition (stdlib only).
PATH binaries must match the configured version pin and support proto --list.
"""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
from temp_cleanup import temporary_directory

PINNED_VERSION = '0.1.13'

ROOT = Path(__file__).resolve().parents[1]


def skip(reason):
    if os.environ.get('LMMOCK_REQUIRED') == '1':
        raise RuntimeError('lmmock required: ' + reason)
    print('SKIP lmmock: ' + reason)
    raise SystemExit(0)


def configured_version():
    version = os.environ.get('LMMOCK_VERSION', PINNED_VERSION).removeprefix('v')
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
        raise ValueError('invalid LMMOCK_VERSION')
    return version


def release_asset(name):
    version = configured_version()
    cache = ROOT / 'build/lmmock-cache' / version
    cache.mkdir(parents=True, exist_ok=True)
    base = f'https://github.com/lmctl-ai/lmmock/releases/download/v{version}/'
    def fetch(filename):
        path = cache / filename
        if not path.exists():
            try:
                with urllib.request.urlopen(base + filename, timeout=60) as response:
                    data = response.read()
            except (urllib.error.URLError, TimeoutError) as exc:
                skip(f'cannot download {filename}: {exc}')
            with temporary_directory(prefix='download-', dir=cache) as directory:
                staged = Path(directory) / filename
                staged.write_bytes(data)
                os.replace(staged, path)
        return path
    sums = fetch('SHA256SUMS').read_text(encoding='utf-8')
    expected = {line.split()[1].lstrip('*'): line.split()[0] for line in sums.splitlines() if line.strip()}
    path = fetch(name)
    if name not in expected or hashlib.sha256(path.read_bytes()).hexdigest() != expected[name]:
        raise RuntimeError(f'lmmock checksum verification failed: {name}')
    return path


def locate_lmmock():
    explicit = os.environ.get('LMMOCK_BIN')
    if explicit is not None:
        found = shutil.which(explicit)
        if not found:
            skip('LMMOCK_BIN is not executable: ' + explicit)
        return str(Path(found).resolve())
    found = shutil.which('lmmock')
    if found and compatible_path_binary(found):
        return str(Path(found).resolve())
    return download_lmmock()


def compatible_path_binary(binary):
    version = configured_version()
    try:
        reported = subprocess.run([binary, '--version'], capture_output=True,
                                  text=True, encoding='utf-8', errors='replace', timeout=5)
        if reported.returncode != 0 or reported.stdout.strip() != f'lmmock {version}':
            return False
        protocols = subprocess.run([binary, 'proto', '--list'], capture_output=True,
                                   timeout=5)
        return protocols.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def download_lmmock():
    system = {'Linux': 'linux', 'Darwin': 'macos', 'Windows': 'windows'}.get(platform.system())
    arch = {'x86_64': 'x64', 'amd64': 'x64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(platform.machine().lower())
    if not system or not arch or (system == 'windows' and arch != 'x64'):
        skip('unsupported platform')
    path = release_asset(f'lmmock-{system}-{arch}' + ('.exe' if system == 'windows' else ''))
    path.chmod(path.stat().st_mode | 0o111)
    return str(path.resolve())


def oauth_source(directory):
    """Extract only regular example files, never archive paths or links."""
    archive = release_asset('examples.tar.gz')
    destination = Path(directory)
    with tarfile.open(archive, 'r:gz') as tar:
        for name in ('examples/oauth.lms', 'examples/schema.json'):
            member = tar.getmember(name)
            if not member.isfile():
                raise RuntimeError('invalid lmmock example archive')
            (destination / Path(name).name).write_bytes(tar.extractfile(member).read())
    return destination / 'oauth.lms'


@contextlib.contextmanager
def _server(arguments, config=None):
    binary = locate_lmmock()
    with temporary_directory(prefix='lmclient-lmmock-') as directory:
        ready = Path(directory) / 'ready.json'
        args = [binary, *arguments, '--ready-file', str(ready)]
        if config is not None:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps(config), encoding='utf-8')
            args += ['--config', str(path)]
        # Files avoid pipe deadlocks; diagnostics are not echoed because fixtures may contain secrets.
        with (Path(directory) / 'output.log').open('w+b') as output:
            child = subprocess.Popen(args, stdout=output, stderr=output)
            try:
                deadline = time.monotonic() + 30
                while not ready.exists():
                    if child.poll() is not None:
                        raise RuntimeError(f'lmmock exited before readiness (exit {child.returncode})')
                    if time.monotonic() >= deadline:
                        raise TimeoutError('lmmock readiness timeout')
                    time.sleep(0.05)
                url = json.loads(ready.read_text(encoding='utf-8'))['url']
                if not isinstance(url, str) or not url:
                    raise RuntimeError('invalid lmmock readiness URL')
                yield url
                if child.poll() is not None:
                    raise RuntimeError(f'lmmock exited during tests (exit {child.returncode})')
            finally:
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill()
                child.wait(timeout=5)


def lmmock_serve(dsl_path, config=None):
    path = Path(dsl_path).resolve()
    return _server(['serve', '--script' if path.suffix == '.lms' else '--dsl', str(path)], config)


def lmmock_proto(name, config=None):
    return _server(['proto', name], config)


if __name__ == '__main__':
    # CI explicitly downloads the pinned asset even if a runner has lmmock on PATH.
    binary = download_lmmock()
    if os.environ.get('GITHUB_ENV'):
        with open(os.environ['GITHUB_ENV'], 'a', encoding='utf-8') as env:
            env.write(f'LMMOCK_BIN={binary}\nLMMOCK_REQUIRED=1\n')
    print(binary)
