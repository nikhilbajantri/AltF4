"""Exact atomic-operation ordering for overlapping shared and private batches."""
import hashlib
import itertools

SHARED = b"shared/status"


def apply(state, ops):
    for op in ops:
        if op[0] == "put":
            state[op[1]] = op[2]
        else:
            state.pop(op[1], None)


def _variants(histories):
    choices = []
    for history in histories:
        pending = [i for i, e in enumerate(history) if e[2] is None]
        if len(pending) > 1 or (pending and pending[0] != len(history) - 1):
            raise ValueError("invalid stop-and-wait history: pending operation must be last")
        if any(e[2] not in ("ACK", "ERR", None) for e in history):
            raise ValueError("unknown response")
        choices.append([[e for e in history if e[2] == "ACK" or (include and e[2] is None)]
                        for include in ([False, True] if pending else [False])])
    return itertools.product(*choices)


def _search(histories, initial=None, actual=None, first=False):
    """Exact whole-operation linearizations, constrained by FIFO and real time.

    State memoization merges equivalent prefixes. Keys that no remaining
    operation can modify are checked immediately against the target. A bounded
    search fails explicitly as a tool error; it never guesses or accepts a subset.
    """
    initial = dict(initial or {})
    results, explored = [], 0
    for streams in _variants(histories):
        keys = sorted(set(initial).union(*(set(op[1] for e in stream for op in e[1]) for stream in streams)))
        if actual is not None and set(actual) - set(keys):
            continue
        key_index = {key: i for i, key in enumerate(keys)}
        values, value_index = [None], {}
        def intern(value):
            if value not in value_index:
                value_index[value] = len(values)
                values.append(value)
            return value_index[value]
        state = [0] * len(keys)
        for key, value in initial.items():
            state[key_index[key]] = intern(value)
        compiled, last_touch = [], [[-1] * len(keys) for _ in streams]
        requirements = []
        for w, stream in enumerate(streams):
            operations, required = [], []
            for n, entry in enumerate(stream):
                final = {}
                for op in entry[1]:
                    k = key_index[op[1]]
                    final[k] = intern(op[2]) if op[0] == "put" else 0
                    last_touch[w][k] = n
                operations.append(tuple(final.items()))
                start = entry[3] if len(entry) > 3 else None
                required.append(tuple(max((j + 1 for j, other in enumerate(other_stream)
                    if len(other) > 4 and other[4] is not None and start is not None and other[4] < start),
                    default=0) if v != w else n for v, other_stream in enumerate(streams)))
            compiled.append(operations)
            requirements.append(required)
        target = tuple(intern(actual[k]) if k in actual else 0 for k in keys) if actual is not None else None
        goal = tuple(len(s) for s in streams)
        stack = [(tuple(0 for _ in streams), tuple(state))]
        seen = set()
        while stack:
            positions, state = stack.pop()
            identity = (positions, state)
            if identity in seen:
                continue
            seen.add(identity)
            explored += 1
            if explored > 250_000:
                raise ValueError("exact oracle search budget exceeded; no verdict issued")
            if target is not None and any(state[k] != target[k] and
                    all(positions[w] > last_touch[w][k] for w in range(len(streams))) for k in range(len(keys))):
                continue
            if positions == goal:
                world = {key: values[state[k]] for k, key in enumerate(keys) if state[k]}
                if target is None or state == target:
                    results.append(world)
                    if first or target is not None:
                        return results
                continue
            for w, stream in enumerate(streams):
                n = positions[w]
                if n == len(stream) or any(positions[v] < count for v, count in enumerate(requirements[w][n])):
                    continue
                next_state = list(state)
                for k, value in compiled[w][n]:
                    next_state[k] = value
                next_positions = list(positions)
                next_positions[w] += 1
                stack.append((tuple(next_positions), tuple(next_state)))
    return results


def worlds(histories, initial=None):
    return _search(histories, initial)



class Mismatch(AssertionError):
    def __init__(self, summary, details):
        super().__init__(summary)
        self.details = details


def describe(value):
    if value is None:
        return "absent"
    return "%r len=%d sha256=%s" % (value[:48], len(value), hashlib.sha256(value).hexdigest()[:12])


def match(histories, actual, initial=None):
    candidates = _search(histories, initial, actual)
    if candidates:
        return 0
    candidates = _search(histories, initial, first=True)
    if not candidates:
        raise ValueError("history has no valid operation ordering")
    for number, expected in enumerate(candidates):
        if actual == expected:
            return number
    differences = []
    for number, expected in enumerate(candidates):
        missing, extra = expected.keys() - actual.keys(), actual.keys() - expected.keys()
        wrong = {k for k in expected.keys() & actual.keys() if expected[k] != actual[k]}
        differences.append((len(missing) + len(extra) + len(wrong), number, missing, extra, wrong))
    _, number, missing, extra, wrong = min(differences, key=lambda d: d[:2])
    expected = candidates[number]
    keys = sorted(missing | extra | wrong)[:5]
    ids = sorted({entry[0] for history in histories for entry in history
                  if any(op[1] in keys for op in entry[1])})[-12:]
    summary = "world=%d missing=%d extra=%d wrong=%d op_ids=%s" % (
        number, len(missing), len(extra), len(wrong), ",".join(ids))
    for key in keys:
        summary += "\n key=%r expected=%s found=%s" % (key[:80], describe(expected.get(key)), describe(actual.get(key)))
    details = "expected worlds=%r\nfound=%r\nhistories=%r" % (candidates, actual, histories)
    raise Mismatch(summary, details)
