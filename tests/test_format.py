"""Tests for src/format.py. Owner: Varsha."""

import mmap
import os
import tempfile
import unittest

from src import format as fmt


def roundtrip(test, ops):
    frame, offsets = fmt.encode_frame(ops)
    decoded, next_pos = fmt.decode_frame(frame, 0, len(frame))
    test.assertEqual(next_pos, len(frame))
    test.assertEqual(len(decoded), len(ops))
    for op, (typ, key, voff, vlen), rel in zip(ops, decoded, offsets):
        test.assertEqual(voff, rel)
        test.assertEqual(key, op[1])
        if op[0] == "put":
            test.assertEqual(typ, fmt.PUT)
            test.assertEqual(frame[voff:voff + vlen], op[2])
        else:
            test.assertEqual((typ, vlen), (fmt.DEL, 0))
    return frame


class HeaderTest(unittest.TestCase):
    def test_roundtrip(self):
        h = fmt.encode_header()
        self.assertEqual(len(h), fmt.HEADER_SIZE)
        self.assertEqual(h[:8], fmt.MAGIC)
        self.assertTrue(fmt.check_header(h))

    def test_corrupted_magic_rejected(self):
        h = bytearray(fmt.encode_header())
        h[0] ^= 0xFF
        self.assertFalse(fmt.check_header(bytes(h)))

    def test_short_or_bad_crc_rejected(self):
        h = bytearray(fmt.encode_header())
        self.assertFalse(fmt.check_header(bytes(h[:15])))
        h[15] ^= 1
        self.assertFalse(fmt.check_header(bytes(h)))


class RoundTripTest(unittest.TestCase):
    def test_single_put(self):
        frame = roundtrip(self, [("put", b"k", b"v")])
        self.assertEqual(len(frame), 12 + 4 + 7 + 1 + 1)

    def test_empty_value(self):
        roundtrip(self, [("put", b"k", b"")])

    def test_delete(self):
        roundtrip(self, [("del", b"gone")])

    def test_two_op_batch(self):
        roundtrip(self, [("put", b"a", b"1"), ("del", b"a")])

    def test_10000_op_batch(self):
        roundtrip(self, [("put", b"k%d" % i, b"v%d" % i) for i in range(10000)])

    def test_1mib_value(self):
        roundtrip(self, [("put", b"big", os.urandom(fmt.MAX_VALUE))])

    def test_decode_from_mmap(self):
        frame, _ = fmt.encode_frame([("put", b"k", b"value")])
        with tempfile.TemporaryFile() as f:
            f.write(fmt.encode_header() + frame)
            f.flush()
            m = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            self.assertTrue(fmt.check_header(m))
            ops, end = fmt.decode_frame(m, fmt.HEADER_SIZE, len(m))
            _, key, off, vlen = ops[0]
            self.assertEqual((key, m[off:off + vlen], end), (b"k", b"value", len(m)))
            m.close()  # would raise BufferError if decode leaked a memoryview


class StopRuleTest(unittest.TestCase):
    def test_truncated_at_every_byte(self):
        frame, _ = fmt.encode_frame([("put", b"a", b"12345"), ("del", b"b")])
        for cut in range(len(frame)):
            self.assertIsNone(fmt.decode_frame(frame[:cut], 0, cut), cut)
            # same, but with stale bytes past `size` still in the buffer
            self.assertIsNone(fmt.decode_frame(frame, 0, cut), cut)

    def test_flipped_bit_in_payload(self):
        frame, _ = fmt.encode_frame([("put", b"key", b"value"), ("del", b"x")])
        for i in range(fmt.FRAME_HDR_SIZE, len(frame)):
            for bit in range(8):
                bad = bytearray(frame)
                bad[i] ^= 1 << bit
                self.assertIsNone(fmt.decode_frame(bytes(bad), 0, len(bad)), (i, bit))

    def test_two_frames_back_to_back(self):
        f1, _ = fmt.encode_frame([("put", b"a", b"1")])
        f2, _ = fmt.encode_frame([("del", b"a")])
        buf = f1 + f2
        ops1, p = fmt.decode_frame(buf, 0, len(buf))
        ops2, p = fmt.decode_frame(buf, p, len(buf))
        self.assertEqual((ops1[0][:2], ops2[0][:2]), ((fmt.PUT, b"a"), (fmt.DEL, b"a")))
        self.assertEqual(p, len(buf))
        self.assertIsNone(fmt.decode_frame(buf, p, len(buf)))


class ValidateTest(unittest.TestCase):
    def test_rejects(self):
        bad = [
            [("put", b"", b"v")],
            [("put", b"k" * 1025, b"v")],
            [("del", b"k" * 1025)],
            [("put", b"k", b"v" * (fmt.MAX_VALUE + 1))],
            [("del", b"k")] * 10001,
            [],
            [("upd", b"k", b"v")],
            [("put", "k", b"v")],
        ]
        for ops in bad:
            with self.assertRaises(ValueError):
                fmt.validate_ops(ops)

    def test_accepts_limits(self):
        fmt.validate_ops([("put", b"k" * 1024, b"v" * fmt.MAX_VALUE)])
        fmt.validate_ops([("del", b"k")] * 10000)


if __name__ == "__main__":
    unittest.main()
