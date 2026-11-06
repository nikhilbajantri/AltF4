"""The crashpoints torture mode must cover exactly the engine's crash points (issue #18)."""

import pathlib
import re
import unittest

from torturelib import modes

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"


def engine_points():
    text = "".join(p.read_text() for p in SRC.glob("*.py"))
    points = set(re.findall(r'crash\.point\("([a-z_]+)"\)', text))
    if "crash.torn_write_prefix(" in text:
        points.add("torn_write")
    return points


class CrashpointsModeTest(unittest.TestCase):
    def test_points_match_src(self):
        self.assertEqual(set(modes.POINTS), engine_points())
        self.assertEqual(len(modes.POINTS), len(set(modes.POINTS)))

    def test_pick_is_seeded_covers_every_point_and_bounds_n(self):
        n = len(modes.POINTS)
        picks = [modes.pick_crashpoint(7, i) for i in range(1, 3 * n + 1)]
        self.assertEqual(picks, [modes.pick_crashpoint(7, i) for i in range(1, 3 * n + 1)])
        for block in range(3):
            self.assertEqual({p for p, _ in picks[block * n:(block + 1) * n]}, set(modes.POINTS))
        for point, hits in picks:
            self.assertTrue(1 <= hits <= modes.MAX_HITS[point], (point, hits))
        self.assertTrue(any(hits > 1 for _, hits in picks))
        self.assertNotEqual(picks, [modes.pick_crashpoint(8, i) for i in range(1, 3 * n + 1)])


if __name__ == "__main__":
    unittest.main()
