"""Targeted destructive tests on isolated databases; never touches user data.

Run in Linux: python3 -m unittest tests.test_crash_campaign -v
KVDB_CAMPAIGN_REPEATS controls repetitions (default 3).
KVDB_CAMPAIGN_DIR selects the persistent evidence folder.
"""
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

if sys.platform.startswith("linux"):
    from src.engine import KVDB
    from src.errors import DiskFull, PoisonedError
    from src.scan import check_file
from torturelib.workload import command

ROOT = Path(__file__).resolve().parents[1]
REPEATS = int(os.environ.get("KVDB_CAMPAIGN_REPEATS", "3"))
BASE = Path(os.environ.get("KVDB_CAMPAIGN_DIR", str(Path.home() / "tmp_test" / "crash_campaign")))


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux real engine required")
class CrashCampaignTests(unittest.TestCase):
    maxDiff = 2000

    def setUp(self):
        BASE.mkdir(parents=True, exist_ok=True)
        self.directory = Path(tempfile.mkdtemp(prefix=self._testMethodName + "-", dir=BASE))
        self.serial = 0

    def seed(self, name="test.db"):
        path = self.directory / name
        expected = {b"anchor": b"acknowledged", b"victim": b"old"}
        db = KVDB(str(path), auto_compact=False)
        try:
            db.batch([("put", key, value) for key, value in expected.items()])
        finally:
            db.close()
        return path, expected

    def state(self, path):
        db = KVDB(str(path), auto_compact=False)
        try:
            actual = dict(db.items())
        finally:
            db.close()
        ok, message = check_file(str(path))
        self.assertTrue(ok, message)
        self.assertEqual(message, "OK")
        return actual

    def child(self, path, commands="quit\n", point=None, hit=1, cap=None, killed=True):
        self.serial += 1
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        env.pop("KVDB_CRASH", None)
        if point:
            env["KVDB_CRASH"] = "%s:%d" % (point, hit)
        # Seeding before engine import makes torn-write prefixes reproducible.
        script = "import random; random.seed(%d); from src.serve import main; raise SystemExit(main())" % self.serial
        args = [sys.executable, "-B", "-c", script, str(path)]
        if cap is not None:
            args += ["--max-bytes", str(cap)]
        digest = hashlib.sha256(commands.encode()).hexdigest()
        (self.directory / (digest + ".commands")).write_text(commands, encoding="utf-8")
        result = subprocess.run(args, input=commands, text=True, capture_output=True,
                                env=env, cwd=ROOT, timeout=30)
        event = {"test": self._testMethodName, "point": point, "hit": hit,
                 "seed": self.serial, "input_sha256": digest,
                 "returncode": result.returncode, "stdout": result.stdout,
                 "stderr": result.stderr, "database": str(path)}
        with (BASE / "events.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps(event) + "\n")
        self.assertEqual(result.returncode, -signal.SIGKILL if killed else 0,
                         json.dumps(event, indent=2))
        return result.stdout

    def test_all_write_points_for_put_delete_batch_large_value_and_large_batch(self):
        kinds = {
            "put": [("put", b"victim", b"new")],
            "delete": [("del", b"victim")],
            "batch": [("put", b"left", b"one"), ("put", b"right", b"two"),
                      ("del", b"victim")],
            "large-value": [("put", b"big", b"op-id:large:" + b"x" * (1_048_576 - 12))],
            "large-batch": [("put", ("key-%05d" % n).encode(), ("value-%d" % n).encode())
                            for n in range(10_000)],
        }
        points = ("before_write", "torn_write", "after_write", "after_fsync", "after_return")
        for repeat in range(REPEATS):
            for kind, ops in kinds.items():
                for point in points:
                    with self.subTest(repeat=repeat, kind=kind, point=point):
                        path, expected = self.seed("%d-%s-%s.db" % (repeat, kind, point))
                        self.child(path, command("w1-target", ops), point)
                        if point in ("after_write", "after_fsync", "after_return"):
                            for op in ops:
                                if op[0] == "put":
                                    expected[op[1]] = op[2]
                                else:
                                    expected.pop(op[1], None)
                        self.assertEqual(self.state(path), expected)
                        # Also prove subsequent writes remain reachable after repair.
                        self.child(path, "put w1-after after recovered\nquit\n", killed=False)
                        expected[b"after"] = b"recovered"
                        self.assertEqual(self.state(path), expected)

    def test_all_compaction_points_with_multiple_frames(self):
        for repeat in range(REPEATS):
            for point in ("compact_mid_copy", "compact_before_rename",
                          "compact_after_rename", "compact_after_swap"):
                with self.subTest(repeat=repeat, point=point):
                    path, expected = self.seed("%d-%s.db" % (repeat, point))
                    db = KVDB(str(path), auto_compact=False)
                    try:
                        for n in range(6):
                            key, value = ("big-%d" % n).encode(), bytes([n]) * 800_000
                            db.put(key, value)
                            expected[key] = value
                        db.delete(b"victim")
                        expected.pop(b"victim")
                    finally:
                        db.close()
                    self.child(path, "compact w1-compact\nquit\n", point)
                    self.assertEqual(self.state(path), expected)
                    self.assertFalse(Path(str(path) + ".compact").exists())
                    self.child(path, "put w1-after after swap\nquit\n", killed=False)
                    expected[b"after"] = b"swap"
                    self.assertEqual(self.state(path), expected)

    def test_repeated_crashes_during_recovery(self):
        for repeat in range(REPEATS):
            for point in ("recovery_mid_scan", "recovery_before_truncate", "recovery_after_truncate"):
                with self.subTest(repeat=repeat, point=point):
                    path, expected = self.seed("%d-%s.db" % (repeat, point))
                    for crash in range(3):
                        # After-truncate repaired the old tail, so make another
                        # incomplete tail to hit this exact recovery step again.
                        if point != "recovery_mid_scan":
                            with path.open("ab") as file:
                                file.write(b"\x07\x00\x00")
                        self.child(path, point=point)
                    self.assertEqual(self.state(path), expected)

    def test_initial_creation_and_close_crashes(self):
        for repeat in range(REPEATS):
            path = self.directory / ("new-%d.db" % repeat)
            self.child(path, point="init_before_rename")
            self.assertEqual(self.state(path), {})
            self.assertFalse(Path(str(path) + ".init").exists())
            text = self.child(path, "put w1-durable saved yes\nquit\n", "close_mid")
            self.assertIn("ACK w1-durable", text)
            self.assertEqual(self.state(path), {b"saved": b"yes"})

    def test_every_byte_of_final_frame_and_short_header(self):
        path, base = self.seed("source.db")
        original = path.read_bytes()
        final_ops = [("put", b"x", b"first"), ("put", b"y", b"second"), ("del", b"victim")]
        self.child(path, command("w1-final", final_ops) + "quit\n", killed=False)
        complete = path.read_bytes()
        for cut in range(len(original), len(complete)):
            with self.subTest(cut=cut):
                torn = self.directory / ("cut-%d.db" % cut)
                torn.write_bytes(complete[:cut])
                self.assertEqual(self.state(torn), base)
                self.assertEqual(torn.stat().st_size, len(original))
        for cut in range(16):
            with self.subTest(header_cut=cut):
                short = self.directory / ("header-%d.db" % cut)
                short.write_bytes(original[:cut])
                self.assertEqual(self.state(short), {})
                self.assertEqual(short.stat().st_size, 16)

    def test_disk_full_rejection_delete_reserve_and_compaction(self):
        for repeat in range(REPEATS):
            path = self.directory / ("full-%d.db" % repeat)
            db = KVDB(str(path), max_bytes=10_000, auto_compact=False)
            expected = {}
            try:
                for n in range(100):
                    key, value = ("key-%03d" % n).encode(), b"x" * 200
                    try:
                        db.put(key, value)
                    except DiskFull:
                        break
                    expected[key] = value
                else:
                    self.fail("disk cap was never reached")
                before = path.stat().st_size
                with self.assertRaises(DiskFull):
                    db.batch([("put", b"new-a", b"x" * 500), ("put", b"new-b", b"y" * 500)])
                self.assertEqual(path.stat().st_size, before)
                self.assertEqual(dict(db.items()), expected)
                removed = list(expected)[::2]
                db.batch([("del", key) for key in removed])
                for key in removed:
                    expected.pop(key)
                db.put(b"new", b"z" * 200)
                expected[b"new"] = b"z" * 200
            finally:
                db.close()
            self.child(path, point="close_mid", cap=10_000)
            self.assertEqual(self.state(path), expected)
            # Compaction under an impossibly small cap must keep the old state.
            db = KVDB(str(path), max_bytes=100)
            try:
                with self.assertRaises(DiskFull):
                    db.compact()
            finally:
                db.close()
            self.assertEqual(self.state(path), expected)

    def test_shared_keys_final_batch_is_not_mixed(self):
        for repeat in range(REPEATS * 5):
            path = self.directory / ("shared-%d.db" % repeat)
            commands = []
            for n in range(20):
                for w in ("w1", "w2"):
                    value = ("%s:%d" % (w, n)).encode()
                    commands.append(command("%s-%d" % (w, n),
                                            [("put", b"left", value), ("put", b"right", value)]))
            text = self.child(path, "".join(commands) + "quit\n", killed=False)
            self.assertEqual(sum(line.startswith("ACK") for line in text.splitlines()), 40)
            actual = self.state(path)
            self.assertEqual(actual[b"left"], actual[b"right"])
            self.assertIn(actual[b"left"], (b"w1:19", b"w2:19"))

    def test_reader_cannot_observe_half_applied_batch(self):
        path, _ = self.seed()
        db = KVDB(str(path))
        midway, release, reader_entered, done = (threading.Event() for _ in range(4))
        errors, seen = [], []
        original_apply = db._apply
        calls = []

        def slow_apply(*args):
            original_apply(*args)
            calls.append(1)
            if len(calls) == 1:
                midway.set()
                if not release.wait(5):
                    raise RuntimeError("test timed out waiting to release writer")

        def writer():
            try:
                db.batch([("put", b"left", b"new"), ("put", b"right", b"new")])
            except BaseException as exc:
                errors.append(exc)

        def reader():
            try:
                reader_entered.set()
                seen.append(dict(db.items()))
            except BaseException as exc:
                errors.append(exc)
            finally:
                done.set()

        with mock.patch.object(db, "_apply", side_effect=slow_apply):
            wt, rt = threading.Thread(target=writer), threading.Thread(target=reader)
            try:
                wt.start()
                self.assertTrue(midway.wait(5))
                rt.start()
                self.assertTrue(reader_entered.wait(5))
                self.assertFalse(done.wait(.05), "reader escaped while only half was applied")
            finally:
                release.set()
                wt.join(5)
                if rt.ident is not None:
                    rt.join(5)
                db.close()
        self.assertFalse(wt.is_alive() or rt.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual((seen[0][b"left"], seen[0][b"right"]), (b"new", b"new"))

    def test_planted_bugs_are_detected_in_isolated_copies(self):
        for bug in ("early-ack", "partial-batch", "skip-truncation"):
            with self.subTest(bug=bug):
                sandbox = self.directory / bug
                sandbox.mkdir()
                for package in ("src", "torturelib"):
                    shutil.copytree(ROOT / package, sandbox / package,
                                    ignore=shutil.ignore_patterns("__pycache__"))
                shutil.copy2(ROOT / "torture", sandbox / "torture")
                env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
                env.pop("KVDB_CRASH", None)
                if bug == "skip-truncation":
                    file = sandbox / "src" / "engine.py"
                    text = file.read_text()
                    needle = "os.ftruncate(self._fd, stop)"
                    self.assertIn(needle, text)
                    file.write_text(text.replace(needle, "pass  # planted: skip truncation"))
                    path, _ = self.seed("skip-truncation.db")
                    with path.open("ab") as out:
                        out.write(b"\x05\x00\x00")
                    args = [sys.executable, "-B", "-m", "torturelib.crash_probe", str(path)]
                else:
                    if bug == "early-ack":
                        file = sandbox / "src" / "serve.py"
                        text = file.read_text()
                        needle = "db.put(decode_token(parts[2]), decode_token(parts[3]))"
                        self.assertIn(needle, text)
                        text = text.replace(needle, 'reply("ACK " + op_id)\n'
                                            '                __import__("time").sleep(.1)\n'
                                            '                ' + needle)
                    else:
                        file = sandbox / "src" / "engine.py"
                        text = file.read_text()
                        needle = "frame, offsets = fmt.encode_frame(ops)"
                        self.assertIn(needle, text)
                        text = text.replace(needle, "ops = ops[:1]  # planted\n        " + needle, 1)
                    file.write_text(text)
                    args = [sys.executable, "-B", "./torture", "--iterations", "50",
                            "--seed", "314159", "--data-dir", str(sandbox / "evidence")]
                result = subprocess.run(args, cwd=sandbox, env=env,
                                        capture_output=True, text=True, timeout=45)
                (sandbox / "detection.log").write_text(result.stdout + result.stderr)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("torn-tail" if bug == "skip-truncation" else "FAIL",
                              result.stdout + result.stderr)

    def test_zero_length_write_fails_instead_of_hanging(self):
        path = self.directory / "zero-progress.db"
        script = '''
import sys
from unittest import mock
from src.engine import KVDB
from src.errors import PoisonedError
db = KVDB(sys.argv[1])
try:
    with mock.patch("os.pwrite", return_value=0):
        try:
            db.put(b"key", b"value")
        except OSError:
            pass
        else:
            raise AssertionError("zero-progress write was accepted")
    try:
        db.put(b"next", b"value")
    except PoisonedError:
        pass
    else:
        raise AssertionError("failed database was not poisoned")
finally:
    db.close()
db = KVDB(sys.argv[1])
assert dict(db.items()) == {}
db.close()
print("ZERO_WRITE_REJECTED")
'''
        try:
            result = subprocess.run([sys.executable, "-B", "-c", script, str(path)],
                                    cwd=ROOT, capture_output=True, text=True, timeout=3)
        except subprocess.TimeoutExpired:
            (self.directory / "failure.txt").write_text("Engine hung on os.pwrite returning zero")
            self.fail("engine hung when os.pwrite returned zero instead of raising an error")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ZERO_WRITE_REJECTED", result.stdout)


if __name__ == "__main__":
    unittest.main()
