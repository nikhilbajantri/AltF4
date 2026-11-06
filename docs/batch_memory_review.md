# Large-batch memory review

## Outcome

The engine no longer constructs an entire large encoded batch and then copies it again to prepend its header. It checks the database size cap first, prepares immutable frame parts, and writes large frames in chunks of at most 4 MiB. One final fsync precedes index publication and ACK. CRC, offsets, on-disk frame layout, 10,000-operation limit and 1 MiB value limit are unchanged.

For the controlled 40 MiB batch, additional tracked memory fell from **80.09 MiB to 8.14 MiB**, about a **90% reduction**. Rejected writes avoid that allocation. This is an encoder-overhead result, not a total process-memory quota.

## Measurements

Command: `python3 -B -m tests.bench_batch_memory`, Python 3.12.3 on Ubuntu/WSL. Inputs are 64 KiB unique immutable values, allocated before tracemalloc starts. Each successful batch is closed, reopened and compared with the full expected map. Capped trials use a 1,024-byte database limit. All benchmark databases are temporary directories on Linux storage under `~/tmp_test` and are cleaned up afterward.

The before measurement used the previous encoder plus the local uncertain-write follow-up, based on 1bb70c6. Main's later documentation-only changes were integrated before final validation. Failure-path reporting does not affect these successful/cap-rejected benchmark writes.

| Caller values | Result | Before: extra peak bytes | After: extra peak bytes |
|---|---|---:|---:|
| 8 MiB | Saved and verified after reopen | 16,795,209 | 8,481,509 |
| 8 MiB | DISKFULL, no append | 16,795,209 | 2,404 |
| 40 MiB | Saved and verified after reopen | 83,975,333 | 8,539,357 |
| 40 MiB | DISKFULL, no append | 83,975,333 | 6,509 |

Raw measurements: [before](evidence/batch_memory_before.json), [after](evidence/batch_memory_after.json). Reproducible benchmark: [tests/bench_batch_memory.py](../tests/bench_batch_memory.py).

## Implementation

- `frame_size` validates and sums encoded lengths without joining payloads. The cap/compaction check occurs before frame preparation. This also means poisoned handles reject large requests without encoding them.
- `prepare_frame` keeps the existing bytes encoder for frames up to 4 MiB. For larger frames it calculates the same CRC incrementally and retains immutable parts. Bytearray inputs are copied to immutable snapshots.
- `FrameParts.chunks` emits at most 4 MiB per chunk. Two chunks can overlap in allocation lifetime, which explains the roughly 8 MiB measured extra peak. Metadata grows with operation count.
- `_pwrite_all` preserves short-write handling for every chunk. The frame remains the atomic recovery unit; chunks are not independently committed. Torn-write prefix views retain the original header and checksum and require no full-frame copy.
- If chunk allocation fails after part of the frame has been written, the append rolls back and poisons the handle. Confirmed rollback yields an ENOMEM I/O error; failed rollback yields UNCERTAIN. No later mutation may continue on that handle.
- Engine API and CLI batch inputs stop collection after encountering the 10,001st operation. Serve already drains an excessive batch through `end`; a regression protects that behaviour. The fake engine uses the bounded collector too.

Encoding now occurs under the engine lock after the cap check. Readers and writers can wait during that preparation; these measurements are not throughput or latency benchmarks.

## Tests

All **8 focused memory tests passed** in 3.299 seconds. The full combined suite passed **138 tests in 42.595 seconds**, including the uncertain-write regressions and existing planted-fault detectors. Build passed. The partial-batch detector's injection point was updated for the new preparation call; it still requires the deliberately broken engine to be caught.

| Test | What it establishes |
|---|---|
| 32 MiB logical batch, extra tracked peak below 12 MiB | Additional encoding allocation stays bounded; reopened values match exactly |
| 10,000 references to one shared 1 MiB value, tiny database cap | A roughly 10 GiB logical frame is rejected without allocating 10 GiB; file stays unchanged and handle remains usable |
| Generator exceeds operation limit | Only 10,001 items are consumed and no operations are applied |
| Prepared frame versus existing encoder | Entire bytes, CRC, offsets and truncated prefixes match |
| Excessive serve batch | Parser drains to end and retains the next command |
| Five real SIGKILL locations on a frame above 4 MiB | before_write/torn_write preserve old state; after_write/after_fsync/after_return recover the complete batch, with earlier ACKed data intact |
| Mutable inputs | Prepared bytes retain their original snapshot |
| Allocation failure after first chunk | The exact old file is restored, later writes are rejected, and reopen returns earlier acknowledged data |

Evidence: [focused tests](evidence/batch_memory_focused.txt), [full suite](evidence/batch_memory_full_suite.txt).

## Remaining limits and qualification

Caller-owned values and decoded serve/CLI operations still occupy RAM. Bytearray snapshots can add a full input copy. Multiple queued batches can multiply input retention. The existing limits allow roughly 10 GiB of distinct input values in one maximum-size batch; that allocation was deliberately not attempted. The 10 GiB logical rejection test reuses one 1 MiB object, and must not be described as a successful 10 GiB write.

There is no aggregate byte quota, global queue-memory budget or disk-backed input spool. Adding one would require a documented input-policy decision or further architectural work. Python allocator failure and an operating-system OOM kill are different: controlled MemoryError handling does not guarantee survival if the OS kills the process. The public format-only `encode_frame` helper still materializes its output; the engine uses `prepare_frame` for large writes.

The historical 7,000-round campaign has not been repeated on this implementation. Its result belongs to its recorded sources. The scanner false-corruption edge case and final demo checks remain separate work; freeze the implementation before the next complete qualification run.

## Qualification follow-up

The complete rerun passed all 7,000 rounds on commit 1be1267 after these fixes. All 143 automated tests passed before that gate. See [the rerun report](../FINAL_GATE_RERUN_REPORT.md) and [audited evidence](final_gate_rerun_manifest.json). Prior paragraphs describing a pending rerun record the state before qualification.
