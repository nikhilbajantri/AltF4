# Manual testing commands: setup to final acceptance

This is the readable command guide for Arsh's 7 November 2026 rehearsal. [Actual results and timing limits](../MANUAL_TEST_REPORT.md) are separate from expected outputs. The [original Terminal A paste](evidence/manual-testing-2026-11-07/terminal-session.txt) is preserved unchanged. Its targeted-mode command display has duplicated/mangled characters; the equivalent valid command is written cleanly below, with seeds/counts verified against the saved logs. This guide is not a verbatim AI prompt log.

## Before starting: which terminal?

Use two Ubuntu/WSL terminals in VS Code, called **Terminal A** and **Terminal B**. Keep Terminal A open throughout: it remembers `$PRACTICE_DIR`, `$DB` and `$LAB`. Run one test at a time so they do not compete for disk/CPU time.

- Terminal A: all setup, shell test commands, starting the server, typing database requests and checking recovery.
- Terminal B: only the `read` and `kill` commands when asked to kill the practice server.
- A prompt like `arsht@...:...$` means Ubuntu is accepting shell commands.
- After `READY ...`, the running database accepts requests such as `put`, `batch` and `end`. Do not type shell commands into it.
- If that server is still running, type `quit` and wait for the Ubuntu prompt. Do not type `quit` at the Ubuntu prompt. If already at that prompt, start below.

If a new VS Code terminal is PowerShell, this optional entry command opens Ubuntu (it was not part of the pasted Terminal A session):

```powershell
wsl -d Ubuntu-24.04
```

The commands below are Bash commands. Test databases stay on Linux storage under `~/tmp_test`. Code is first read from D:, then tested from a fresh Linux clone. These commands create new practice directories rather than overwriting previous evidence.

## 1. Build the original working copy — Terminal A

```bash
cd "/mnt/d/ALT F4/AltF4"
unset KVDB_CRASH
make build
```

Purpose: enter the repository, clear any old crash-injection setting, and check/build using the README command. Expected last line: `BUILD OK`. The initial build was not timed.

`make build` prints and runs these child commands; you do not need to type them separately:

```bash
python3 --version
python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else \"Python 3.10+ required\")"
python3 -m compileall -q src torturelib
chmod +x kvdb torture
```

They check Python 3.10+, compile Python modules to catch syntax errors, and make the two launchers executable. This run used Python 3.12.3.

## 2. Create a practice location — Terminal A

```bash
mkdir -p "$HOME/tmp_test"
PRACTICE_DIR=$(mktemp -d "$HOME/tmp_test/arsh-manual-XXXXXX")
DB="$PRACTICE_DIR/practice.db"
echo "$DB"
```

`mkdir -p` creates the parent if needed; `mktemp -d` creates a unique directory; `DB` remembers the file path; `echo` displays it. The suffix changes on every rehearsal. The recorded location was `/home/arsht/tmp_test/arsh-manual-XwvXdf/practice.db`.

## 3. Create, save and read — Terminal A

```bash
python3 ./kvdb open "$DB"
python3 ./kvdb put "$DB" name Arsh
python3 ./kvdb get "$DB" name
```

Expected:

```text
keys=0 recovery_ms=<number>
OK
Arsh
```

Purpose: check file creation, a successful saved write and a later read. These are separate processes, so the value must persist between commands. Recorded initial recovery: 2.752 ms.

## 4. Update the same key — Terminal A

```bash
python3 ./kvdb put "$DB" name Arsh_updated
python3 ./kvdb get "$DB" name
```

Expected: `OK`, then `Arsh_updated`. Purpose: the latest successful value replaces the old value.

## 5. Delete and check absence — Terminal A

```bash
python3 ./kvdb del "$DB" name
python3 ./kvdb get "$DB" name
```

Expected: `OK`, then `NOTFOUND`. Purpose: successful deletion survives reopening; an old value must not reappear.

## 6. Start the server, save a batch, and kill it

In **Terminal A**:

```bash
bash -c 'echo "SERVER_PID=$$"; exec python3 -B -m src.serve "$1"' _ "$DB"
```

The child Bash prints its process ID, then `exec` replaces it with the server, keeping that PID. `-B` avoids writing Python bytecode files. Expected:

```text
SERVER_PID=<current number>
READY keys=0 recovery_ms=<number>
```

Terminal A is now the database input. Type the following request and wait for `ACK w1-1`:

```text
put w1-1 name Arsh
```

Then type:

```text
batch w1-2
put city Delhi
put status learning
end
```

Wait for `ACK w1-2`. `w1-1` and `w1-2` are operation IDs; the `w1` prefix identifies the writer. `end` submits the complete batch. ACK is the database's durability promise.

In **Terminal B**:

```bash
read -r -p "Paste SERVER_PID from Terminal A: " TEST_PID
```

Paste **only the number currently shown after `SERVER_PID=` in Terminal A**, then press Enter. Do not copy any historical PID from the evidence. Now run:

```bash
kill -KILL "$TEST_PID"
```

Purpose: force the practice process to die without graceful cleanup. The variable is local to Terminal B; that terminal does not need `$DB` or `$LAB`. Terminal A returns to its Ubuntu prompt, usually printing `Killed`.

Evidence distinction: Terminal B's commands are the instructed procedure and are included for reproducibility; its actual terminal output was not supplied. Terminal A records the ACKs, `Killed`, and subsequent recovery.

Back in **Terminal A**:

```bash
python3 ./kvdb open "$DB"
python3 ./kvdb check "$DB"
python3 ./kvdb dump "$DB"
```

Expected:

```text
keys=3 recovery_ms=<number>
OK
city    Delhi
name    Arsh
status  learning
```

`open` recovers; `check` inspects integrity without repairing; `dump` lists the complete visible contents sorted by key. Actual dump uses tabs. Recorded recovery: 0.204 ms. All acknowledged data survived.

## 7. Deliberately interrupt an unfinished batch — Terminal A

At the Ubuntu prompt:

```bash
KVDB_CRASH=torn_write:1 python3 -B -m src.serve "$DB"
```

This environment setting applies only to this command. The first frame write is deliberately cut short and the child kills itself. After `READY`, type:

```text
batch w1-3
put city Mumbai
put status finished
end
```

Expected: `Killed` with no `ACK w1-3`. Terminal B is not used for this injected crash.

At the returned Ubuntu prompt:

```bash
python3 ./kvdb check "$DB"
```

Expected: `OK torn-tail=<number> bytes (open will truncate)`. Actual: 52 bytes. This is a detected repairable incomplete ending, not proof of completed repair.

Now run:

```bash
python3 ./kvdb open "$DB"
python3 ./kvdb check "$DB"
python3 ./kvdb dump "$DB"
```

Expected: three keys, `OK`, and the earlier `Delhi / Arsh / learning` contents. Recorded recovery: 14.206 ms. Neither new batch value appeared. Purpose: a partial frame must not expose a partial batch.

## 8. Remove exactly one final byte — Terminal A

With the server stopped and `$DB` still pointing at the practice file:

```bash
truncate -s -1 "$DB"
python3 ./kvdb open "$DB"
python3 ./kvdb check "$DB"
python3 ./kvdb dump "$DB"
```

`truncate -s -1` removes one byte from this file. Use only the practice database. Expected: the same three keys and `OK`. Recorded recovery: 2.635 ms.

Purpose: verify the F4 tail-loss fix. The current writer places one expendable guard byte after complete records; removing it does not remove acknowledged payload. Recovery restores it. This is not an arbitrary-corruption test.

### The harmless `quit` mistake in the transcript

Arsh typed `quit` after already returning to Ubuntu and saw `Command 'quit' not found`. No database failure occurred. Ubuntu's suggestion `sudo snap install quit` was output, not a recorded installation command, and is unnecessary. Continue at the existing shell prompt.

## 9. Set up the timed clean-clone rehearsal — Terminal A

```bash
mkdir -p "$HOME/tmp_test"
LAB=$(mktemp -d "$HOME/tmp_test/arsh-judging-XXXXXX")
mkdir -p "$LAB/evidence"

unset KVDB_CRASH
set -o pipefail
TIMEFORMAT='Elapsed: %3R seconds'
```

`LAB` remembers a new rehearsal directory. `pipefail` makes a future pipeline report an upstream failure rather than hiding it behind a successful logger. `TIMEFORMAT` controls Bash's `time` display. These setup steps were outside the measured build block.

```bash
time (
  git clone --no-hardlinks "/mnt/d/ALT F4/AltF4" "$LAB/AltF4" &&
  cd "$LAB/AltF4" &&
  make build
)
```

Purpose: prove the committed repository builds from a fresh local clone. `--no-hardlinks` avoids sharing Git object files by hard links; `&&` stops this chain if an earlier command fails. Parentheses run the block in a subshell, so enter the clone afterward:

```bash
cd "$LAB/AltF4"
git rev-parse --short HEAD
```

Actual: `BUILD OK`, **2.559 seconds** for clone plus build, and commit `f1a1c0c`. Judge build slot: **60 seconds**. Future commits/times can differ. Uncommitted working-copy files are not included in a Git clone.

## 10. Run 200 random crash rounds — Terminal A

```bash
time ./torture \
  --iterations 200 \
  --seed 84217 \
  --mode default \
  --compress-log \
  --data-dir "$LAB/evidence/default" \
  --host-storage-dir /mnt/c \
  --host-storage-dir /mnt/d \
  --min-free-gib 20
```

Expected summary: `PASS=200/200 TOOL_ERROR=0 FAIL=0`. Actual time: **103.159 seconds**. Judge slot: **180 seconds**.

Purpose: concurrent writers issue puts/deletes/batches while the tool kills the server after random delays. The tool's independent sent/ACK history checks the complete recovered map. An unacknowledged operation may survive or disappear; acknowledged history and batch atomicity must remain valid.

| Option | Meaning |
|---|---|
| `--iterations` | Number of crash/recovery rounds |
| `--seed` | Random workload seed; judges may choose another. OS scheduling can still differ |
| `--mode` | Which crash workload to exercise |
| `--compress-log` | Preserve the oracle transcript in compressed form |
| `--data-dir` | Keep each workload's evidence separate |
| `--host-storage-dir` | Also check the Windows volumes, not only free space inside WSL |
| `--min-free-gib 20` | Stop if a checked volume falls below the reserve |

## 11. Compaction and recovery-crash — Terminal A

```bash
time (
  ./torture \
    --iterations 100 --seed 84218 --mode compaction \
    --compress-log \
    --data-dir "$LAB/evidence/compaction" \
    --host-storage-dir /mnt/c --host-storage-dir /mnt/d \
    --min-free-gib 20 &&
  ./torture \
    --iterations 100 --seed 84219 --mode recovery-crash \
    --compress-log \
    --data-dir "$LAB/evidence/recovery" \
    --host-storage-dir /mnt/c --host-storage-dir /mnt/d \
    --min-free-gib 20
)
```

Expected: two `PASS=100/100 TOOL_ERROR=0 FAIL=0` summaries. Actual combined time: **37.069 seconds**. Judge targeted-mode slot: **120 seconds**. The PDF does not specify round counts for this slot; 100 each is this rehearsal's choice, not a claimed judge mandate.

Purpose: compaction kills test safe file replacement; recovery-crash tests repeated death during scan and torn-tail repair. Targeted hooks report zero random delay because they kill at named locations. Zero `awaiting_response` in recovery mode does not mean no crashes occurred.

## 12. Judge-format manual batch and kill

In **Terminal A**, at the shell:

```bash
DB="$LAB/manual.db"
bash -c 'echo "SERVER_PID=$$"; exec python3 -B -m src.serve "$1"' _ "$DB"
```

This changes `$DB` to the new rehearsal file. After `READY`, type:

```text
batch w1-1
put round 1
put status saved
end
```

Wait for `ACK w1-1`. In **Terminal B**:

```bash
read -r -p "Paste the current SERVER_PID: " TEST_PID
kill -KILL "$TEST_PID"
```

Enter the current numeric PID at the first command's prompt before running the second. In **Terminal A**, after `Killed`:

```bash
python3 ./kvdb open "$DB"
python3 ./kvdb check "$DB"
python3 ./kvdb dump "$DB"
```

Actual: `keys=2 recovery_ms=0.534`, `OK`, `round=1`, `status=saved`.

Purpose: manually check an acknowledged batch after a forced process death. **The supplied transcript records one repetition in this section, with no whole-slot duration.** Completing 5-10 manual kills within the 120-second judging slot remains a follow-up. Restart the server for each repetition, use its newly printed PID, and update the round value/operation ID. Do not present this repeat instruction as completed evidence.

## 13. Million-key crash recovery benchmark — Terminal A

```bash
python3 -B -m tests.bench_f3_kill --seed 84220
```

Purpose: save at least one million keys through the real engine, kill it, recover, and verify every acknowledged value. Expected: `serve_exit=-9`, `strict_recovery_under_2000_ms=True`, `check: OK`, `missing ACKed=0`, `unexpected=0`, and `PASS`.

Actual: 1,030,000 acknowledged keys; 1,040,000 recovered keys; **571.145 ms engine recovery**, **614.9 ms complete open CLI**. The extra complete unacknowledged batch is allowed. Strict recovery limit: **less than 2,000 ms**. The whole benchmark includes dataset creation and verification and is not subject to a two-second total runtime limit.

## 14. Exact halfway cut of a 10,000-operation batch — Terminal A

```bash
python3 -B tools/check_ps_half_batch.py \
  --output "$LAB/evidence/half-batch"
```

Purpose: cut the frame after exactly 5,000 operation bodies, perform a real partial write and SIGKILL, then verify the whole batch remains absent. Expected JSON: `status=PASS`, `batch_ops=10000`, `complete_operation_prefix=5000`, `child_exit=-9`, `partial_batch_visible=false`.

Actual: **5.222 ms engine recovery / 5.232 ms API wall time**, both below the strict **2,000 ms** threshold. The test uses a controlled prefix selector; it is not a claim that a random manual kill landed exactly halfway.

## 15. Full preparation campaign — Terminal A

```bash
python3 -B tools/run_ps_acceptance.py \
  --data-dir "$LAB/evidence/full" \
  --host-storage-dir /mnt/c \
  --host-storage-dir /mnt/d \
  --seed 84221 \
  --f1-seed 84222
```

Purpose: orchestrate all regression, CLI, specific-scenario, strict performance and broader crash checks. This is preparation outside the fixed 15-minute demo. It prints a new `PS_EVIDENCE` directory containing its manifest and per-phase logs.

Actual: all eight phases exited zero; 153 regressions passed; seven modes x 500 = 3,500 rounds plus 500 consecutive restarts of one database passed. Total controller wall time: **699.249 seconds (11 min 39.249 sec)**. Some phases run concurrently; do not add their durations to calculate elapsed time.

The final line was:

```text
PS_ACCEPTANCE_COMPLETE; noncompliance=["Prompt log empty"]
```

The controller deliberately returns nonzero for this outstanding requirement. It does not mean a storage test failed, and it does not mean full submission compliance. Leave the original prompt log pending as requested. Any additional failure/noncompliance needs investigation.

### Child commands run by the controller

These were invoked automatically, not typed as separate manual tests. The exact commands and paths are archived in [the manifest](evidence/manual-testing-2026-11-07/acceptance-manifest.json). In this listing, `$RUN` means that run's printed `PS_EVIDENCE` directory; do not paste these as a second run into old evidence folders.

```bash
python3 -B tools/ps_measure_recovery.py --output "$RUN/performance"
make build
python3 -B -m unittest -v
python3 -B tools/ps_check_contracts.py --output "$RUN/contracts"
python3 -B tools/ps_specific_scenarios.py --output "$RUN/specific"
python3 -B tools/check_ps_half_batch.py --output "$RUN/half_batch"
python3 -B tools/run_final_gate.py --iterations 500 --seeds 84221 --workers 4 \
  --data-dir "$RUN/modes" --host-storage-dir /mnt/c --host-storage-dir /mnt/d
python3 -B tools/ps_f1_same_database.py --output "$RUN/same_database_f1" \
  --iterations 500 --seed 84222 --host-storage-dir /mnt/c --host-storage-dir /mnt/d
```

The performance helper also invokes the F3 benchmark with seeds 31337, 2026110608 and 2026110609 and `python3 -B -m tests.bench_recovery`. It constructs a separate exactly-one-million-frame replay diagnostic. The gate invokes `torture` for each of default, large-values, large-batch, recovery-crash, compaction, disk-full and crashpoints. The independent oracle checks every round; these are automated checks launched manually, not 4,000 human-issued kills.

## Reading unusual output correctly

- `Killed` / child exit `-9`: expected for a deliberately killed database child. An unexplained death of the test tool is a failure.
- `ERR` in workload mix: can be an expected rejected invalid/full request. `FAIL` and `TOOL_ERROR` must remain zero.
- `OK torn-tail=...`: read-only diagnosis of an incomplete ending; `open` performs recovery.
- `ACK`: successful durable mutation. Do not assume a request without ACK necessarily disappeared.
- `awaiting_response`: protocol observation, not proof the engine was inside a write at that instant.
- `PASS`: applies to that workload and conditions, not every possible crash schedule or physical power failure.

## Remaining human rehearsal

Repeat 5-10 manual kills with a stopwatch, physically disconnect Wi-Fi/Ethernet/tethering, and practise the three source-line questions and expiry-time design discussion. These are not certified by this transcript or the automated controller. The full original prompt log remains pending. Do not use AI or the internet during the official demo.
