"""Deterministic private-key workloads, independent of the storage engine."""
import hashlib
import random


def generate(seed, iteration, writer, count=100):
    rng = random.Random("%s:%s:%s" % (seed, iteration, writer))
    result = []
    for number in range(count):
        op_id = "%s-%d" % (writer, number)
        ops = []
        size = rng.randint(2, 5) if rng.random() < .25 else 1
        for item in range(size):
            key = (writer + "/" + str(rng.randrange(8))).encode()
            if rng.random() < .2:
                ops.append(("del", key))
            else:
                tag = "%s:%s:%s:%s" % (seed, iteration, op_id, item)
                filler = hashlib.sha256(tag.encode()).hexdigest().encode()
                value = tag.encode() + b":" + filler * rng.randint(1, 64)
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
