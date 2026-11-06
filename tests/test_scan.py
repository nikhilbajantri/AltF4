"""Tests for src/scan.py (read-only check/inspect scanner). Owner: Varsha."""

import hashlib
import os
import struct
import unittest
import zlib

from src import format as fmt
from src.engine import KVDB
from src.scan import Frame, Tail, check_file, iter_frames
from tests.test_engine import EngineTestCase


class ScanTest(EngineTestCase):
    def seed(self):
        db = KVDB(self.path)
        db.put(b"a", b"secret-value")
        db.batch([("put", b"b", b"2"), ("del", b"a")])
        db.close()
        os.remove(self.path + ".lock")

    def scan(self):
        """Run both scanners, asserting the file and directory are untouched."""
        def snapshot():
            with open(self.path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest(), sorted(os.listdir(self.dir))
        before = snapshot()
        records = list(iter_frames(self.path))
        result = check_file(self.path)
        self.assertEqual(snapshot(), before)
        self.assertIsInstance(records[-1], Tail)
        return records, result

    def append(self, data):
        records = list(iter_frames(self.path))
        with open(self.path, "r+b") as f:
            if len(records) > 1 and records[-2].status == "ok" and not records[-1].tail_bytes:
                f.truncate(records[-2].offset + records[-2].length)
            f.seek(0, os.SEEK_END)
            f.write(data)

    def test_clean(self):
        self.seed()
        records, result = self.scan()
        frames, tail = records[:-1], records[-1]
        self.assertEqual(result, (True, "OK"))
        self.assertEqual([f.status for f in frames], ["ok", "ok"])
        self.assertEqual(frames[0].offset, 16)
        self.assertEqual(frames[1].ops, [(fmt.PUT, b"b", 1), (fmt.DEL, b"a", 0)])
        self.assertEqual((tail.offset, tail.tail_bytes, tail.later_frame), (self.size(), 0, None))
        self.assertNotIn(b"secret-value", repr(records).encode())

    def test_torn_tail(self):
        self.seed()
        good = self.size() - len(fmt.TAIL_GUARD)
        frame, _ = fmt.encode_frame([("put", b"c", b"3")])
        self.append(frame[:-3])
        records, result = self.scan()
        self.assertEqual(result, (True, "OK torn-tail=%d bytes (open will truncate)" % (len(frame) - 3)))
        self.assertEqual((records[-2].status, records[-2].offset), ("torn", good))
        self.assertEqual(records[-1].offset, good)

    def test_corrupt_frame(self):
        self.seed()
        good = self.size() - len(fmt.TAIL_GUARD)
        payload = fmt.NOPS.pack(1) + fmt.OP_HDR.pack(9, 1, 0) + b"k"
        lb = fmt.LEN.pack(len(payload))
        self.append(lb + struct.pack("<I", zlib.crc32(payload, zlib.crc32(lb))) + payload)
        records, (ok, msg) = self.scan()
        self.assertFalse(ok)
        self.assertEqual(msg, "CORRUPT offset=%d op 0 unknown type 9" % good)
        self.assertEqual(records[-2].status, "corrupt")

    def test_damage_mid_file_reports_later_frame(self):
        db = KVDB(self.path)
        for k in (b"a", b"b", b"c"):
            db.put(k, b"v")
        db.close()
        second = 16 + 25  # 12 + 4 + 7 + 1 + 1 per frame
        with open(self.path, "r+b") as f:
            f.seek(second + 20)
            f.write(b"\xff")  # break frame 2's payload; frame 3 is intact
        records, (ok, msg) = self.scan()
        self.assertFalse(ok)
        self.assertEqual(records[-1].later_frame, second + 25)
        self.assertEqual(msg, "CORRUPT offset=%d damaged frame followed by CRC-valid frame at %d"
                         % (second, second + 25))

    def test_header_prefix_and_bad_header(self):
        for data, expected in ((b"", (True, "OK")),
                               (fmt.encode_header()[:15],
                                (True, "OK torn-tail=15 bytes (open will truncate)")),
                               (b"\xff" * 10, (False, "CORRUPT offset=0 file shorter than header")),
                               (b"X" * 40, (False, "CORRUPT offset=0 bad header"))):
            with self.subTest(data=data[:4]):
                with open(self.path, "wb") as f:
                    f.write(data)
                records, result = self.scan()
                self.assertEqual(result, expected)

    def test_works_while_database_is_open(self):
        db = KVDB(self.path)  # holds the flock
        db.put(b"a", b"1")
        self.assertEqual(check_file(self.path), (True, "OK"))
        db.close()


if __name__ == "__main__":
    unittest.main()
