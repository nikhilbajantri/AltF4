"""Tests for src/engine.py. Owner: Varsha."""

import os
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
import zlib

from src import format as fmt
from src.engine import KVDB
from src.errors import CorruptError, DiskFull

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class EngineTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="kvdb_test_")
        self.path = os.path.join(self.dir, "t.db")

    def tearDown(self):
        shutil.rmtree(self.dir)

    def reopen(self, db=None, **kw):
        if db is not None:
            db.close()
        return KVDB(self.path, **kw)

    def size(self):
        return os.path.getsize(self.path)


class BasicTest(EngineTestCase):
    def test_put_get_delete_batch(self):
        db = KVDB(self.path)
        self.assertIsNone(db.get(b"a"))
        db.put(b"a", b"1")
        db.put(b"a", b"2")
        db.put(b"e", b"")
        self.assertEqual((db.get(b"a"), db.get(b"e")), (b"2", b""))
        db.delete(b"a")
        db.delete(b"never-existed")
        self.assertIsNone(db.get(b"a"))
        db.batch([("put", b"b", b"1"), ("put", b"c", b"2"), ("del", b"e")])
        self.assertEqual(sorted(db.items()), [(b"b", b"1"), (b"c", b"2")])
        self.assertEqual(db.stats["keys"], 2)
        self.assertEqual(db.stats["file_bytes"], self.size())
        db.close()

    def test_batch_put_then_del_leaves_absent(self):
        db = KVDB(self.path)
        db.batch([("put", b"x", b"1"), ("del", b"x")])
        self.assertIsNone(db.get(b"x"))
        db = self.reopen(db)
        self.assertIsNone(db.get(b"x"))
        db.close()

    def test_invalid_and_closed(self):
        db = KVDB(self.path)
        with self.assertRaises(ValueError):
            db.put(b"", b"v")
        with self.assertRaises(ValueError):
            db.batch([])
        db.close()
        db.close()
        for call in (lambda: db.put(b"k", b"v"), lambda: db.get(b"k"), db.keys):
            with self.assertRaises(ValueError):
                call()

    def test_1000_keys_survive_reopen(self):
        db = KVDB(self.path)
        for i in range(1000):
            db.put(b"k%d" % i, b"v%d" % i)
        db = self.reopen(db)
        self.assertEqual(db.stats["keys"], 1000)
        for i in range(1000):
            self.assertEqual(db.get(b"k%d" % i), b"v%d" % i)
        db.close()

    def test_two_threads(self):
        db = KVDB(self.path)

        def writer(t):
            for i in range(500):
                db.put(b"t%d-%d" % (t, i), b"v%d" % i)

        threads = [threading.Thread(target=writer, args=(t,)) for t in (1, 2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        db = self.reopen(db)
        self.assertEqual(db.stats["keys"], 1000)
        for t in (1, 2):
            for i in range(500):
                self.assertEqual(db.get(b"t%d-%d" % (t, i)), b"v%d" % i)
        db.close()


class TornTailTest(EngineTestCase):
    def test_truncate_one_byte(self):
        db = KVDB(self.path)
        db.put(b"a", b"1")
        db.put(b"b", b"2")
        good_end = db.stats["file_bytes"]
        db.put(b"c", b"3")
        db.close()
        os.truncate(self.path, self.size() - 1)
        db = KVDB(self.path)
        self.assertEqual((db.get(b"a"), db.get(b"b"), db.get(b"c")), (b"1", b"2", None))
        self.assertEqual(self.size(), good_end)
        db.close()

    def test_garbage_tail(self):
        db = KVDB(self.path)
        db.put(b"a", b"1")
        db.close()
        good_end = self.size()
        with open(self.path, "ab") as f:
            f.write(b"\xde\xad\xbe\xef\x01\x02\x03")
        db = KVDB(self.path)
        self.assertEqual(db.get(b"a"), b"1")
        self.assertEqual(self.size(), good_end)
        db.close()

    def test_corrupt_frame_propagates_without_truncating(self):
        db = KVDB(self.path)
        db.put(b"a", b"1")
        db.close()
        payload = fmt.NOPS.pack(1) + fmt.OP_HDR.pack(9, 1, 0) + b"k"
        len_bytes = fmt.LEN.pack(len(payload))
        crc = zlib.crc32(payload, zlib.crc32(len_bytes))
        with open(self.path, "ab") as f:
            f.write(len_bytes + struct.pack("<I", crc) + payload)
        before = self.size()
        with self.assertRaises(CorruptError):
            KVDB(self.path)
        self.assertEqual(self.size(), before)


class DiskFullTest(EngineTestCase):
    def test_max_bytes(self):
        # max 1000, reserve 100: non-delete frames must end at <= 900
        db = KVDB(self.path, max_bytes=1000)
        db.put(b"k", b"v" * 840)  # 16 + 24 + 840 = 880
        before = self.size()
        with self.assertRaises(DiskFull):
            db.put(b"k2", b"v" * 10)  # would end at 915
        self.assertEqual(self.size(), before)
        db.delete(b"k")  # ends at 904, inside the reserve
        self.assertIsNone(db.get(b"k"))
        with self.assertRaises(DiskFull):
            db.batch([("del", b"x%d" % i) for i in range(10)])  # 904 + 96 + 16 > 1000
        db.close()


CHILD = r"""
import sys
from src.engine import KVDB
db = KVDB(sys.argv[1])
if sys.argv[2] == "put":
    db.put(b"x", b"crash-value")
db.close()
"""


class CrashPointTest(EngineTestCase):
    def run_child(self, point, action):
        env = dict(os.environ, KVDB_CRASH=point + ":1")
        p = subprocess.run([sys.executable, "-c", CHILD, self.path, action],
                           cwd=ROOT, env=env, capture_output=True)
        self.assertEqual(p.returncode, -signal.SIGKILL, p.stderr.decode())

    def seed(self, torn_tail=False):
        db = KVDB(self.path)
        db.put(b"a", b"1")
        db.batch([("put", b"b", b"2"), ("put", b"c", b"3")])
        db.close()
        if torn_tail:
            with open(self.path, "ab") as f:
                f.write(b"\x05\x00\x00")
        return {b"a": b"1", b"b": b"2", b"c": b"3"}

    def assertState(self, expected):
        db = KVDB(self.path)
        self.assertEqual(dict(db.items()), expected)
        self.assertEqual(self.size(), db.stats["file_bytes"])
        db.close()

    def check_write_point(self, point, survives):
        expected = self.seed()
        size_before = self.size()
        self.run_child(point, "put")
        if survives:
            expected[b"x"] = b"crash-value"
        self.assertState(expected)
        if not survives:
            self.assertEqual(self.size(), size_before)

    def test_before_write(self):
        self.check_write_point("before_write", survives=False)

    def test_torn_write(self):
        for _ in range(5):  # random prefix length each run
            self.check_write_point("torn_write", survives=False)

    def test_after_write(self):
        # SIGKILL does not drop the page cache, so the unsynced frame is still read back
        self.check_write_point("after_write", survives=True)

    def test_after_fsync(self):
        self.check_write_point("after_fsync", survives=True)

    def test_close_mid(self):
        self.check_write_point("close_mid", survives=True)

    def test_recovery_points(self):
        for point, torn in (("recovery_mid_scan", False),
                            ("recovery_before_truncate", True),
                            ("recovery_after_truncate", True)):
            with self.subTest(point=point):
                _remove_db(self.path)
                expected = self.seed(torn_tail=torn)
                self.run_child(point, "open")
                self.assertState(expected)

    def test_init_before_rename(self):
        self.run_child("init_before_rename", "open")
        self.assertFalse(os.path.exists(self.path))
        self.assertTrue(os.path.exists(self.path + ".init"))
        self.assertState({})
        self.assertFalse(os.path.exists(self.path + ".init"))


def _remove_db(path):
    if os.path.exists(path):
        os.remove(path)


if __name__ == "__main__":
    unittest.main()
