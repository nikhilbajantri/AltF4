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
id prefix before "-" names the writer (w1-17); each writer prefix gets its own worker thread. "hex:" prefix = hex-encoded bytes. ERR reasons: DISKFULL, INVALID, POISONED. ACK is printed only after the engine call returned (after fsync).

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
