# Review fixes and verification

Date: 2026-11-06. Baseline: main 95743fd, merged into feat-arsh before implementation. The original review in review_report.md remains historical evidence of the earlier defects.

## Outcome

All eleven original open issues (#3-#13) are addressed in this branch. One additional documentation defect was filed as #14 and corrected here. Issues remain open until the PR merges.

| Issue | Problem | Resolution |
|---|---|---|
| [#3](https://github.com/nikhilbajantri/AltF4/issues/3) | Non-UTF-8 serve input | Decode physical lines safely; reject invalid input and whole invalid batches without exiting. |
| [#4](https://github.com/nikhilbajantri/AltF4/issues/4) | CLI stubs | Implement all ten documented commands, including read-only check/inspect; runner uses CLI open/check/dump. |
| [#5](https://github.com/nikhilbajantri/AltF4/issues/5) | Six missing torture modes | All seven modes are runnable; three random concurrent modes and four targeted modes. |
| [#6](https://github.com/nikhilbajantri/AltF4/issues/6) | Skipped truncation undetected | Default forces torn_write every fifth round starting at one; isolated planted omission fails iteration 1, seed 12345. |
| [#7](https://github.com/nikhilbajantri/AltF4/issues/7) | Undocumented errors | Document IO, UNSUPPORTED, INTERNAL, BUSY and startup errors in README. |
| [#8](https://github.com/nikhilbajantri/AltF4/issues/8) | Unreadable failure dumps | Bound console differences to five keys and twelve op IDs, with lengths/hashes; preserve full details in failure.txt. |
| [#9](https://github.com/nikhilbajantri/AltF4/issues/9) | Narrow workload | Broader delay range, batches through 10,000, shared-key ordering, deliberate rejection, idle gaps, three crashes per default database. |
| [#10](https://github.com/nikhilbajantri/AltF4/issues/10) | Benchmark script imports | Both standalone benchmark scripts add the repository root before imports; actual direct executions succeeded. |
| [#11](https://github.com/nikhilbajantri/AltF4/issues/11) | Uncaught oracle errors | ValueError and malformed tool data become TOOL ERROR/exit 2. |
| [#12](https://github.com/nikhilbajantri/AltF4/issues/12) | Broken BUGS table | Remove separating blank line and record statuses. |
| [#13](https://github.com/nikhilbajantri/AltF4/issues/13) | Writer queue stalls input | Nonblocking enqueue returns BUSY when full; another writer continues. |
| [#14](https://github.com/nikhilbajantri/AltF4/issues/14) | Stale BREAKING proof | Newly filed issue: restore after_return in the 14-hook table and update evidence/failure history. |

## Validation

- `make build`: BUILD OK. This WSL installation initially lacked make; installing the Ubuntu make package resolved that environment prerequisite.
- `python3 -B -m unittest -q`: 104 tests passed in 35.759 seconds.
- Direct `./kvdb open` and `./kvdb check` executions passed.
- All seven modes passed 100 rounds each using the original review's recorded seeds (700 rounds total):

| Mode | Seed | Result |
|---|---|---|
| default | 552777022 | 100/100 |
| large-values | 77173339 | 100/100 |
| large-batch | 972750935 | 100/100 |
| compaction | 978142283 | 100/100 |
| recovery-crash | 132829190 | 100/100 |
| disk-full | 281923561 | 100/100 |
| crashpoints | 664061492 | 100/100 |

The new default-mode evidence includes 10,000-operation batches, 254 shared-key operations and 145 rejected operations. Random kill delays span approximately 2 ms to 1 s, and the run's awaiting-response rate was 80%; it is no longer assumed to be 100%. Large-values and large-batch had 56% and 79% awaiting-response rates respectively. These are observed coverage metrics, not proof that the engine was inside a syscall when killed.

Targeted modes report a zero random delay because they use exact named crash hooks. Recovery can be killed before READY; compaction covers all four swap/copy points; disk-full validates rejected batches, deletes at the cap, close crashes, and reclaimed space; crashpoints cycles all 14 names. Those targeted modes are not claims of two concurrent random writers at every crash.

Planted-fault regression: a disposable copy with recovery ftruncate removed fails default mode at iteration 1, seed 12345. Production engine files were not altered for the trial. Existing isolated early-ACK and partial-batch detector trials also pass in the full suite.

Direct benchmark execution now works:

| Command / case | Observed result |
|---|---|
| python3 tests/bench_recovery.py | 1M-key recovery 657.4 ms; deletes + compact reduced 54,003,216 bytes to 16 |
| python3 tests/bench_compact.py: 1M live + overwrites | 1,504.7 ms; 74,003,216 to 37,001,616 bytes |
| python3 tests/bench_compact.py: 100k x 1 KiB | 269.0 ms; 104,100,176 to 104,100,416 bytes (no dead data; frame packing adds overhead) |

These measurements were on this WSL host, during other test activity, and are not a dedicated demo-laptop qualification.

## Evidence and rerun commands

Mode results and full stdout/stderr: `/home/arsht/tmp_test/review-fix-runs/modes-ut78_mw7/results.json` and adjacent mode-name `.log` files. Each mode subdirectory contains its unique run directory, operation transcript, and databases. Tests run against Linux test databases; source is the existing mounted Windows checkout.

```bash
make build
python3 -B -m unittest -q
./torture --iterations 100 --seed 552777022 --mode default
./torture --iterations 100 --seed 77173339 --mode large-values
./torture --iterations 100 --seed 972750935 --mode large-batch
./torture --iterations 100 --seed 978142283 --mode compaction
./torture --iterations 100 --seed 132829190 --mode recovery-crash
./torture --iterations 100 --seed 281923561 --mode disk-full
./torture --iterations 100 --seed 664061492 --mode crashpoints
```

## Remaining scope

The shared-key oracle supports single-operation changes to shared/status, with ordering constrained by observed SENT/response events. Batches use private keys; arbitrary shared multi-key batches remain outside this checker. Shared coverage here therefore does not imply general transaction serializability checking. Full 500-round-per-mode qualification, physical power-loss tests, and final clean-clone/offline/demo rehearsal remain separate release work. No new engine data-loss bug was found during this issue-fix verification.
