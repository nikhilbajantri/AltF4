"""./prove <ID>: live crash proof for the demo, driving only the public ./kvdb CLI.

Each scenario builds a fresh database in $KVDB_PROVE_DIR (default ~/tmp_test/prove),
SIGKILLs a ./kvdb command at a named crash point (KVDB_CRASH=name:n, see src/crash.py),
then shows inspect / check / open / get evidence and states the invariant it proves.
Files are deleted at the start of a scenario and kept at the end for inspection.
Standard library only; nothing here imports the storage engine.

Usage: ./prove <ID> | ./prove --list | ./prove --all
"""

import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SIDE_SUFFIXES = (".lock", ".compact", ".init")


class Failed(Exception):
    pass


class Skipped(Exception):
    pass


def prove_dir():
    d = Path(os.environ.get("KVDB_PROVE_DIR") or Path.home() / "tmp_test" / "prove")
    d.mkdir(parents=True, exist_ok=True)
    return d


class Proof:
    """One scenario run: numbered steps, CLI calls, and checks."""

    def __init__(self, sid):
        self.sid = sid
        self.db = prove_dir() / ("%s.db" % sid)
        self.n = 0
        self.reset()

    def reset(self):
        for p in [self.db] + [Path(str(self.db) + s) for s in SIDE_SUFFIXES]:
            if p.exists():
                p.unlink()
        for p in self.db.parent.glob(self.db.name + ".batch*"):
            p.unlink()

    def step(self, text):
        self.n += 1
        print("[%d] %s" % (self.n, text))

    def note(self, text):
        print("    " + text)

    def kvdb(self, *args, crash=None, show=True):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        env.pop("KVDB_CRASH", None)
        if crash:
            env["KVDB_CRASH"] = crash
        argv = [str(a) for a in args]
        shown = " ".join("$DB" if a == str(self.db) else
                         ("$DB" + a[len(str(self.db)):] if a.startswith(str(self.db)) else
                          (a if len(a) <= 40 else a[:20] + "...(%d chars)" % len(a)))
                         for a in argv)
        r = subprocess.run([sys.executable, str(ROOT / "kvdb")] + argv, cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=120)
        if show:
            prefix = "KVDB_CRASH=%s " % crash if crash else ""
            print("    $ %s./kvdb %s" % (prefix, shown))
            for line in r.stdout.splitlines()[:12]:
                print("      " + line)
            if len(r.stdout.splitlines()) > 12:
                print("      ... (%d lines)" % len(r.stdout.splitlines()))
            print("      " + ("killed by SIGKILL" if r.returncode == -signal.SIGKILL else
                              "exit code %d" % r.returncode))
        return r

    def ok(self, *args, **kw):
        r = self.kvdb(*args, **kw)
        if r.returncode != 0:
            raise Failed("expected exit 0 from ./kvdb %s, got %s %r" % (args[0], r.returncode, r.stdout.strip()))
        return r.stdout.strip()

    def crash(self, crash, *args):
        r = self.kvdb(*args, crash=crash)
        if r.returncode != -signal.SIGKILL:
            raise Failed("expected SIGKILL at %s, got exit code %s" % (crash, r.returncode))
        return r

    def batch_file(self, lines, tag=""):
        f = Path(str(self.db) + ".batch" + tag)
        f.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
        return f

    def size(self):
        return self.db.stat().st_size if self.db.exists() else 0

    def side_files(self):
        return sorted(p.name for p in self.db.parent.glob(self.db.name + ".*")
                      if p.name.endswith((".compact", ".init")))

    def inspect(self):
        r = self.kvdb("inspect", self.db, show=False)
        lines = r.stdout.splitlines()
        frames = sum(line.startswith("offset=") and "crc=OK" in line for line in lines)
        tail = next((line for line in lines if line.startswith("end=")), "")
        torn = int(tail.split("torn_tail_bytes=")[1]) if "torn_tail_bytes=" in tail else 0
        side = self.side_files()
        self.note("$ ./kvdb inspect $DB -> frames=%d %s" % (frames, tail))
        self.note("$ ls $DB.compact $DB.init -> %s" % (", ".join(side) if side else "none"))
        return frames, torn, side

    def check(self):
        out = self.ok("check", self.db)
        return out

    def open(self):
        before = self.size()
        out = self.ok("open", self.db)
        after = self.size()
        self.note("file size before open=%d after open=%d" % (before, after))
        return out, before, after

    def get(self, key):
        return self.ok("get", self.db, key)

    def dump(self, show=True):
        out = self.kvdb("dump", self.db, show=show)
        if out.returncode:
            raise Failed("dump failed: %r" % out.stdout)
        return dict(line.split("\t", 1) for line in out.stdout.splitlines())

    def expect(self, what, actual, expected):
        if actual != expected:
            raise Failed("expected %s = %r, got %r" % (what, expected, actual))

    def base(self, pairs=(("anchor", "durable"), ("victim", "before"))):
        self.step("base state: " + ", ".join("%s=%s" % kv for kv in pairs))
        for k, v in pairs:
            self.ok("put", self.db, k, v)
        return dict(pairs)

    def evidence(self, base_size=None):
        """Steps 3-5: inspect, check, open. Returns (torn bytes, size before open, size after open)."""
        self.step("inspect after the crash")
        _, torn, self.side_before_open = self.inspect()
        self.step("check (read-only)")
        self.check()
        self.step("open (recovery)")
        self.last_open, before, after = self.open()
        if base_size is not None:
            self.expect("file size after open", after, base_size)
        self.ok("check", self.db)
        return torn, before, after


# ---- scenarios: each returns the PASS rule ----

def write_point(point, expect_present):
    def run(p):
        base = p.base()
        base_size = p.size()
        p.step("crash command (new key 'newkey'):")
        p.crash(point + ":1", "put", p.db, "newkey", "newvalue")
        torn, _, _ = p.evidence(None if expect_present else base_size)
        if point == "torn_write":
            p.note("torn tail before open: %d bytes; cut back to %d bytes by open" % (torn, base_size))
        p.step("keys after recovery")
        p.expect("get newkey", p.get("newkey"), "newvalue" if expect_present else "NOTFOUND")
        p.expect("dump without newkey", {k: v for k, v in p.dump().items() if k != "newkey"}, base)
    return run


def a1(p):
    write_point("before_write", False)(p)
    return "crash before any byte of the put reached the file: new key absent, old keys intact"


def a2(p):
    write_point("torn_write", False)(p)
    return "torn put: new key absent, torn tail truncated, torn bytes never returned"


def a3(p):
    write_point("after_write", True)(p)
    p.note("SIGKILL keeps the kernel page cache, so the unsynced frame is replayed; power cut is NOT tested")
    return "written but not fsynced, not ACKed: either outcome allowed; under SIGKILL the key is present"


def a4(p):
    write_point("after_fsync", True)(p)
    return "fsynced before put returned: new key present with its new value"


def a6(p):
    base = p.base()
    base_size = p.size()
    p.step("crash command (delete 'victim'):")
    p.crash("torn_write:1", "del", p.db, "victim")
    p.evidence(base_size)
    p.step("keys after recovery")
    p.expect("get victim", p.get("victim"), "before")
    p.expect("dump", p.dump(), base)
    return "torn delete: key keeps its old value, nothing corrupted"


def a7(p):
    base = p.base()
    base_size = p.size()
    big = p.batch_file(["put big " + "x" * 1_048_576])
    p.step("crash command (1 MiB value via a one-line batch file = one frame):")
    p.crash("torn_write:1", "batch", p.db, big)
    torn, _, _ = p.evidence(base_size)
    p.note("torn tail before open: %d bytes of the 1,048,576-byte value's frame" % torn)
    p.step("keys after recovery")
    p.expect("get big", p.get("big"), "NOTFOUND")
    p.expect("dump", p.dump(), base)
    return "torn 1 MiB put: key absent, old keys intact"


def b1(p):
    base = p.base()
    base_size = p.size()
    f = p.batch_file(["put b%d v%d" % (i, i) for i in range(10)])
    p.step("crash command (10-op batch b0..b9, one frame):")
    p.crash("torn_write:1", "batch", p.db, f)
    p.evidence(base_size)
    p.step("keys after recovery")
    found = p.dump()
    p.expect("visible batch keys", sorted(k for k in found if k.startswith("b")), [])
    p.expect("dump", found, base)
    return "torn 10-op batch: none of the 10 ops visible (the frame is the commit)"


def b5(p):
    p.step("base state: empty database")
    p.ok("open", p.db)
    p.step("batches applied first to last, each followed by a SIGKILL in close (after commit):")
    p.crash("close_mid:1", "batch", p.db, p.batch_file(["put X 1", "del X"], "1"))
    p.step("inspect after the crash")
    p.inspect()
    p.step("check (read-only)")
    p.check()
    p.step("open (recovery)")
    p.open()
    p.step("key after 'put X 1 / del X'")
    p.expect("get X", p.get("X"), "NOTFOUND")
    p.crash("close_mid:1", "batch", p.db, p.batch_file(["del X", "put X 2"], "2"))
    p.ok("open", p.db)
    p.note("after 'del X / put X 2' and another SIGKILL:")
    p.expect("get X", p.get("X"), "2")
    return "ops in a batch apply first to last, and recovery replays them in the same order"


def b6(p):
    base = p.base()
    base_size = p.size()
    f = p.batch_file(["put k%05d v%05d" % (i, i) for i in range(10_000)])
    p.step("crash command (10,000-op batch, one frame):")
    p.crash("torn_write:1", "batch", p.db, f)
    p.evidence(base_size)
    ms = float(p.last_open.split("recovery_ms=")[1])
    p.note("recovery_ms of the open that cut the torn 10,000-op frame = %.3f" % ms)
    p.step("keys after recovery")
    found = p.dump()
    p.expect("visible batch keys", sum(k.startswith("k") for k in found), 0)
    p.expect("dump", found, base)
    if ms >= 2000:
        raise Failed("expected recovery under 2000 ms, got %.1f ms" % ms)
    return "torn 10,000-op batch: none visible; recovery %.1f ms (< 2 s)" % ms


def torn_tail(p):
    p.note("making a real torn tail with the torn_write hook:")
    p.crash("torn_write:1", "put", p.db, "torn", "never")


def c1(p):
    base = p.base()
    base_size = p.size()
    torn_tail(p)
    torn_size = p.size()
    p.step("crash command (open killed while replaying, 2nd scan step):")
    p.crash("recovery_mid_scan:2", "open", p.db)
    p.expect("file size after the crashed scan (scan only reads)", p.size(), torn_size)
    p.evidence(base_size)
    p.step("keys after recovery")
    p.expect("dump", p.dump(), base)
    return "crash during replay changes nothing; the next open rebuilds the same state"


def c2(p):
    for n, point in enumerate(("recovery_before_truncate", "recovery_after_truncate")):
        if n:
            print("  -- part 2 (same database file, reset) --")
            p.reset()
        base = p.base()
        base_size = p.size()
        torn_tail(p)
        p.step("crash command (open killed at %s):" % point)
        p.crash(point + ":1", "open", p.db)
        p.note("file size after the crashed open = %d (%s)" % (
            p.size(), "torn tail still there" if point.endswith("before_truncate") else "already repaired"))
        p.evidence(base_size)
        p.step("keys after recovery")
        p.expect("dump", p.dump(), base)
    return "crash during tail repair: the next open repeats or finds the repair, same state"


def compact_case(p, point, temp_left):
    base = {"k%d" % i: "v%d" % i for i in range(5)}
    p.step("base state: k0..k4, each overwritten once (dead bytes to reclaim)")
    for k in base:
        p.ok("put", p.db, k, "old", show=False)
    for k, v in base.items():
        p.ok("put", p.db, k, v, show=False)
    p.note("size before compaction = %d" % p.size())
    p.step("crash command (compaction killed at %s):" % point)
    p.crash(point + ":1", "compact", p.db)
    p.evidence()
    p.expect(".compact left by the crash", p.side_before_open == ["%s.compact" % p.db.name], temp_left)
    p.expect(".compact after open", p.side_files(), [])
    p.step("keys after recovery")
    p.expect("dump", p.dump(), base)


def c3(p):
    compact_case(p, "compact_before_rename", True)
    print("  -- part 2 (same database file, reset) --")
    p.reset()
    compact_case(p, "compact_mid_copy", True)
    return "crash before the rename: old file authoritative, .compact deleted by open, data intact"


def c4(p):
    compact_case(p, "compact_after_rename", False)
    return "crash after the rename: compacted file authoritative, no .compact, data intact"


def c6(p):
    base = p.base()
    p.step("crash command (put, then SIGKILL inside close):")
    p.crash("close_mid:1", "put", p.db, "committed", "yes")
    p.evidence()
    p.step("keys after recovery")
    base["committed"] = "yes"
    p.expect("dump", p.dump(), base)
    return "crash during close: everything committed before it is intact"


def e1(p):
    cap = 1000
    p.step("base state: puts of 100-byte values with --max-bytes %d (reserve %d for deletes)" % (cap, min(65536, cap // 10)))
    kept, n = {}, 0
    while True:
        size = p.size()
        r = p.kvdb("put", p.db, "key%d" % n, "v" * 100, "--max-bytes", cap, show=False)
        if r.stdout.strip() == "ERR DISKFULL":
            break
        if r.returncode:
            raise Failed("unexpected put result %r" % r.stdout)
        kept["key%d" % n] = "v" * 100
        n += 1
    p.note("%d puts accepted, file size %d" % (n, size))
    p.step("rejected command (no crash):")
    p.kvdb("put", p.db, "key%d" % n, "v" * 100, "--max-bytes", cap)
    p.expect("file size after rejection", p.size(), size)
    p.step("inspect")
    p.inspect()
    p.step("check (read-only)")
    p.check()
    p.step("open")
    p.open()
    p.step("keys")
    p.expect("get rejected key%d" % n, p.get("key%d" % n), "NOTFOUND")
    p.expect("dump", p.dump(show=False), kept)
    p.note("dump: %d keys, all accepted values intact" % len(kept))
    return "cap reached: put returns ERR DISKFULL, writes nothing, database readable, old data intact"


def f4(p):
    pairs = (("a", "1"), ("b", "2"), ("c", "3"))
    base = p.base(pairs)
    full = p.size()
    p.step("damage (no crash): truncate -s -1 $DB")
    os.truncate(p.db, full - 1)
    p.note("size %d -> %d" % (full, p.size()))
    p.evidence()
    p.step("keys after recovery")
    found = p.dump()
    lost = sorted(set(base) - set(found))
    if lost not in ([], ["c"]) or any(found.get(k) != v for k, v in base.items() if k not in lost):
        raise Failed("expected at most the last record (c) lost, got lost=%s found=%s" % (lost, found))
    p.note("records lost: %s" % (", ".join(lost) if lost else
                                  "none (the 1-byte EOF guard was cut, not frame data)"))
    return "one byte cut from the end: open succeeds, at most the last record lost (here: %s)" % (
        ", ".join(lost) if lost else "none")


def tail_hex(p, label):
    data = p.db.read_bytes()
    start = max(0, len(data) - 16)
    p.note("%s: last %d bytes (offsets %d..%d), hex:" % (label, len(data) - start, start, len(data) - 1))
    p.note("  " + " ".join("%02x" % b for b in data[start:]))
    return data


def guard(p):
    pairs = (("a", "1"), ("b", "2"), ("c", "3"))
    base = p.base(pairs)
    p.step("tail of the file")
    data = tail_hex(p, "after 3 puts")
    p.expect("last byte", data[-1:], b"\x00")
    p.note("the final 00 is the EOF guard: 1 byte after the last complete frame, outside every frame and CRC")
    full = len(data)
    p.step("damage (no crash): truncate -s -1 $DB")
    os.truncate(p.db, full - 1)
    p.note("size %d -> %d" % (full, p.size()))
    p.step("check (read-only)")
    p.expect("check", p.check(), "OK")
    p.step("open (recovery)")
    p.open()
    data = tail_hex(p, "after open")
    p.expect("last byte after open", data[-1:], b"\x00")
    p.expect("size after open", len(data), full)
    p.note("guard restored; nothing else changed")
    p.step("keys after recovery")
    p.expect("dump", p.dump(), base)
    print("PASS: one byte cut removed only the guard; no acknowledged record lost")
    p.step("damage again: truncate -s -2 $DB (the guard and the last byte of frame c)")
    os.truncate(p.db, full - 2)
    p.note("size %d -> %d" % (full, p.size()))
    p.ok("check", p.db)
    p.open()
    tail_hex(p, "after open")
    found = p.dump()
    p.expect("dump", found, {"a": "1", "b": "2"})
    p.expect("last byte after open", p.db.read_bytes()[-1:], b"\x00")
    return "a real torn frame is discarded, earlier data intact"


SCENARIOS = {
    "A1": ("before_write on put -> new key absent", a1),
    "A2": ("torn_write on put -> new key absent, torn tail cut", a2),
    "A3": ("after_write on put -> new key present (page cache survives SIGKILL)", a3),
    "A4": ("after_fsync on put -> new key present", a4),
    "A6": ("torn_write on del -> key keeps old value", a6),
    "A7": ("torn_write on a 1 MiB value -> absent", a7),
    "B1": ("torn_write on a 10-op batch -> none of the 10 visible", b1),
    "B5": ("batch 'put X / del X' -> absent; 'del X / put X 2' -> present, after SIGKILL", b5),
    "B6": ("torn_write on a 10,000-op batch -> none visible, recovery_ms printed", b6),
    "C1": ("recovery_mid_scan -> next open, same state", c1),
    "C2": ("recovery_before_truncate / recovery_after_truncate -> same state", c2),
    "C3": ("compact_before_rename / compact_mid_copy -> old data, .compact removed", c3),
    "C4": ("compact_after_rename -> data intact, no .compact", c4),
    "C6": ("close_mid -> committed data intact", c6),
    "E1": ("--max-bytes cap -> ERR DISKFULL, nothing written", e1),
    "F4": ("file truncated by 1 byte -> open succeeds, at most last record lost", f4),
    "GUARD": ("EOF guard live: 1-byte cut loses nothing, 2-byte cut loses only the last frame", guard),
}


def run(sid):
    desc, fn = SCENARIOS[sid]
    p = Proof(sid)
    print("=== %s: %s" % (sid, desc))
    print("DB=%s" % p.db)
    try:
        rule = fn(p)
    except Skipped as exc:
        print("SKIPPED: %s" % exc)
        return "SKIPPED"
    except Failed as exc:
        print("FAIL: %s" % exc)
        return "FAIL"
    print("PASS: %s" % rule)
    return "PASS"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Live crash proof through the public ./kvdb CLI.")
    parser.add_argument("id", nargs="?", help="scenario ID, e.g. A2")
    parser.add_argument("--list", action="store_true", help="list scenario IDs")
    parser.add_argument("--all", action="store_true", help="run every scenario and print a table")
    args = parser.parse_args(argv)
    if args.list:
        for sid, (desc, _) in SCENARIOS.items():
            print("%-5s %s" % (sid, desc))
        return 0
    if args.all:
        results = {}
        for sid in SCENARIOS:
            results[sid] = run(sid)
            print()
        print("ID | result")
        print("---|-------")
        for sid, result in results.items():
            print("%s | %s" % (sid, result))
        return 1 if "FAIL" in results.values() else 0
    if not args.id:
        parser.error("give a scenario ID, --list or --all")
    sid = args.id.upper()
    if sid not in SCENARIOS:
        parser.error("unknown scenario %s; see ./prove --list" % args.id)
    return 1 if run(sid) == "FAIL" else 0
