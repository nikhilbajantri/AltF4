# Ordering argument (draft for Varsha)

Line numbers are `src/engine.py` unless another file is named.

**Invariant.** At every instant, the file at `<path>` is:

- a valid header,
- followed by zero or more CRC-valid frames,
- optionally followed by a torn tail.

Every acknowledged operation is inside a frame in that durable prefix. Any other file present (`<path>.init`, `<path>.compact`) is a leftover that the next open deletes without reading it.

## 1. Appends: pwrite → fsync → index → return → ACK

- **pwrite before fsync** (`_write` lines 212, 214). `fsync` makes durable only what has already been written, so the frame must be completely written first. `_pwrite_all` loops until every byte is written, so `fsync` never covers half a frame.
- **fsync before index** (`_commit` lines 191-195). If `pwrite` or `fsync` fails, the index must never have known about the frame. With this order, the failure path only needs `ftruncate(end)` + poison and has nothing to undo in memory. (A concurrent `get` cannot see the index mid-update in either order, because `_commit` holds `self._lock` from before `pwrite` until after the index update.)
- **index before return.** The caller's next `get` must see its own write.
- **return before ACK** (`src/serve.py` `run.execute`). `ACK` is printed only after the engine call returns, and that return happens only after `fsync`. Every kill point therefore falls into one of these cases:
  - Before `fsync` returned: no ACK exists, so losing the op is allowed, and recovery either drops it (torn) or keeps it (complete). The oracle allows both.
  - After `fsync` but before the ACK (`after_fsync`, `after_return`): the op survives without an ACK. That is allowed, because a client that got no reply cannot assume either outcome.
  - After the ACK: the frame was durable before the ACK existed.

The planted-bug run on 2026-11-06 shows why this order matters: serve was changed to ACK before the engine call, and `./torture --iterations 100 --seed 12345` failed at iteration 2, with an acknowledged 10,000-op batch `w2-0` missing.

## 2. Why an append needs no directory fsync

`fsync(2)` on the file descriptor flushes the file's data and the inode metadata needed to read it back, including the new size. What it does not cover is the directory entry that names the file. That is only needed when a name is created or changed.

An append creates no name. `<path>` got its entry once, in `_create`, and that entry was made durable by `_fsync_dir` (line 129) before the first frame could be written. So for an append, `fsync(fd)` alone is enough.

## 3. Temp-file-then-rename: write → fsync → os.replace → dir fsync

This pattern is used by `_create` (`<path>.init`, lines 119-129) and by `_compact_locked` (`<path>.compact`, lines 265-291).

1. **Write and fsync the temp file before the rename.** Otherwise a power cut after the rename could leave `<path>` naming a file whose data blocks never reached disk. That would be an empty or partial file under the real name: the old data is gone and the new data is missing.
2. **`os.replace`** is `rename(2)`. On the same filesystem it atomically swaps which inode the name points to, so any observer sees the complete old file or the complete new file, never a mix. The temp file is in the same directory, so the rename is always on the same filesystem.
3. **Directory fsync after the rename** (`_fsync_dir`, line 282). The rename changed a directory entry, so it is durable only once the directory is synced. Until then, a power cut may bring back the old name. That is still safe, because the old file is complete. After the directory fsync, the compacted file is permanent, so the engine can reopen it and switch to the new fd (line 283).

If the directory fsync or the reopen fails, the engine is poisoned (lines 284-288). Its old fd now points at an unlinked inode, so further writes through it would be lost.

4. **Any crash before step 3 leaves a temp file.** `_open_file` (lines 105-110) deletes both temp names first thing on the next open. A half-written temp file is never read.

## 4. SIGKILL after write but before fsync keeps the data; a power cut might not

After `os.pwrite` returns, the bytes are in the kernel's page cache, which belongs to the kernel, not to the process. SIGKILL destroys the process's memory and file descriptors, but not the page cache. The kernel still writes those dirty pages back later, and any process that opens the file in the meantime reads them from the cache.

So after a SIGKILL at `after_write` (line 213), the next open finds the complete frame with a valid CRC and replays it. `tests.test_engine.CrashPointTest.test_after_write` asserts exactly that.

A power cut destroys the page cache. If the frame was not yet written back, it is absent. If part of it was written back (the kernel may write blocks in any order), the CRC check in `format.decode_frame` (`src/format.py` line 123) rejects it, or it is short. Either way it is a torn tail and `_recover` truncates it.

None of this loses an acknowledged op, because the ACK only happens after `fsync`. The power-cut half of this argument has not been tested (no power-cut rig). It relies on ext4 honouring `fsync`, and on the drive not lying about its write cache.
