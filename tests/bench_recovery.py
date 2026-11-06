"""Recovery benchmark (not a unittest). Owner: Nikhil.

Writes 1,000,000 keys with ~20-byte values in 100 batches of 10,000, closes,
then times KVDB(path) and prints recovery_ms.

Run from the repo root: python3 -m tests.bench_recovery [path]
"""

import os
import sys
import tempfile
import time

from src.engine import KVDB


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(tempfile.mkdtemp(), "bench.db")
    if os.path.exists(path):
        os.remove(path)
    db = KVDB(path)
    t0 = time.monotonic()
    for b in range(100):
        db.batch([("put", b"key%07d" % (b * 10000 + i), b"value-%014d" % i) for i in range(10000)])
    write_s = time.monotonic() - t0
    db.close()

    db = KVDB(path)
    s = db.stats
    db.close()
    print("keys=%d file_bytes=%d write_s=%.2f recovery_ms=%.1f"
          % (s["keys"], s["file_bytes"], write_s, s["recovery_ms"]))
    os.remove(path)


if __name__ == "__main__":
    main()
