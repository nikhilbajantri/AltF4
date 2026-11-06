"""Exact possible worlds for two stop-and-wait writers using disjoint keys.

No engine imports or file decoding: expected state comes only from SENT/ACK/ERR.
At most one unanswered operation per writer means at most four possible worlds.
"""
import itertools


def apply(state, ops):
    for op in ops:
        if op[0] == "put":
            state[op[1]] = op[2]
        else:
            state.pop(op[1], None)


def worlds(histories):
    choices = []
    for history in histories:
        state = {}
        pending = []
        for op_id, ops, response in history:
            if response == "ACK":
                apply(state, ops)
            elif response is None:
                pending.append(ops)
            elif response != "ERR":
                raise ValueError("unknown response")
        if len(pending) > 1:
            raise ValueError("more than one pending operation for a writer")
        variants = [state]
        if pending:
            present = dict(state)
            apply(present, pending[0])
            variants.append(present)
        choices.append(variants)
    result = []
    for combination in itertools.product(*choices):
        merged = {}
        for state in combination:
            if merged.keys() & state.keys():
                raise ValueError("this milestone requires disjoint writer keys")
            merged.update(state)
        result.append(merged)
    return result


def match(histories, actual):
    candidates = worlds(histories)
    for number, expected in enumerate(candidates):
        if actual == expected:
            return number
    # Include exact bytes in failure evidence; never silently accept a subset.
    raise AssertionError("expected worlds=%r; found=%r" % (candidates, actual))
