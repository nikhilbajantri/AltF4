# Major crash-testing report

Recorded: 2026-11-06 15:09 IST. Platform: Ubuntu 24.04 / WSL2, Python 3.12.3. Test databases: Linux ext4 under `~/tmp_test`; source files: mounted Windows repository. This is functional crash testing, not a performance or power-loss certification.

## Result

- 2,000 random SIGKILL/recovery rounds passed across four seeds (500 each).
- The first 1,500 rounds preceded the zero-progress write guard; the final 500 used the fixed engine and stricter recovery probe.
- Final full unittest suite: 92 tests passed in 33.059 seconds, including the targeted campaign.
- Final targeted campaign: 123 confirmed SIGKILL exits covering all 14 named crash points. These are additional to the random rounds; repeated earlier test executions are not counted here.
- One engine hang was reproduced with injected zero-progress writes, fixed, and verified by a regression test. No recovered-data violation was found in the healthy-engine campaign.
- Three planted faults were rejected using isolated copies; production files were not deliberately broken.

## Random results

| Seed | Passing rounds | w1 ACKs | w2 ACKs | Kills with a request awaiting response |
|---|---|---|---|---|
| 20261106 | 500/500 | 2279 | 2015 | 100.0% |
| 987654321 | 500/500 | 1937 | 1698 | 100.0% |
| 42 | 500/500 | 1900 | 1646 | 100.0% |
| 20261107 | 500/500 | 2263 | 2010 | 100.0% |

Each round sends seeded puts, deletes, and small batches from two stop-and-wait writers using private key namespaces. A separate transcript tracks SENT/ACK/ERR. Recovery runs open, check, and dump through a subprocess adapter. The independent oracle compares the entire recovered map against up to four allowed worlds. An unanswered operation may be wholly present or absent; partial batches, lost acknowledged operations, extra keys, and incorrect values fail.

The awaiting-response metric includes pipe transit and scheduling; it does not establish that a disk write was actively executing at the instant of each random kill. Named hooks provide deterministic crash locations. Identical seeds reproduce planned workloads and delays, not OS scheduling or identical sent/ACK counts.

## Named crash locations (final suite)

| Crash point | Confirmed SIGKILL exits | Result |
|---|---|---|
| `after_fsync` | 15 | PASS |
| `after_return` | 15 | PASS |
| `after_write` | 15 | PASS |
| `before_write` | 15 | PASS |
| `close_mid` | 6 | PASS |
| `compact_after_rename` | 3 | PASS |
| `compact_after_swap` | 3 | PASS |
| `compact_before_rename` | 3 | PASS |
| `compact_mid_copy` | 3 | PASS |
| `init_before_rename` | 3 | PASS |
| `recovery_after_truncate` | 9 | PASS |
| `recovery_before_truncate` | 9 | PASS |
| `recovery_mid_scan` | 9 | PASS |
| `torn_write` | 15 | PASS |

Write locations were exercised for overwrites, deletes, multi-operation batches, maximum 1,048,576-byte values, and 10,000-operation batches, with three repetitions each. Every write-crash case also verifies a subsequent acknowledged write after recovery. Compaction uses multiple output frames and verifies writes after reopening the swapped file. Recovery tests crash three successive opens before a final successful open.

## Additional coverage

- Every incomplete byte boundary of a 56-byte final batch frame: previous acknowledged state preserved and torn tail removed.
- Every short valid-header prefix from 0 through 15 bytes: opens as an empty database.
- Disk cap: writes and oversized batches rejected without changing acknowledged state; delete reserve works; compaction frees space; too-small compaction caps preserve the authoritative file.
- Shared-key contention: 15 sessions with 40 competing two-key batches each; final keys agree and contain a valid final writer value. This is not yet a full shared-key random-crash oracle.
- Reader deliberately scheduled while the batch index is half applied: blocked until the complete batch becomes visible.
- Existing suite also covers checksum/malformed frames, process locking, short-write failures, fsync failures, and compaction failures.

## Faults found and detector validation

1. **Engine zero-progress write hang.** Injecting `os.pwrite(...)=0` made `_pwrite_all` loop forever. A disposable subprocess timed out after 3 seconds before the fix. The loop now raises an I/O error when no progress is made; existing rollback/poison handling rejects subsequent writes, and reopen recovers the previous state. Regression test passes. This was injected behavior, not observed physical disk failure.
2. **Tester accepted an unrepaired torn tail.** The probe previously accepted any successful `check_file` result, including `OK torn-tail=...` after recovery. It now requires exactly `OK` after recovery.
3. **Planted early ACK:** seed 314159, caught in iteration 1 by the random runner.
4. **Planted partial batch:** seed 314159, caught in iteration 1 by the random runner.
5. **Planted skipped truncation:** rejected by the stricter recovery probe on a prepared torn-tail fixture. This was a targeted detector trial, not a random-run detection claim.

First-failure reproduction evidence: `/home/arsht/tmp_test/major-campaign-zero-write-before/`. Final regression evidence is in the final campaign folder below. Early, partial, and skip-truncation detector copies and detection logs are retained there as well.

## Reproduce

From the repository root in WSL:

```bash
python3 -B -m unittest -q
python3 -B -m unittest tests.test_crash_campaign -v
python3 -B ./torture --iterations 500 --seed 20261106
python3 -B ./torture --iterations 500 --seed 987654321
python3 -B ./torture --iterations 500 --seed 42
python3 -B ./torture --iterations 500 --seed 20261107
```

Optional: set `KVDB_CAMPAIGN_REPEATS` to increase targeted repetitions (default 3) and `KVDB_CAMPAIGN_DIR` to choose a fresh evidence directory. The campaign preserves disposable databases, command fixtures, child stdout/stderr, input hashes, and crash seeds. To reproduce the exact evidence layout, use `KVDB_CAMPAIGN_DIR=/home/arsht/tmp_test/major-campaign-fixed-final-20261106` with a new suffix to avoid appending to existing evidence.

## Evidence

Final full-suite targeted events: `/home/arsht/tmp_test/major-campaign-fixed-final-20261106/events.jsonl`.

Random transcript/database directories:

- `/home/arsht/tmp_test/torture_data/seed-20261106-8scjn5ux`
- `/home/arsht/tmp_test/torture_data/seed-987654321-dsew1niu`
- `/home/arsht/tmp_test/torture_data/seed-42-22v0ke1o`
- `/home/arsht/tmp_test/torture_data/seed-20261107-ke88ls44`

## Limits and remaining work

Finite tests do not exhaust every instruction timing. No physical power cut, host/VM reset, real filesystem exhaustion, sector-level torn-write emulator, or hardware fault was induced. Most disk-full testing uses the configured byte cap; low-level I/O errors in unit tests are injected. Process SIGKILL preserves the OS page cache, so successful process-crash runs do not prove power-loss durability. Targeted short-header and tail tests intentionally truncate copied fixture files; arbitrary middle-file bit rot remains outside the product guarantee.

The random CLI currently supports default mode only. Large values/batches, recovery crashes, compaction, and disk-full have targeted campaign coverage, not independent 500-round qualifications for all seven PRD modes. Shared-key random-crash ordering, a 1M-key benchmark on the demo laptop, and full seven-mode release gates remain pending. The main CLI is still a stub, so the runner uses `src.serve` and the temporary open/check/dump adapter.

## Tested source identity

Git base: `02f5c47f4573a0ffeff447895a4d96e0e335121f` plus local, uncommitted changes. No commit, push, or PR update was performed for this campaign. Hashes identify the final tested implementation:

| File | SHA-256 |
|---|---|
| `src/engine.py` | `67ab34cf98e0367f487c014b39d16263852cff4495b91d3d17b4bbcf154bdbfe` |
| `src/serve.py` | `3e381ee21f0082d64e795a28aa36b8550ca2187e1c6b799fcb710e754dd0382c` |
| `torturelib/runner.py` | `4a78e9ee1ee6ffc1cbb82349bd15a69ff9add1a5cdc43c8cb04aa1a1acc7628e` |
| `torturelib/crash_probe.py` | `5c6de1278b262f19318c6056979c8ad9bf7094678b44b0328188135bca3bdaf1` |
| `tests/test_crash_campaign.py` | `f48bea63f36e7570c2fb934898d1c85bafc2d841ecfe887c1a6e0f06ae76c12c` |
