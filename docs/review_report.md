# Review report: serve, torture, crash testing

Reviewed commit: `d259b98` (main, "Merge pull request #2 from nikhilbajantri/feat-arsh").
Date: 2026-11-06. Reviewer: Nikhil (with Claude Code).
Machine: Arch Linux, kernel 7.2, Python 3.14.8. All databases were on ext4 (`/dev/nvme0n1p3`, `/home`), under `~/tmp_test/` and `~/tmp_test/torture_data/`. Nothing ran under `/tmp`.
No source files were changed. The planted bugs lived only on the throwaway branch `planted-bugs`, which was deleted afterwards, and main's `git status` was clean.

## Summary

| Area | Status | Blocker? |
|---|---|---|
| Build + unit tests (92) | PASS | no |
| Serve (`src/serve.py`) | PASS except garbage input: one non-UTF-8 byte crashes serve (R-01) | no |
| CLI (`./kvdb`) | MISSING: every subcommand prints "not implemented yet" (R-02) | **yes**: the demo, `check`/`dump`, and the torture contract all need it |
| Torture, default mode | PASS 200/200 with a fresh seed; deterministic | no |
| Torture modes | MISSING: only `default` exists; 6 of 7 modes are absent (R-03) | **yes** |
| Torture detection power | PARTIAL: caught planted bugs a and c at iteration 1, missed bug b (skipped torn-tail truncate) in 50/50 iterations (R-04) | **yes**: "prove it" needs bug b caught |
| Torture workload coverage | PARTIAL: at most 10 of 100 planned ops reached, batches of at most 5 ops, no shared keys, no ERR ops (R-07) | no, but it weakens every PASS |
| Manual crash checks (kill -9, F4 truncate) | PASS, using the fallbacks because the CLI is a stub | no |
| 1M-key recovery benchmark | PASS: 830 ms (only runs with `-m`, R-08) | no |

## Unit tests

- `make build`: BUILD OK.
- `python3 -m unittest -q`: **Ran 92 tests in 19.609s, OK**. 92 passed, 0 failed, 0 errors.
- Files changed since `d166261`: `BREAKING.md`, `BUGS.md`, `CRASH_TEST_REPORT.md` (new), `README.md`, `src/engine.py` (the zero-progress `pwrite` guard, +2 lines), `src/serve.py`, `tests/test_crash_campaign.py` (new), `tests/test_serve.py` (new), `tests/test_torture.py` (new), `torture`, `torturelib/crash_probe.py` (new), `torturelib/oracle.py`, `torturelib/runner.py`, `torturelib/workload.py`. In total: 14 files, +1304 / -21 lines.
- `src/cli.py` and `src/inspect_cmd.py` are still the M0 stubs.

## Serve review (`src/serve.py`)

| Check | Result | Evidence |
|---|---|---|
| READY printed after recovery, before reading input | PASS | `KVDB(...)` (which runs recovery) at serve.py:180; `READY keys=%d recovery_ms=%.3f` at serve.py:136-138; the input loop starts at serve.py:139-140 |
| ACK only after the engine call returned | PASS | engine calls at serve.py:81 `db.batch(ops)`, :83 `db.put(...)`, :85 `db.delete(...)`, :87 `db.compact()`; then :96-98 `from src import crash` / `crash.point("after_return")` / `reply("ACK " + op_id)`. An exception skips the ACK and goes to the ERR handlers at :99-108 |
| stdout flushed after every reply | PASS | serve.py:70-72 `with output_lock: print(message, file=output_stream, flush=True)` |
| `after_return` crash point between engine return and ACK | PASS | serve.py:97 |
| One worker thread per writer prefix | PASS | serve.py:124 `prefix = op_id.split("-", 1)[0]`; :125-132 one `threading.Thread` and `Queue` per prefix (capped at 64 writers, :126) |
| Replies for different writers can interleave; stdout under a lock | PASS | each worker calls `reply()` separately; the lock is at serve.py:67 and :71. Observed interleaving in the manual run (`ERR e-1` printed before `ACK c-1`) |
| put / del / get / batch...end / compact / quit | PASS | put :82, del :84, get :88-92 (`VAL`/`NOTFOUND`), batch :146-147 plus `read_batch` :35-60, compact :86, quit :142 (drains queued work, :153-159) |
| `hex:` decoding | PASS | serve.py:18-19 decodes input; :23-32 hex-encodes `VAL` output when a value is not printable |
| ERR DISKFULL / INVALID / POISONED | PASS, with extras | :99-104. It also emits `ERR <id> IO` (:105-106), `UNSUPPORTED` (:107-108) and `INTERNAL` (:120), none of which the README lists (R-05) |
| Garbage input never crashes serve | **FAIL** | text garbage, a missing id, bad `hex:`, an empty key, and a batch missing `end` all give `ERR ... INVALID`. **A non-UTF-8 byte kills serve**: `UnicodeDecodeError` from `for line in lines` (serve.py:140), traceback, exit 1 (R-01) |
| Uses the real engine | PASS | serve.py:178 `from src.engine import KVDB`; the fake is used only with `--fake` (:171-172). The torture runner launches serve without `--fake` (runner.py:56) |

Further observation (R-11): `dispatch` blocks the single input thread when one writer's queue (maxsize 64, serve.py:129, :133) is full. A writer that sends without waiting can therefore stall every other writer. Stop-and-wait clients never hit this.

## Torture review (`./torture`, `torturelib/`)

The PRD is not in the repository. TT-01..TT-15 below are the 15 checks from the review request, numbered in order; they are not taken from a PRD.

| ID | Requirement | Result | Evidence |
|---|---|---|---|
| TT-01 | Kill with SIGKILL, never SIGTERM | PASS | runner.py:134 `proc.kill()`; :149 requires `returncode == -SIGKILL`. No SIGTERM anywhere |
| TT-02 | Kill delay: random ms from the seeded RNG, not "after N ops" | PASS | runner.py:48 `random.Random("kill:%s:%s" % (seed, number)).uniform(.002, .025)`; :127 `time.sleep(delay)`. The 2-25 ms window is narrow (R-07) |
| TT-03 | Two concurrent writers | PASS | runner.py:38 (`w1`, `w2`), :113 one thread each |
| TT-04 | Stop-and-wait, at most one op in flight per writer | PASS | runner.py:99-110 waits for its own reply before sending more; oracle.py:29-30 rejects more than one pending op |
| TT-05 | Batches of 2..10,000 ops | **FAIL** | workload.py:12 `rng.randint(2, 5)`: the largest batch is 5 ops (confirmed: max batch size 5 in 2,313 sent ops) |
| TT-06 | Oracle independent: no `src/` imports, records SENT/ACK/ERR itself, only reads `./kvdb dump` | PARTIAL | runner.py, oracle.py and workload.py import only the standard library plus `torturelib`. SENT is recorded at runner.py:87-91 and ACK/ERR at :64-75. But the state is read by `torturelib/crash_probe.py`, which imports `src.engine` and `src.scan` (crash_probe.py:8-9), not by `./kvdb dump` (the CLI is a stub) |
| TT-07 | After each kill: open, check (must be OK), dump, compare | PASS (via adapter) | crash_probe.py:12-26: open+close, `check_file` must return exactly `OK`, reopen, dump; runner.py:155-165 compares |
| TT-08 | Possible worlds: own keys exactly match one world | PASS | oracle.py:17-54 builds up to 4 worlds and requires exact dict equality (`actual == expected`, :51) |
| TT-09 | Shared-key rule; ERR ops must be absent | **FAIL / MISSING** | oracle.py:41-42 rejects shared keys outright ("requires disjoint writer keys"). runner.py:153-154 treats any ERR as a test failure, so the "ERR op is absent after recovery" rule is never exercised |
| TT-10 | Self-describing values checked byte for byte | PASS | workload.py:18-20: value = `seed:iteration:op_id:item:` + SHA-256 filler x N; compared byte for byte through dict equality |
| TT-11 | `--seed` and `--iterations` work; same seed gives the same op stream | PASS | runner.py:174-175; workload.py:7 seeds per (seed, iteration, writer). Verified: two runs of seed 552777022 had 2,313 SENT ops in common with 0 mismatches and identical kill delays |
| TT-12 | Modes: default, large-values, large-batch, recovery-crash, compaction, disk-full, crashpoints | **FAIL** | runner.py:176 `choices=["default"]`. Present: default. Missing: large-values, large-batch, recovery-crash, compaction, disk-full, crashpoints |
| TT-13 | Per-iteration line (delay, in-flight, world, PASS/FAIL); summary with pass count and % kills with ops in flight | PASS | runner.py:205-206 and :207-209. The in-flight % is 100% by construction, because a stop-and-wait writer always has one op outstanding, so it says little |
| TT-14 | First FAIL stops and prints seed, iteration, expected vs found, op ids; tool errors print TOOL ERROR without crashing | PARTIAL | runner.py:192-196 stops on the first FAIL with seed and iteration. The FAIL line dumps every world and value in full (thousands of characters), with no diff and no op ids (R-06). runner.py:197-199 prints TOOL ERROR for ToolError/OSError/Timeout, but a `ValueError` from oracle.py:28-30/:42 is not caught and crashes with a traceback (R-09) |
| TT-15 | Database path on ext4, not /tmp | PASS | runner.py:177 defaults to `~/tmp_test/torture_data`; `df -T` shows ext4. There is no guard against `--data-dir /tmp` |

## Torture runs

Fresh seeds came from `secrets.randbelow(10**9)` and are saved in `~/tmp_test/review_seeds.txt`. Logs are in `~/tmp_test/review/`.

| Mode | Seed | Iterations | Result | Run time | Kills with ops in flight | Notes |
|---|---|---|---|---|---|---|
| default | 552777022 | 200 | **PASS 200/200** | 32.2 s (timed on the same-seed re-run) | 100.0% | ACKs w1=1054, w2=950; mix put 1475 / batch 562 / del 339; worlds {0: 17, 1: 106, 2: 77}. Re-run of the same seed: 200/200 PASS |
| large-values | 77173339 | 100 | MISSING | - | - | `argument --mode: invalid choice: 'large-values' (choose from 'default')`, exit 2 |
| large-batch | 972750935 | 50 | MISSING | - | - | same argparse error |
| compaction | 978142283 | 100 | MISSING | - | - | same argparse error |
| recovery-crash | 132829190 | 100 | MISSING | - | - | same argparse error |
| disk-full | 281923561 | 100 | MISSING | - | - | same argparse error |
| crashpoints | 664061492 | 100 | MISSING | - | - | same argparse error |

No run failed, so nothing needed a reproduction re-run. Coverage note: no iteration got past op index 10 of the 100 planned per writer, so every database stayed a few KB. Auto-compaction, large files, and late-stream ops are never exercised (R-07).

## Manual checks

All of these ran in `~/tmp_test/review/manual` (ext4).

**CLI**

```
$ ./kvdb serve m.db      -> not implemented yet   (rc=1)
$ ./kvdb check m.db      -> not implemented yet   (rc=1)
```

**Serve, a 3-op batch typed in, then kill -9.** I fed serve through a FIFO and used `python3 -m src.serve` because `./kvdb serve` is a stub.

```
put w1-1 seed before
batch w1-2
put a 1
put b 2
del seed
end
--- serve output
READY keys=0 recovery_ms=4.933
ACK w1-1
ACK w1-2
$ kill -9 35884          -> serve exit=137 (SIGKILL)
$ ./kvdb check k.db      -> not implemented yet (rc=1)
$ ./kvdb dump k.db       -> not implemented yet (rc=1)
$ python3 -m torturelib.crash_probe k.db    (fallback: open + check + dump)
check: OK
a	1
b	2
```

Result: PASS. The acknowledged batch is fully present (`seed` deleted, `a` and `b` present).

**F4: truncate by 1 byte**

```
size before: 94
$ truncate -s -1 k.db                  -> size 93
check_file before open:  (True, 'OK torn-tail=44 bytes (open will truncate)')
KVDB open:               keys=1 recovery_ms=3.115
dump:                    [(b'seed', b'before')]
size after open:         49
check_file after open:   (True, 'OK')
```

Result: PASS. The torn batch frame (44 bytes) was dropped, the earlier `put` survived, and the file was truncated back to the end of the last valid frame.

**Garbage input to serve**

```
input: hello / (empty) / put / put a-1 k / put a-2 hex:zz v / get a-3 / batch b-1 + put x 1 + end /
       batch + end / put c-1 k v / get c-2 k / compact d-1 / put e-1 hex: hex: / quit
output: READY ..., ERR - INVALID x4, ERR a-1 INVALID, ERR a-2 INVALID, ERR a-3 INVALID,
        ACK b-1, ERR e-1 INVALID, ACK c-1, ACK d-1, VAL c-2 v       rc=0   (PASS)
input: printf 'put a-1 k \xff\xfe\n...'
output: READY ..., then Traceback ... UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff   rc=1   (FAIL, R-01)
input: batch z-1 / put k v / <EOF, no end>
output: READY ..., ERR z-1 INVALID   rc=0   (PASS)
```

**1M-key recovery benchmark**

```
$ python3 tests/bench_recovery.py
ModuleNotFoundError: No module named 'src'          (R-08)
$ python3 -m tests.bench_recovery
puts:    keys=1000000 file_bytes=37001616 write_s=2.04 recovery_ms=830.4
compact: delete_s=1.27 size_before=54003216 size_after=16 compact_ms=7.8
```

## Planted bugs

All on the throwaway branch `planted-bugs`, one bug at a time, each reverted with `git checkout -- <file>` before the next. Command for each: `./torture --iterations 50 --seed 12345`.

| Bug | Change | Caught? | Iteration |
|---|---|---|---|
| a) ACK before the engine call | serve: `reply("ACK ...")` moved before `db.put/delete/batch/compact` | **YES** | 1 |
| b) Skip the torn-tail ftruncate | engine `_recover`: `os.ftruncate` + `os.fsync` replaced by `pass` | **NO**: 50/50 PASS in 10 s | - |
| c) Encode only the first op of a batch | engine `_commit`: `fmt.encode_frame(ops[:1])` | **YES** | 1 |

**a)** `FAIL seed=12345 iteration=1: expected worlds=[...4 worlds...]; found={...5 keys...}`. The raw line is several KB of values. The diff below comes from my parsing; the tool doesn't print it.
- Closest world (0): `missing=[b'w1/1']`.
- `w1/1` was written by op `w1-2`, which got an `ACK`, so an acknowledged write was lost.
- Kill at 5.534 ms; in flight: `w2-2`, `w1-3`.

**b)** `SUMMARY PASS=50/50 kills_awaiting_response=100.0% ACKs={'w1': 198, 'w2': 170}`. Not caught, for this reason:
- A SIGKILL can't interrupt a `pwrite` system call partway through, so random kills never leave a torn tail.
- With no torn tail, recovery never reaches the truncate, so skipping it is invisible.
- The probe's strict `check == "OK"` rule (crash_probe.py:16) would catch it, but only if a torn tail existed.
- Catching it needs the `torn_write` crash point (a `crashpoints` mode) or deliberately torn fixtures (R-04).

**c)** `FAIL seed=12345 iteration=1`. Closest world (1): `missing=[b'w2/1', b'w2/4', b'w2/6']`. Op `w2-0` was the ACKed batch `[del w2/4, del w2/3, put w2/6, put w2/1, put w2/4]`, and only its first op reached disk.

Cleanup: `git checkout main && git branch -D planted-bugs` gave "Deleted branch planted-bugs (was d259b98)". Then `git status` showed `nothing to commit, working tree clean`.

## Bugs found

| # | Severity | Summary | Owner |
|---|---|---|---|
| R-01 | Medium | serve crashes (traceback, exit 1) on any non-UTF-8 input byte | Arsh |
| R-02 | **Blocker** | `./kvdb` CLI is a stub: no open/put/get/del/batch/dump/check/serve/inspect/compact | Srushti |
| R-03 | **Blocker** | torture has only `default` mode; 6 of the 7 README modes are missing | Arsh |
| R-04 | **Blocker** | torture misses planted bug b (no torn-tail truncate): random SIGKILL never produces torn tails | Arsh |
| R-05 | Low | serve emits ERR reasons that are not in the README contract: `IO`, `UNSUPPORTED`, `INTERNAL` | Arsh |
| R-06 | Low | torture FAIL line dumps every world and value in full, with no diff or op ids | Arsh |
| R-07 | Medium | workload coverage: 2-25 ms kill window (at most op 10 of 100 reached), batches of at most 5, no shared keys, no ERR ops, databases only a few KB; the in-flight % is 100% by construction | Arsh |
| R-08 | Low | `python3 tests/bench_recovery.py` fails with ModuleNotFoundError; only `python3 -m tests.bench_recovery` works | Nikhil |
| R-09 | Low | a `ValueError` from oracle.worlds (e.g. two pending ops, or a shared key) is not caught: traceback instead of TOOL ERROR | Arsh |
| R-10 | Low | BUGS.md: a blank line separates the header from the ARSH-001/002 rows, so they don't render as a table | Varsha |
| R-11 | Low | serve: a full per-writer queue (maxsize 64) blocks the single input thread, so one writer can stall all writers | Arsh |

## Missing features

- **`./kvdb` CLI:** every subcommand (R-02). `src/inspect_cmd.py` is also still a stub. `src/scan.py` already provides `iter_frames` and `check_file` for it.
- **Torture modes:** large-values, large-batch, recovery-crash, compaction, disk-full, crashpoints (R-03).
- **Torture oracle:** the shared-key rule, the "ERR op absent" rule, and repeated crashes on one database.
- **Torture reading state through `./kvdb`:** it still uses the `crash_probe` adapter, which imports the engine directly.
- **Release qualification:** a seven-mode, 500-iteration run.
- **Docs:** the ARCHITECTURE.md proof table is still empty, and the BREAKING.md crash-point table still says "Not run" even though CRASH_TEST_REPORT.md records those points as run.

## Recommended next actions (priority order)

1. **Srushti:** implement `./kvdb` (open/put/get/del/batch/dump/check/serve/inspect/compact) on top of `src.engine` and `src.scan`. This unblocks the demo and the torture contract (R-02).
2. **Arsh:** add a `crashpoints` torture mode that runs serve with `KVDB_CRASH=<point>:<n>` across all named points, including `torn_write`, so that planted bug b is caught. Re-run the planted-bug check (R-04).
3. **Arsh:** add the remaining modes: large-values (up to 1 MiB), large-batch (up to 10,000 ops), recovery-crash (kill during open), compaction, disk-full (`--max-bytes`, where ERR ops must be absent) (R-03, TT-09).
4. **Arsh:** fix the non-UTF-8 crash in serve. Read stdin as bytes, or use `errors="surrogateescape"`, and answer `ERR <id> INVALID` (R-01).
5. **Arsh:** widen the workload. Use a wider or log-uniform kill window so later ops and bigger files are reached, add shared keys with the ordering rule, and allow several crashes per database (R-07).
6. **Arsh:** switch the oracle's state read to `./kvdb check` + `./kvdb dump` once the CLI lands, and drop the engine import in `crash_probe` (TT-06).
7. **Arsh:** improve the FAIL output: per-world missing/extra/wrong keys plus the op ids behind them. Catch oracle `ValueError` as TOOL ERROR (R-06, R-09).
8. **Arsh + Varsha:** decide whether `IO`/`UNSUPPORTED`/`INTERNAL` become part of the README ERR contract or get mapped onto the frozen reasons (R-05).
9. **Nikhil:** make `tests/bench_recovery.py` and `tests/bench_compact.py` runnable as plain scripts, or document only the `-m` form. Add the compaction lock pause (about 2.5 s at 1M keys) to BREAKING.md "Known weaknesses" (R-08).
10. **Varsha:** fix the BUGS.md table (R-10). Fill the ARCHITECTURE.md proof table and the BREAKING.md crash-point results from CRASH_TEST_REPORT.md and this report.
