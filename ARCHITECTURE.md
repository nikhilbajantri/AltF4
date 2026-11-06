# Architecture

## Part 1 Diagram
```mermaid
flowchart TD
    caller["Application, CLI, server, or test"] --> api["KVDB methods: put, get, delete, batch"]
    api --> lock["Engine lock"]
    lock --> validate["Validate and encode operations"]
    validate --> frame["Build CRC-protected frame"]
    frame --> write["Write frame with os.pwrite"]
    write --> sync["os.fsync database file"]
    sync --> index["Update in-memory index"]
    index --> success["Return success; server may send ACK"]

    open["Open database"] --> filelock["Acquire path lock"]
    filelock --> check["Create file if missing; check header"]
    check --> scan["Scan frames and check CRC"]
    scan --> replay["Apply valid operations to rebuild index"]
    replay --> scan
    scan -->|Incomplete tail| truncate["Truncate tail and fsync"]
    truncate --> ready["Database ready"]
    scan -->|Malformed valid-CRC frame| error["Raise corruption error"]
    replay --> ready

    compact["Compact database"] --> live["Copy live keys into .compact file"]
    live --> tempsync["fsync temporary file"]
    tempsync --> rename["Replace database with os.replace"]
    rename --> dirsync["fsync parent directory"]
    dirsync --> swap["Reopen file and swap engine state"]
```

## Part 2 Proof table
| B1 | Crash during a 10-operation batch write | Previous saved data and possibly part of the new batch are on disk | Recovery should remove the incomplete ending | `_write()` and `_recover()` | Not verified |

| B2 | Repeat the torn batch-write test | Previous frames and possibly a partial final frame | Reopening should recover valid earlier frames and handle the incomplete tail | `_write()`; `_recover()`; `_scan()` | Not verified |

| B5 | Batch deletes X, puts X, then deletes X | A complete batch frame is on disk | Operations apply first to last, so X should be absent | `_commit()`; `_apply()`; `_scan()` | Not verified |

| C1 | Crash at `compact_before_rename` | Old database file plus a complete `.compact` file | The old database remains at the database path; reopening removes the leftover `.compact` file | `_compact_locked()`; `_open_file()`; `os.replace()` | Not verified |

| C4 | Crash at `compact_after_rename` | The compacted file is at the database path; parent-directory sync has not run yet | Reopen and check that the compacted database contains the live keys | `_compact_locked()`; `_fsync_dir()` | Not verified |

| C5 | Check the data after `compact_after_rename` | The database path points to the compacted file | Compare reopened keys and values with the expected live data | `_compact_locked()`; `_recover()` | Not verified |

| E1 | Fill a size-limited database until a put returns `DISKFULL` | Database is at its configured size limit | A rejected put should not be written or visible | `_check_space()`; `_commit()` | Not verified |

| E2 | Send a batch that does not fit | Existing database plus a batch too large for the remaining allowed space | The rejected batch should not be appended; none of its changes should be visible | `_check_space()`; `_commit()` | Not verified |

| E5 | After `DISKFULL`, delete keys and try a put again | Deleted records leave dead space that may be reclaimed | The later put should succeed if compaction frees enough space | `_commit()`; `_compact_locked()`; `_check_space()` | Not verified |

| ID | Scenario | Disk state | Mechanism | Where in code | Verified by |
|---|---|---|---|---|---|
| A1 | Crash before a write begins | Only previous frames are on disk | No new operation should appear | `_write()`; `before_write` | Not verified |
| A2 | Crash partway through a frame write | Previous frames plus an incomplete frame may be on disk | Recovery should discard the incomplete tail | `_write()`; `_recover()`; `_scan()` | Not verified |
| A3 | Crash after the complete frame write, before `fsync` | Complete frame may be in the file cache but not synced | No ACK has been sent; reopen checks whether the frame is complete and valid | `_write()`; `after_write`; `_recover()` | Not verified |
| A4 | Crash after successful `fsync`, before index update | Complete frame has been synced; in-memory index was not updated | Recovery rebuilds the index from saved frames | `_write()`; `after_fsync`; `_scan()` | Not verified |
| A5 | Crash after engine return, before server ACK | Complete frame has been synced; client may not know the result | Reopen should include the operation; client outcome is uncertain | `src/serve.py`; `after_return` (confirm hook) | Not verified |
| A6 | Write or `fsync` returns an error | A partial frame may have been written | Engine tries to truncate to old end, syncs rollback, and becomes poisoned | `_write()` | Not verified |
| A7 | Invalid operation fails validation | No new frame should be written | Validation rejects operation before append | `fmt.encode_frame()`; `_commit()` | Not verified |
| B1 | Crash during a 10-operation batch write | Previous frames and possibly part of batch are on disk | Incomplete batch frame should be discarded as a whole | `_write()`; `_recover()`; `_scan()` | Not verified |
| B2 | Repeat torn batch write at another write point | Previous frames and possibly part of batch are on disk | Reopen should retain earlier valid frames and reject incomplete tail | `_write()`; `_recover()`; `_scan()` | Not verified |
| B3 | Batch contains an invalid operation | No batch frame should be written | Validate/encode rejects batch before append | `fmt.encode_frame()`; `_commit()` | Not verified |
| B4 | Batch exceeds the operation limit | No batch frame should be written | Validation rejects batch above 10,000 operations | `fmt.encode_frame()` | Not verified |
| B5 | Batch deletes X, puts X, then deletes X | A complete batch frame is on disk | Operations apply first to last, so X ends absent | `_commit()`; `_apply()`; `_scan()` | Not verified |
| B6 | Batch contains several valid operations | One complete frame contains all operations | Recovery applies all operations from that valid frame in order | `fmt.encode_frame()`; `_scan()`; `_apply()` | Not verified |
| C1 | Crash at `compact_before_rename` | Old database plus complete synced `.compact` file | Old database remains at the database path; leftover temp is removed on next open | `_compact_locked()`; `_open_file()` | Not verified |
| C2 | Crash during `compact_mid_copy` | Old database plus partial `.compact` file | Old database remains usable; next open removes temp file | `_copy_live()`; `_open_file()` | Not verified |
| C3 | Complete a normal compaction | New compacted file contains live keys only | Synced temp file replaces old file; engine swaps to new file/index | `_compact_locked()`; `_copy_live()` | Not verified |
| C4 | Crash at `compact_after_rename` | Compacted file is at database path; directory sync has not run yet | Reopen checks the file at the database path; power-loss durability is not proven by process-kill test | `_compact_locked()`; `_fsync_dir()` | Not verified |
| C5 | Check live values after `compact_after_rename` | Database path points to compacted file | Reopen and compare all live keys/values with expected state | `_compact_locked()`; `_recover()` | Not verified |
| C6 | Crash at `compact_after_swap` | Compacted file was renamed and directory-synced; engine swapped file/index | Reopen should recover compacted data | `_compact_locked()`; `_recover()` | Not verified |
| D1 | Open database with incomplete final frame | Valid frames followed by incomplete tail | Recovery truncates at last valid frame and syncs file | `_recover()`; `_scan()` | Not verified |
| D2 | Open database with CRC-mismatched final frame | Valid frames followed by frame with bad CRC | Recovery treats final damaged tail according to format decoder and truncates it | `_recover()`; `fmt.decode_frame()` | Not verified |
| D3 | Open database with CRC-valid malformed frame | Frame bytes and CRC are present, but operation data is invalid | Report corruption; do not silently truncate as a torn tail | `_scan()`; `fmt.decode_frame()` | Not verified |
| D4 | Crash during recovery truncation | File may still contain torn tail, or truncation may have completed | Reopen repeats recovery; after truncation it syncs valid end | `_recover()`; `recovery_before_truncate`; `recovery_after_truncate` | Not verified |
| E1 | Fill limited database until a put returns `DISKFULL` | Database has reached configured limit | Rejected put should not be appended or visible | `_check_space()`; `_commit()` | Not verified |
| E2 | Send a batch that does not fit | Existing database plus oversized batch | None of the rejected batch changes should be visible | `_check_space()`; `_commit()` | Not verified |
| E3 | Use reserved space for a delete | File is near limit but delete reserve remains | Delete-only write may use reserved bytes | `_check_space()` | Not verified |
| E4 | `DISKFULL` occurs while dead bytes exist | File contains obsolete records that can be reclaimed | Engine compacts and retries the write once | `_commit()`; `_compact_locked()`; `_check_space()` | Not verified |
| E5 | After `DISKFULL`, delete keys and try a put again | Deleted records leave reclaimable dead bytes | Later put should succeed if compaction frees enough room | `_commit()`; `_compact_locked()`; `_check_space()` | Not verified |
| F1 | Open same database a second time | First process holds `<path>.lock` | Second open should fail with `LockedError` | `_flock()` | Not verified |
| F2 | Two operations from the same writer arrive in order | Both operations are submitted to same writer queue | Server should process that writer’s commands in input order | `src/serve.py` worker/queue (confirm) | Not verified |
| F3 | Two writer threads write concurrently | Multiple complete frames may be appended | Engine lock serializes writes so frames do not overlap | `_commit()`; `self._lock` | Not verified |
| F4 | Read while a write or compaction is in progress | File/index update is protected by engine lock | Reader waits for lock and sees a consistent index/file state | `get()`; `items()`; `_commit()`; `compact()` | Not verified |

| ID | Scenario | Disk state | Mechanism | Where in code | Verified by |
|----|----------|------------|-----------|---------------|-------------|
| A1 | | | | | |
| A2 | | | | | |
| A3 | | | | | |
| A4 | | | | | |
| A5 | | | | | |
| A6 | | | | | |
| A7 | | | | | |
| B1 | | | | | |
| B2 | | | | | |
| B3 | | | | | |
| B4 | | | | | |
| B5 | | | | | |
| B6 | | | | | |
| C1 | | | | | |
| C2 | | | | | |
| C3 | | | | | |
| C4 | | | | | |
| C5 | | | | | |
| C6 | | | | | |
| D1 | | | | | |
| D2 | | | | | |
| D3 | | | | | |
| D4 | | | | | |
| E1 | | | | | |
| E2 | | | | | |
| E3 | | | | | |
| E4 | | | | | |
| E5 | | | | | |
| F1 | | | | | |
| F2 | | | | | |
| F3 | | | | | |
| F4 | | | | | |

## Part 3 Durability / Atomicity / Recoverability

### Durability
A successful write is not reported immediately. The engine first writes the encoded frame to the database file using `_pwrite_all()`, which calls `os.pwrite()` until all frame bytes have been written. It then calls `os.fsync()` on the database file. Only after `_write()` returns does `_commit()` update the in-memory index and finish the operation. The server can send an ACK after the engine call returns.

This ordering means that if the process crashes after `fsync()` but before updating the in-memory index, reopening the database can rebuild the index by scanning the saved frames. If a write or sync raises `OSError`, `_write()` tries to truncate the file back to the previous end, syncs that rollback, marks the engine poisoned, and raises the error.


### Atomicity
A batch is encoded into one frame. The frame is treated as the commit unit: recovery should apply the batch only if the complete frame passes the format checks. Operations inside a valid batch are applied in order, from first to last. For example, deleting X, putting X, and then deleting X should leave X absent.

An incomplete frame or a frame with a CRC mismatch at the end is handled as a torn tail during recovery. A CRC-valid frame with malformed contents is reported as corruption rather than silently treated as a torn write. Confirm these cases against `src/format.py`.


### Recoverability
When opening the database, the engine takes an exclusive lock, removes leftover `.compact` and `.init` files, checks the database header, and scans frames to rebuild the index. If it finds a torn tail, it truncates the file to the last valid frame and calls `fsync()`.

During compaction, the engine writes live keys to a `.compact` file, syncs and closes that file, replaces the database using `os.replace()`, and syncs the parent directory. It then reopens the database and swaps in the new file and index.

These steps are intended to leave a recoverable database if the process stops during recovery or compaction. The crash tests should confirm the behavior at each crash point. The code shown does not by itself prove behavior during a real power failure or on filesystems that have not been tested.
