"""Targeted crash workloads using only the public CLI and observed responses."""
from collections import Counter
import json
import random
import signal
from torturelib import oracle, protocol, workload

POINTS = ("torn_write", "before_write", "after_write", "after_fsync", "after_return",
          "init_before_rename", "recovery_mid_scan", "recovery_before_truncate",
          "recovery_after_truncate", "compact_mid_copy", "compact_before_rename",
          "compact_after_rename", "compact_after_swap", "close_mid")
WRITE_POINTS = {"torn_write", "before_write", "after_write", "after_fsync", "after_return"}
COMPACT_POINTS = {p for p in POINTS if p.startswith("compact_")}
# Hits one serve process can reach with the commands below: write points once
# per write, compaction points once per compact command, recovery_mid_scan
# once per frame scanned (+1 at the end); the rest at most once per process.
MAX_HITS = {p: 3 if p in WRITE_POINTS | COMPACT_POINTS | {"recovery_mid_scan"} else 1
            for p in POINTS}


def pick_crashpoint(seed, number):
    """Seeded (point, n). Each block of len(POINTS) iterations covers every point once."""
    block = (number - 1) // len(POINTS)
    order = random.Random("crashpoints:%s:%d" % (seed, block)).sample(POINTS, len(POINTS))
    point = order[(number - 1) % len(POINTS)]
    return point, random.Random("crashpoints-n:%s:%d" % (seed, number)).randint(1, MAX_HITS[point])


def session(path, commands, log, number, point=None, cap=None, hits=1):
    env = protocol.environment()
    if point:
        env["KVDB_CRASH"] = "%s:%d" % (point, hits)
    args = ["serve", path]
    if cap is not None:
        args += ["--max-bytes", str(cap)]
    log.write(json.dumps({"iteration": number, "event": "SUBMIT", "point": point,
                          "hits": hits, "commands": commands}) + "\n")
    log.flush()
    result = protocol.cli(*args, env=env, text=commands + "quit\n")
    log.write(json.dumps({"iteration": number, "event": "RESULT", "point": point,
                          "returncode": result.returncode, "stdout": result.stdout,
                          "stderr": result.stderr}) + "\n")
    log.flush()
    expected_code = -signal.SIGKILL if point else 0
    if result.returncode != expected_code:
        raise AssertionError("point=%s exit=%s expected=%s output=%s %s" %
                             (point, result.returncode, expected_code, result.stdout[:300], result.stderr[:300]))
    return result.stdout.splitlines()


def iteration(mode, seed, number, directory, log):
    path = directory / ("%s-%04d.db" % (mode, number))
    base = {b"anchor": b"durable", b"victim": b"before"}
    mix = Counter()
    counts = {"w1": 0, "w2": 0}
    if mode == "disk-full":
        plans = [("w1-%d" % n, [("put", ("key%d" % n).encode(), b"v" * 100)]) for n in range(30)]
        plans += [("w1-batch", [("put", b"a", b"x" * 1500), ("put", b"b", b"y" * 1500)])]
        plans += [("w1-del%d" % n, [("del", ("key%d" % n).encode())]) for n in range(8)]
        lines = session(path, "".join(workload.command(*plan) for plan in plans),
                        log, number, "close_mid", cap=3000)
        responses = {line.split()[1]: line.split()[0] for line in lines if line.startswith(("ACK ", "ERR "))}
        if set(responses) != {p[0] for p in plans}:
            raise AssertionError("missing responses before close crash")
        if not any(line.endswith(" DISKFULL") for line in lines):
            raise AssertionError("disk-full mode did not reach the cap")
        if not all(responses["w1-del%d" % n] == "ACK" for n in range(8)):
            raise AssertionError("delete reserve failed")
        history = [[op_id, ops, responses[op_id]] for op_id, ops in plans]
        actual = protocol.recovered(path)
        world = oracle.match([history], actual)
        counts["w1"] = sum(v == "ACK" for v in responses.values())
        mix["ERR"] = sum(v == "ERR" for v in responses.values())
        lines = session(path, "compact w1-compact\nput w1-new new available\n", log, number, cap=3000)
        if "ACK w1-new" not in lines:
            raise AssertionError("write failed after compaction freed space")
        actual[b"new"] = b"available"
        oracle.match([], protocol.recovered(path), actual)
        return 0., [], world, counts, mix, actual
    hits = 1
    point = (None if mode == "crashpoints" else
             ("recovery_mid_scan", "recovery_before_truncate", "recovery_after_truncate")[(number - 1) % 3]
             if mode == "recovery-crash" else
             ("compact_mid_copy", "compact_before_rename", "compact_after_rename", "compact_after_swap")[(number - 1) % 4])
    if mode == "crashpoints":
        point, hits = pick_crashpoint(seed, number)
    if point != "init_before_rename":
        if point.startswith("compact_"):
            for n in range(6):
                base[("live%d" % n).encode()] = ("%s:%d:%d:" % (seed, number, n)).encode() + b"x" * (800_000 if number % 5 == 0 else 512)
        lines = session(path, workload.command("w1-base", [("put", k, v) for k, v in base.items()]), log, number)
        if "ACK w1-base" not in lines:
            raise AssertionError("fixture was not acknowledged")
        counts["w1"] += 1
    else:
        base = {}
    write_points = WRITE_POINTS
    ops = [("put", b"left", b"new"), ("put", b"right", b"new"), ("del", b"victim")]
    command = workload.command("w2-target", ops) if point in write_points else (
        "compact w2-target\n" if point.startswith("compact_") else "")
    # n > 1: the first n-1 hits must pass. Earlier writes are ACKed and must survive;
    # earlier compactions change nothing; recovery_mid_scan needs one frame per hit.
    pre_ops = [("w2-pre%d" % i, [("put", b"pre%d" % i, b"done")]) for i in range(hits - 1)]
    if point in write_points:
        command = "".join(workload.command(*plan) for plan in pre_ops) + command
    elif point in COMPACT_POINTS:
        command = "".join("compact w2-pre%d\n" % i for i in range(hits - 1)) + command
    elif point == "recovery_mid_scan" and pre_ops:
        lines = session(path, "".join(workload.command(*plan) for plan in pre_ops), log, number)
        if not all("ACK " + op_id in lines for op_id, _ in pre_ops):
            raise AssertionError("recovery_mid_scan fixture frames were not acknowledged")
    repeats = 3 if mode == "recovery-crash" else 1
    for _ in range(repeats):
        if point in ("recovery_before_truncate", "recovery_after_truncate"):
            # Use the real torn-write hook, never fabricate a storage-format fixture.
            session(path, workload.command("w2-torn", ops), log, number, "torn_write")
        lines = session(path, command, log, number, point, hits=hits)
    if point in write_points | COMPACT_POINTS:
        missing = [op_id for op_id, _ in pre_ops if "ACK " + op_id not in lines]
        if missing:
            raise AssertionError("point=%s:%d earlier ops not acknowledged: %s" % (point, hits, missing))
    expected = dict(base)
    if point in write_points or point == "recovery_mid_scan":
        for _, plan_ops in pre_ops:
            oracle.apply(expected, plan_ops)
    if point in ("after_write", "after_fsync", "after_return"):
        oracle.apply(expected, ops)
    actual = protocol.recovered(path)
    oracle.match([], actual, expected)
    mix[point if mode != "crashpoints" else "%s:%d" % (point, hits)] = repeats
    return 0., (["w2-target"] if command else []), 0, counts, mix, actual
