"""Independent worlds for private keys and ordered single-key shared mutations."""
import hashlib
import itertools

SHARED = b"shared/status"


def apply(state, ops):
    for op in ops:
        if op[0] == "put":
            state[op[1]] = op[2]
        else:
            state.pop(op[1], None)


def worlds(histories, initial=None):
    initial = dict(initial or {})
    choices = []
    for history in histories:
        pending = [entry for entry in history if entry[2] is None]
        if len(pending) > 1:
            raise ValueError("more than one pending operation for a writer")
        if any(entry[2] not in ("ACK", "ERR", None) for entry in history):
            raise ValueError("unknown response")
        variants = []
        for include in ([False, True] if pending else [False]):
            variants.append([entry for entry in history
                             if entry[2] == "ACK" or (include and entry[2] is None)])
        choices.append(variants)
    results = []
    for combination in itertools.product(*choices):
        state = dict(initial)
        owners = {}
        last_shared = []
        for writer, entries in enumerate(combination):
            shared = None
            for entry in entries:
                _, ops, *_ = entry
                if any(op[1] == SHARED for op in ops):
                    if len(ops) != 1:
                        raise ValueError("shared mutations must be single-operation requests")
                    shared = entry
                    continue
                for op in ops:
                    if op[1] in owners and owners[op[1]] != writer:
                        raise ValueError("unsupported shared key; use shared/status")
                    owners[op[1]] = writer
                apply(state, ops)
            if shared is not None:
                last_shared.append(shared)
        if not last_shared:
            results.append(state)
        for candidate in last_shared:
            end = candidate[4] if len(candidate) > 4 else None
            overtaken = any(other is not candidate and end is not None and
                            len(other) > 3 and end < other[3] for other in last_shared)
            if not overtaken:
                world = dict(state)
                apply(world, candidate[1])
                results.append(world)
    return results


class Mismatch(AssertionError):
    def __init__(self, summary, details):
        super().__init__(summary)
        self.details = details


def describe(value):
    if value is None:
        return "absent"
    return "%r len=%d sha256=%s" % (value[:48], len(value), hashlib.sha256(value).hexdigest()[:12])


def match(histories, actual, initial=None):
    candidates = worlds(histories, initial)
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
