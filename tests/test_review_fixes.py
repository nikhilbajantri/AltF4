"""Regression checks for GitHub review issues #3 through #13."""
import contextlib
import io
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

from src.engine_fake import FakeKVDB
from src.serve import run
from torturelib import oracle, runner, workload

ROOT = Path(__file__).resolve().parents[1]


class ServeReviewTests(unittest.TestCase):
    def test_invalid_utf8_line_and_batch_do_not_kill_session(self):
        raw = io.BytesIO(b"put w1-1 key \xff\nget w1-2 key\nbatch w1-3\nput a ok\nput b \xfe\nend\nget w1-4 a\nput w1-5 good yes\n")
        output = io.StringIO()
        run(FakeKVDB("unused"), raw, output)
        self.assertEqual(output.getvalue().splitlines()[1:], ["ERR w1-1 INVALID", "NOTFOUND w1-2",
            "ERR w1-3 INVALID", "NOTFOUND w1-4", "ACK w1-5"])

    def test_full_writer_queue_does_not_block_other_writer(self):
        release = threading.Event()
        timed_out = []
        class Engine(FakeKVDB):
            def put(self, key, value):
                if key == b"w2":
                    release.set()
                elif not release.wait(2):
                    timed_out.append(True)
                super().put(key, value)
        commands = "".join("put w1-%d w1 value\n" % n for n in range(70))
        output = io.StringIO()
        run(Engine("unused"), io.StringIO(commands + "put w2-1 w2 value\nquit\n"), output)
        self.assertEqual(timed_out, [])
        self.assertIn("ACK w2-1", output.getvalue())
        self.assertIn(" BUSY", output.getvalue())


class OracleReviewTests(unittest.TestCase):
    def test_shared_key_cannot_hold_overtaken_value(self):
        h = [[["w1-1", [("put", oracle.SHARED, b"old")], "ACK", 1, 2]],
             [["w2-1", [("put", oracle.SHARED, b"new")], "ACK", 3, 4]]]
        oracle.match(h, {oracle.SHARED: b"new"})
        with self.assertRaises(oracle.Mismatch):
            oracle.match(h, {oracle.SHARED: b"old"})

    def test_overlapping_shared_writes_allow_either_whole_value(self):
        h = [[["w1-1", [("put", oracle.SHARED, b"a")], "ACK", 1, 4]],
             [["w2-1", [("put", oracle.SHARED, b"b")], "ACK", 2, 3]]]
        oracle.match(h, {oracle.SHARED: b"a"})
        oracle.match(h, {oracle.SHARED: b"b"})

    def test_error_operation_is_absent_and_previous_state_survives(self):
        h = [[["w1-1", [("put", b"a", b"bad")], "ERR", 1, 2]]]
        oracle.match(h, {b"a": b"old"}, {b"a": b"old"})

    def test_failure_is_short_with_ids_and_preserves_full_details(self):
        h = [[["w1-7", [("put", b"key", b"x" * 10000)], "ACK"]]]
        with self.assertRaises(oracle.Mismatch) as failure:
            oracle.match(h, {})
        self.assertLess(len(str(failure.exception)), 1500)
        self.assertIn("missing=1", str(failure.exception))
        self.assertIn("w1-7", str(failure.exception))
        self.assertIn("x" * 10000, failure.exception.details)

    def test_value_error_becomes_tool_error(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(runner, "iteration", side_effect=ValueError("invalid oracle state")), \
                mock.patch.object(sys, "platform", "linux"), contextlib.redirect_stdout(io.StringIO()) as output:
            code = runner.main(["--iterations", "1", "--data-dir", directory])
            self.assertEqual(code, 2)
            self.assertIn("TOOL ERROR", output.getvalue())

    def test_large_modes_reach_exact_boundaries(self):
        values = workload.generate(1, 1, "w1", mode="large-values")
        self.assertEqual(len(values[0][1][0][2]), 1_048_576)
        batches = workload.generate(1, 1, "w1", mode="large-batch")
        self.assertEqual(len(batches[0][1]), 10_000)


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux CLI")
class CLIReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "db")

    def cli(self, *args, data=None):
        return subprocess.run([sys.executable, "-B", str(ROOT / "kvdb"), *map(str, args)],
                              input=data, capture_output=True, cwd=ROOT, timeout=15)

    def test_cli_end_to_end_and_read_only_tools(self):
        self.assertEqual(self.cli("put", self.path, "hex:ff", "hex:000a").stdout, b"OK\n")
        self.assertEqual(self.cli("get", self.path, "hex:ff").stdout, b"hex:000a\n")
        before = Path(self.path).read_bytes()
        self.assertEqual(self.cli("check", self.path).stdout, b"OK\n")
        self.assertIn(b"crc=OK", self.cli("inspect", self.path).stdout)
        self.assertEqual(Path(self.path).read_bytes(), before)
        self.assertEqual(self.cli("dump", self.path).stdout, b"hex:ff\thex:000a\n")
        self.assertEqual(self.cli("del", self.path, "hex:ff").stdout, b"OK\n")
        self.assertIn(b"after=16", self.cli("compact", self.path).stdout)

    def test_malformed_batch_file_changes_nothing(self):
        self.cli("put", self.path, "anchor", "old")
        before = Path(self.path).read_bytes()
        batch = Path(self.temp.name) / "batch.txt"
        batch.write_text("put a one\ninvalid\n")
        result = self.cli("batch", self.path, batch)
        self.assertEqual((result.returncode, result.stdout), (1, b"ERR INVALID\n"))
        self.assertEqual(Path(self.path).read_bytes(), before)

    def test_real_stdin_invalid_bytes_keeps_serve_alive(self):
        result = self.cli("serve", self.path, data=b"put w1-1 key \xff\nput w1-2 good yes\nquit\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"ERR w1-1 INVALID", result.stdout)
        self.assertIn(b"ACK w1-2", result.stdout)

    def test_default_detects_skipped_truncation_within_first_iteration(self):
        clone = Path(self.temp.name) / "clone"
        clone.mkdir()
        for package in ("src", "torturelib"):
            shutil.copytree(ROOT / package, clone / package, ignore=shutil.ignore_patterns("__pycache__"))
        for entry in ("kvdb", "torture"):
            shutil.copy2(ROOT / entry, clone / entry)
        engine = clone / "src" / "engine.py"
        text = engine.read_text()
        self.assertIn("os.ftruncate(self._fd, stop)", text)
        engine.write_text(text.replace("os.ftruncate(self._fd, stop)", "pass # planted"))
        result = subprocess.run([sys.executable, "-B", "./torture", "--iterations", "50", "--seed", "12345",
                                 "--data-dir", str(clone / "evidence")], cwd=clone,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("FAIL seed=12345 iteration=1", result.stdout)
        self.assertIn("torn-tail", result.stdout)


if __name__ == "__main__":
    unittest.main()
