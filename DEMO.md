# Demo
# Demo

## Build

Run from the project folder:

```bash
make build
```

Actual output:

```text
[TODO: paste the output from your run]
```

## Torture commands

Run the current default torture test:

```bash
python3 ./torture --iterations 25 --seed 12345
```

Actual output:

```text
[TODO: paste the output from your run]
```

## Manual kill session

Start the server:

```bash
mkdir -p ~/tmp_test
python3 -m src.serve ~/tmp_test/practice.db
```

When the server is ready, type:

```text
put w1-1 color blue
get w1-2 color
del w1-3 color
quit
```

Actual server output:

```text
[TODO: paste the output from your run]
```

## 12-minute demo plan

| Minute | Action |
|---:|---|
| 0 | Introduce the database. |
| 1 | Run `make build` and show its result. |
| 2 | Start the server. |
| 3 | Put a value and show the response. |
| 4 | Get the value and show the response. |
| 5 | Delete the value and show the response. |
| 6 | Run the torture test. |
| 7 | Show the torture test result. |
| 8 | Explain the write order: write frame, `fsync`, update index, return success. |
| 9 | Explain recovery after an incomplete frame. |
| 10 | Explain what happens during compaction. |
| 11 | Answer the crash questions below. |
| 12 | Answer the TTL question and summarize what was tested. |

## Crash-here answers

Use this answer order: **what is on disk → what the next open does → what safety rule this shows**. These are expected behaviors from the engine code; mark them verified only after running the tests.

1. **`before_write`:** No new frame is written → reopening finds earlier frames → a write that never started is absent.
2. **Torn write:** A partial frame may be on disk → recovery removes the incomplete ending → a partial frame is not committed.
3. **`after_write`:** The full frame may be present but is not synced → reopening checks whether it is complete and valid → no ACK was sent yet.
4. **`after_fsync`:** The frame is synced, but the index may not be updated → reopening rebuilds the index → saved data can be recovered.
5. **`after_return`:** The engine returned, but an ACK may not have been sent → reopening checks the saved frame → the client may not know whether the operation completed.
6. **`recovery_mid_scan`:** The database is being read → reopening scans it again → scanning does not change the file.
7. **`recovery_before_truncate`:** The damaged ending is still present → reopening should truncate it → only valid frames remain.
8. **`recovery_after_truncate`:** The damaged ending was removed and synced → reopening finds valid frames → the repair was saved.
9. **`compact_mid_copy`:** The old file and a partial temporary file may exist → reopening removes the temporary file and uses the old file → incomplete compaction does not replace the database.
10. **`compact_before_rename`:** The old file and a complete temporary file exist → reopening should use the old file → replacement happens after the new file is ready.
11. **`compact_after_rename`:** The compacted file is at the database path, but the directory sync has not run → reopen and check it → a process-crash test does not prove power-loss behavior.
12. **`compact_after_swap`:** The compacted file was renamed and synced → reopening should recover it → compaction should preserve live keys.

## TTL answer

This database does not support TTL (automatic key expiration). Keys stay in the database until they are deleted.

## Rehearsal

I will rehearse this demo twice and correct any command or explanation that does not match what actually happens.

## Build

## Torture commands

## Manual kill session

## Crash-here answers

## TTL answer
