"""Compaction benchmark (not a unittest). Owner: Nikhil.

A. 1,000,000 live keys (~20-byte values) + 1,000,000 overwrites (half the file dead).
B. 100,000 live keys with 1 KB values (no dead bytes: pure copy cost).
Each case times compact() and prints file size before/after. auto_compact is off.

Runs under tests.util.test_dir() (a real disk). Run from the repo root:
python3 -m tests.bench_compact
"""

import os
import shutil
import tempfile
import time

# Support both python3 tests/... and python3 -m tests....
import sys
from pathlib import Path
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.engine import KVDB
from tests.util import test_dir

BATCH = 10_000


def fill(db, n, value_of):
    for b in range(0, n, BATCH):
        db.batch([("put", b"key%07d" % (b + i), value_of(b + i)) for i in range(min(BATCH, n - b))])


def timed_compact(label, db, path):
    before = os.path.getsize(path)
    t0 = time.monotonic()
    db.compact()
    ms = (time.monotonic() - t0) * 1000
    print("%-28s keys=%d size_before=%d size_after=%d compact_ms=%.1f"
          % (label, db.stats["keys"], before, os.path.getsize(path), ms))


def main():
    tmpdir = tempfile.mkdtemp(prefix="bench_", dir=test_dir())
    try:
        path = os.path.join(tmpdir, "a.db")
        db = KVDB(path, auto_compact=False)
        fill(db, 1_000_000, lambda i: b"value-%014d" % i)
        fill(db, 1_000_000, lambda i: b"VALUE-%014d" % i)
        timed_compact("1M live + 1M overwrites", db, path)
        db.close()

        path = os.path.join(tmpdir, "b.db")
        db = KVDB(path, auto_compact=False)
        value = os.urandom(1024)
        fill(db, 100_000, lambda i: value)
        timed_compact("100k live x 1 KB", db, path)
        db.close()
    finally:
        shutil.rmtree(tmpdir)


if __name__ == "__main__":
    main()
