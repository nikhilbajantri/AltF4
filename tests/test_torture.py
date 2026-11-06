"""Oracle regressions: reject lost ACKs, partial batches, and invented values."""
import unittest
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from torturelib.oracle import match, worlds
from torturelib.workload import generate, command


class OracleTests(unittest.TestCase):
    def test_missing_acknowledged_write_fails(self):
        history = [[["w1-1", [("put", b"w1/a", b"yes")], "ACK"]], []]
        with self.assertRaises(AssertionError):
            match(history, {})

    def test_pending_batch_is_all_or_nothing(self):
        history = [[["w1-1", [("put", b"w1/a", b"a"),
                               ("put", b"w1/b", b"b")], None]], []]
        self.assertEqual(match(history, {}), 0)
        match(history, {b"w1/a": b"a", b"w1/b": b"b"})
        with self.assertRaises(AssertionError):
            match(history, {b"w1/a": b"a"})

    def test_foreign_value_and_unexpected_key_fail(self):
        history = [[["w1-1", [("put", b"w1/a", b"yes")], "ACK"]], []]
        for actual in ({b"w1/a": b"wrong"}, {b"w1/a": b"yes", b"extra": b"bad"}):
            with self.assertRaises(AssertionError):
                match(history, actual)

    def test_two_pending_writers_have_four_worlds(self):
        history = [[["w1-1", [("put", b"w1/a", b"a")], None]],
                   [["w2-1", [("put", b"w2/a", b"b")], None]]]
        self.assertEqual(len(worlds(history)), 4)
        for state in worlds(history):
            match(history, state)

    def test_delete_and_batch_order(self):
        history = [[["w1-1", [("put", b"w1/a", b"old")], "ACK"],
                    ["w1-2", [("put", b"w1/a", b"new"), ("del", b"w1/a")], "ACK"]]]
        self.assertEqual(match(history, {}), 0)

    def test_rejected_operation_is_absent(self):
        self.assertEqual(match([[["w1-1", [("put", b"w1/a", b"a")], "ERR"]]], {}), 0)

    def test_multiple_pending_operations_rejected(self):
        with self.assertRaises(ValueError):
            worlds([[["w1-1", [("del", b"a")], None],
                     ["w1-2", [("del", b"b")], None]]])

    def test_workload_is_seeded_and_uses_private_keys(self):
        first = generate(123, 1, "w1")
        self.assertEqual(first, generate(123, 1, "w1"))
        self.assertNotEqual(first, generate(124, 1, "w1"))
        for op_id, ops in first:
            self.assertTrue(all(op[1].startswith(b"w1/") or op[1].startswith(b"shared/") or op[1] == b"" for op in ops))
            self.assertIn(op_id, command(op_id, ops))


@unittest.skipUnless(sys.platform.startswith("linux"), "real engine needs Linux")
class CrashIntegrationTests(unittest.TestCase):
    def test_runner_kills_recovers_and_records_both_writers(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, "-B", "./torture", "--iterations", "3",
                                     "--seed", "777", "--data-dir", directory],
                                    cwd=root, text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("SUMMARY PASS=3/3", result.stdout)
            log = next(Path(directory).glob("*/oracle.log"))
            events = [json.loads(line) for line in log.read_text().splitlines()]
            sent = [event["id"] for event in events if event["event"] == "SENT"]
            self.assertTrue(any(op.startswith("w1-") for op in sent))
            self.assertTrue(any(op.startswith("w2-") for op in sent))
            self.assertEqual(sum(e["event"] == "KILL" for e in events), 3)

    def test_after_return_crash_keeps_value_without_ack(self):
        from src.engine import KVDB
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "test.db")
            env = dict(os.environ, KVDB_CRASH="after_return:1")
            result = subprocess.run([sys.executable, "-B", "-m", "src.serve", path],
                                    input="put w1-1 name Arsh\n", cwd=root, env=env,
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, -signal.SIGKILL, result.stderr)
            self.assertNotIn("ACK", result.stdout)
            db = KVDB(path)
            try:
                self.assertEqual(db.get(b"name"), b"Arsh")
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
