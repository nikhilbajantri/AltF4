"""Recovery and compaction benchmark (not a unittest). Owner: Nikhil.

1. Writes 1,000,000 keys with ~20-byte values in 100 batches of 10,000, closes,
   then times KVDB(path) and prints recovery_ms.
2. Deletes all 1,000,000 keys (100 batches) and times compact(), printing the
   file size before/after. auto_compact is off so the explicit compact is measured.

Runs under tests.util.test_dir() (a real disk). Run from the repo root:
python3 -m tests.bench_recovery [path]
"""

import os
import shutil
import sys
import tempfile
import time

# Support both python3 tests/... and python3 -m tests....
from pathlib import Path
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.engine import KVDB
from tests.util import test_dir

N, BATCH = 1_000_000, 10_000


def key(i):
    return b"key%07d" % i


def main():
    tmpdir = None
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        tmpdir = tempfile.mkdtemp(prefix="bench_", dir=test_dir())
        path = os.path.join(tmpdir, "bench.db")
    if os.path.exists(path):
        os.remove(path)

    db = KVDB(path, auto_compact=False)
    t0 = time.monotonic()
    for b in range(0, N, BATCH):
        db.batch([("put", key(b + i), b"value-%014d" % i) for i in range(BATCH)])
    write_s = time.monotonic() - t0
    db.close()

    db = KVDB(path, auto_compact=False)
    s = db.stats
    print("puts:    keys=%d file_bytes=%d write_s=%.2f recovery_ms=%.1f"
          % (s["keys"], s["file_bytes"], write_s, s["recovery_ms"]))

    t0 = time.monotonic()
    for b in range(0, N, BATCH):
        db.batch([("del", key(b + i)) for i in range(BATCH)])
    delete_s = time.monotonic() - t0
    before = os.path.getsize(path)
    t0 = time.monotonic()
    db.compact()
    compact_ms = (time.monotonic() - t0) * 1000
    after = os.path.getsize(path)
    db.close()
    print("compact: delete_s=%.2f size_before=%d size_after=%d compact_ms=%.1f"
          % (delete_s, before, after, compact_ms))

    os.remove(path)
    if tmpdir:
        shutil.rmtree(tmpdir)


if __name__ == "__main__":
    main()
