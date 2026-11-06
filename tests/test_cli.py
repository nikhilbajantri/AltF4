"""CLI contract tests for ./kvdb (issue #17). Owner: Srushti (written by Nikhil while she is out)."""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from tests.util import test_dir

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class CLITest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cli_", dir=test_dir())
        self.addCleanup(shutil.rmtree, self.dir)
        self.path = os.path.join(self.dir, "t.db")

    def kvdb(self, *args):
        p = subprocess.run([sys.executable, "-B", os.path.join(ROOT, "kvdb"), *args],
                           cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertNotIn("Traceback", p.stderr)
        return p.returncode, p.stdout

    def batch_file(self, text):
        f = os.path.join(self.dir, "batch.txt")
        with open(f, "w") as out:
            out.write(text)
        return f

    def test_batch_values_keep_spaces(self):
        f = self.batch_file("put b1 hello world\nput b2  two  spaces \n\ndel zz\nput e \n")
        self.assertEqual(self.kvdb("batch", self.path, f), (0, "OK\n"))
        # everything after "put <key> " is the value; dump hex-encodes values with spaces
        hexed = lambda v: "hex:" + v.encode().hex()
        self.assertEqual(self.kvdb("dump", self.path)[1],
                         "b1\t%s\nb2\t%s\ne\t%s\n" % (hexed("hello world"), hexed(" two  spaces "), hexed("")))
        self.assertEqual(self.kvdb("get", self.path, "b1"), (0, hexed("hello world") + "\n"))

    def test_batch_is_one_frame_and_malformed_line_writes_nothing(self):
        self.kvdb("put", self.path, "anchor", "old")
        f = self.batch_file("put a 1\nput b 2\ndel a\n")
        self.assertEqual(self.kvdb("batch", self.path, f), (0, "OK\n"))
        frames = [l for l in self.kvdb("inspect", self.path)[1].splitlines() if l.startswith("offset=")]
        self.assertEqual(len(frames), 2)  # anchor put + one batch frame
        self.assertIn("ops=3", frames[1])
        with open(self.path, "rb") as fh:
            before = fh.read()
        for bad in ("put a 1\nbogus\n", "put a 1\ndel\n", "put a 1\ndel a b\n", "put onlykey\n"):
            with self.subTest(bad=bad):
                self.assertEqual(self.kvdb("batch", self.path, self.batch_file(bad)), (1, "ERR INVALID\n"))
                with open(self.path, "rb") as fh:
                    self.assertEqual(fh.read(), before)

    def test_missing_database_is_not_created(self):
        missing = os.path.join(self.dir, "missing.db")
        for args in (("get", missing, "k"), ("del", missing, "k"), ("dump", missing),
                     ("check", missing), ("inspect", missing), ("compact", missing)):
            with self.subTest(cmd=args[0]):
                self.assertEqual(self.kvdb(*args), (1, "ERR not found\n"))
        self.assertEqual(os.listdir(self.dir), [])

    def test_open_put_batch_still_create(self):
        self.assertEqual(self.kvdb("put", self.path, "k", "v"), (0, "OK\n"))
        self.assertEqual(self.kvdb("get", self.path, "k"), (0, "v\n"))

    def test_check_never_modifies(self):
        self.kvdb("put", self.path, "k", "v")
        with open(self.path, "ab") as fh:
            fh.write(b"abc")
        def digest():
            with open(self.path, "rb") as fh:
                return hashlib.sha256(fh.read()).hexdigest()
        before = digest()
        self.assertEqual(self.kvdb("check", self.path),
                         (0, "OK torn-tail=4 bytes (open will truncate)\n"))
        self.assertEqual(digest(), before)


if __name__ == "__main__":
    unittest.main()
