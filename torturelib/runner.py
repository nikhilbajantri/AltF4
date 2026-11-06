"""Seven crash modes with transcript-based expected state and public CLI checks."""
import argparse
import gzip
import shutil
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

from torturelib import oracle, workload, protocol, modes

ROOT = Path(__file__).resolve().parents[1]


class ToolError(Exception):
    pass


def clean_environment():
    env = dict(os.environ)
    env.pop("KVDB_CRASH", None)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def iteration(seed, number, directory, log, mode="default", initial=None):
    plans = {w: workload.generate(seed, number, w, mode=mode) for w in ("w1", "w2")}
    histories = {w: [] for w in plans}
    replies = {w: queue.Queue() for w in plans}
    started = {w: threading.Event() for w in plans}
    stop = threading.Event()
    ready = queue.Queue()
    guard, pipe_lock = threading.Lock(), threading.Lock()
    records = {}
    problems = []
    group = (number - 1) // 3 if mode == "default" else number
    db_path = directory / ("iteration-%04d.db" % group)
    delay = 10 ** random.Random("kill:%s:%s" % (seed, number)).uniform(-2.7, 0)
    event_order = 0

    def record(event, **fields):
        nonlocal event_order
        event_order += 1
        # Caller holds guard; record and state transitions share one ordering.
        log.write(json.dumps(dict(iteration=number, event=event, order=event_order, **fields)) + "\n")
        log.flush()
        return event_order

    with open(directory / ("stderr-%04d.log" % number), "w") as stderr:
        proc = subprocess.Popen([sys.executable, str(ROOT / "kvdb"), "serve", str(db_path)],
                                cwd=ROOT, env=clean_environment(), stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=stderr, text=True, bufsize=1)

        def reader():
            for line in proc.stdout:
                fields = line.split()
                with guard:
                    response_order = record("RESPONSE", line=line.rstrip("\n"))
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
                        records[op_id][4] = response_order
                        if fields[0] == "ERR" and (len(fields) != 3 or fields[2] not in ("INVALID", "DISKFULL", "BUSY")):
                            problems.append("unexpected error: " + line.strip())
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
                    entry = [op_id, ops, None, event_order + 1, None]
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
                # Deliberate quiet gaps allow kills with no pending requests too.
                pause = random.Random("pause:%s:%s:%s" % (seed, number, op_id)).uniform(0, .006)
                if stop.wait(pause):
                    return

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
            try:
                proc.stdin.close()
            except BrokenPipeError:
                pass
            proc.stdout.close()
        if proc.returncode != -signal.SIGKILL:
            raise ToolError("child did not exit via SIGKILL: %s" % proc.returncode)
    if problems:
        raise AssertionError("; ".join(problems))
    if mode == "default" and (number - 1) % 5 == 0:
        modes.session(db_path, workload.command("w1-tail", [("put", b"tail-fixture", b"uncommitted")]),
                      log, number, "torn_write")
    actual = protocol.recovered(db_path)
    world = oracle.match(list(histories.values()), actual, initial)
    counts = {w: sum(entry[2] == "ACK" for entry in h) for w, h in histories.items()}
    mix = Counter("batch" if len(entry[1]) > 1 else entry[1][0][0]
                  for entry in records.values())
    mix["ERR"] = sum(entry[2] == "ERR" for entry in records.values())
    mix["shared"] = sum(any(op[1] == oracle.SHARED for op in entry[1]) for entry in records.values())
    mix["max_batch"] = max((len(entry[1]) for entry in records.values()), default=0)
    return delay * 1000, in_flight, world, counts, mix, actual


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=12345)
    parser.add_argument("--iterations", type=int, default=25)
    parser.add_argument("--mode", choices=["default", "large-values", "large-batch", "recovery-crash", "compaction", "disk-full", "crashpoints"], default="default")
    parser.add_argument("--data-dir", type=Path, default=Path.home() / "tmp_test" / "torture_data")
    parser.add_argument("--compress-log", action="store_true", help="store the complete transcript as oracle.log.gz")
    parser.add_argument("--host-storage-dir", type=Path, action="append", default=[],
                        help="also check the physical host volume, e.g. /mnt/d for a WSL disk on D:")
    parser.add_argument("--min-free-gib", type=float, default=2,
                        help="stop before a round if a checked volume has less free space")
    args = parser.parse_args(argv)
    if not sys.platform.startswith("linux"):
        parser.error("run this tool in Ubuntu/WSL, using the real engine")
    if args.iterations < 1:
        parser.error("--iterations must be positive")
    if not 0 < args.min_free_gib < float("inf"):
        parser.error("--min-free-gib must be positive and finite")
    args.data_dir.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="seed-%s-" % args.seed, dir=args.data_dir))
    print("seed=%s mode=%s evidence=%s" % (args.seed, args.mode, directory), flush=True)
    histogram, totals, mix = Counter(), Counter(), Counter()
    flying = passed = 0
    previous = {}
    opener = gzip.open if args.compress_log else open
    log_name = "oracle.log.gz" if args.compress_log else "oracle.log"
    with opener(directory / log_name, "wt", encoding="utf-8") as log:
        for number in range(1, args.iterations + 1):
            try:
                for volume in [directory, *args.host_storage_dir]:
                    free = shutil.disk_usage(volume).free
                    if free < args.min_free_gib * 1024**3:
                        raise ToolError("low free space on %s: %.2f GiB; reserve %.2f GiB" %
                                        (volume, free / 1024**3, args.min_free_gib))
                if args.mode in ("default", "large-values", "large-batch"):
                    initial = previous if args.mode == "default" and (number - 1) % 3 else {}
                    result = iteration(args.seed, number, directory, log, args.mode, initial)
                else:
                    result = modes.iteration(args.mode, args.seed, number, directory, log)
                delay, pending, world, counts, operations, previous = result
            except AssertionError as exc:
                message = "FAIL seed=%s iteration=%s: %s" % (args.seed, number, exc)
                (directory / "failure.txt").write_text(message + "\n" + getattr(exc, "details", ""), encoding="utf-8")
                print(message, flush=True)
                return 1
            except (ToolError, OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError) as exc:
                print("TOOL ERROR seed=%s iteration=%s: %s" % (args.seed, number, exc), flush=True)
                return 2
            passed += 1
            flying += bool(pending)
            histogram[world] += 1
            totals.update(counts)
            largest = max(mix.get("max_batch", 0), operations.pop("max_batch", 0))
            mix.update(operations)
            mix["max_batch"] = largest
            log.write(json.dumps({"iteration": number, "event": "PASS", "world": world}) + "\n")
            log.flush()
            print("iteration=%d kill_ms=%.3f awaiting_response=%s world=%d ACKs=%s PASS" %
                  (number, delay, pending, world, counts), flush=True)
    print("SUMMARY PASS=%d/%d kills_awaiting_response=%.1f%% ACKs=%s mix=%s worlds=%s" %
          (passed, args.iterations, 100 * flying / passed, dict(totals), dict(mix), dict(histogram)),
          flush=True)
    print("Awaiting a response does not prove the engine was inside a write at kill time.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
