# Guarantees (draft for Varsha)

Draft written by Nikhil from the code at commit 686bbbb plus the uncommitted torture tuning. Line numbers are `src/engine.py` unless another file is named. Varsha owns the final wording.

## Durability

An operation is durable before anyone is told it succeeded.

1. `KVDB.put` / `delete` / `batch` all call `KVDB._commit` (lines 168-196).
2. `_commit` validates and calculates the encoded size without materializing the payload. Under `self._lock`, it rejects poisoned handles and checks the database cap before calling `format.prepare_frame`. Small frames use the existing encoder; large frames use immutable parts and bounded chunks. Line numbers below describe the earlier baseline; see docs/batch_memory_review.md for this follow-up.
3. Inside the lock, `KVDB._write` calls `os.pwrite` through `_pwrite_all`, which handles a large frame in bounded chunks. `_pwrite_all` loops until every byte is written and raises `OSError` if a call makes no progress.
4. `_write` then calls `os.fsync(self._fd)` (line 214).
5. Only after `_write` returns does `_commit` update the in-memory index and `self.end` (lines 192-195). Then the lock is released and the method returns.
6. In `src/serve.py` `run.execute`, `reply("ACK " + op_id)` runs only after `db.put` / `db.delete` / `db.batch` / `db.compact` returned. `reply` uses `print(..., flush=True)`.

So the order is: `pwrite` → `fsync(file)` → index → return → `ACK` → flush.

The file's own directory entry is made durable once, when the file is created, by `KVDB._create` (lines 119-129):

- `os.open(<path>.init, O_CREAT|O_TRUNC)`, `pwrite` of the 16-byte header, then `fsync`;
- `os.replace(<path>.init, <path>)`;
- `_fsync_dir` (lines 22-27): `os.open(dir, O_RDONLY|O_DIRECTORY)` + `os.fsync`.

If `pwrite` or `fsync` fails, `_write` calls `os.ftruncate(fd, self.end)` + `os.fsync`, sets `self._poisoned`, and re-raises. If rollback truncation or its synchronization also fails, `UncertainWriteError` retains both errors and the public response is `UNCERTAIN`: the operation may be replayed after reopen. A caller must reconcile that outcome before retrying. An append failure with confirmed rollback remains `IO`. It never retries the failed append `fsync`. Every later write raises `PoisonedError` (line 182), so a write after a failed `fsync` can never be acknowledged.

The limit of this claim: it rests on Linux `fsync(2)` semantics on ext4. It has been tested only with SIGKILL, never with a power cut.

## Atomicity

Every `put`, `delete` and `batch` (up to 10,000 ops) is exactly one frame: `len u64 | crc u32 | payload`.

- The CRC covers the 8 length bytes and the whole payload (`format.encode_frame`, `src/format.py` lines 95-98).
- On recovery, `format.decode_frame` (`src/format.py` lines 101-127) accepts a frame only if:
  - at least 12 header bytes remain (line 112),
  - every payload byte is present (line 118),
  - and the CRC matches (line 123).
  Otherwise it returns `None`, and the frame and everything after it count as a torn tail.
- `KVDB._scan` (lines 146-155) applies a frame's ops with `_apply` only after `decode_frame` has returned the whole decoded frame. A half-written batch therefore contributes zero ops.

While the process is running, the index for all ops of a frame is updated inside `self._lock`, and `get` takes the same lock (line 229). A reader sees a batch either entirely or not at all; `tests.test_crash_campaign.test_reader_cannot_observe_half_applied_batch` checks this.

Compaction swaps files atomically with one `os.replace` (line 276).

## Recoverability

`KVDB.__init__` (lines 68-91) always runs the same sequence, so every crash leaves a state that this sequence can handle:

1. `_flock`: `os.open(<path>.lock, O_RDWR|O_CREAT)` + `fcntl.flock(LOCK_EX|LOCK_NB)`. If it is held, raise `LockedError`. A SIGKILLed holder releases the lock automatically.
2. `_open_file`: `os.remove` of `<path>.compact` and `<path>.init` (leftovers of a crashed compaction or creation). Then, if `<path>` is missing or holds only a prefix of a valid header (`_is_header_prefix`), call `_create` (see Durability above).
3. `_recover`: `os.fstat` size, `mmap.mmap(ACCESS_READ)`, `format.check_header`.
4. `_scan`: walk the frames from offset 16 until `decode_frame` returns `None`.
5. If `stop < size`: `os.ftruncate(fd, stop)` + `os.fsync(fd)`.
6. `end = stop`.

The scan only reads, so a crash at any point during recovery leaves the file as it was, or with the tail already cut and synced. The next open repeats the same steps.

Recovery deliberately refuses to "fix" some files. These raise `CorruptError` and truncate nothing, so a person has to look at them:

- a bad header;
- a file shorter than 16 bytes that is not a header prefix;
- a frame whose CRC is valid but whose content is malformed (`format._parse_payload`).
