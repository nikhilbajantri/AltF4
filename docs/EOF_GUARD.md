# The EOF guard, explained

Owner: Nikhil. A one-page explainer so anyone on the team can answer judges from memory. It describes the code after commit f1a1c0c (PR #23). Live demo: `./prove GUARD`.

## What it is

One `00` byte written after the last complete frame of a nonempty database (`src/format.py` `TAIL_GUARD`).

- It is **not** part of any frame. No CRC covers it, and it holds no data.
- Every write ends with it: `KVDB._write` writes the frame, then the guard, then one `fsync` covers both.
- The next append starts exactly at the guard's position and overwrites it, so the file only ever has one guard, at its very end.

## Why it exists

Scenario F4 asks: if someone cuts the database file short by one byte, does `open` still succeed, and is at most the last *unacknowledged* record lost?

- **Without a guard:** the last byte of the file is the last byte of the last frame. That frame was acknowledged, so a one-byte cut loses an acknowledged record.
- **With the guard:** the last byte is the guard. A one-byte cut removes only the guard. Every frame stays complete, CRC-valid and replayable, and `open` simply writes a new guard.

## Byte pictures

Measured with `./prove GUARD`: puts `a=1`, `b=2`, `c=3`, each a 25-byte frame (12-byte frame header + 4 nops + 7 op header + 1 key + 1 value).

```
before writing c (67 bytes)
  0      16          41          66
  [HEADER][ frame a  ][ frame b  ][00]
                                   ^ guard at 66

after writing c (92 bytes): frame c starts on top of the old guard
  0      16          41          66          91
  [HEADER][ frame a  ][ frame b  ][ frame c  ][00]
                                               ^ guard at 91

after a 1-byte cut (91 bytes): only the guard is gone
  [HEADER][ frame a  ][ frame b  ][ frame c  ]
  open: all 3 frames are valid -> keeps them, writes 00 at 91 -> 92 bytes

after a torn write of frame c (kill during pwrite; k bytes landed, 1 <= k < 25)
  [HEADER][ frame a  ][ frame b  ][c, first k bytes]
  open: scan stops at 66 -> ftruncate(66), write 00 at 66 -> 67 bytes, c absent
```

## Every case, tested

Each test runs on a real disk via `tests.util.test_dir()`. Results are from this commit's full suite run, where all passed.

| Case | Disk state | What `open()` does | Result | Test |
|---|---|---|---|---|
| a | After a put | (nothing to repair) | File = frames + exactly one `00`; size = last frame end + 1 | `test_eof_guard.test_a_put_ends_with_exactly_one_guard_byte` (new) |
| b | Empty database; delete-all + compact | No guard is written for an empty database | Exactly 16 bytes | `test_engine.ShortHeaderTest.test_zero_byte_file_opens_empty`, `test_compact.CompactTest.test_delete_all_then_compact_is_header_only` (existing) |
| c | 1 byte cut (guard gone) | Every frame is valid, so nothing is truncated; guard rewritten | All keys present, including the last ACKed one | `test_tail_guard.test_put_delete_and_batch_survive_one_byte_tail_loss` (existing) |
| d | 2 bytes cut (guard + last frame byte) | The last frame is short, so it is truncated; guard rewritten | Only the last frame lost | `test_eof_guard.test_d_two_byte_cut_loses_only_the_last_frame` (new) |
| e | Torn write of 1 byte, value `00` | Size = stop + 1 and the byte is `00`, so it is taken as the guard | Nothing lost; the next put and reopen work | `test_eof_guard.test_e_one_byte_torn_write_of_00_is_read_as_the_guard` (new) |
| f | Torn write of 1 non-zero byte | Not a guard, so truncate to stop and rewrite the guard | Earlier data intact | `test_eof_guard.test_f_one_byte_torn_write_nonzero_is_truncated_and_guard_restored` (new) |
| g | Complete frame, guard missing (kill between the two writes) | Frame is valid, so it is kept; guard added and fsynced | Frame replayed (it was never ACKed; both outcomes are allowed) | `test_tail_guard.test_process_kill_between_frame_and_guard_recovers_whole_frame` (existing, real SIGKILL) |
| h | Guard + 2 junk bytes | 3 bytes past the last frame, so it is a torn tail: truncate and rewrite the guard | Back to frames + guard | `test_eof_guard.test_h_guard_plus_junk_is_truncated_back_and_guard_restored` (new) |
| i | After compaction | Compaction writes the guard into `.compact` before fsync and rename | Compacted file ends with `00` | `test_eof_guard.test_i_compaction_output_ends_with_guard` (new) |
| j | Legacy file exactly at `max_bytes`, no guard | `_restore_tail_guard` skips the guard because there is no room | Readable; file not grown | `test_tail_guard.test_legacy_frames_migrate_and_tight_cap_does_not_grow` (existing) |
| k | `./kvdb check` on frames + guard / guard + 1 junk byte | Read-only scan (`src/scan.py`) | `OK` / `OK torn-tail=2 bytes (open will truncate)`; sha256 unchanged | `test_eof_guard.test_k_check_treats_guard_as_clean_eof_and_never_modifies` (new) |
| l | `KVDB_CRASH=torn_write:1` put (SIGKILL) | Torn tail truncated, guard rewritten | Key absent; file ends with the guard | `test_eof_guard.test_l_torn_write_crash_point_then_open_keeps_guard` (new) |

## Crash-here answers (disk → open → rule)

**F4, one byte cut by hand.**
- *Disk:* every frame complete; only the trailing `00` is missing.
- *Open:* `_scan` stops at EOF, so there is no torn tail; `_restore_tail_guard` writes `00` and fsyncs.
- *Rule:* no record is lost, acknowledged or not.

**A2, torn write.**
- *Disk:* earlier frames, then the first k bytes of the new frame, written over the old guard.
- *Open:* `decode_frame` returns `None` (header or payload incomplete), so `ftruncate(stop)`, rewrite the guard, then `fsync`.
- *Rule:* the unacknowledged write is absent and earlier data is intact.

**Kill between the frame write and the guard write.**
- *Disk:* the new frame is complete; there is no guard.
- *Open:* the frame decodes with a valid CRC and is replayed; the guard is added.
- *Rule:* it was never ACKed (no `fsync` had returned), so keeping it is allowed.

**A 1-byte torn write that happens to be `00`.**
- *Disk:* byte-for-byte identical to before the write, because that position already held the guard `00`.
- *Open:* sees "stop + 1 byte, value `00`" and treats it as the guard; nothing changes.
- *Rule:* no data lost; the next append overwrites that byte as usual.
- When does it happen? Only if the new frame's length field starts with byte `00`, which means the payload length is a multiple of 256.

**"Why does the file end in `00`?" (hex dump question)**
- That byte is the EOF guard, outside every frame and CRC.
- It exists so that cutting the last byte removes padding instead of acknowledged data.
- The next write overwrites it. An empty 16-byte database has none.

## Limits

- **Empty database:** no guard; the file stays exactly the 16-byte header. There is no record to protect.
- **At-cap files:** if `max_bytes` leaves no room for one extra byte (for example, a legacy file opened with a tight cap), `_restore_tail_guard` skips the guard so the file never grows past the cap. Such a file is unprotected until room is made. New writes always reserve the byte in `_check_space`.
- **Older engine versions** (before f1a1c0c) truncate the guard away as a 1-byte torn tail. Their files are still readable by this version, which adds the guard on open.
- **Only the last byte is protected.** Cutting 2 or more bytes still reaches the last frame, which is then discarded as torn (case d).
- **Not tested:** physical power loss.

## Show it live

```bash
./prove GUARD
```

It prints the last 16 bytes in hex (the final `00` is the guard), cuts 1 byte (`check` OK, `open` restores the guard, all 3 keys present), then cuts 2 bytes (only key `c` is lost).
