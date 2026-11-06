# Kill It and Prove It

A crash-safe key-value database in Python. Owner of this file: Varsha.

## Build
make build

## Platform
Linux, ext4. Tested on Arch Linux and WSL2 Ubuntu (repo under ~/). Python 3.10+ standard library only.

## On-disk format (all integers little-endian, append-only)
HEADER 16 bytes: magic "KVDB0001" (8) | version u32 = 1 (4) | hcrc u32 (4) = crc32 of first 12 bytes
FRAME: len u64 (8) | crc u32 (4) | payload (len bytes); crc = crc32(len bytes + payload); frame header = 12 bytes
PAYLOAD: nops u32 (4) | OP...
OP: type u8 (1=PUT, 2=DEL) | klen u16 | vlen u32 | key | value (DEL: vlen=0, no value bytes); op header = 7 bytes
The frame is the commit: a frame counts only if all its bytes are present and its CRC matches. A single put is a frame with nops=1.
Limits: key 1..1024 bytes, value 0..1,048,576 bytes, batch 1..10,000 ops.
Batch order: ops apply first to last (put X then del X leaves X absent).

## Write order (put, delete, batch)
1 validate and calculate frame size  2 take global lock  3 refuse if poisoned  4 check max_bytes before allocating the encoded frame (compact/retry if dead space exists)  5 prepare frame and CRC  6 os.pwrite at end, in bounded chunks for large frames (loop until complete)  7 os.fsync(fd)  8 update index, end += frame size  9 release lock, return; serve prints ACK <id> and flushes.
On error in 6 or 7: ftruncate(fd, end), fsync, mark poisoned, re-raise. If rollback truncation or its fsync also fails, raise UncertainWriteError: the operation may be present after reopen. Never retry the failed append fsync.
Delete reserve = min(65536, max_bytes // 10).

## Recovery (open)
1 flock <path>.lock  2 delete <path>.compact and <path>.init if present  3 if <path> missing: write header to <path>.init, fsync, os.replace to <path>, fsync directory  4 mmap, validate header  5 scan frames from offset 16; stop if <12 bytes left, or pos+12+len > size, or CRC mismatch; else apply ops  6 if stop < size: ftruncate(stop), fsync  7 end = stop, READY.

## Compaction
Hold the lock. Write live keys as PUT frames (<= 4 MB each) to <path>.compact, fsync, close, os.replace to <path>, fsync directory, reopen and swap fd/index/end. Triggers: compact command; DISKFULL with dead bytes (then retry once); dead bytes > 50% of a file > 4 MB.

## Engine API (src/engine.py)
KVDB(path, max_bytes=None); put(key: bytes, value: bytes); get(key) -> bytes | None; delete(key); batch([("put", k, v) | ("del", k)]); compact(); keys(); items(); close(); stats -> {keys, file_bytes, dead_bytes, recovery_ms}. Errors: DiskFull, PoisonedError, LockedError, ValueError, OSError, UncertainWriteError (an OSError subclass).

## CLI
./kvdb open <path> [--max-bytes N]   -> keys=<n> recovery_ms=<ms>
./kvdb put <path> <key> <value>      -> OK | ERR <reason> (exit 1)
./kvdb get <path> <key>              -> value | NOTFOUND
./kvdb del <path> <key>              -> OK
./kvdb batch <path> <file>           -> OK | ERR <reason>   (file lines: "put k v" or "del k")
./kvdb dump <path>                   -> key<TAB>value per line, sorted by key
./kvdb check <path>                  -> OK | CORRUPT <reason>
./kvdb serve <path> [--max-bytes N]  -> serve protocol
./kvdb inspect <path>                -> every frame: offset, len, crc OK/BAD, ops
./kvdb compact <path>                -> size before/after

## Serve protocol (one line in, one line out, flushed)
startup: READY keys=<n> recovery_ms=<ms>
put <id> <key> <value>  -> ACK <id> | ERR <id> <reason>
del <id> <key>          -> ACK <id> | ERR <id> <reason>
get <id> <key>          -> VAL <id> <value> | NOTFOUND <id>
batch <id> / op lines "put k v" or "del k" / end  -> ACK <id> | ERR <id> <reason>
compact <id>            -> ACK <id> | ERR <id> <reason>
quit
id prefix before "-" names the writer (w1-17); each writer prefix gets its own worker thread. "hex:" prefix = hex-encoded bytes. ERR reasons: DISKFULL, INVALID, POISONED, IO, UNCERTAIN, UNSUPPORTED, INTERNAL, BUSY. IO reports an operating-system error. For append failures with confirmed rollback the operation is absent. UNCERTAIN reports an append failure whose rollback could not be confirmed: the operation may be present or absent after reopening. It is neither an ACK nor a guaranteed rejection. Reopen and reconcile the application state before retrying; do not assume an automatic retry is safe. POISONED rejects later writes and compaction on that handle. The Python UncertainWriteError retains write_error and rollback_error for diagnosis. BUSY rejects a request whose writer queue is full without blocking other writers. UNSUPPORTED and INTERNAL report unavailable operations and unexpected failures. Startup may report LOCKED, CORRUPT, IO, or INVALID without an operation id. ACK is printed only after the engine call returned (after fsync).

## Torture
./torture --iterations 500 --seed 12345 [--mode default|large-values|large-batch|recovery-crash|compaction|disk-full|crashpoints]

## Implementation notes
These add to the contracts above; none of them changes one.

- `KVDB(path, max_bytes=None, auto_compact=True)`: `auto_compact=False` turns off the "dead bytes > 50% of a file > 4 MB" trigger. Compaction on DISKFULL and the compact command always work.
- Compaction frames: each PUT frame holds at most 4 MiB of payload and at most 10,000 ops (the batch limit).
- CRC-valid but malformed frame (bad nops, unknown op type, bad klen/vlen, DEL with vlen != 0, payload not matching its length): this is not a torn write, so `open` raises CorruptError and truncates nothing. `check` reports `CORRUPT offset=<n> <reason>`. Only an incomplete frame or a CRC mismatch counts as a torn tail and is truncated.
- `check` and `inspect` use the read-only scanner in `src/scan.py`. It takes no lock, never truncates and never creates files. `check` also reports CORRUPT if a CRC-valid frame exists within 1 MiB after the stop point (damage in the middle of the file, which `open` would otherwise truncate away).
- CLI tokens: keys and values use the serve `hex:` rule in both directions. `get` and `dump` print a value as `hex:<bytes>` when it is empty, not UTF-8, or contains whitespace (so every `dump` line stays `key<TAB>value`). In a `batch` file, everything after `put <key> ` is the value, spaces included; blank lines are skipped.
- `get`, `del`, `dump`, `check`, `inspect` and `compact` on a missing database print `ERR not found` (exit 1) and create nothing; `open`, `put`, `batch` and `serve` create the database.
- Tests and benchmarks run in `$KVDB_TEST_DIR` or `~/tmp_test` (a real disk, never tmpfs `/tmp`).

## Measured (ext4 on NVMe, Arch Linux, Python 3.14)
| What | Result |
|---|---|
| Recovery (`open`), 1,000,000 keys, ~20-byte values, 37 MB file | ~800 ms |
| Write 1,000,000 keys as 100 batches of 10,000 | ~1.4 s |
| `compact()`, 1M live keys + 1M overwrites (74 MB -> 37 MB) | ~2.5 s |
| `compact()`, 100,000 live keys x 1 KB values (104 MB, no dead bytes) | ~0.4 s |
| `compact()`, 1M keys all deleted (54 MB -> 16 bytes) | ~8 ms |

Reproduce: `python3 -m tests.bench_recovery` and `python3 -m tests.bench_compact`.

## Team
Nikhil: engine, format, crash points. Arsh: serve + torture. Srushti: CLI, inspect, Makefile. Varsha: docs, proof table, tests.

## Layout note
The torture harness package lives in `torturelib/` (runner.py, oracle.py, workload.py) because `./torture` is the executable entry point and a file and directory cannot share that name.

## Serve and torture usage

Run in WSL/Linux from the repository root:

    make build
    ./kvdb serve ~/tmp_test/practice.db
    ./torture --iterations 100 --seed 12345 --mode default

Serve uses one worker per operation-ID prefix. Accepted commands retain per-writer order; responses from different writers may interleave. Each queue has 64 pending slots and at most 64 prefixes are supported. A full queue returns BUSY immediately (which may precede earlier queued responses). Stop-and-wait clients avoid queue overflow. Invalid UTF-8 is rejected per physical line; invalid batches are consumed through end and never partly submitted. EOF/quit finish accepted queued operations before close. ACK follows engine return; after_return kills just before ACK.

| Mode | Actual coverage |
|---|---|
| default | Two writers, private and shared keys, puts/deletes/batches through 10,000 operations, half of single and small-batch values 64-256 KiB, invalid requests, 2 ms to 1 s log-uniform kill delays; three crashes per database |
| large-values | Two writers, a maximum-size 1 MiB value at the start of each stream, followed by 128 KiB values |
| large-batch | Two writers, 10,000 operations at the start of each stream, followed by random 2..10,000-operation batches |
| recovery-crash | Three consecutive kills during replay or tail repair; torn tails produced by the real torn_write hook |
| compaction | Cycles four compaction crash hooks; every fifth round uses multiple output frames |
| disk-full | Rejected puts and whole batches, successful reserve deletes, close crash, reclaiming space and writing again |
| crashpoints | Cycles all 14 hooks; use at least 14 iterations for complete hook coverage |

Writers per mode: default, large-values and large-batch run two concurrent stop-and-wait writers (w1, w2). compaction, recovery-crash and crashpoints intentionally use one writer at a time: each round must crash at an exact named hook on an exact hit (for example the third compaction, or the scan after a torn_write), and a second concurrent writer would make that hit count depend on thread scheduling. A write racing a compaction would also just wait on the engine lock, so it adds timing noise but no new disk state. Their fixture session (w1-base) finishes before the target session (w2-target) starts. disk-full currently also uses one writer (every op id is w1-*): its point is the exact order of rejected puts, the rejected batch and the reserve deletes, which a second writer would make depend on scheduling.

The first three modes use random wall-clock delays and two stop-and-wait writers. Targeted modes use deterministic crash locations and report zero random delay; recovery/close crashes need not have a request awaiting a response. Default also forces a torn_write every fifth round, starting at round one, so omitted recovery truncation is observable even when random kills leave complete frames.

The runner launches the public kvdb CLI and obtains actual state only through open, check, and dump. The oracle/workload/runner import no storage implementation. crash_probe remains only a compatibility wrapper over these same public commands. Expectation comes from recorded requests and replies, not the database dump.

Private-key states must match a permitted world exactly. Shared and private mutations, including overlapping multi-key batches, are checked against whole-operation orderings respecting writer FIFO and observed SENT/response precedence. The exact search uses memoization and finalized-key pruning; a 250,000-state budget produces TOOL ERROR with no verdict if exceeded. See docs/shared_batch_fix.md for before/after evidence. INVALID, DISKFULL, and BUSY operations must leave no changes. Unexpected IO, UNCERTAIN, POISONED, INTERNAL or UNSUPPORTED responses fail the run.

Seeds reproduce planned operations and kill delays, not OS scheduling or the number of ACKs. Intentional idle gaps let the report distinguish kills with and without requests awaiting responses. That metric does not prove a write was executing at kill time. Logs and databases remain under the unique evidence directory printed at startup (default ~/tmp_test/torture_data). Failures stop with exit 1 and concise key/op-ID differences; failure.txt retains full details. A TOOL ERROR (harness or OS trouble, not an engine verdict) is printed with its evidence and never counted as a PASS; that database is renamed to `*.tool-error` and the run continues on a fresh one, then exits 2. After SIGKILL the runner waits up to 60 s for the child to exit (a child inside fsync exits only when the kernel finishes that I/O) and prints WARN if that took more than 5 s; post-kill open, check and dump each get 120 s. The summary reads `PASS=n/N TOOL_ERROR=t FAIL=f max_exit_wait_s=s`.

## Verification records

See [docs/review_fixes.md](docs/review_fixes.md) for the current issue-resolution checks. [CRASH_TEST_REPORT.md](CRASH_TEST_REPORT.md) records the earlier campaign against its stated source hashes; it is historical, not a claim about later commits. The targeted suite runs with `python3 -B -m unittest tests.test_crash_campaign -v`.

These are process-crash and injected-I/O checks. The two-seed, 500-round-per-mode gate passed (7,000 rounds); see FINAL_TEST_REPORT.md. Physical power-loss testing and arbitrary media corruption remain separate work. Keep benchmark/test databases on Linux ext4; the currently open Windows source checkout is not itself an ext4 checkout.

## Final qualification

See [FINAL_TEST_REPORT.md](FINAL_TEST_REPORT.md) for the complete test history, before/after shared-batch evidence, the 7,000-round gate, and limitations. From the repository root, `python3 tools/run_final_gate.py --host-storage-dir /mnt/d --host-storage-dir /mnt/c` repeats the gate on this WSL setup with compressed evidence and a 20 GiB reserve. Use the actual Windows volume holding your WSL disk.

## Large-batch memory

The engine checks the encoded size against the database cap before encoding. Frames above 4 MiB retain immutable input parts, calculate the original CRC incrementally, and write chunks of at most 4 MiB, followed by one final fsync. The on-disk format and atomic batch semantics are unchanged. API iterators and CLI batch files stop collecting after the 10,001st operation instead of exhausting an unbounded input. The limit remains 10,000 operations, 1 MiB per value.

Measured additional encoding memory for a 40 MiB batch fell from about 80.1 MiB to 8.1 MiB; rejected batches avoid that allocation. Caller-owned input values are excluded from these measurements. Serve still retains decoded batch input and queued requests, and mutable API inputs need snapshots; this is not a total RAM quota. See [docs/batch_memory_review.md](docs/batch_memory_review.md) for measurements, tests and remaining limits.
