"""First crash-test milestone: two writers, private keys, puts/deletes/batches.

Expected state is computed solely from the command/response transcript. The
separate crash_probe adapter supplies open/check/dump until the CLI is ready.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import queue
import random
import signal
import subprocess
import sys
import tempfile
import threading
import time

from torturelib import oracle, workload

ROOT = Path(__file__).resolve().parents[1]


class ToolError(Exception):
    pass


def clean_environment():
    env = dict(os.environ)
    env.pop("KVDB_CRASH", None)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def iteration(seed, number, directory, log):
    plans = {w: workload.generate(seed, number, w) for w in ("w1", "w2")}
    histories = {w: [] for w in plans}
    replies = {w: queue.Queue() for w in plans}
    started = {w: threading.Event() for w in plans}
    stop = threading.Event()
    ready = queue.Queue()
    guard, pipe_lock = threading.Lock(), threading.Lock()
    records = {}
    problems = []
    db_path = directory / ("iteration-%04d.db" % number)
    delay = random.Random("kill:%s:%s" % (seed, number)).uniform(.002, .025)

    def record(event, **fields):
        # Caller holds guard; record and state transitions share one ordering.
        log.write(json.dumps(dict(iteration=number, event=event, **fields)) + "\n")
        log.flush()

    with open(directory / ("stderr-%04d.log" % number), "w") as stderr:
        proc = subprocess.Popen([sys.executable, "-m", "src.serve", str(db_path)],
                                cwd=ROOT, env=clean_environment(), stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=stderr, text=True, bufsize=1)

        def reader():
            for line in proc.stdout:
                fields = line.split()
                with guard:
                    record("RESPONSE", line=line.rstrip("\n"))
                    if fields and fields[0] == "READY":
                        ready.put(line)
                    elif len(fields) >= 2 and fields[0] in ("ACK", "ERR"):
                        op_id = fields[1]
                        if op_id not in records or records[op_id][2] is not None:
                            problems.append("unknown or duplicate response: " + line.strip())
                            continue
                        if fields[0] == "ACK" and len(fields) != 2:
                            problems.append("malformed ACK: " + line.strip())
                        records[op_id][2] = fields[0]
                        replies[op_id.split("-", 1)[0]].put(op_id)
                    else:
                        problems.append("unexpected response: " + line.strip())
            ready.put(None)

        def writer(w):
            for op_id, ops in plans[w]:
                if stop.is_set():
                    return
                with guard:
                    if stop.is_set():
                        return
                    entry = [op_id, ops, None]
                    histories[w].append(entry)
                    records[op_id] = entry
                    record("SENT", id=op_id, ops=[[op[0]] + [x.hex() for x in op[1:]]
                                                  for op in ops])
                started[w].set()
                try:
                    with pipe_lock:
                        proc.stdin.write(workload.command(op_id, ops))
                        proc.stdin.flush()
                except (BrokenPipeError, OSError):
                    return
                # Stop-and-wait: this writer cannot submit its next operation
                # until the reader observes a response for this one.
                while not stop.is_set():
                    try:
                        reply_id = replies[w].get(timeout=.05)
                    except queue.Empty:
                        continue
                    if reply_id != op_id:
                        with guard:
                            problems.append("response out of order for " + op_id)
                        return
                    break

        read_thread = threading.Thread(target=reader, daemon=True)
        writers = [threading.Thread(target=writer, args=(w,), daemon=True) for w in plans]
        read_thread.start()
        try:
            try:
                greeting = ready.get(timeout=10)
            except queue.Empty:
                raise ToolError("serve did not print READY within 10 seconds") from None
            if greeting is None:
                raise ToolError("serve exited before READY; see stderr log")
            for thread in writers:
                thread.start()
            for event in started.values():
                if not event.wait(5):
                    raise ToolError("writer did not start")
            time.sleep(delay)
            with guard:
                stop.set()
                in_flight = [op_id for op_id, entry in records.items() if entry[2] is None]
                record("KILL", delay_ms=round(delay * 1000, 3), in_flight=in_flight)
                if proc.poll() is not None:
                    raise ToolError("serve exited before the scheduled kill")
                proc.kill()  # SIGKILL on Linux, never a graceful shutdown.
            proc.wait(timeout=5)
        finally:
            stop.set()
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
            for thread in writers:
                if thread.ident is not None:
                    thread.join(timeout=5)
            read_thread.join(timeout=5)
            if any(t.is_alive() for t in writers + [read_thread]):
                raise ToolError("pipe thread failed to stop after kill")
            proc.stdin.close()
            proc.stdout.close()
        if proc.returncode != -signal.SIGKILL:
            raise ToolError("child did not exit via SIGKILL: %s" % proc.returncode)
    if problems:
        raise AssertionError("; ".join(problems))
    if any(entry[2] == "ERR" for entry in records.values()):
        raise AssertionError("unexpected ERR in default workload; inspect oracle.log")
    probe = subprocess.run([sys.executable, "-m", "torturelib.crash_probe", str(db_path)],
                           cwd=ROOT, env=clean_environment(), capture_output=True,
                           text=True, timeout=15)
    if probe.returncode:
        raise AssertionError("open/check/dump failed: " + probe.stderr)
    try:
        result = json.loads(probe.stdout)
        actual = {bytes.fromhex(k): bytes.fromhex(v) for k, v in result["items"]}
    except (ValueError, KeyError, TypeError) as exc:
        raise ToolError("invalid probe output: " + str(exc)) from None
    world = oracle.match(list(histories.values()), actual)
    counts = {w: sum(entry[2] == "ACK" for entry in h) for w, h in histories.items()}
    mix = Counter("batch" if len(entry[1]) > 1 else entry[1][0][0]
                  for entry in records.values())
    return delay * 1000, in_flight, world, counts, mix


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=12345)
    parser.add_argument("--iterations", type=int, default=25)
    parser.add_argument("--mode", choices=["default"], default="default")
    parser.add_argument("--data-dir", type=Path, default=Path.home() / "tmp_test" / "torture_data")
    args = parser.parse_args(argv)
    if not sys.platform.startswith("linux"):
        parser.error("run this tool in Ubuntu/WSL, using the real engine")
    if args.iterations < 1:
        parser.error("--iterations must be positive")
    args.data_dir.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="seed-%s-" % args.seed, dir=args.data_dir))
    print("seed=%s mode=default evidence=%s" % (args.seed, directory), flush=True)
    histogram, totals, mix = Counter(), Counter(), Counter()
    flying = passed = 0
    with open(directory / "oracle.log", "w", encoding="utf-8") as log:
        for number in range(1, args.iterations + 1):
            try:
                delay, pending, world, counts, operations = iteration(args.seed, number, directory, log)
            except AssertionError as exc:
                message = "FAIL seed=%s iteration=%s: %s" % (args.seed, number, exc)
                (directory / "failure.txt").write_text(message, encoding="utf-8")
                print(message, flush=True)
                return 1
            except (ToolError, OSError, subprocess.TimeoutExpired) as exc:
                print("TOOL ERROR seed=%s iteration=%s: %s" % (args.seed, number, exc), flush=True)
                return 2
            passed += 1
            flying += bool(pending)
            histogram[world] += 1
            totals.update(counts)
            mix.update(operations)
            print("iteration=%d kill_ms=%.3f awaiting_response=%s world=%d ACKs=%s PASS" %
                  (number, delay, pending, world, counts), flush=True)
    print("SUMMARY PASS=%d/%d kills_awaiting_response=%.1f%% ACKs=%s mix=%s worlds=%s" %
          (passed, args.iterations, 100 * flying / passed, dict(totals), dict(mix), dict(histogram)),
          flush=True)
    print("Awaiting a response does not prove the engine was inside a write at kill time.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
