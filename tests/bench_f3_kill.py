"""F3 benchmark (not a unittest): 1,000,000 keys, SIGKILL mid-write, timed open. Owner: Nikhil.

1. Starts ./kvdb serve on a fresh database under tests.util.test_dir() (a real disk).
2. Writes 1,000,000 keys as 100 batches of 10,000 (key%07d -> v%07d), stop-and-wait,
   recording each ACK from serve's stdout independently of the database.
3. Keeps writing extra batches and SIGKILLs serve while one is in flight: after a
   seeded number of extra ACKed batches (0-9), a seeded 0-40 ms after sending the next.
4. Times ./kvdb open, then runs ./kvdb check (must print OK) and ./kvdb dump.
5. Every ACKed key must be present with its value; keys that were sent but not ACKed
   may be present or absent; anything else is a failure.

Run from the repo root: python3 -m tests.bench_f3_kill --seed N
Exit 0 on PASS, 1 on FAIL.
"""

import argparse
import os
import random
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

# Support both python3 tests/... and python3 -m tests....
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.util import test_dir

ROOT = Path(__file__).resolve().parents[1]
KVDB = [sys.executable, str(ROOT / "kvdb")]
N, BATCH = 1_000_000, 10_000


def batch_command(op_id, first):
    lines = ["batch %s" % op_id]
    lines += ["put key%07d v%07d" % (k, k) for k in range(first, first + BATCH)]
    return "\n".join(lines) + "\nend\n"


def strict_recovery_ok(output):
    """A benchmark PASS must enforce the PDF's strict recovery threshold."""
    try:
        elapsed = float(output.split("recovery_ms=", 1)[1].split()[0])
    except (IndexError, ValueError):
        return False
    return 0 <= elapsed < 2000


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args(argv)
    rng = random.Random("f3:%d" % args.seed)
    extra_batches, delay = rng.randrange(10), rng.uniform(0, 0.040)

    tmpdir = tempfile.mkdtemp(prefix="bench_f3_", dir=test_dir())
    path = os.path.join(tmpdir, "f3.db")
    try:
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        env.pop("KVDB_CRASH", None)
        proc = subprocess.Popen(KVDB + ["serve", path], cwd=ROOT, env=env, text=True,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        replies, acked, unacked = {}, set(), set()
        cond = threading.Condition()

        def reader():
            for line in proc.stdout:
                fields = line.split()
                with cond:
                    if len(fields) >= 2:
                        replies[fields[1]] = fields[0]
                    cond.notify_all()
            with cond:
                cond.notify_all()

        threading.Thread(target=reader, daemon=True).start()

        def send(number):
            op_id = "w1-%d" % number
            proc.stdin.write(batch_command(op_id, number * BATCH))
            proc.stdin.flush()
            return op_id

        def await_reply(op_id):
            with cond:
                if not cond.wait_for(lambda: op_id in replies or proc.poll() is not None, 120):
                    raise SystemExit("no reply for %s within 120 s" % op_id)
                if replies.get(op_id) != "ACK":
                    raise SystemExit("unexpected reply for %s: %s" % (op_id, replies.get(op_id)))

        t0 = time.monotonic()
        for number in range(N // BATCH + extra_batches):
            await_reply(send(number))
            acked.update(range(number * BATCH, (number + 1) * BATCH))
        write_s = time.monotonic() - t0
        in_flight = N // BATCH + extra_batches
        send(in_flight)
        time.sleep(delay)
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=60)
        with cond:
            # An ACK that reached the pipe before the kill still counts.
            if replies.get("w1-%d" % in_flight) == "ACK":
                acked.update(range(in_flight * BATCH, (in_flight + 1) * BATCH))
            else:
                unacked.update(range(in_flight * BATCH, (in_flight + 1) * BATCH))

        t0 = time.monotonic()
        opened = subprocess.run(KVDB + ["open", path], cwd=ROOT, capture_output=True, text=True, timeout=120)
        open_ms = (time.monotonic() - t0) * 1000
        check = subprocess.run(KVDB + ["check", path], cwd=ROOT, capture_output=True, text=True, timeout=120)
        dump = subprocess.run(KVDB + ["dump", path], cwd=ROOT, capture_output=True, text=True, timeout=120)

        found, wrong = {}, []
        for line in dump.stdout.splitlines():
            key, value = line.split("\t")
            found[key] = value
        for key, value in found.items():
            k = int(key[3:]) if key.startswith("key") and key[3:].isdigit() else -1
            if (k not in acked and k not in unacked) or value != "v%07d" % k:
                wrong.append(key)
        missing = sum("key%07d" % k not in found for k in acked)

        timing_ok = strict_recovery_ok(opened.stdout)
        ok = (timing_ok and proc.returncode == -signal.SIGKILL and opened.returncode == 0 and
              check.stdout.strip() == "OK" and dump.returncode == 0 and not missing and not wrong)
        print("seed=%d extra_batches=%d kill_delay_ms=%.1f serve_exit=%s write_s=%.1f"
              % (args.seed, extra_batches, delay * 1000, proc.returncode, write_s))
        print("in_flight=w1-%d (%s)" % (in_flight, "ACKed before kill" if not unacked else "not ACKed"))
        print("open: %s (wall %.1f ms, includes interpreter start)" % (opened.stdout.strip(), open_ms))
        print("strict_recovery_under_2000_ms=%s" % timing_ok)
        print("check: %s" % check.stdout.strip())
        print("keys found=%d keys ACKed=%d missing ACKed=%d unexpected=%d"
              % (len(found), len(acked), missing, len(wrong)))
        print("PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmpdir)


if __name__ == "__main__":
    raise SystemExit(main())
