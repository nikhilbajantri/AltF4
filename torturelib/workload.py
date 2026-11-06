"""Seeded operation streams, shared keys, large boundaries and rejected requests."""
import hashlib
import random


def generate(seed, iteration, writer, count=100, mode="default"):
    rng = random.Random("%s:%s:%s" % (seed, iteration, writer))
    if mode in ("large-values", "large-batch"):
        count = min(count, 12)
    result = []
    for number in range(count):
        op_id = "%s-%d" % (writer, number)
        ops = []
        if mode == "large-batch":
            size = 10_000 if number == 0 else rng.randint(2, 10_000)
        else:
            size = rng.choice([2, 5, 32, 256, 10_000]) if rng.random() < .25 else 1
        if mode == "large-values":
            size = 1
        for item in range(size):
            key = (writer + "/" + str(rng.randrange(32))).encode()
            if size == 1 and number % 9 == 4:
                key = b"shared/status"
            if size == 1 and number % 17 == 7:
                key = b""
            if mode != "large-values" and rng.random() < .2:
                ops.append(("del", key))
            else:
                tag = "%s:%s:%s:%s:" % (seed, iteration, op_id, item)
                filler = hashlib.sha256(tag.encode()).hexdigest().encode()
                length = 1_048_576 if mode == "large-values" and number == 0 else (
                    131_072 if mode == "large-values" else 96 if size > 5 else (rng.randint(65_536, 262_144) if rng.random() < .5 else rng.randint(128, 4096)))
                value = (tag.encode() + filler * ((length // len(filler)) + 1))[:length]
                ops.append(("put", key, value))
        result.append((op_id, ops))
    return result


def command(op_id, ops):
    def line(op):
        return " ".join([op[0]] + ["hex:" + part.hex() for part in op[1:]])
    if len(ops) == 1:
        fields = line(ops[0]).split(" ", 1)
        return fields[0] + " " + op_id + " " + fields[1] + "\n"
    return "batch " + op_id + "\n" + "\n".join(map(line, ops)) + "\nend\n"
