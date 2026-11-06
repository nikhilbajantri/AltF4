# Offline test plan

This is a pre-judging rehearsal plan for the problem statement, not evidence that Wi-Fi was physically switched off. Do not use an AI tool or the internet during the official judging session. The human team must verify the manual checkpoints below.

## Objective and pass criteria

On the judging laptop, with every internet uplink disconnected, a fresh local clone must build with the documented command and run the CLI, recovery benchmarks and crash tests using only installed tools and local files. The exact checked commit and results must be saved. Recovery must stay below 2,000 ms with at least one million keys; record engine time and complete CLI time separately. No invariant failure or tool error counts as PASS.

Use docs/GAP_FIX_REPORT.md for current automated results. The original prompt log remains pending by user choice; a successful offline run does not waive it or the human demo requirements.

## Before disconnecting

1. Save the work and commit the final intended implementation, acceptance tools and documents. Uncommitted/untracked files will not be included by git clone. Record git rev-parse HEAD and git status --short; the clone should represent the submission, not an incomplete snapshot.
2. Fetch any desired remote changes now. Resolve conflicts and rerun checks before freezing the commit. Network cloning must happen before disconnecting; the offline clone below uses a local repository.
3. Confirm Ubuntu/WSL starts normally. If Windows reports a VHD sharing violation, resolve it before the rehearsal, not while the judge is timing the build.
4. Check installed tools: python3 --version, make --version, git --version, and findmnt. Runtime code needs Python 3.10+ standard library, Linux file locking and fsync support; no package download should be needed.
5. Keep database/evidence directories on Linux ext4 under ~/tmp_test. Check findmnt -T ~/tmp_test. Also check df -h /mnt/c /mnt/d: a dynamic WSL disk's Linux free-space number alone does not establish Windows-host free space. Keep at least 20 GiB on the volume containing the WSL disk and adequate space on the Windows system drive.
6. Charge the laptop and connect its charger. Download/mark local any notes needed for the demo; source is in D:/ALT F4/AltF4 and must be available without OneDrive fetching content.
7. Keep local copies of README.md, ARCHITECTURE.md, BREAKING.md and DEMO.md open or accessible. A teammate should be able to explain each recovery path without online assistance.

## Physically disconnect (human checkpoint)

In Windows, switch Wi-Fi off, unplug Ethernet, and disconnect phone USB tethering/hotspots and VPN-provided uplinks. Do not merely close a browser. Record the adapter state and local time. A PowerShell inventory is:

```powershell
Get-Date -Format o
Get-NetAdapter -Physical | Select-Object Name, Status
```

Physical uplinks should be disabled/disconnected. WSL virtual adapters can remain present; their existence alone does not prove internet access. No adapter setting is changed by the acceptance scripts. Restore connectivity manually only after the rehearsal and saved results are complete.

## Fresh local clone and build

From Ubuntu/WSL, with connectivity still off:

```bash
set -o pipefail
mkdir -p "$HOME/tmp_test"
OFFLINE_PARENT=$(mktemp -d "$HOME/tmp_test/kvdb-offline-XXXXXX")
OFFLINE_EVIDENCE="$OFFLINE_PARENT/evidence"
mkdir -p "$OFFLINE_EVIDENCE"
git clone --no-hardlinks '/mnt/d/ALT F4/AltF4' "$OFFLINE_PARENT/AltF4"
cd "$OFFLINE_PARENT/AltF4"
git rev-parse HEAD | tee "$OFFLINE_EVIDENCE/commit.txt"
git status --short | tee "$OFFLINE_EVIDENCE/git-status.txt"
python3 --version | tee "$OFFLINE_EVIDENCE/python.txt"
findmnt -T "$OFFLINE_PARENT" | tee "$OFFLINE_EVIDENCE/filesystem.txt"
unset KVDB_CRASH
make build 2>&1 | tee "$OFFLINE_EVIDENCE/build.txt"
```

Pass: clone is the intended commit, the data filesystem is ext4, no missing dependency or network fetch is required, and build exits zero with BUILD OK. Stop and document an actual failure instead of silently enabling the network to repair it.

## Full pre-demo offline acceptance run

This is longer than the 15-minute judging slot. Run it during preparation, not during the live session:

```bash
python3 -B tools/run_ps_acceptance.py \
  --data-dir "$OFFLINE_PARENT" \
  --host-storage-dir /mnt/d --host-storage-dir /mnt/c \
  --seed 2026110707 --additional-seeds 2026110708 --f1-seed 2026110709 \
  2>&1 | tee "$OFFLINE_EVIDENCE/acceptance-console.txt"
ACCEPTANCE_EXIT=${PIPESTATUS[0]}
printf '%s\n' "$ACCEPTANCE_EXIT" > "$OFFLINE_EVIDENCE/acceptance-exit.txt"
```

Use host paths matching the actual Windows volumes. The command prints PS_EVIDENCE and saves a manifest plus per-phase logs. It measures recovery before starting concurrent crash workloads. It runs the regression suite, CLI/contracts, exact added scenarios, two seeds with 500 rounds per mode (7,000), plus 500 restarts of one database. An exit of 1 with known noncompliance means the project has not passed the whole statement; a passing unit suite or successful evidence collection alone cannot turn that red result green. Manual requirements still need human sign-off even if automated failures are later fixed.

The controller also runs the exact B6 halfway-boundary check: 5,000 of 10,000 operation bodies, actual SIGKILL, no partial visibility and recovery strictly below 2,000 ms. It saves half_batch/results.json.

Required evidence: manifest.json, performance/results.json, contracts/results.json, specific/results.json, half_batch/results.json, unit.txt, each mode manifest/transcript and same_database_f1/result.json plus its transcript. Read errors as well as summaries. Retain failed/incomplete campaigns under their original names.

## Short judge-format rehearsal

Follow the PDF's fixed order, with the judge choosing seeds/counts in the real session:

| Minutes | Rehearsal action | Pass criterion |
|---|---|---|
| 0-1 | Build the fresh clone using README | First-time build works offline |
| 1-4 | Run 200 default rounds with a newly chosen seed | Every attempted round passes; record actual elapsed time rather than assuming it fits |
| 4-6 | Compaction and recovery-crash modes | Zero failures/tool errors; use the judge's chosen counts |
| 6-8 | Manual serve, batch, 5-10 kills, check/dump | Acknowledged changes survive; batches remain whole; use the current server PID |
| 8-12 | Three questions at actual source lines | Explain disk bytes and recovery action precisely |
| 12-15 | TTL design extension | Discuss format, recovery, compaction and a clock/batch edge case; no implementation claim |

Example seed-selected default command, timed independently:

```bash
time python3 -B ./torture --iterations 200 --seed 2026110618 \
  --compress-log --host-storage-dir /mnt/d --min-free-gib 20 \
  --data-dir "$OFFLINE_EVIDENCE/torture" \
  2>&1 | tee "$OFFLINE_EVIDENCE/default-200.txt"
```

Targeted pre-demo examples (the actual judge controls live counts and seeds):

```bash
python3 -B ./torture --iterations 100 --seed 2026110619 --mode compaction \
  --compress-log --host-storage-dir /mnt/d --min-free-gib 20 \
  --data-dir "$OFFLINE_EVIDENCE/compaction" \
  2>&1 | tee "$OFFLINE_EVIDENCE/compaction-100.txt"
python3 -B ./torture --iterations 100 --seed 2026110620 --mode recovery-crash \
  --compress-log --host-storage-dir /mnt/d --min-free-gib 20 \
  --data-dir "$OFFLINE_EVIDENCE/recovery" \
  2>&1 | tee "$OFFLINE_EVIDENCE/recovery-100.txt"
```

Use DEMO.md's two-terminal procedure for manual kills; repeat with acknowledged new values. Recorded PID 668 is historical and must never be copied as a new kill target. The automated capture helper covers two controlled demonstrations, not a human's 5-10 unpredictable kills. For each manual round, record the last ACKs, killed PID, check result and complete dump.

## Human sign-off sheet

- [ ] Exact commit recorded and fresh local clone built first time.
- [ ] Wi-Fi off, Ethernet/tethering disconnected for the full rehearsal; adapter evidence saved.
- [ ] No network download or online tool was needed.
- [ ] All required CLI commands work offline.
- [ ] Recovery timing passes on this laptop with the actual test datasets.
- [ ] Crash summaries, independent transcript checks and per-scenario results are satisfactory; unresolved failures are not hidden.
- [ ] Manual kills repeated 5-10 times with the invariant checked each time.
- [ ] ARCHITECTURE.md has the correct 32 rows and current diagram; BREAKING.md meets its five-section/two-page requirement.
- [ ] Original chronological prompt log is complete.
- [ ] Every member answers three source-line questions and the TTL design question without AI or internet.
- [ ] Final intended commit is submitted/pushed before the actual event deadline, after connectivity is restored if necessary.

Only mark offline validation complete after the human checkpoints are actually performed. The earlier process-level socket guard is supplementary evidence, not proof that the Wi-Fi-off rehearsal happened.
