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
# SIGKILL is delivered at once, but a child inside fsync/writeback exits only when
# the kernel finishes that I/O; on a loaded disk this has taken more than 5 s.
EXIT_WAIT, SLOW_EXIT = 60, 5

ToolError = protocol.ToolError


class LowSpace(ToolError):
    """Host disk nearly full: every later round would fail the same way, so stop."""


def database_path(directory, mode, number):
    group = (number - 1) // 3 if mode == "default" else number
    return directory / ("iteration-%04d.db" % group)


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
    db_path = database_path(directory, mode, number)
    delay = 10 ** random.Random("kill:%s:%s" % (seed, number)).uniform(-2.7, 0)
    event_order = 0
    killed_at = None

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
                killed_at = time.monotonic()
            try:
                proc.wait(timeout=EXIT_WAIT)
            except subprocess.TimeoutExpired:
                raise ToolError("serve pid %d still alive %d s after SIGKILL (stat: %s)"
                                % (proc.pid, EXIT_WAIT, process_state(proc.pid))) from None
            exit_wait = time.monotonic() - killed_at
        finally:
            stop.set()
            if proc.poll() is None and killed_at is None:
                proc.kill()
                try:
                    proc.wait(timeout=EXIT_WAIT)
                except subprocess.TimeoutExpired:
                    pass  # still alive: a ToolError is already propagating
            for thread in writers:
                if thread.ident is not None:
                    thread.join(timeout=5)
            read_thread.join(timeout=5)
            if proc.poll() is not None and any(t.is_alive() for t in writers + [read_thread]):
                raise ToolError("pipe thread failed to stop after kill")
            try:
                proc.stdin.close()
            except BrokenPipeError:
                pass
            if proc.poll() is not None:  # a stuck child keeps the reader blocked on this pipe
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
    mix["exit_wait_ms"] = round(exit_wait * 1000, 3)
    return delay * 1000, in_flight, world, counts, mix, actual


def process_state(pid):
    try:
        with open("/proc/%d/stat" % pid) as stat:
            return stat.read().split(")", 1)[1].split()[0]  # D = uninterruptible I/O
    except OSError:
        return "gone"


def quarantine(path):
    """Move a database a tool error left behind aside, so the next round starts fresh."""
    for name in (path, Path(str(path) + ".lock")):
        if name.exists():
            name.rename(name.with_name(name.name + ".tool-error"))


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=12345)
    parser.add_argument("--iterations", type=int, default=500)
    parser.add_argument("--mode", choices=["default", "large-values", "large-batch", "recovery-crash", "compaction", "disk-full", "crashpoints"], default="default")
    parser.add_argument("--data-dir", type=Path, default=Path.home() / "tmp_test" / "torture_data")
    parser.add_argument("--compress-log", action="store_true", help="store the complete transcript as oracle.log.gz")
    parser.add_argument("--host-storage-dir", type=Path, action="append", default=[],
                        help="also check the physical host volume, e.g. /mnt/d for a WSL disk on D:")
    parser.add_argument("--min-free-gib", type=float, default=2,
                        help="stop before a round if a checked volume has less free space")
    return parser


def main(argv=None):
    parser = argument_parser()
    args = parser.parse_args(argv)
    if not sys.platform.startswith("linux"):
        parser.error("run this tool in Ubuntu/WSL, using the real engine")
    if args.iterations < 1:
        parser.error("--iterations must be positive")
    if not 0 < args.min_free_gib < float("inf"):
        parser.error("--min-free-gib must be positive and finite")
    for volume in args.host_storage_dir:
        if not volume.is_dir():
            # A typo or a WSL-only path (/mnt/d) on plain Linux would otherwise
            # turn every round into the same TOOL ERROR.
            parser.error("--host-storage-dir %s is not a directory on this machine" % volume)
    args.data_dir.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="seed-%s-" % args.seed, dir=args.data_dir))
    print("seed=%s mode=%s evidence=%s" % (args.seed, args.mode, directory), flush=True)
    histogram, totals, mix = Counter(), Counter(), Counter()
    flying = passed = tool_errors = 0
    max_wait = 0.
    previous = {}
    opener = gzip.open if args.compress_log else open
    log_name = "oracle.log.gz" if args.compress_log else "oracle.log"
    with opener(directory / log_name, "wt", encoding="utf-8") as log:
        for number in range(1, args.iterations + 1):
            try:
                for volume in [directory, *args.host_storage_dir]:
                    free = shutil.disk_usage(volume).free
                    if free < args.min_free_gib * 1024**3:
                        raise LowSpace("low free space on %s: %.2f GiB; reserve %.2f GiB" %
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
                summary(number, passed, tool_errors, 1, max_wait, flying, totals, mix, histogram)
                return 1
            except (ToolError, OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError) as exc:
                # Not a verdict on the engine: record it, never count it as PASS, and
                # continue on a fresh database so one stuck child cannot end the run.
                tool_errors += 1
                print("TOOL ERROR seed=%s iteration=%s: %s" % (args.seed, number, exc), flush=True)
                log.write(json.dumps({"iteration": number, "event": "TOOL_ERROR", "error": str(exc)}) + "\n")
                log.flush()
                if isinstance(exc, LowSpace):
                    return 2
                try:
                    quarantine(database_path(directory, args.mode, number))
                except OSError:
                    pass
                previous = {}
                continue
            exit_wait = operations.pop("exit_wait_ms", 0) / 1000
            max_wait = max(max_wait, exit_wait)
            if exit_wait > SLOW_EXIT:
                print("WARN seed=%s iteration=%d: serve took %.1f s to exit after SIGKILL"
                      % (args.seed, number, exit_wait), flush=True)
            passed += 1
            flying += bool(pending)
            histogram[world] += 1
            totals.update(counts)
            largest = max(mix.get("max_batch", 0), operations.pop("max_batch", 0))
            mix.update(operations)
            mix["max_batch"] = largest
            log.write(json.dumps({"iteration": number, "event": "PASS", "world": world,
                                  "exit_wait_s": round(exit_wait, 3)}) + "\n")
            log.flush()
            print("iteration=%d kill_ms=%.3f exit_wait_s=%.3f awaiting_response=%s world=%d ACKs=%s PASS" %
                  (number, delay, exit_wait, pending, world, counts), flush=True)
    summary(args.iterations, passed, tool_errors, 0, max_wait, flying, totals, mix, histogram)
    print("Awaiting a response does not prove the engine was inside a write at kill time.", flush=True)
    return 2 if tool_errors else 0


def summary(ran, passed, tool_errors, failures, max_wait, flying, totals, mix, histogram):
    print("SUMMARY PASS=%d/%d TOOL_ERROR=%d FAIL=%d max_exit_wait_s=%.3f kills_awaiting_response=%.1f%% "
          "ACKs=%s mix=%s worlds=%s" %
          (passed, ran, tool_errors, failures, max_wait, 100 * flying / max(passed, 1),
           dict(totals), dict(mix), dict(histogram)), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
