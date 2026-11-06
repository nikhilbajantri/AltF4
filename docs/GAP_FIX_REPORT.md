# Gap fixes and fresh qualification

Completed UTC: 2026-11-06T20:18:08.881978+00:00. Base commit: d9d3c2811c01d3da66cd6723cfb8d545ecd676be; the qualified working-tree source hashes are recorded separately. The intended source matches the tested Linux ext4 snapshot after CRLF-to-LF normalization only. Original raw hashes remain untouched; normalized hashes make clean-checkout verification portable. The capture-only hash checker was updated separately and is exercised by the refreshed demo capture.

**Result: code and documentation fixes below passed fresh automated qualification. The original prompt log remains pending by explicit user choice; physical offline rehearsal and event/demo sign-off remain human tasks. No claim of complete submission compliance is made.**

## Gaps explained and fixed

| Gap | Why it mattered | Fix / evidence |
|---|---|---|
| One-byte truncation lost an acknowledged final record | The PDF F4 case failed even though normal process-kill tests passed | One expendable 00 byte follows the complete log. It is synced with each write and overwritten at the next append. Truncating one byte removes padding, not saved payload. Puts/deletes/batches/compaction and repeated/interrupted restoration have regressions. |
| Default torture count was 25 | Explicit 500-round runs did not fix the required default | Parser default is now 500; regression verifies default and overrides. |
| Standalone F3 benchmark could print PASS above two seconds | A slow recovery could be reported as successful | strict_recovery_ok is part of the benchmark PASS condition; tests reject 2,000 ms, slower, missing, negative and NaN timing. |
| Architecture had wrong/duplicate scenarios and stale diagram | Judges could select a row describing a different failure | Exactly 32 correct IDs, disk state, mechanism, exact functions and test references; current diagram includes byte layout, numbered ordering, index, cap, locks and recovery/compaction. B2 is honestly explained as design equivalent. |
| README, BREAKING and demo schedule were incomplete | Build/parser/source questions and the fixed demo would be hard to verify | README has a parser-level format diagram and prerequisites; BREAKING has all five sections and exact hook functions, rendered and visually checked as two pages; demo uses the fixed 15-minute schedule. Old captured timings are labelled historical. |

## How the tail fix works

Frame encoding and version-1 headers remain unchanged. The file contains contiguous complete frames and, for a nonempty current-writer log, one final guard byte outside the frame CRC. It is not a commit marker. Internal end excludes this byte; physical stats/cap include it. _write overwrites the prior guard with the next frame, writes a new guard, fsyncs, then permits index publication/return/ACK. Thus the overhead is one byte per file, not per record. A complete frame killed before guard creation can still recover (allowed before ACK); a frame missing even its final payload byte is still discarded, preserving the torn-write rule.

Recovery recognizes a present guard or restores a missing one after replay, and can recover again if that restoration is killed. Compaction writes/syncs its guard before replacement. Rejected cap writes reserve the guard in advance. Legacy files migrate when there is room: an imported file already at/over a newly configured cap stays readable without growth, but its old unguarded tail requires room and a current write/compaction before this guarantee applies. Older program versions can strip the guard.

## Fresh automated results

- 153 regression tests passed in 22.968 seconds; ten new default/timing/tail-guard tests are included.
- Five direct scenarios plus the exact halfway 10,000-operation B6 case passed. B6 recovery was 3.450 ms, with no batch operations visible.
- 12 real CLI smoke calls cover all eight required commands plus inspect/compact. Seven additional calls now reproduce F4 with all acknowledged keys retained.
- **7,500 crash rounds passed:** 7 modes Ã— 2 seeds Ã— 500 = 7,000, plus 500 consecutive restarts of one persistent database. No invariant failures or tool errors.
- 11941 SIGKILL events were recorded within those rounds. Recovery trials can kill multiple times per round. All compressed transcripts were parsed, with exactly 1â€“500 PASS entries per workload and no FAIL/TOOL_ERROR; targeted exits were -9.
- Frozen source fingerprints match before/after the run; current source differs only in verified line-ending normalization (apart from the separately executed capture-only portability fix); all 14 named hooks were exercised for each seed.

| Workload | Seed | Passed rounds | Logged kills |
|---|---:|---:|---:|
| compaction | 2026110701 | 500 | 500 |
| crashpoints | 2026110701 | 500 | 572 |
| default | 2026110701 | 500 | 600 |
| disk-full | 2026110701 | 500 | 500 |
| large-batch | 2026110701 | 500 | 500 |
| large-values | 2026110701 | 500 | 500 |
| recovery-crash | 2026110701 | 500 | 2499 |
| compaction | 2026110702 | 500 | 500 |
| crashpoints | 2026110702 | 500 | 571 |
| default | 2026110702 | 500 | 600 |
| disk-full | 2026110702 | 500 | 500 |
| large-batch | 2026110702 | 500 | 500 |
| large-values | 2026110702 | 500 | 500 |
| recovery-crash | 2026110702 | 500 | 2499 |
| F1 one persistent database | 2026110703 | 500 | 600 |

## Recovery and compaction measurements

| Real-engine million-key SIGKILL seed | Engine recovery ms | Complete open CLI ms | Result |
|---|---:|---:|---|
| 31337 | 576.419 | 624.600 | PASS |
| 2026110608 | 590.413 | 641.100 | PASS |
| 2026110609 | 614.015 | 664.800 | PASS |

These F3 runs use actual engine ACKs and verify all recovered keys/values. A separate diagnostic contains exactly one million one-operation frames; it is not an engine-ACK/crash experiment. First diagnostic open checked all million values.

| Million separate records: repetition | Engine recovery ms | API wall ms | Result |
|---|---:|---:|---|
| 1 | 1501.031 | 1501.044 | PASS |
| 2 | 1514.751 | 1535.136 | PASS |
| 3 | 1516.947 | 1536.394 | PASS |

The strict limit is less than 2,000 ms. Measurements ran before the concurrent campaign on this laptop, with no OS-cache eviction; these are measured conditions, not guarantees for every device/log size.

```text
puts:    keys=1000000 file_bytes=37001617 write_s=1.84 recovery_ms=590.9
compact: delete_s=1.48 size_before=54003217 size_after=16 compact_ms=8.9
```

## Before/after and test-development record

Pre-fix evidence is retained in docs/evidence/ps-acceptance-2026-11-07 and docs/evidence/pdf-requirements-2026-11-06. Before: F4 lost c after three successful writes; torture default was 25; the standalone recovery benchmark did not enforce its printed time. After: contracts.json reports no lost acknowledged key and default 500; the maintained benchmark enforces the strict threshold.

The first new cap-boundary test incorrectly required byte-for-byte unchanged storage after a rejected write that was allowed to compact dead records. Its assertion was corrected to require unchanged logical state and cap compliance; a separate live-data case verifies byte-for-byte rejection without compaction. This was a test expectation error, not evidence of storage corruption. The earlier cross-writer reply-order test correction and failed-run evidence are also retained.

## Still pending and real limits

- PROMPTS.md: deliberately unchanged and pending, per the user reply. An edited summary cannot be claimed as the PDFâ€™s original unedited prompt history.
- Physical Wi-Fi-off clean-clone rehearsal, 5â€“10 human kills, source-line answers, every-member readiness, event provenance/deadline and final submission need human sign-off. The process-level socket guard is supplementary, not proof of physical network disconnection.
- The 10,000 distinct maximum-sized values combination is roughly 10 GiB of input and is not qualified. Chunked encoding bounds encoding overhead, not retained inputs, queues or the index.
- Recovery is linear in log size, and compaction holds the global mutex. Power loss, arbitrary media corruption and filesystems other than tested ext4 are outside these results.
- Legacy at-cap migration and older writers have the guard limitations described above. B2 has no separate trailing marker state in this allowed CRC-frame design; its proof table explains the equivalence without inventing a test.

## Evidence and reproduction

- [Fresh source/phase manifest](evidence/gap-fixes-2026-11-07/manifest.json), [independent transcript audit](evidence/gap-fixes-2026-11-07/audit.json), [unit output](evidence/gap-fixes-2026-11-07/unit.txt), [performance](evidence/gap-fixes-2026-11-07/performance.json), [CLI/contracts](evidence/gap-fixes-2026-11-07/contracts.json), [halfway B6](evidence/gap-fixes-2026-11-07/half_batch.json). Checksums cover the copied small artifacts.
- Large raw transcripts/databases remain at /home/arsht/tmp_test/gap-fix-qualification-30x9lkfq/results/ps-acceptance-2ehcsq9l. Their paths, lengths and SHA-256 hashes are in audit.json. The frozen source checkout is /home/arsht/tmp_test/gap-fix-qualification-30x9lkfq/repository.
- Reproduce: python3 -B tools/run_ps_acceptance.py --host-storage-dir /mnt/c --host-storage-dir /mnt/d --seed 2026110701 --additional-seeds 2026110702 --f1-seed 2026110703 --workers 4. Use a fresh Linux evidence directory. A nonzero final exit still records the pending prompt requirement; it does not disguise failed tests as passes.
- [Offline plan](../OFFLINE_TEST_PLAN.md); [current architecture](../ARCHITECTURE.md); [two-page printable breaking document](../output/pdf/BREAKING.pdf).

The commit is made only after this qualification and report verification. No push or PR is part of this request.
