# Breaking It

## Crash points

All 14 hooks are exercised by `--mode crashpoints` (at least 14 iterations), and by the targeted regression campaign. The original campaign's exact counts and evidence are in CRASH_TEST_REPORT.md; current issue verification is in docs/review_fixes.md.

| Point | Disk state at interruption | Recovery / expected result |
|---|---|---|
| init_before_rename | Complete synced .init, authoritative path not yet replaced | Reinitialize and remove stale temp |
| before_write | Previous frames only | New operation absent |
| torn_write | Previous frames plus incomplete prefix | Discard tail; preserve earlier operations |
| after_write | Complete frame in page cache | Process-crash replay accepts frame; power loss is a separate claim |
| after_fsync | Durable frame, index not yet updated | Replay entire operation |
| after_return | Engine completed, ACK not yet printed | Operation survives although caller has no ACK |
| recovery_mid_scan | Original file unchanged | Restart scan |
| recovery_before_truncate | Torn tail still present | Retry repair |
| recovery_after_truncate | Tail removed and file synced | Reopen valid prefix |
| compact_mid_copy | Old authoritative file plus partial temp | Use old file; delete temp |
| compact_before_rename | Old file plus complete synced temp | Use old file; delete temp |
| compact_after_rename | Path refers to complete compacted file | Recover new file |
| compact_after_swap | New file installed, directory synced | Recover new file; later writes use new descriptor |
| close_mid | Committed data already durable | Recover independently of close |

An fsync error is an injected I/O-failure test, not a fifteenth SIGKILL hook. The engine rolls back the failed append where possible and poisons the handle so later writes cannot be acknowledged.

## Ordering argument

Validation precedes frame writing; the complete frame is synced before index publication and success. A batch is one frame. Reads and updates share the engine lock. Recovery reads complete checked frames then truncates incomplete tails before allowing new writes. Compaction syncs the temporary file before replacement and syncs the containing directory after replacement; the old descriptor is replaced before future writes. Process-kill tests verify restart behavior but cannot verify hardware power-loss semantics.

## Known weaknesses

1. No physical power cut, storage firmware fault, or arbitrary middle-file bit rot is simulated. CRC32 detects accidental damage, not deliberate tampering.
2. Compaction holds the global lock while copying live data; readers and writers pause for its duration. Benchmark this on the demo laptop.
3. The exact shared-batch oracle has a 250,000-state search budget; pathological histories produce a tool error without a verdict. Mutation histories are checked; general read-linearizability is not covered.
4. Random timing and thread scheduling vary even with a fixed seed. Full command transcripts and named crash hooks support reproduction.

## Failures found and detector trials

- Injected zero-progress pwrite hung the engine; aa46909 adds a progress guard and regression coverage.
- The recovery probe formerly accepted an unrepaired torn tail; strict post-recovery check now requires exactly OK.
- Review R-04 showed default random kills could miss skipped truncation. Default now includes deliberate torn_write trials, and the regression with seed 12345 detects the planted omission at iteration 1.
- Review found invalid UTF-8 crashed serve; line-level rejection now keeps the session alive. A saturated writer queue now returns BUSY rather than blocking dispatch to other writers.
- The isolated planted early-ACK and partial-batch tests still verify that the checker rejects actual data loss.

## Next priorities

1. The two-seed 500-round-per-mode qualification passed; repeat it if storage or checker code changes. See FINAL_TEST_REPORT.md.
2. Compare exact shared-batch checks with independent reference cases and retain search-budget failures as qualification failures.
3. Rehearse crash-here answers against the final code and verify clean-clone/offline operation.
