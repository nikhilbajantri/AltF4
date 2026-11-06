# Final crash-gate rerun after memory, error and scanner fixes

All **7,000 rounds passed**, with zero failed or missing rounds. The run summaries recorded **TOOL_ERROR=0 and FAIL=0 for every mode/seed**. All 14 transcripts independently contain exactly 500 distinct PASS records for iterations 1 through 500. No TOOL_ERROR or FAIL records were accepted. Source hashes remained unchanged during the gate and matched the checkout during this audit.

Tested commit: `1be12670688f67d7d8d3b9ed5bf4365de3d11482`. Seeds: [2026110606, 2026110607]. Build passed and all **143 automated tests passed in 41.548 seconds** before the gate; exact suite output is in [the evidence](docs/evidence/final_fixes_full_suite.txt).

## Fixes included

- [Large-batch memory](docs/batch_memory_review.md): size preflight, bounded encoding chunks, bounded operation collection, rollback after allocation failure. Controlled 40 MiB batch: roughly 80 MiB to 8.1 MiB extra encoding memory.
- [Uncertain writes](docs/uncertain_write_report.md): double I/O failures now report UNCERTAIN and block later mutations; callers reconcile after reopening. Unknown outcomes are never counted as passing crash checks.
- [Scanner boundaries](docs/scanner_fix_report.md): embedded payload records no longer become false evidence of later records. Tests retain actual later-record detection and read-only inspection.

Main was fetched and reviewed before the final fix; it had no incoming changes beyond those already in feat-arsh. The fix commit preceded this run. This report is a later documentation change.

## Gate results

Seven modes x two seeds x 500 rounds = 7,000 rounds. Default, large-values and large-batch use two stop-and-wait writers with random kill delays. Recovery-crash, compaction, disk-full and crashpoints use targeted scenarios. Crashpoints uses the current seeded hook/hit selection. All 14 named hooks were verified for each seed; compaction exercised its four locations 125 times per seed.

| Mode | Seed | Passed | Verified SIGKILL exits | Seconds |
|---|---|---|---|---|
| compaction | 2026110606 | 500/500 | 500 | 330.6 |
| compaction | 2026110607 | 500/500 | 500 | 342.6 |
| crashpoints | 2026110606 | 500/500 | 572 | 322.6 |
| crashpoints | 2026110607 | 500/500 | 572 | 267.4 |
| default | 2026110606 | 500/500 | 600 | 461.9 |
| default | 2026110607 | 500/500 | 600 | 465.8 |
| disk-full | 2026110606 | 500/500 | 500 | 510.9 |
| disk-full | 2026110607 | 500/500 | 500 | 502.8 |
| large-batch | 2026110606 | 500/500 | 500 | 793.4 |
| large-batch | 2026110607 | 500/500 | 500 | 803.4 |
| large-values | 2026110606 | 500/500 | 500 | 370.6 |
| large-values | 2026110607 | 500/500 | 500 | 381.7 |
| recovery-crash | 2026110606 | 500/500 | 2499 | 532.0 |
| recovery-crash | 2026110607 | 500/500 | 2499 | 549.9 |

Verified SIGKILL exits: **11342**. Submitted shared batches: **4892**. Some rounds contain multiple kills, so the kill count exceeds the round count. Submission does not prove that a request reached disk; observed ACKs and the full recovered-map check determine the required outcome.

## Evidence and reproduction

Raw evidence directory: `/home/arsht/tmp_test/final_gate/gate-oh9xkahi`. The [audited manifest](docs/final_gate_rerun_manifest.json) contains source hashes, timestamps, per-run summaries, compressed transcript checksums, round counts and hook counts. Files remain on the Linux filesystem in Ubuntu's virtual disk on D:. Lossless gzip transcripts and actual host-volume free-space monitoring preserve a 20 GiB reserve. No earlier campaign rounds were added to this total.

Gate start (UTC): 2026-11-06T15:54:38.518258+00:00. End (UTC): 2026-11-06T16:24:15.790453+00:00.

```bash
make build
python3 -B -m unittest -q
python3 -B tools/run_final_gate.py --seeds 2026110606 2026110607 --host-storage-dir /mnt/d --host-storage-dir /mnt/c
python3 -B tools/audit_gate_rerun.py /path/printed/by/gate
```

The audit validates the entire campaign before writing either report file. Reusing a seed reproduces planned operations and delays; thread scheduling may produce different histories. Adapt host volumes to the actual location of the WSL disk.

## Limits and remaining release work

These are process-crash, configured-cap and injected-failure checks. Physical power cuts, arbitrary media failures and dishonest hardware are outside this evidence. Damaged length fields can still hide later records from the read-only scanner. Caller inputs and queued batches still require RAM; the encoding improvement is not a global memory quota. Pathological oracle searches fail qualification rather than approximate a pass.

Remaining release tasks are demo-machine/offline validation, final proof/document reconciliation and rehearsal. The earlier [test-history report](FINAL_TEST_REPORT.md) remains historical evidence for its own source version, including the first interrupted campaign and storage recovery.
