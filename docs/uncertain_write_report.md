# Double I/O-failure review: explicit uncertain write outcomes

Baseline: `1bb70c6`, on branch `feat-arsh`. This is a focused follow-up to the earlier crash qualification.

## Finding

The append can write a complete valid frame, then its `fsync` can fail. The engine attempts to undo the append using `ftruncate` followed by `fsync`. If either rollback step also fails, it cannot establish that the operation is absent from durable storage.

The baseline swallowed the rollback error and returned ordinary `IO`. With both the append sync and rollback truncation deliberately failed, a process-only reopen recovered the new put, delete, or complete batch. Earlier acknowledged data remained intact. A partial append was repaired on reopen when the injected failures were removed.

These are controlled fault injections in temporary Linux databases. They establish a reachable code path; they are not measurements of real hardware-failure frequency or physical power-loss tests.

## Resolution and caller contract

- The engine now raises `UncertainWriteError`, an `OSError` subclass, if append and rollback both fail. Its `write_error` and `rollback_error` attributes retain both exceptions, and exception chaining retains the original append error.
- Serve replies `ERR <id> UNCERTAIN`; the command-line interface prints `ERR UNCERTAIN` and exits 1. No ACK/OK is emitted for that operation.
- The poisoned handle rejects later writes and compaction. Close it, reopen when storage is usable, and reconcile the affected application state before deciding whether to retry. A blindly repeated batch may overwrite changes made by another client in the meantime.
- `UNCERTAIN` is an unknown outcome: the operation may be present or absent after recovery. It does not promise that rollback succeeded. Existing clients must handle this additional response explicitly.
- If rollback truncation and synchronization both succeed, the original append error remains ordinary `IO`. Existing regression tests cover this confirmed rollback path.
- The crash tester's strict response checks reject `UNCERTAIN`. No oracle rule was relaxed, and no uncertain round is counted as passing qualification.

This corrects error reporting and preserves diagnostic evidence. It does not force an uncooperative storage system to undo a write. The file format, successful-write ordering and recovery format are unchanged.

## Before and after

Before the implementation change, seven new tests failed against the baseline because the engine exposed ordinary `OSError` and serve/CLI printed `IO`. Their recovery assertions established that complete operations could survive. These failures describe the missing error distinction, not seven independent engine-corruption defects.

Afterward, all eight focused tests passed. The eighth test launches a real server with injected double failures and confirms that the crash runner rejects its `UNCERTAIN` response.

| Check | Verified behaviour |
|---|---|
| Complete put, sync failure, truncate failure | Reopen can contain the put; caller receives explicit uncertainty; later writes and compaction are blocked |
| Complete multi-key batch, failed rollback | Reopen applies the entire batch, including its delete |
| Delete, failed rollback | Deleted key can remain deleted after reopen |
| Rollback truncates but its sync fails | Current process-only reopen sees the old state, but durability remains unconfirmed and is reported as uncertain |
| Partial append followed by failed rollback | Later successful recovery discards the incomplete tail and preserves earlier acknowledged data |
| Serve protocol | UNCERTAIN followed by POISONED, with no ACK |
| Public CLI | ERR UNCERTAIN, exit 1 |
| Crash runner | Uncertain server response raises a failed check, not PASS |

`make build` passed. The complete automated suite passed **130 tests in 45.957 seconds**. Focused suite: **8 tests in 1.312 seconds**, all passing.

Raw evidence: [before](evidence/uncertain_write_before.txt), [after](evidence/uncertain_write_after.txt), [full suite](evidence/uncertain_write_full_suite.txt). Test source: [tests/test_uncertain_write.py](../tests/test_uncertain_write.py).

## Reproduce

From the repository root in Ubuntu/WSL:

```bash
make build
python3 -B -m unittest tests.test_uncertain_write -v
python3 -B -m unittest -q
```

The earlier 7,000-round result remains evidence for its recorded source hashes. It has not been rerun on this change. Remaining technical reviews include aggregate batch memory use and the read-only scanner's possible false corruption report. Complete those reviews before freezing the code for the next final qualification.
