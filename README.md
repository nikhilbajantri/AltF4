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
1 validate  2 encode frame  3 take global lock  4 refuse if poisoned  5 if end+frame > max_bytes (minus reserve for non-delete frames) -> DISKFULL, nothing written  6 os.pwrite at end (loop until complete)  7 os.fsync(fd)  8 update index, end += len  9 release lock, return; serve prints ACK <id> and flushes.
On error in 6 or 7: ftruncate(fd, end), fsync, mark poisoned, re-raise. Never retry fsync.
Delete reserve = min(65536, max_bytes // 10).

## Recovery (open)
1 flock <path>.lock  2 delete <path>.compact and <path>.init if present  3 if <path> missing: write header to <path>.init, fsync, os.replace to <path>, fsync directory  4 mmap, validate header  5 scan frames from offset 16; stop if <12 bytes left, or pos+12+len > size, or CRC mismatch; else apply ops  6 if stop < size: ftruncate(stop), fsync  7 end = stop, READY.

## Compaction
Hold the lock. Write live keys as PUT frames (<= 4 MB each) to <path>.compact, fsync, close, os.replace to <path>, fsync directory, reopen and swap fd/index/end. Triggers: compact command; DISKFULL with dead bytes (then retry once); dead bytes > 50% of a file > 4 MB.

## Engine API (src/engine.py)
KVDB(path, max_bytes=None); put(key: bytes, value: bytes); get(key) -> bytes | None; delete(key); batch([("put", k, v) | ("del", k)]); compact(); keys(); items(); close(); stats -> {keys, file_bytes, dead_bytes, recovery_ms}. Errors: DiskFull, PoisonedError, LockedError, ValueError.

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
id prefix before "-" names the writer (w1-17); each writer prefix gets its own worker thread. "hex:" prefix = hex-encoded bytes. ERR reasons: DISKFULL, INVALID, POISONED, IO, UNSUPPORTED, INTERNAL, BUSY. IO reports the initial operating-system error; POISONED rejects later writes on an unsafe handle. BUSY rejects a request whose writer queue is full without blocking other writers. UNSUPPORTED and INTERNAL report unavailable operations and unexpected failures. Startup may report LOCKED, CORRUPT, IO, or INVALID without an operation id. ACK is printed only after the engine call returned (after fsync).

## Torture
./torture --iterations 500 --seed 12345 [--mode default|large-values|large-batch|recovery-crash|compaction|disk-full|crashpoints]

## Implementation notes
These add to the contracts above; none of them changes one.

- `KVDB(path, max_bytes=None, auto_compact=True)`: `auto_compact=False` turns off the "dead bytes > 50% of a file > 4 MB" trigger. Compaction on DISKFULL and the compact command always work.
- Compaction frames: each PUT frame holds at most 4 MiB of payload and at most 10,000 ops (the batch limit).
- CRC-valid but malformed frame (bad nops, unknown op type, bad klen/vlen, DEL with vlen != 0, payload not matching its length): this is not a torn write, so `open` raises CorruptError and truncates nothing. `check` reports `CORRUPT offset=<n> <reason>`. Only an incomplete frame or a CRC mismatch counts as a torn tail and is truncated.
- `check` and `inspect` use the read-only scanner in `src/scan.py`. It takes no lock, never truncates and never creates files. `check` also reports CORRUPT if a CRC-valid frame exists within 1 MiB after the stop point (damage in the middle of the file, which `open` would otherwise truncate away).
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
| default | Two writers, private and shared keys, puts/deletes/batches through 10,000 operations, invalid requests, 2 ms to 1 s log-uniform kill delays; three crashes per database |
| large-values | Two writers, a maximum-size 1 MiB value at the start of each stream, followed by 128 KiB values |
| large-batch | Two writers, 10,000 operations at the start of each stream, followed by random 2..10,000-operation batches |
| recovery-crash | Three consecutive kills during replay or tail repair; torn tails produced by the real torn_write hook |
| compaction | Cycles four compaction crash hooks; every fifth round uses multiple output frames |
| disk-full | Rejected puts and whole batches, successful reserve deletes, close crash, reclaiming space and writing again |
| crashpoints | Cycles all 14 hooks; use at least 14 iterations for complete hook coverage |

The first three modes use random wall-clock delays and two stop-and-wait writers. Targeted modes use deterministic crash locations and report zero random delay; recovery/close crashes need not have a request awaiting a response. Default also forces a torn_write every fifth round, starting at round one, so omitted recovery truncation is observable even when random kills leave complete frames.

The runner launches the public kvdb CLI and obtains actual state only through open, check, and dump. The oracle/workload/runner import no storage implementation. crash_probe remains only a compatibility wrapper over these same public commands. Expectation comes from recorded requests and replies, not the database dump.

Private-key states must match a permitted world exactly. The shared/status key is mutated only by single-operation requests; observed SENT/response order rejects values overtaken by later completed operations. Batches remain private to avoid accepting inconsistent independent shared-key outcomes. General shared-key multi-operation batch checking is still outside this oracle's scope. INVALID, DISKFULL, and BUSY operations must leave no changes. Unexpected IO, POISONED, INTERNAL or UNSUPPORTED responses fail the run.

Seeds reproduce planned operations and kill delays, not OS scheduling or the number of ACKs. Intentional idle gaps let the report distinguish kills with and without requests awaiting responses. That metric does not prove a write was executing at kill time. Logs and databases remain under the unique evidence directory printed at startup (default ~/tmp_test/torture_data). Failures stop with exit 1 and concise key/op-ID differences; failure.txt retains full details. Tool errors stop with TOOL ERROR and exit 2.

## Verification records

See [docs/review_fixes.md](docs/review_fixes.md) for the current issue-resolution checks. [CRASH_TEST_REPORT.md](CRASH_TEST_REPORT.md) records the earlier campaign against its stated source hashes; it is historical, not a claim about later commits. The targeted suite runs with `python3 -B -m unittest tests.test_crash_campaign -v`.

These are process-crash and injected-I/O checks. Physical power-loss testing, arbitrary media corruption, and the final 500-round-per-mode release gate remain separate work. Keep benchmark/test databases on Linux ext4; the currently open Windows source checkout is not itself an ext4 checkout.
