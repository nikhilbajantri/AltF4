# Breaking It

## 1 Crash points table
| # | Crash point in engine | What the code says should happen after reopening | Test result |
|---:|---|---|---|
| 1 | `init_before_rename` | The database header was synced to `.init`, but not renamed to the database path. Reopening should handle the missing database and initialize it. | Not run |
| 2 | `before_write` | No new frame bytes were written. Previous committed data should remain. | Not run |
| 3 | `torn_write_prefix` / `crash.kill()` | Only part of a frame was written. Recovery should discard the incomplete tail and keep earlier valid frames. | Not run |
| 4 | `after_write` | The full frame was written, but `fsync` has not happened. No ACK was sent. On reopening, check whether recovery accepts the complete valid frame. | Not run |
| 5 | `after_fsync` | The frame was synced, but the in-memory index was not yet updated and no ACK was sent. Reopening should rebuild the index from the file. | Not run |
| 6 | `recovery_mid_scan` | The crash happens while recovery is reading frames. Reopening should scan again from the beginning. | Not run |
| 7 | `recovery_before_truncate` | Recovery found a torn tail but has not truncated it yet. Reopening should retry recovery. | Not run |
| 8 | `recovery_after_truncate` | Recovery truncated and synced the torn tail. Reopening should find the valid frames only. | Not run |
| 9 | `compact_mid_copy` | The old database still exists; the temporary `.compact` file is only partly written. Reopening should use the old database. | Not run |
| 10 | `compact_before_rename` | The old database exists and the new `.compact` file is complete and synced. Reopening should use the old database if the rename has not happened. | Not run |
| 11 | `compact_after_rename` | The database path now refers to the compacted file; directory sync has not yet happened. Test reopening after this point. | Not run |
| 12 | `compact_after_swap` | The compacted file has been renamed, directory-synced, and swapped into the engine. Reopening should recover the compacted data. | Not run |
| 13 | `close_mid` | The comment says committed frames are already durable. Reopening should retain committed data. | Not run |
| 14 | `fsync` error | `_write()` tries to truncate back to the old end, syncs again, and marks the engine poisoned. No dedicated fsync-error crash hook is visible in this file. | Not implemented / not run |

## 2 Ordering argument
The engine validates and encodes each operation, writes the complete frame to the database file, and calls fsync before updating the in-memory index or returning success. This means the caller receives success only after the frame has been synced. If the program crashes after the frame is synced but before the index is updated, recovery rebuilds the index from valid frames in the file. If a crash leaves an incomplete frame at the end, recovery truncates the torn tail. In this code, after_write is before fsync, and after_fsync is after fsync but before the index update.

## 3 Known weaknesses
1. The database has only been tested on WSL2 with ext4; behavior on other filesystems has not been verified.
2. The crash tests stop the program, but do not simulate a real power failure or faulty storage.
3. CRC32 can detect accidental data damage, but it is not designed to prevent deliberate tampering.

## 4 What we tried that failed
No failed attempt has been captured yet. Crash tests not yet run are listed as “Not tested” in the crash points table.
- Mode: [actual test mode]
- Seed: [actual seed]
- Command: `[exact command you ran]`
- What failed: [what actually happened]
- Status: [still open / fixed in commit <commit-id>]


## 5 If we had 24 more hours
1. **P0:** Run every implemented crash point, reopen the database, and record whether the expected keys and values survived.
2. **P1:** Test crashes during compaction before and after the file replacement; verify the database reopens with all live keys.
3. **P2:** Test recovery on another supported Linux filesystem and record the results.
