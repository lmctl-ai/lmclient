"""Temporary test directories with bounded retries for Windows file-release delays."""
from contextlib import contextmanager
import shutil
import tempfile
import time


@contextmanager
def temporary_directory(**kwargs):
    directory = tempfile.mkdtemp(**kwargs)
    try:
        yield directory
    finally:
        # Callers must close SQLite connections and reap children first. Retrying
        # is only for transient permission/sharing failures, never a silent skip.
        for attempt in range(11):
            try:
                shutil.rmtree(directory)
                break
            except PermissionError:
                if attempt == 10:
                    raise
                time.sleep(0.5)
