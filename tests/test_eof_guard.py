"""EOF guard edge cases not covered by tests/test_tail_guard.py. Owner: Nikhil.

The guard is one 00 byte after the last complete frame (src/format.py TAIL_GUARD).
Already covered elsewhere: empty database / delete-all compaction is 16 bytes
(test_engine.test_zero_byte_file_opens_empty, test_compact.test_delete_all_then_
compact_is_header_only); one-byte cut keeps every record (test_tail_guard.test_put_
delete_and_batch_survive_one_byte_tail_loss); missing guard after a kill between
frame and guard (test_tail_guard.test_process_kill_between_frame_and_guard_recovers_
whole_frame); at-cap legacy file not grown (test_tail_guard.test_legacy_frames_
migrate_and_tight_cap_does_not_grow).
"""

import hashlib
import os
from pathlib import Path
import signal
import subprocess
import sys

from src import format as fmt
from src.engine import KVDB
from tests.test_engine import EngineTestCase, ROOT


class EOFGuardTest(EngineTestCase):
    def data(self):
        return Path(self.path).read_bytes()

    def state(self):
        db = KVDB(self.path)
        try:
            return dict(db.items())
        finally:
            db.close()

    def seed(self):
        db = KVDB(self.path)
        db.put(b"a", b"1")
        db.put(b"b", b"2")
        end = db.end
        db.put(b"c", b"3")
        last_end = db.end
        db.close()
        return {b"a": b"1", b"b": b"2", b"c": b"3"}, end, last_end

    def test_a_put_ends_with_exactly_one_guard_byte(self):
        _, _, last_end = self.seed()
        data = self.data()
        self.assertEqual(len(data), last_end + 1)
        self.assertEqual(data[last_end:], fmt.TAIL_GUARD)
        self.assertNotEqual(data[last_end - 1:last_end], b"")  # the frame ends right before it

    def test_d_two_byte_cut_loses_only_the_last_frame(self):
        expected, end_before_c, _ = self.seed()
        os.truncate(self.path, self.size() - 2)  # the guard and the last byte of frame c
        del expected[b"c"]
        self.assertEqual(self.state(), expected)
        self.assertEqual(self.size(), end_before_c + 1)
        self.assertEqual(self.data()[-1:], fmt.TAIL_GUARD)

    def torn_one_byte(self, value_len):
        """Write the first byte of a new frame over the old guard, as a 1-byte torn write would."""
        expected, _, last_end = self.seed()
        frame, _ = fmt.encode_frame([("put", b"k", b"v" * value_len)])
        with open(self.path, "r+b") as f:
            f.seek(last_end)
            f.write(frame[:1])
        return expected, last_end, frame[:1]

    def test_e_one_byte_torn_write_of_00_is_read_as_the_guard(self):
        # payload = nops 4 + op header 7 + key 1 + value 244 = 256, so the
        # little-endian length starts with byte 00, the same value as the guard.
        expected, last_end, first = self.torn_one_byte(244)
        self.assertEqual(first, b"\x00")
        before = self.data()
        self.assertEqual(self.state(), expected)  # no data lost, nothing truncated
        self.assertEqual(self.data(), before)
        db = KVDB(self.path)
        db.put(b"next", b"works")
        db.close()
        expected[b"next"] = b"works"
        self.assertEqual(self.state(), expected)
        self.assertEqual(self.data()[-1:], fmt.TAIL_GUARD)

    def test_f_one_byte_torn_write_nonzero_is_truncated_and_guard_restored(self):
        expected, last_end, first = self.torn_one_byte(10)
        self.assertNotEqual(first, b"\x00")
        self.assertEqual(self.state(), expected)
        self.assertEqual(self.size(), last_end + 1)
        self.assertEqual(self.data()[-1:], fmt.TAIL_GUARD)

    def test_h_guard_plus_junk_is_truncated_back_and_guard_restored(self):
        expected, _, last_end = self.seed()
        with open(self.path, "ab") as f:
            f.write(b"\x07\x08")
        self.assertEqual(self.size(), last_end + 3)
        self.assertEqual(self.state(), expected)
        self.assertEqual(self.size(), last_end + 1)
        self.assertEqual(self.data()[-1:], fmt.TAIL_GUARD)

    def test_i_compaction_output_ends_with_guard(self):
        db = KVDB(self.path, auto_compact=False)
        db.put(b"k", b"old")
        db.put(b"k", b"new")
        db.compact()
        end = db.end
        db.close()
        self.assertEqual(self.size(), end + 1)
        self.assertEqual(self.data()[-1:], fmt.TAIL_GUARD)
        self.assertEqual(self.state(), {b"k": b"new"})

    def cli(self, *args):
        return subprocess.run([sys.executable, "-B", os.path.join(ROOT, "kvdb"), *args], cwd=ROOT,
                              capture_output=True, text=True, timeout=30)

    def test_k_check_treats_guard_as_clean_eof_and_never_modifies(self):
        self.seed()
        digest = hashlib.sha256(self.data()).hexdigest()
        self.assertEqual(self.cli("check", self.path).stdout, "OK\n")
        self.assertEqual(hashlib.sha256(self.data()).hexdigest(), digest)
        with open(self.path, "ab") as f:
            f.write(b"\x01")  # guard + 1 junk byte: 2 bytes past the last frame
        digest = hashlib.sha256(self.data()).hexdigest()
        self.assertEqual(self.cli("check", self.path).stdout,
                         "OK torn-tail=2 bytes (open will truncate)\n")
        self.assertEqual(hashlib.sha256(self.data()).hexdigest(), digest)

    def test_l_torn_write_crash_point_then_open_keeps_guard(self):
        expected, _, last_end = self.seed()
        env = dict(os.environ, KVDB_CRASH="torn_write:1")
        child = subprocess.run([sys.executable, "-B", "-c",
                                "import sys\nfrom src.engine import KVDB\n"
                                "KVDB(sys.argv[1]).put(b'new', b'value' * 50)\n", self.path],
                               cwd=ROOT, env=env, capture_output=True, timeout=30)
        self.assertEqual(child.returncode, -signal.SIGKILL, child.stderr)
        self.assertEqual(self.state(), expected)
        self.assertEqual(self.size(), last_end + 1)
        self.assertEqual(self.data()[-1:], fmt.TAIL_GUARD)
