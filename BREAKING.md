# Breaking It

## Crash points
All 14 hooks are exercised by `--mode crashpoints` with at least 14 iterations and by the targeted regression campaign. Campaign counts and evidence are in `CRASH_TEST_REPORT.md`; current issue verification is in `docs/review_fixes.md`.

| Point | Disk state at interruption | Recovery result | Where in code |
|---|---|---|---|
| `init_before_rename` | Complete, synced `.init`; database path not replaced | Open removes stale `.init` and creates the database again | `src/engine.py:_create` |
| `before_write` | Previous frames only | New operation is absent | `src/engine.py:_write` |
| `torn_write` | Previous frames and an incomplete frame prefix | Recovery truncates the torn tail and preserves earlier frames | `src/engine.py:_write`, `src/engine.py:_recover` |
| `after_write` | Complete frame may be in the page cache but is not synced | Process-crash recovery replays a complete frame with a valid CRC; power-loss behavior is untested | `src/engine.py:_write` |
| `after_fsync` | Durable frame; index not yet updated | Recovery replays the complete operation | `src/engine.py:_write`, `src/engine.py:_scan` |
| `after_return` | Engine returned; ACK not yet printed | The operation is durable, but the caller has no ACK | `src/serve.py:execute` |
| `recovery_mid_scan` | Original file unchanged | Next open repeats the scan | `src/engine.py:_scan` |
| `recovery_before_truncate` | Torn tail still present | Next open repeats the repair | `src/engine.py:_recover` |
| `recovery_after_truncate` | Tail removed and file synced | Next open scans the valid prefix | `src/engine.py:_recover` |
| `compact_mid_copy` | Old authoritative file and partial temporary file | Open uses the old file and removes the temporary file | `src/engine.py:_copy_live` |
| `compact_before_rename` | Old file and complete, synced temporary file | Open uses the old file and removes the temporary file | `src/engine.py:_compact_locked` |
| `compact_after_rename` | Database path names the complete compacted file; directory sync has not run | Open recovers the file at the database path | `src/engine.py:_compact_locked` |
| `compact_after_swap` | New file installed and directory synced | Open recovers the new file; later writes use its descriptor | `src/engine.py:_compact_locked` |
| `close_mid` | Every acknowledged frame is already durable | Recovery reads the committed frames; close writes nothing | `src/engine.py:close` |

If append and rollback both fail, the server returns `UNCERTAIN` and the handle refuses further mutations. Recovery may include a complete frame from that operation; callers reconcile the result. Evidence: `docs/uncertain_write_report.md`.

An `fsync` error is an injected I/O-failure test, not a fifteenth SIGKILL hook. The engine attempts rollback and poisons the handle so later writes cannot be acknowledged.


## Ordering argument

A normal append follows `os.pwrite` through `_pwrite_all()` → `os.fsync(fd)` → index update → engine return → server ACK. Large frames are written in chunks of up to 4 MiB. An ACK therefore follows a successful file sync.

If a write or sync fails, the engine calls `ftruncate` to restore the previous end and then calls `fsync` for the rollback. It poisons the handle and raises an error. If rollback also fails, it returns `UncertainWriteError` as `ERR <id> UNCERTAIN`. The failed write is not retried.

Appending does not change the database directory entry; syncing the database file covers its contents and size. Compaction changes the directory entry, so it syncs `.compact`, calls `os.replace`, then syncs the parent directory. A complete frame after `after_write` can survive SIGKILL because the kernel page cache remains available; a power cut can lose unsynced data. Power-cut behavior is not tested.
## Known weaknesses

1. Tests do not simulate physical power cuts, storage firmware faults, or arbitrary middle-file bit rot. CRC32 detects accidental damage, not deliberate tampering.
2. Compaction holds the global lock while copying live data; at 1M live keys this takes about 2.5 seconds. The index also uses RAM per key.
3. `check` can report a false positive when a value contains bytes that resemble a valid frame. The `.lock` file is deliberately never deleted. Rename atomicity has been verified only on ext4.
4. The shared-batch oracle has a 250,000-state search budget; pathological histories return a tool error without a verdict. Mutation histories are checked; general read-linearizability is not covered.
5. Input and queued work still use RAM. Encoding memory changed from 80.1 MiB to 8.1 MiB; see `docs/batch_memory_review.md`.
   
## Failures found and detector trials
- Zero-progress `pwrite` hung the engine. Commit `aa46909` added a progress guard and regression coverage.
- Default random kills missed skipped truncation. Review R-04 added deliberate torn-write trials; seed `12345` detects the planted omission at iteration 1.
- A slow exit after SIGKILL caused a TOOL ERROR at iteration 116 after a 60-second wait. Commit `09e69ec` records the fix.
- The WSL disk filled during the 7,000-round gate. Commit `4bc6000` added a free-space check.
- Coverage was 71%; coverage tuning raised it to 84%. Commit `b4bd0be` records the change.
- PR #16 reported duplicate dump output.
- Issue #17 records CLI gaps.

## Next priorities

1. The two-seed 500-round-per-mode qualification passed; repeat it if storage or checker code changes. See FINAL_TEST_REPORT.md.
2. Compare exact shared-batch checks with independent reference cases and retain search-budget failures as qualification failures.
3. Rehearse crash-here answers against the final code and verify clean-clone/offline operation.

## Large-frame follow-up

Large batches now use bounded encoding chunks with a single final fsync and the existing frame format. Memory allocation failure after a partial write triggers rollback and handle poisoning; failed rollback reports UNCERTAIN. Focused tests kill streamed frames at before_write, torn_write, after_write, after_fsync and after_return. Input retention and queued work still require RAM. See [the memory review](docs/batch_memory_review.md).
