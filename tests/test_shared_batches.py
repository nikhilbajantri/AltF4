"""Exact shared-batch ordering and crash-outcome regression cases."""
import itertools
import random
import unittest
from torturelib import oracle


def batch(writer, value, start=1, end=4, response="ACK"):
    return [writer + "-1", [("put", b"city", value), ("put", b"postcode", value)], response, start, end]


class SharedBatchTests(unittest.TestCase):
    def test_valid_overlapping_batches_accept_either_whole_batch(self):
        history = [[batch("w1", b"A")], [batch("w2", b"B", 2, 3)]]
        for value in (b"A", b"B"):
            oracle.match(history, {b"city": value, b"postcode": value})

    def test_mixed_batch_result_is_rejected(self):
        history = [[batch("w1", b"A")], [batch("w2", b"B", 2, 3)]]
        with self.assertRaises(oracle.Mismatch):
            oracle.match(history, {b"city": b"A", b"postcode": b"B"})

    def test_completed_before_next_send_forces_order(self):
        history = [[batch("w1", b"A", 1, 2)], [batch("w2", b"B", 3, 4)]]
        oracle.match(history, {b"city": b"B", b"postcode": b"B"})
        with self.assertRaises(oracle.Mismatch):
            oracle.match(history, {b"city": b"A", b"postcode": b"A"})

    def test_pending_batch_is_wholly_optional_and_errors_absent(self):
        history = [[batch("w1", b"A", 1, 2)], [batch("w2", b"B", 3, None, None)]]
        for value in (b"A", b"B"):
            oracle.match(history, {b"city": value, b"postcode": value})
        history[1][0][2] = "ERR"
        with self.assertRaises(oracle.Mismatch):
            oracle.match(history, {b"city": b"B", b"postcode": b"B"})

    def test_delete_order_and_initial_state(self):
        h = [[["w1-1", [("put", b"x", b"new"), ("del", b"x"), ("put", b"y", b"yes")], "ACK"]],
             [["w2-1", [("put", b"x", b"other")], None]]]
        oracle.match(h, {b"y": b"yes"}, {b"x": b"old"})
        oracle.match(h, {b"x": b"other", b"y": b"yes"}, {b"x": b"old"})

    def test_small_histories_agree_with_exhaustive_reference(self):
        rng = random.Random(8123)
        for case in range(30):
            h = [[['%s-%d' % (w, n), [("put", b"x", bytes([rng.randrange(4)])),
                   ("put", b"y", bytes([rng.randrange(4)]))], "ACK"] for n in range(2)] for w in ("w1", "w2")]
            valid = set()
            for order in itertools.permutations([(w, n) for w in range(2) for n in range(2)]):
                if any(order.index((w, 0)) > order.index((w, 1)) for w in range(2)):
                    continue
                state = {}
                for w, n in order:
                    for _, key, value in h[w][n][1]:
                        state[key] = value
                valid.add(tuple(sorted(state.items())))
            for x, y in itertools.product(range(4), repeat=2):
                actual = {b"x": bytes([x]), b"y": bytes([y])}
                if tuple(sorted(actual.items())) in valid:
                    oracle.match(h, actual)
                else:
                    with self.assertRaises(oracle.Mismatch):
                        oracle.match(h, actual)


if __name__ == "__main__":
    unittest.main()
