# Known weaknesses (draft for Varsha)

All numbers were measured on 2026-11-06 on this machine (ext4 on NVMe, Arch Linux, Python 3.14). The tools were `tests.bench_recovery`, `tests.bench_compact` and a one-off RSS script (results below). Line numbers are `src/engine.py`.

1. **Recovery time grows linearly with file size.** Every open replays the whole log: `_scan` decodes each frame through `mmap`, and there is no checkpoint or index file. With 1,000,000 keys (37 MB file), `recovery_ms` measured 874.7 ms in `bench_recovery` and 847.6 ms in the RSS script (README says ~800 ms). A file that is mostly dead bytes takes as long as a live one until it is compacted.

2. **Compaction blocks everything.** `_compact_locked` runs inside `self._lock`, the same lock every `put`, `get` and `delete` takes. Measured lock-hold times:
   - 2,587.7 ms for 1M live keys + 1M overwrites (74 MB → 37 MB);
   - 411.0 ms for 100k × 1 KB.

   During that time every reader and writer waits. Auto-compaction (line 196) runs inside a `put` before it returns, so the `put` that triggers it is not ACKed until the compaction finishes. Compaction also re-reads every live value with `pread` (line 301) and holds all of a frame's values, up to 4 MiB, in memory at once.

3. **The whole index lives in RAM.** Each key costs a dict entry plus the key `bytes` plus an `(offset, vlen)` tuple. With 1M keys (10-byte keys), RSS grew by 154,428 KB after open, about 158 bytes per key. Peak RSS in that process was 458,688 KB, and it also held the earlier write phase. A dataset whose key count does not fit in memory cannot be opened.

4. **Input batches still consume RAM; encoder duplication has been reduced.** The engine now preflights the database cap, uses 4 MiB chunks for large encoded frames, and bounds operation collection. A controlled 40 MiB input required about 8.1 MiB additional tracked encoding memory, compared with 80.1 MiB before. The allowed 10,000 operations x 1 MiB values can still imply roughly 10 GiB of caller/decoded input; no maximum-size allocation was attempted. Serve queues and concurrent requests can multiply input retention, and bytearray inputs require immutable copies. There is no global memory quota or disk-backed input spool. See docs/batch_memory_review.md for exact evidence and scope.

5. **CorruptError and `check` false positives.**
   - `open` raises `CorruptError` and refuses to start when a frame's CRC is valid but its payload is malformed (`format._parse_payload`). That is the right call for real damage. But a torn tail made of stale bytes whose CRC happens to match (about 1 in 2^32) would also stop the database instead of being truncated.
   - More practically, `check` (`src/scan.py` `_find_later_frame`) searches 1 MiB past the stop point for any CRC-valid frame. Values are arbitrary bytes, so a value that contains an encoded frame makes a harmless torn tail look like mid-file damage. Reproduced by hand: put a value of 100 bytes + `encode_frame([("put", b"inner", b"v")])` + 100 bytes, then cut 50 bytes off the end. `check` printed `CORRUPT offset=41 damaged frame followed by CRC-valid frame at 168`, while `open` correctly truncated to 41 bytes and kept key `a`.
   - The reverse also holds: CRC32 detects accidental damage, not deliberate tampering.

6. **`<path>.lock` is never deleted.** `_flock` creates it with `O_CREAT`, and `close()` only closes the fd (line 342). After a clean close, the directory still holds `fp.db` and `fp.db.lock` (checked by hand). This is harmless, because `flock` locks are released on close or on process death, but it leaves a stray file. Deleting it safely would need care, since unlinking a lock file another process is about to lock is racy.

7. **Rename atomicity and fsync semantics are verified only on ext4, and only against SIGKILL.**
   - Compaction and creation rely on `os.replace` being atomic and on the directory `fsync` making it durable.
   - Appends rely on `fsync(fd)` covering the inode size.

   All of this was tested only on ext4 (the README platform line). No power-cut, other-filesystem or lying-disk-cache test exists. The crash between rename and directory fsync (`compact_after_rename`) was tested only with SIGKILL, where the rename is always visible.

8. **One fsync per operation, one writer at a time.** There is no group commit. A single `put` with a 100-byte value measured 1.12 ms per op (893 ops/s, 500 puts) on NVMe. Two serve writers still serialise on `self._lock` across `pwrite` + `fsync`. Batching is the only way to go faster (1M keys in 100 batches took 1.49 s).

9. **A double I/O failure leaves the write outcome uncertain.** Reproduced with injected append-sync and rollback failures. If rollback cannot be confirmed, a complete frame can remain replayable. The engine now raises `UncertainWriteError` (with both underlying errors); serve/CLI report `UNCERTAIN`, never ACK, and later mutations on the handle remain poisoned. This is an explicit unknown outcome, not a guaranteed rejection. Reopen and reconcile before retrying. No on-disk format change or guarantee of rollback through arbitrary storage failures is claimed. See `docs/uncertain_write_report.md` and `tests/test_uncertain_write.py`.

10. **Compaction can grow a file that has no dead bytes.** The 100k × 1 KB case went from 104,100,176 to 104,100,416 bytes (+240), because compaction rewrites into frames of at most 4 MiB, which gives a different frame count. Running it on a file with no dead bytes costs 411 ms of lock time for nothing. There is no "skip if dead_bytes == 0" check (`compact()` line 248).
