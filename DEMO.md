# Demo with current captured results

Captured 2026-11-07 01:48:08 IST through 2026-11-07 01:48:37 IST on this laptop, Python 3.12.3, Linux ext4. Capture base commit: d9d3c2811c01d3da66cd6723cfb8d545ecd676be, plus the qualified working tree. The exact current core source matches the successful two-seed qualification after documented CRLF/LF normalization. Raw source hashes remain preserved; portable verification uses the additional canonical hashes. [Current qualification](docs/GAP_FIX_REPORT.md). Recorded PIDs and paths are historical; use new ones when repeating.

## Fixed 15-minute schedule

| Minutes | Judge action |
|---|---|
| 0-1 | Build a clean local clone with make build, Wi-Fi off |
| 1-4 | 200 default rounds, judge-selected seed |
| 4-6 | Compaction and recovery-crash, judge-selected seeds/counts |
| 6-8 | Human batches and 5-10 manual kills, then check/dump |
| 8-12 | Three source-line crash questions |
| 12-15 | TTL design only, including a subtle clock/batch problem |

The automated capture below contains 25 rehearsal rounds and two controlled demonstrations. It does not claim to complete the judge's 200-round timed run or 5-10 human kills. Follow [the offline plan](OFFLINE_TEST_PLAN.md) for that rehearsal, without AI or internet during official judging.

## Build and short rehearsal

From the repository root in Ubuntu/WSL:

```bash
unset KVDB_CRASH
make build
./torture --iterations 25 --seed 12345 --mode default \
  --compress-log --host-storage-dir /mnt/d --min-free-gib 20
```

Actual build output:

```text
python3 --version
Python 3.12.3
python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else \"Python 3.10+ required\")"
python3 -m compileall -q src torturelib
chmod +x kvdb torture
BUILD OK
```

Actual 25-round summary:

```text
SUMMARY PASS=25/25 TOOL_ERROR=0 FAIL=0 max_exit_wait_s=0.007 kills_awaiting_response=88.0% ACKs={'w1': 129, 'w2': 116} mix={'batch': 107, 'ERR': 8, 'shared': 22, 'max_batch': 10000, 'put': 135, 'del': 42} worlds={0: 25}
```

## Manual two-terminal procedure

In terminal one, make a fresh Linux directory and print its path, then start a child that prints its real server PID:

```bash
mkdir -p "$HOME/tmp_test"
DEMO_DIR=$(mktemp -d "$HOME/tmp_test/kvdb-manual-XXXXXX")
printf '%s\n' "$DEMO_DIR"
bash -c 'echo "SERVER_PID=$$"; exec python3 -B -m src.serve "$1"' _ "$DEMO_DIR/demo.db"
```

Send the put/get/batch/delete commands shown in the captured transcript below. In terminal two, set DEMO_DIR to the newly printed path and SERVER_PID to the newly printed numeric PID, then run `kill -KILL "$SERVER_PID"`. Use only the server started for this rehearsal; do not copy a recorded PID. Run open/check/dump/get, compare the acknowledged data, restart and repeat 5-10 times with fresh changes. A missing ACK allows a whole operation to appear or disappear, never a partial batch.

Actual controlled transcript (IN/OUT/ACTION are labels from the capture tool):

```text
OUT SERVER_PID=107389
OUT READY keys=0 recovery_ms=15.051
IN  put w1-1 color blue
OUT ACK w1-1
IN  get w1-2 color
OUT VAL w1-2 blue
IN  batch w1-3
IN  put city Delhi
IN  put status ready
IN  end
OUT ACK w1-3
IN  put w1-4 obsolete temporary
OUT ACK w1-4
IN  del w1-5 obsolete
OUT ACK w1-5
IN  get w1-6 obsolete
OUT NOTFOUND w1-6
ACTION kill -KILL 107389
OBSERVED subprocess returncode=-9 (SIGKILL)
```

Actual reopen verification:

```text
$ python3 -B ./kvdb open "$DEMO_DIR/demo.db"
keys=3 recovery_ms=0.105
$ python3 -B ./kvdb check "$DEMO_DIR/demo.db"
OK
$ python3 -B ./kvdb dump "$DEMO_DIR/demo.db"
city	Delhi
color	blue
status	ready
$ python3 -B ./kvdb get "$DEMO_DIR/demo.db" obsolete
NOTFOUND
```

## Deliberately torn batch

The second controlled demonstration starts serve with KVDB_CRASH=torn_write:1 and sends a batch changing city and status together. The real child exits -9, without ACK for that batch. The recovered map must retain the earlier complete city/status values, with neither new value visible.

Actual check before repair:

```text
OK torn-tail=9 bytes (open will truncate)
```

Actual repair and verification:

```text
$ python3 -B ./kvdb open "$DEMO_DIR/demo.db"
keys=3 recovery_ms=13.356
$ python3 -B ./kvdb check "$DEMO_DIR/demo.db"
OK
$ python3 -B ./kvdb dump "$DEMO_DIR/demo.db"
city	Delhi
color	blue
status	ready
$ python3 -B ./kvdb get "$DEMO_DIR/demo.db" obsolete
NOTFOUND
```

## Crash-here answers

| Location | Disk and next open |
|---|---|
| Before append | Earlier frames plus guard; new operation absent |
| During frame write | Incomplete frame replaces old guard; drop entire tail, restore guard |
| Full frame before fsync | Full CRC-valid frame can survive; no ACK yet; not a power-cut claim |
| After fsync before return/ACK | Complete frame and guard durable; replay operation even without reply |
| Missing final guard byte | Full frames still valid; restore guard when cap permits; current writes reserve it |
| EOF guard questions (F4, torn write, why the file ends in 00) | docs/EOF_GUARD.md, demo with ./prove GUARD |
| During recovery scan/repair | Rebuild RAM index again and repeat any incomplete repair |
| Compaction before replacement | Old authoritative file survives; remove leftover temp |
| After replacement | Complete new file is authoritative; directory is synced before descriptor/index swap |
| Cap reached | Reject before append; optional compaction can change file bytes without applying the rejected operation |
| Saving and rollback both fail | UNCERTAIN, no success promise; handle poisoned; reopen and reconcile |
| B2 without a trailing commit marker | This design commits a complete CRC-prefixed frame; no separate absent-marker state exists. Explain the equivalent incomplete-frame case |

Use [the exact 32-row proof](ARCHITECTURE.md) and [14 exact functions](BREAKING.md). In the proof table's Verified-by column, add `./prove <ID>` for every row it covers (A1 A2 A3 A4 A6 A7 B1 B5 B6 C1 C2 C3 C4 C6 E1 F4; `./prove --list`), so a judge can rerun that row live in a few seconds. Every member should explain disk bytes and the next recovery action, not merely say the tests passed.

## TTL design extension (not implemented)

Persist an absolute expiry time with each latest value, using a versioned/compatible format change (for example a 64-bit epoch timestamp, with zero meaning no expiry). Recovery must replay expiry metadata without restarting timers. Reads hide expired latest values; compaction excludes them. An expired overwrite must still suppress an older value: simply skipping that record during replay can resurrect the old value. Define a clock-backward policy and evaluate batch expiry consistently under the lock; a controlled-clock oracle must test restart, overwrite, delete, expiry and compaction. This is a design answer, not an existing feature.

## Repeat capture

```bash
python3 -B tools/record_demo_results.py --qualification-manifest docs/gap_fixes_gate_manifest.json
```

The helper checks source identity against successful qualification, starts/kills only its own servers, validates responses and compares full recovered data. It reports success only after all assertions pass. New timings/PIDs can differ. Small raw outputs and checksums are in [docs/evidence/gap-demo-2026-11-07](docs/evidence/gap-demo-2026-11-07); full local capture: /home/arsht/tmp_test/demo-evidence-6ee339u0.
