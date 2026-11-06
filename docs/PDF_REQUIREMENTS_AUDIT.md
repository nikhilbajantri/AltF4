# PDF requirements audit

Historical pre-fix audit. Current fixes and fresh qualification: [GAP_FIX_REPORT.md](GAP_FIX_REPORT.md). Original evidence below remains unchanged.

Audit date: 2026-11-06 22:54 IST. Checked commit: d9d3c2811c01d3da66cd6723cfb8d545ecd676be on feat-arsh. This is a requirements review, not a claim that every deliverable is finished. Production implementation and existing tests were not edited during this audit.

Source: [Kill It and Prove It.pdf](<D:/notes/srinathon/Kill It and Prove It.pdf>), 19 pages. All pages were extracted and read; pages 2, 8, 11-15 and 19 were also visually reviewed. PDF statements are the comparison criteria for this audit, not independent authorization to change the repository, publish prompt logs or contact judges.

## Overall finding

The strict recovery measurements pass on this laptop under the measured conditions. Fresh real-engine CLI checks and all 143 automated tests passed. The earlier 7,000-round qualification remains evidence for the unchanged implementation. However, the repository is **not fully compliant with the PDF deliverables yet**: the proof table is mismapped, the prompt log is empty, the default iteration count is wrong, and F4's literal acknowledged-record requirement needs clarification or a fix.

## Strict two-second recovery requirement

PDF page 2 requires open under two seconds with 1,000,000 keys; F3 on page 8 adds process kill and preservation of acknowledged keys. Page 19 says the limit is strict on the judging laptop and mentions replaying 1,000,000 log records. A million keys in 100 batches is not the same workload as a million separate one-operation records, so both were measured.

### Real-engine million-key SIGKILL benchmark

The existing tests.bench_f3_kill writes through serve, records ACKs independently, SIGKILLs the process, runs CLI open/check/dump, and compares every recovered key/value. Three fresh seeds passed with no missing acknowledged keys or unexpected values. Timing includes both the engine's reported recovery and the complete CLI invocation.

| Seed | Recovered keys | Engine recovery | CLI wall incl. interpreter | Strict result |
|---|---:|---:|---:|---|
| 31337 | 1010000 | 0.585 s | 0.797 s | PASS |
| 2026110608 | 1040000 | 0.610 s | 0.788 s | PASS |
| 2026110609 | 1100000 | 0.635 s | 0.951 s | PASS |

This uses roughly 100-110 batch frames containing more than one million put operations, not one million independent frame headers.

### Exactly one million separate records

A separate format-generated diagnostic fixture contains exactly 1,000,000 distinct keys in 1,000,000 one-operation frames, 41,000,016 bytes. It uses the repository's format encoder and a final file fsync. It is **not** an engine-issued-ACK or SIGKILL durability experiment; the real-engine runs above provide that evidence. The first API-open measurement verified all million values individually after timing.

API constructor measurements: 1.480, 1.498 and 1.504 seconds internally (external API wall 1.480, 1.519 and 1.526 seconds). Additional CLI measurements after the other tests finished:

| Repetition | Engine recovery | CLI wall incl. interpreter | Strict result |
|---|---:|---:|---|
| 1 | 1.558 s | 1.750 s | PASS |
| 2 | 1.565 s | 1.940 s | PASS |
| 3 | 1.543 s | 1.747 s | PASS |

These results pass, but the slowest CLI observation was 1.940 seconds: only about 60 ms below two seconds. CPU load, storage and laptop conditions matter. The tests did not evict the OS cache or reboot between opens; repeated diagnostic reads are warm-cache measurements. The PDF's crash model is process death, not OS restart. This is measured compliance, not a guarantee for every log size or future load.

### Large-batch recovery (B6)

A real 10,000-operation batch was interrupted using torn_write:1. The child exited -9 without ACK; reopening exposed none of the batch and retained the earlier anchor. Engine recovery was 2.501 ms, API wall 2.510 ms, both below two seconds.

### Benchmark enforcement gap

The existing tests/bench_f3_kill.py prints recovery_ms but its PASS expression does not enforce less than 2,000 ms. This audit evaluated the threshold explicitly. Add a threshold assertion to the maintained benchmark before relying on its PASS label as performance evidence. Production code was left unchanged.

## Other functional requirements

| PDF requirement | Result and evidence |
|---|---|
| Mandatory put/get/delete/batch/open/close | Implemented; fresh CLI smoke tests and the 143-test suite passed |
| Byte keys 1..1,024; values 0..1 MB; batches through 10,000 ops | Constants and boundary tests exist. Current maximum value is 1 MiB (1,048,576 bytes). Empty/binary values are supported through hex protocol tokens |
| At least 1,000,000 keys | Fresh real-engine runs recovered 1.01-1.10 million keys; diagnostic fixture recovered exactly one million |
| Concurrent writers and readers | Global-lock design is allowed by page 2. Current tests cover two writers, shared keys, whole batches and reader visibility; the earlier gate validates actual recovered histories |
| One authoritative data file | One append-only data file; .lock/.init/.compact are auxiliary or temporary. The in-memory index is rebuilt from frames |
| File shrinks after million puts/deletes | Fresh benchmark: 37,001,616 bytes after puts; 54,003,216 after deletes; compaction to 16 bytes in 9.6 ms |
| Configurable cap, rejected batches absent, readability and recovery | Fresh CLI and existing cap/compaction tests pass; full suite includes reserve deletes, rejected batches, failed compaction and later writes |
| Eight required CLI commands | All exercised successfully: open, put, get, del, batch, dump, check and serve. Extra inspect/compact smoke checks also passed |
| ACK after durability | Engine pwrite/fsync/index ordering and serve ACK ordering have regression coverage, including planted early-ACK detection |
| Independent oracle, random-delay SIGKILL, two writers, targeted modes | Implemented. Operation/response logs belong to the harness. The expected history is not obtained from the recovered dump |
| Stop on first invariant failure | Assertion failures stop with a mismatch. Tool errors are recorded separately and may continue on a fresh database; they never count as PASS and the final exit is nonzero. Low space stops immediately |
| Default 500 torture iterations | **FAIL:** runner currently defaults to 25. Explicit --iterations 500 works and passed qualification |
| Standard-library-only implementation | Static import inspection found no non-stdlib runtime imports outside the project packages. This does not certify code provenance or team conduct |
| Clean clone / offline operation | Fresh local clone built successfully; put/get worked under a verified Python process-level socket block. This is useful evidence, but Wi-Fi was not physically switched off and the Git clone used local source |
| Physical power cuts / bit rot / networking / MVCC | Explicitly not required by pages 5 and 8; they should not be presented as mandatory unfinished engine features |
| TTL | A design-extension answer, not a mandatory implemented feature. Current DEMO.md correctly labels it as proposed |

Raw results: [recovery measurements](evidence/pdf-requirements-2026-11-06/recovery_measurements.json), [CLI/build/contract checks](evidence/pdf-requirements-2026-11-06/contract_checks.json), [fresh full suite](evidence/pdf-requirements-2026-11-06/full_suite.txt). The full suite passed 143 tests in 93.693 seconds; performance measurements above were run separately from that concurrent validation phase, with the later CLI samples taken afterward.

## Literal F4 issue

PDF page 8 says that removing one byte from the end should lose at most the last unacknowledged record. Fresh reproduction:

1. CLI put a a, put b b, put c c each returned OK.
2. The closed file was manually shortened by one byte.
3. Read-only check reported OK torn-tail=24 bytes (open will truncate).
4. Reopen succeeded, but dump contained only a and b; get c returned NOTFOUND.

Therefore the current design loses the final **acknowledged** record in this specific external-truncation experiment. The existing unit test expects that loss, so its PASS is not proof of the PDF's literal F4 wording. This does not invalidate the measured process-kill results: manual deletion of already-synchronized bytes is a different fault model. It does require an organizer interpretation or a recovery/redundancy change before claiming strict F4 compliance. Do not silently weaken the test or state that the literal requirement passes.

## Mandatory documentation and submission gaps

| Deliverable / PDF pages | Finding | Required follow-up |
|---|---|---|
| ARCHITECTURE.md, pp.12-13 | 41 scenario rows, 32 unique IDs and 9 duplicated IDs; all 41 say Not verified. Many IDs describe the wrong scenario: A6 is an I/O error instead of a delete crash, A7 is validation instead of large-value crash, D1-D4 are recovery cases instead of concurrency, and F1-F4 are locks/queues instead of repeated abuse | Replace with exactly the PDF's 32 scenarios, correct code/function locations, and truthful evidence citations |
| Architecture diagram, p.12 | Mermaid has broad flows but lacks a byte-field layout, numbered write ordering and explicit disk-full guard. Existing PNG still labels CLI/serve as stubs and planned interfaces, which is stale | Publish one current diagram with the actual format, lock/index/cap, numbered write sequence and complete recovery/compaction paths |
| README, p.9 | Text format and commands exist; there is no on-disk diagram in README itself | Embed or link a current format diagram explicitly and verify instructions on the final checkout |
| BREAKING.md, pp.10-11 | Has 14 hook rows, ordering, weaknesses, failed attempts and priorities. Table lacks explicit file/function locations per row. The priority list is not a concrete remaining-development plan; at-most-two-page rendering is not verified | Make all five requested sections explicit, add code locations and concrete prioritized 24-hour improvements, and verify the two-page limit |
| PROMPTS.md, pp.11-12 | File exists but the log is empty | Populate the actual chronological, unedited prompts with tool and approximate time. A polished paraphrase is not the specified log; this audit has not changed it |
| DEMO.md, pp.14-15 | Real captured evidence exists, but its run-of-show differs from the fixed judging schedule | Align to 0-1 build, 1-4 random torture, 4-6 targeted modes, 6-8 manual kills, 8-12 crash questions, 12-15 TTL design; rehearse the 5-10 manual kills |
| Git/provenance/event rules, pp.3-4,14,17 | Meaningful commit history exists. Official start/end time, source originality, inter-team conduct, final submission/push deadline and battery readiness cannot be certified from this audit | Team confirms event provenance, deadline and presentation readiness; do not infer compliance from test counts |

The more detailed draft proof table is useful working material, but a draft in another file does not make the incorrect final ARCHITECTURE.md table compliant.

## Correct scenario checklist for final proof-table reconciliation

Evidence labels below describe the inspected tests/earlier qualification, not a claim that every exact timing point has been freshly rerun here. W = test_all_write_points_for_put_delete_batch_large_value_and_large_batch; C = test_all_compaction_points_with_multiple_frames; R = test_repeated_crashes_during_recovery, all in tests/test_crash_campaign.py.

| ID | Actual PDF scenario | Mechanism/evidence or gap |
|---|---|---|
| A1 | Kill before put writes any bytes | before_write; W |
| A2 | Torn single put | torn_write; W; byte-cut recovery tests |
| A3 | Complete put before fsync | after_write; W; complete CRC-valid frame may be replayed |
| A4 | After fsync, before put returns | after_fsync; W |
| A5 | Immediately after successful put return | Engine return precedes serve ACK; after_return and acknowledged-state SIGKILL history tests cover the relevant states |
| A6 | Kill during delete | W includes delete across five write points |
| A7 | Kill during 1 MB value | W includes exactly 1 MiB value; large-values gate mode |
| B1 | First 3 of 10 batch operations written | Entire frame is the commit unit; generic torn-batch tests exist. Exact 3-of-10 boundary is not separately identified in evidence |
| B2 | Ten operations written, commit marker absent | No separate trailing marker in this format. Explain incomplete frame versus complete CRC-valid frame; do not invent an absent-marker state |
| B3 | Marker present before fsync | after_write equivalent for complete frame; batch all-or-nothing tests |
| B4 | Batch returns success | Whole acknowledged batch survives; W and concurrent oracle histories |
| B5 | Put X then delete X in one batch | README lists ordered application; test_batch_put_then_del_leaves_absent and oracle-order tests. Add a direct post-crash exact-case citation if required |
| B6 | Kill halfway through 10,000-op batch; recovery <2s | Fresh torn 10,000-op batch: no batch keys visible, recovery 2.501 ms; W large-batch |
| C1 | Kill recovery scan | recovery_mid_scan; R |
| C2 | Kill tail repair | recovery_before_truncate/recovery_after_truncate; R |
| C3 | Kill compaction before replacement | compact_mid_copy/compact_before_rename; C |
| C4 | Kill around rename/swap | compact_before_rename/compact_after_rename; C |
| C5 | Kill after swap before temp cleanup | compact_after_swap; next open removes leftovers; C |
| C6 | Kill close | close_mid; test_initial_creation_and_close_crashes |
| D1 | Two writers, different keys | default concurrent histories; test_two_threads |
| D2 | Two writers, same key | shared-key default histories and shared-batch oracle regressions |
| D3 | Long batch racing single puts | default mixes batches/singles and whole-operation oracle; scheduling varies |
| D4 | Reader during same-key batch | test_reader_cannot_observe_half_applied_batch; test_reader_sees_batch_all_or_nothing |
| E1 | Cap during single put | test_max_bytes and cap campaign |
| E2 | Cap during batch | cap preflight rejects entire batch; cap campaign |
| E3 | Cap then process kill | disk-full mode close_mid and post-recovery full map checks |
| E4 | Cap during compaction | test_tiny_cap_during_compaction and failed-compaction preservation tests |
| E5 | Reclaim after deletes, later writes succeed | test_compact_and_retry_on_disk_full and disk-full mode |
| F1 | 500 consecutive random kill/restarts | default qualified twice for 500 rounds. Current default reuses each database for three rounds before a fresh file; 500 kills of one unchanged file are not separately demonstrated |
| F2 | Repeated kills during recovery | recovery-crash mode, three successive kills each round; R |
| F3 | Million keys, kill, recovery <2s, all ACKed data | Three fresh real-engine seeds pass time and full recovered-state checks |
| F4 | Manually cut one byte; lose at most unacknowledged tail | Literal acknowledged-last-record case does not pass; see reproduction above |

## Recommended order

1. Resolve the F4 interpretation and make performance benchmarks enforce the strict threshold; keep the million-record diagnostic distinct from batched million-key F3.
2. Correct torture's default to 500 and add a default-argument regression.
3. Reconcile the final 32-row proof table and diagram with the exact PDF IDs; use real test results, never blanket PASS labels.
4. Complete the actual prompt log, the five-section/two-page BREAKING document, README diagram and fixed demo schedule.
5. Rehearse on the judging laptop with Wi-Fi genuinely off, then record and push the final submission. A language rewrite is not needed to meet the measured recovery target.

No production fixes, prompt-log edits, commits or external issue/PR changes were made by this audit. Existing measured passes do not waive the outstanding requirements above.
