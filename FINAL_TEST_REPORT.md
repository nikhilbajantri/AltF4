# Final crash qualification and test history

## Outcome

The shared-batch checker limitation was reproduced, fixed, tested, committed and pushed before the final gate. The final gate passed all **7,000 rounds**: seven modes, two fresh seeds, 500 rounds for every mode/seed pair. All 14 run summaries agree with an independent audit of exactly 500 distinct passing rounds per transcript. Source SHA-256 hashes match the code present for the gate.

This is evidence about the tested mutation histories and process crashes, not a proof of every possible timing or physical power-loss behavior. Any tool error, search-budget exhaustion, unexpected child exit or invalid recovered state would fail qualification rather than be silently counted as a pass.

In plain language: we repeatedly stopped the database without letting it shut down, reopened it, and checked its entire contents. Every acknowledged change had to survive, and every batch had to appear as one complete operation. The improved checker can now do this even when both writers change the same group of keys.

## Before and after the shared-batch fix

Baseline: 4c80833. Before changing the checker, six new regressions all errored with `ValueError: unsupported shared key; use shared/status`. That demonstrated unsupported checker coverage, not an observed database data-loss defect.

Fix commit: 2a9c3c3 (`Check overlapping shared batches with exact atomic orderings`). Pushed to feat-arsh before starting this gate.

The replacement checker searches whole-operation orderings, respecting writer order and response-before-send precedence. ACKed operations must be included, ERR operations must be absent, and an unanswered operation is wholly optional. A batch is applied atomically in list order. Keys are never validated as unrelated independent winners. Repeated values are interned; equivalent states are memoized; finalized-key mismatches are pruned. A 250,000-state budget fails as a tool error without a verdict.

After the fix: all six new cases passed, and the complete suite passed **110 tests in 30.581 seconds**. `make build` returned BUILD OK. A fresh Linux-home clone of commit 2a9c3c3 also built successfully and passed all 110 tests in 19.797 seconds at `/home/arsht/tmp_test/qualification-clone-6y_q3wed/repo`. A separate brute-force permutation checker tested 30 generated histories against 16 recovered maps each (**480 accept/reject comparisons**). The tests accept valid complete A/B outcomes, reject mixed batches, enforce timing order, and cover initial state, pending batches, rejection and ordered deletion. Existing planted-fault checks for early ACKs, partial batches and skipped truncation also passed.

Detailed before/after evidence: [docs/shared_batch_fix.md](docs/shared_batch_fix.md).

Raw outputs: [before-fix errors](docs/evidence/shared_batches_before.txt) and [after-fix passes](docs/evidence/shared_batches_after.txt). The before-fix output was preserved from a disposable checkout of the original baseline; it does not overwrite the working implementation.

## Final gate results

Fresh seeds: 2026110603 and 2026110604. Qualification source commit: 508121f. Four independent jobs ran concurrently. Timings include contention and are not performance benchmarks. Test data stayed under the WSL Linux filesystem.

| Mode | Seed | Passed rounds | Verified SIGKILL exits | Shared batches sent | Wall seconds |
|---|---|---|---|---|---|
| compaction | 2026110603 | 500/500 | 500 | 0 | 338.6 |
| compaction | 2026110604 | 500/500 | 500 | 0 | 338.6 |
| crashpoints | 2026110603 | 500/500 | 572 | 0 | 328.6 |
| crashpoints | 2026110604 | 500/500 | 572 | 0 | 267.5 |
| default | 2026110603 | 500/500 | 600 | 1516 | 452.8 |
| default | 2026110604 | 500/500 | 600 | 1469 | 463.8 |
| disk-full | 2026110603 | 500/500 | 500 | 0 | 528.0 |
| disk-full | 2026110604 | 500/500 | 500 | 0 | 500.9 |
| large-batch | 2026110603 | 500/500 | 500 | 1078 | 812.4 |
| large-batch | 2026110604 | 500/500 | 500 | 1072 | 817.3 |
| large-values | 2026110603 | 500/500 | 500 | 0 | 375.7 |
| large-values | 2026110604 | 500/500 | 500 | 0 | 383.7 |
| recovery-crash | 2026110603 | 500/500 | 2499 | 0 | 519.9 |
| recovery-crash | 2026110604 | 500/500 | 2499 | 0 | 537.9 |

Total verified SIGKILL exits: **11342**. This differs from 7,000 rounds because some rounds include multiple kills (repeated recovery and deliberate torn-write trials). Shared batches sent by random concurrent modes: **5135**. A SENT record is not proof that a complete frame reached disk; ACK and recovery checking determine the required outcome.

No failing round or newly observed database corruption occurred in this completed rerun. Source hashes stayed unchanged throughout this rerun. The earlier interrupted campaign is excluded from its totals.

## Interrupted campaign and storage recovery

The first campaign (seeds 2026110601/2026110602) did **not** complete. It reported six complete 500-round successes, then the test environment ran out of host C: space and Ubuntu returned I/O errors. The virtual Linux disk had reported hundreds of GiB free, but it was dynamically backed by C:. Full uncompressed transcripts and retained databases consumed host space. This was a test-infrastructure failure, not an established database corruption finding. It must not be presented as a successful 7,000-round gate.

With the user's approval, Ubuntu was stopped and moved using WSL's supported command to D:\WSL\Ubuntu-24.04, then restarted. A first attempt encountered a sharing violation; a full WSL shutdown released the disk and the retry succeeded. User identity and file read/write checks passed. Original raw evidence remains in the moved distro; the manifest and small logs were also copied to D:. Systemd replaced journals marked corrupted or uncleanly shut down, so the restart check is not a certification of every distro file.

Commit 508121f adds optional lossless gzip transcripts, per-round free-space checks and a monitored gate driver. On WSL, the driver requires an explicit Windows host volume; this run monitored /mnt/c, /mnt/d and the Linux evidence filesystem, reserving 20 GiB. It checks once per second, stops its own process groups on failure or timeout, and atomically replaces the results manifest. The reserve is a safety margin, not a hard quota. Compression preserves complete commands rather than discarding payloads.

Before this rerun, **112 tests passed in 39.320 seconds**, the build passed, and a one-round smoke check passed all seven modes. Two new regressions establish that low host space stops work before a round begins, and that gzip transcripts retain submitted batches, crash events and PASS records from real subprocess tests. The complete rerun used fresh seeds against the committed safeguards. See [docs/gate_interruption.md](docs/gate_interruption.md) for the incident record.

## What each mode tests and why it matters

| Mode | Procedure | What a pass establishes within that workload |
|---|---|---|
| default | Two concurrent stop-and-wait writers; overlapping shared batches; private changes; invalid input; random delays; three crashes per database; periodic torn_write | A complete recovered map can be explained by one permitted ordering of atomic operations, across repeated recovery |
| large-values | Begin each writer with an exactly 1 MiB value, then 128 KiB values; random kills | Large payloads do not become partial or foreign values in accepted recovery states |
| large-batch | Begin each writer with 10,000 operations, including shared keys; later batches range 2..10,000; random kills | Large batches remain atomic, and overlapping batch results have a valid whole-operation ordering |
| recovery-crash | Kill three successive opens during scanning or tail repair, then recover cleanly | Recovery can restart safely; tail repair is repeatable |
| compaction | Cycle copy, before-rename, after-rename and after-swap hooks; periodically use multi-frame live sets | Either authoritative representation preserves the expected live state after interrupted compaction |
| disk-full | Reach the cap, reject puts and whole batches, use delete reserve, kill close, compact and write again | Rejected operations leave no partial changes and reclaimed space can be used again |
| crashpoints | Cycle all 14 implemented hooks with explicit exit checks | Each named location was actually reached and killed; its disk/recovery expectation was checked |

The first three modes are concurrent random-delay workloads. The remaining four are targeted hook-based scenarios, not 500 unrelated random timing samples. Source-generated values carry operation IDs and deterministic filler; equality checks cover the complete bytes, not only a tag or checksum.

## Automated test families

| Files | Tests explain | Why they matter |
|---|---|---|
| tests/test_gate_storage.py | Low host-space refusal and lossless real-crash gzip evidence | Prevents a repeat of unmonitored evidence growth and checks compressed logs remain auditable |
| tests/test_shared_batches.py | Exact whole-batch ordering, mixed-outcome rejection, timing constraints and brute-force agreement | Tests the tester, including valid outcomes it must accept and invalid outcomes it must reject |
| tests/test_torture.py | Lost ACKed data, invented values, optional operations, seeded workloads and real subprocess kills | Prevents a permissive or broken expected-state checker from producing misleading passes |
| tests/test_review_fixes.py | Invalid UTF-8, full queues, CLI operations, compact diffs, oracle tool errors and skipped-truncation detection | Protects against every reviewed failure path being reintroduced |
| tests/test_serve.py | Protocol, batch boundaries, binary data, ACK ordering, independent workers and shutdown | Ensures the interface does not promise success early, mix responses or drop queued work |
| tests/test_crash_campaign.py | Named hooks, 1 MiB values, 10,000-op batches, truncation boundaries, repeated recovery, disk caps, reader visibility and planted faults | Exercises rare exact locations that wall-clock kills may miss |
| tests/test_engine.py | Persistence, recovery, locking, errors and durability ordering | Tests the core storage behavior directly, separately from the harness |
| tests/test_format.py | Encoding/decoding, CRC checks, malformed records and frame cuts | Ensures recovery can distinguish complete frames from incomplete or invalid records |
| tests/test_scan.py | Read-only examination, corrupt/torn files and middle-file damage reporting | Ensures check/inspect do not repair evidence accidentally |
| tests/test_compact.py | Space reclamation, descriptor replacement, cap failures and swap crashes | Guards against writing to the old unlinked file or losing data during replacement |

## Earlier campaigns and issues (historical versions)

These are separate verification phases, not extra passes on the final code. Repeated unittest executions are not added into a fabricated cumulative test count.

| Phase | Recorded evidence | What was learned |
|---|---|---|
| Initial serve | Five, then eleven passing focused tests | Command routing, response ordering and atomic batch submission worked with the practice engine |
| First real concurrent runner | 82 automated tests and 125 random rounds across two seeds | Two writers could drive the real engine and recovered state matched permitted private-key worlds |
| Major campaign | 92 tests; 2,000 random rounds across four seeds; 123 targeted SIGKILLs over all 14 hooks | Found the zero-progress write hang and insufficient post-recovery tail checking; both fixed |
| GitHub review fixes | 104 tests and 700 rounds (100 per mode) | Completed the public CLI and all modes, rejected invalid bytes, removed queue blocking and improved error/difference reporting |
| Shared-batch fix | Six failures before, six passes after; 110 total tests and 480 reference comparisons | Removed the single-shared-key restriction and validated complete atomic orderings |
| Interrupted qualification | Six completed 500-round runs; remaining work incomplete | Exposed host disk exhaustion; excluded from final gate totals |
| Storage safeguards | 112 tests and seven smoke rounds | Verified low-space stopping and compressed evidence |
| Final qualification | 7,000 rounds on the fixed code | Passed every mode/seed gate with preserved evidence |

Earlier exact results: [CRASH_TEST_REPORT.md](CRASH_TEST_REPORT.md), [docs/review_report.md](docs/review_report.md), and [docs/review_fixes.md](docs/review_fixes.md). Issues #3–#14 were addressed in cf044c7 and merged via PR #15. This report does not retroactively assign shared-batch coverage to those older tests.

## Failures found and corrections

1. Injected pwrite returning zero hung the retry loop. A progress guard now raises an I/O error; rollback/poison behavior and subsequent reopen are tested.
2. The original probe accepted a remaining torn tail after recovery. A clean check now requires exactly OK.
3. Random kills missed a deliberately removed truncation step. Default periodically forces a torn write; an isolated broken copy is detected at iteration one.
4. The review found missing CLI/modes, invalid UTF-8 crashes, blocking queues, incomplete errors, oversized failure output, import-path errors and stale proof documentation. Those changes and their regression evidence are linked in docs/review_fixes.md.
5. Shared multi-key batches were unsupported by the oracle. Six before-fix errors established that limitation; exact whole-operation checking now accepts valid outcomes and rejects mixed ones.

6. The first final-gate campaign exhausted Windows host space. Supported distro relocation, compressed transcripts, physical-volume monitoring and failure-safe manifests were added before the complete rerun.

Planted faults live only in disposable copies. A detector test passing means it correctly rejected that broken copy, not that the deliberately broken engine passed qualification.

## Reproduce

From the repository root in Ubuntu/WSL:

```bash
make build
python3 -B -m unittest -q
python3 -B -m unittest tests.test_shared_batches -v
```

Run the complete gate with the actual Windows volume holding the WSL virtual disk (D: on this machine):

```bash
python3 -B tools/run_final_gate.py --host-storage-dir /mnt/d --host-storage-dir /mnt/c
```

Use --data-dir to select a Linux evidence directory. The gate creates a unique directory and prints it. Transcripts are oracle.log.gz; read them with gzip.open or zcat. On native Linux, the host-volume arguments can be omitted. For a standalone torture run use --compress-log and --host-storage-dir /mnt/d; its default free-space reserve is 2 GiB, while this gate uses 20 GiB. Reusing a seed reproduces planned operations and delays; operating-system timing still changes which operations were sent, acknowledged or interrupted.

## Evidence and source identity

Gate manifest, source SHA-256 hashes, timestamps and per-task summaries: `/home/arsht/tmp_test/final_gate/gate-7k5i2d_3/manifest.json`. Per-mode stdout logs and operation transcripts/databases are adjacent. Every one of the 14 transcripts was audited for exactly 500 PASS records. No source file hash changed during the gate. The committed [audit manifest](docs/final_gate_manifest.json) also records each compressed transcript's SHA-256 checksum, round count, kill count, shared-batch count and named crash-point counts.

Gate start (UTC): 2026-11-06T13:19:42.042366+00:00. Gate end (UTC): 2026-11-06T13:49:26.311059+00:00.

Checker fix: 2a9c3c3; storage safeguards and tested gate source: 508121f. This report is a later documentation commit and does not change the tested storage/checker implementation.

## Practical limits

These checks cover process SIGKILL, configured byte caps, injected errors and explicit torn-write hooks. They do not simulate an actual power cut, host/VM failure, arbitrary media corruption or dishonest storage firmware. General read-linearizability is not modeled by the mutation oracle. Pathological histories that exceed the exact search budget receive no verdict and fail the gate. Performance observations from earlier benchmarks are not fresh demo-laptop measurements.

Remaining release work: an explicit Wi-Fi-off build and command check, final demo-machine performance checks, proof-table reconciliation and rehearsed crash-here explanations. The fresh-clone build and test check has passed; it did not involve disabling the user's Wi-Fi.
