"""Tests for compaction in src/engine.py. Owner: Varsha."""

import os
import signal
import subprocess
import sys
import unittest
from unittest import mock

from src.engine import KVDB
from src.errors import DiskFull
from tests.test_engine import ROOT, EngineTestCase


class CompactTest(EngineTestCase):
    def test_delete_all_then_compact_is_header_only(self):
        db = KVDB(self.path)
        keys = [b"k%05d" % i for i in range(10000)]
        db.batch([("put", k, b"value") for k in keys])
        db.batch([("del", k) for k in keys])
        db.compact()
        self.assertEqual((self.size(), db.stats["file_bytes"], db.stats["dead_bytes"]), (16, 16, 0))
        db = self.reopen(db)
        self.assertEqual(db.stats["keys"], 0)
        db.close()

    def test_overwrite_one_key_1000_times(self):
        db = KVDB(self.path)
        for i in range(1000):
            db.put(b"hot", b"v%04d" % i)
        before = self.size()
        db.compact()
        self.assertLess(self.size(), before)
        self.assertEqual(self.size(), 16 + 12 + 4 + 7 + 3 + 5 + 1)
        self.assertEqual(db.get(b"hot"), b"v0999")
        db.put(b"after", b"compact")  # writes go to the new file
        db = self.reopen(db)
        self.assertEqual(dict(db.items()), {b"hot": b"v0999", b"after": b"compact"})
        db.close()

    def test_multi_frame_compaction(self):
        db = KVDB(self.path, auto_compact=False)
        big = os.urandom(500_000)
        for i in range(20):  # ~10 MB live, so several <= 4 MB frames
            db.put(b"k%02d" % i, big + bytes([i]))
        db.put(b"k00", b"small")
        db.compact()
        db = self.reopen(db)
        self.assertEqual(db.get(b"k00"), b"small")
        for i in range(1, 20):
            self.assertEqual(db.get(b"k%02d" % i), big + bytes([i]))
        db.close()

    def test_failure_before_rename_keeps_old_state(self):
        db = KVDB(self.path)
        db.put(b"a", b"1")
        db.put(b"a", b"2")
        before = self.size()
        with mock.patch("os.replace", side_effect=OSError(5, "injected EIO")):
            with self.assertRaises(OSError):
                db.compact()
        self.assertFalse(os.path.exists(self.path + ".compact"))
        self.assertEqual(self.size(), before)
        db.put(b"b", b"3")  # not poisoned, still writing to the original file
        db = self.reopen(db)
        self.assertEqual(dict(db.items()), {b"a": b"2", b"b": b"3"})
        db.close()

    def test_auto_compact(self):
        db = KVDB(self.path)
        value = b"x" * 100_000
        for _ in range(60):  # 6 MB written, one live value: dead > 50% of > 4 MiB
            db.put(b"k", value)
        self.assertLess(self.size(), 4 * 1024 * 1024)
        self.assertEqual(db.get(b"k"), value)
        db.close()


class CompactDiskFullTest(EngineTestCase):
    def test_compact_and_retry_on_disk_full(self):
        db = KVDB(self.path, max_bytes=10_000)  # reserve 1000: puts must end <= 9000
        n = 0
        while True:
            try:
                db.put(b"k%02d" % n, b"v" * 200)
            except DiskFull:
                break
            n += 1
        full = self.size()
        db.batch([("del", b"k%02d" % i) for i in range(0, n, 2)])  # delete half, in the reserve
        db.put(b"new", b"v" * 200)  # DiskFull -> compact -> retry succeeds
        self.assertLess(self.size(), full)
        expected = {b"k%02d" % i: b"v" * 200 for i in range(1, n, 2)}
        expected[b"new"] = b"v" * 200
        self.assertEqual(dict(db.items()), expected)
        db = self.reopen(db, max_bytes=10_000)
        self.assertEqual(dict(db.items()), expected)
        db.close()

    def test_tiny_cap_during_compaction(self):
        db = KVDB(self.path)
        for i in range(50):
            db.put(b"k%02d" % i, b"v" * 100)
        db.put(b"k00", b"new")
        db = self.reopen(db, max_bytes=200)
        before = self.size()
        with self.assertRaises(DiskFull):
            db.compact()
        self.assertFalse(os.path.exists(self.path + ".compact"))
        self.assertEqual(self.size(), before)
        self.assertEqual((db.get(b"k00"), db.get(b"k49")), (b"new", b"v" * 100))
        db.max_bytes = None
        db.put(b"still", b"works")
        db = self.reopen(db)
        self.assertEqual((db.stats["keys"], db.get(b"still")), (51, b"works"))
        db.close()


CHILD = r"""
import sys
from src.engine import KVDB
db = KVDB(sys.argv[1], auto_compact=False)
db.compact()
"""


class CompactCrashPointTest(EngineTestCase):
    def seed(self):
        db = KVDB(self.path, auto_compact=False)
        value = b"x" * 300_000
        for i in range(30):  # ~9 MB live -> 3 compaction frames
            db.put(b"k%02d" % i, value + bytes([i]))
        for i in range(0, 30, 3):
            db.put(b"k%02d" % i, b"overwritten")
        db.delete(b"k01")
        expected = dict(db.items())
        db.close()
        return expected

    def test_crash_points(self):
        for point in ("compact_mid_copy", "compact_before_rename",
                      "compact_after_rename", "compact_after_swap"):
            with self.subTest(point=point):
                for f in (self.path, self.path + ".compact"):
                    if os.path.exists(f):
                        os.remove(f)
                expected = self.seed()
                env = dict(os.environ, KVDB_CRASH=point + ":1")
                p = subprocess.run([sys.executable, "-c", CHILD, self.path],
                                   cwd=ROOT, env=env, capture_output=True)
                self.assertEqual(p.returncode, -signal.SIGKILL, p.stderr.decode())
                left_temp = point in ("compact_mid_copy", "compact_before_rename")
                self.assertEqual(os.path.exists(self.path + ".compact"), left_temp)
                db = KVDB(self.path)
                self.assertFalse(os.path.exists(self.path + ".compact"))
                self.assertEqual(dict(db.items()), expected)
                db.close()


if __name__ == "__main__":
    unittest.main()
