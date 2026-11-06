# Demo

This is the rehearsable demo with actual captured results. Run commands from the repository root in Ubuntu/WSL using the real engine. Source is on D:; databases and crash evidence are on Linux ext4 under ~/tmp_test.

Recorded on **2026-11-06 22:22:15–22:22:56 IST** (Asia/Kolkata), Python 3.12.3. Capture commit: 5c2ed535fafaed659d3c82a15fc372a3af273091. Implementation hashes matched the qualified sources in [FINAL_GATE_RERUN_REPORT.md](FINAL_GATE_RERUN_REPORT.md). Process IDs, temporary paths, recovery timings and torn-write prefix lengths vary between runs.

Small raw outputs and checksums: [docs/evidence/demo-2026-11-06](docs/evidence/demo-2026-11-06). Complete local evidence: /home/arsht/tmp_test/demo-evidence-f8om2wag. These are process-kill demonstrations; physical power-loss behaviour is outside this evidence.

## 15-minute run of show

| Time | What to demonstrate |
|---|---|
| 0-2 min | Build and explain the success-after-fsync promise |
| 2-5 min | Run the short torture rehearsal and point out PASS, errors and the awaiting-response metric |
| 5-10 min | Acknowledged puts/batch/delete, SIGKILL, reopen and compare data |
| 10-13 min | Deliberate torn batch, tail repair, and crash-here questions |
| 13-15 min | Guarantees, limitations and proposed TTL design |

Run longer workloads before the presentation; use their saved evidence when timing is tight.

## Build

~~~bash
cd "/mnt/d/ALT F4/AltF4"
unset KVDB_CRASH
make build
~~~

For a fresh clone on Linux storage, use the real repository URL and a new directory:

~~~bash
mkdir -p "$HOME/tmp_test"
CLEAN_CLONE_PARENT=$(mktemp -d "$HOME/tmp_test/kvdb-clean-XXXXXX")
git clone https://github.com/nikhilbajantri/AltF4.git "$CLEAN_CLONE_PARENT/AltF4"
cd "$CLEAN_CLONE_PARENT/AltF4"
make build
~~~

The captured output below came from the working checkout identified above. A new clean-clone/offline rehearsal is a separate release check; these instructions do not claim it was performed in this capture.

Captured output:

~~~text
python3 --version
Python 3.12.3
python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else \"Python 3.10+ required\")"
python3 -m compileall -q src torturelib
chmod +x kvdb torture
BUILD OK
~~~

## Torture commands

Create a fresh Linux directory. The /mnt/d check matches the Windows volume holding this machine's WSL disk; adapt it if that disk moves.

~~~bash
mkdir -p "$HOME/tmp_test"
DEMO_DIR=$(mktemp -d "$HOME/tmp_test/kvdb-demo-XXXXXX")
printf 'DEMO_DIR=%s\n' "$DEMO_DIR"
python3 -B ./torture --iterations 25 --seed 12345 --mode default \
  --compress-log --host-storage-dir /mnt/d --min-free-gib 20 \
  --data-dir "$DEMO_DIR/torture"
~~~

Captured final summary (full output: [torture.txt](docs/evidence/demo-2026-11-06/torture.txt)):

~~~text
SUMMARY PASS=25/25 TOOL_ERROR=0 FAIL=0 max_exit_wait_s=0.003 kills_awaiting_response=96.0% ACKs={'w1': 137, 'w2': 129} mix={'batch': 112, 'ERR': 7, 'shared': 22, 'max_batch': 10000, 'put': 146, 'del': 49} worlds={0: 25}
~~~

The saved compressed transcript independently contains **25 distinct passing rounds**, zero error records, and **30 SIGKILL events**. Some rounds deliberately tear a write in addition to the random kill. Awaiting a reply does not prove a disk write was executing at that instant. This short rehearsal supplements the earlier 7,000-round qualification.

### Longer pre-demo rehearsal

Seed 12345 is the recorded seed for this document. If the team changes it, record the selected number and the new outputs. These extended commands preserve main's 200-round rehearsal plan; this document's fresh capture was the 25-round default run above. Existing complete per-mode qualification is in FINAL_GATE_RERUN_REPORT.md.

~~~bash
for MODE in default compaction recovery-crash; do
  python3 -B ./torture --iterations 200 --seed 12345 --mode "$MODE" \
    --compress-log --host-storage-dir /mnt/d --min-free-gib 20 \
    --data-dir "$DEMO_DIR/extended-$MODE"
done
~~~

Explain the concurrent workload's awaiting-response percentage once; it is not proof of a write executing at kill time. Compaction and recovery-crash use targeted hooks, rather than the same random-delay workload.

## Manual kill session

Keep two Ubuntu terminals open in the repository root. The capture helper exercised this sequence with a real subprocess and checked each reply before advancing.

### Terminal 1: save data

Use the fresh DEMO_DIR above. This launcher prints the exact server PID before starting the real server. The terminal's main shell remains open after the kill.

~~~bash
bash -c 'echo "SERVER_PID=$$"; exec python3 -B -m src.serve "$1"' _ "$DEMO_DIR/demo.db"
~~~

After READY, type these requests. Wait for each reply; a batch receives one ACK after end.

~~~text
put w1-1 color blue
get w1-2 color
batch w1-3
put city Delhi
put status ready
end
put w1-4 obsolete temporary
del w1-5 obsolete
get w1-6 obsolete
~~~

Keep the server running after the final response. Actual recorded transcript: IN is input, OUT is stdout, and ACTION is the separately issued kill.

~~~text
OUT SERVER_PID=668
OUT READY keys=0 recovery_ms=2.969
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
ACTION kill -KILL 668
OBSERVED subprocess returncode=-9 (SIGKILL)
~~~

### Terminal 2: kill and reopen

Copy the current directory and PID from Terminal 1 when prompted. **Recorded PID 668 is historical; use your new server's PID.**

~~~bash
cd "/mnt/d/ALT F4/AltF4"
read -r -p 'Paste DEMO_DIR from Terminal 1: ' DEMO_DIR
read -r -p 'Paste SERVER_PID from Terminal 1: ' SERVER_PID
test "$SERVER_PID" -gt 1 && kill -KILL "$SERVER_PID"
python3 -B ./kvdb open "$DEMO_DIR/demo.db"
python3 -B ./kvdb check "$DEMO_DIR/demo.db"
python3 -B ./kvdb dump "$DEMO_DIR/demo.db"
python3 -B ./kvdb get "$DEMO_DIR/demo.db" obsolete
~~~

The capture confirmed exit -9 (SIGKILL) without sending quit. Actual reopen results:

~~~text
$ python3 -B ./kvdb open "$DEMO_DIR/demo.db"
keys=3 recovery_ms=0.113
$ python3 -B ./kvdb check "$DEMO_DIR/demo.db"
OK
$ python3 -B ./kvdb dump "$DEMO_DIR/demo.db"
city	Delhi
color	blue
status	ready
$ python3 -B ./kvdb get "$DEMO_DIR/demo.db" obsolete
NOTFOUND
~~~

Every acknowledged put and the two-key batch survived. The acknowledged deletion survived too: obsolete is absent. After recovery, check returns exactly OK.

## Deliberately interrupt a batch

Continue in Terminal 2 after the previous server has been killed. This named hook starts a new server and kills it after writing only a prefix of the requested batch. Its changes try to replace city and status together.

~~~bash
printf 'batch w2-1\nput city Mumbai\nput status broken\nend\n' | \
  KVDB_CRASH=torn_write:1 python3 -B -m src.serve "$DEMO_DIR/demo.db"
python3 -B ./kvdb check "$DEMO_DIR/demo.db"
~~~

Captured server output before the kill (there was no ACK w2-1; child exit was -9):

~~~text
READY keys=3 recovery_ms=0.104
~~~

The read-only check before recovery reported:

~~~text
OK torn-tail=5 bytes (open will truncate)
~~~

Now recover and inspect:

~~~bash
python3 -B ./kvdb open "$DEMO_DIR/demo.db"
python3 -B ./kvdb check "$DEMO_DIR/demo.db"
python3 -B ./kvdb dump "$DEMO_DIR/demo.db"
python3 -B ./kvdb get "$DEMO_DIR/demo.db" obsolete
~~~

Actual results:

~~~text
$ python3 -B ./kvdb open "$DEMO_DIR/demo.db"
keys=3 recovery_ms=1.563
$ python3 -B ./kvdb check "$DEMO_DIR/demo.db"
OK
$ python3 -B ./kvdb dump "$DEMO_DIR/demo.db"
city	Delhi
color	blue
status	ready
$ python3 -B ./kvdb get "$DEMO_DIR/demo.db" obsolete
NOTFOUND
~~~

Recovery removed the incomplete tail. Earlier city=Delhi and status=ready remain together; neither change from the interrupted batch is visible. The earlier deletion stays absent.

## Crash-here answers

| Judge's question | Answer to explain |
|---|---|
| Before a write starts? | Earlier saved state survives; the new operation is absent. |
| Halfway through a batch? | Recovery accepts complete CRC-checked frames. An incomplete batch frame is discarded as a whole. |
| After writing, before fsync? | A complete frame can survive a process kill through the OS cache. There is no ACK yet; this does not establish power-cut durability. |
| After fsync, before the engine returns or sends ACK? | The complete change survives even if the caller missed its reply. |
| During recovery's scan? | The scan reads the file; reopening can scan it again. |
| During tail truncation? | The next open rescans and repeats any repair to the valid stopping point, synchronizing the truncated file. |
| During compaction, before or after replacement? | Before replacement the original file remains authoritative; after replacement the complete compacted file is authoritative in the tested process-crash scenarios. |
| After compaction rename, before directory fsync? | The process-crash tests reopen the new compacted file. Directory synchronization is a separate requirement for power-loss durability. |
| During initialization or close? | Incomplete initialization is restarted and stale temporary files are removed; previously saved data survives an interrupted close. See the exact hook expectations in BREAKING.md. |
| When the size cap is reached? | A rejected batch changes nothing. Deletes use reserved space; compaction can reclaim dead data for later writes. |
| Saving and rollback both fail? | UNCERTAIN is reported, later mutations on that handle are blocked, and the caller reconciles state after reopening before retrying. |

Full hook table: [BREAKING.md](BREAKING.md). Qualification and limits: [FINAL_GATE_RERUN_REPORT.md](FINAL_GATE_RERUN_REPORT.md).

## TTL answer

TTL means a value expires after a specified duration. **Automatic expiry is not implemented in the current database API or format.** Values remain until deleted or overwritten.

If asked how to add it: persist an absolute expiry timestamp with each value so a restart does not restart its lifetime; define reads of expired values as missing; apply expiry consistently during recovery and compaction. We would need explicit clock/backward-time rules, a compatible format change, and crash tests around expiry, batches, restart and compaction. A proposed encoding can store absolute epoch milliseconds with 0 meaning never expires. Reads and dumps would hide expired keys, compaction would skip them, and recovery would replay saved expiry metadata without restarting timers. The torture oracle would need a controllable clock. This is a proposed extension, not an existing demonstrated feature.

## Repeat the capture automatically

~~~bash
python3 -B tools/record_demo_results.py
~~~

The helper creates a fresh directory and kills only the servers it starts. It checks source identity, expected replies, SIGKILL exits and complete recovered data. It prints DEMO_EVIDENCE only after every assertion passes. A partial or failed capture is not a successful demo: inspect its errors and retained evidence. Refresh this document's recorded examples after a new successful capture rather than inventing timings or replies.
