"""./prove --all must pass every live crash-proof scenario (tools/prove.py)."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.util import test_dir

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform.startswith("linux"), "real engine needs Linux")
class ProveTest(unittest.TestCase):
    def test_all_scenarios_pass(self):
        directory = tempfile.mkdtemp(prefix="prove_", dir=test_dir())
        self.addCleanup(shutil.rmtree, directory)
        env = dict(os.environ, KVDB_PROVE_DIR=directory)
        result = subprocess.run([sys.executable, "-B", str(ROOT / "prove"), "--all"], cwd=ROOT,
                                env=env, capture_output=True, text=True, timeout=300)
        self.assertEqual(result.returncode, 0, result.stdout[-3000:] + result.stderr)
        self.assertNotIn("FAIL", result.stdout)
        self.assertNotIn("Traceback", result.stderr)
        table = result.stdout.split("ID | result", 1)[1]
        self.assertEqual(table.count("| PASS"), 17, table)
        self.assertTrue(Path(directory, "A2.db").exists())  # kept for inspection


if __name__ == "__main__":
    unittest.main()
