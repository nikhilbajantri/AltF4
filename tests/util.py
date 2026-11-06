"""Test helpers. Owner: Varsha.

Tests and benchmarks must run on a real disk (ext4), not tmpfs, or fsync costs
nothing and durability timings are meaningless. Override with $KVDB_TEST_DIR.
"""

import os


def test_dir():
    d = os.environ.get("KVDB_TEST_DIR") or os.path.expanduser("~/tmp_test")
    os.makedirs(d, exist_ok=True)
    return d
