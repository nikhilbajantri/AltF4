# Arsh manual testing and judge rehearsal report

**Test date: 7 November 2026 (Asia/Kolkata). Tested commit: `f1a1c0cc008dcd764baad749d35d4f1ed0d6822b`.** Operator: Arsh, using Ubuntu 24.04/WSL and Python 3.12.3 on his laptop.

**Result: the recorded manual database checks and all executed automated tests passed. The measured build, 200-round and selected targeted-mode workloads fit their judging slots; strict recovery measurements passed. The complete 15-minute human/offline judging rehearsal is not yet verified.**

[Command-by-command guide](docs/MANUAL_TEST_COMMANDS.md) | [Original terminal output](docs/evidence/manual-testing-2026-11-07/terminal-session.txt) | [Evidence audit](docs/evidence/manual-testing-2026-11-07/audit.json) | [File checksums](docs/evidence/manual-testing-2026-11-07/checksums.json)

## What was tested and how to read the times

Arsh typed the setup and test commands himself. The put/get/delete/batch checks and external kills were hands-on checks; the torture and acceptance commands then automated many child-process crashes. This report does not label those automated rounds as human manual kills.

Bash `time` measures total elapsed wall time for its command block. `recovery_ms` measures engine recovery inside open. CLI wall time also includes interpreter startup; API wall time surrounds the library call. These measurements are labelled separately. A time not captured in the source evidence is marked unmeasured.

The tested source was cloned locally from D: into `/home/arsht/tmp_test/arsh-judging-gdhZIl/AltF4`; database/evidence files were on Linux storage. All source hashes in the full campaign manifest match the tested clone and the current branch after CRLF-to-LF normalization. Subsequent changes for this report and the merge from main affect documentation only.

## Judge-format timing results

| Check | Measured elapsed time | Limit / judging slot | Result |
|---|---:|---|---|
| Fresh local clone plus README build | 2.559 s | 60 s, minutes 0-1 | PASS; 57.441 s spare |
| 200 default random crash rounds, seed 84217 | 103.159 s | 180 s, minutes 1-4 | PASS 200/200; 76.841 s spare |
| Compaction 100 rounds + recovery-crash 100 rounds, seeds 84218/84219 | 37.069 s combined | 120 s, minutes 4-6 | PASS 100/100 in each; 82.931 s spare |
| Judge-format human batch and kill repetitions | Whole-slot time not recorded; one repetition visible | 5-10 manual kills in 120 s, minutes 6-8 | One successful recovery; full slot not verified |
| Three source-line crash questions | Not recorded | 240 s, minutes 8-12 | Human rehearsal pending |
| Expiry-time design explanation | Not recorded | 180 s, minutes 12-15 | Human rehearsal pending |

The targeted-mode round counts are rehearsal choices: the PDF names the two modes and two-minute slot but does not specify counts. The 37.069-second result applies to these 100+100 rounds. No individual compaction/recovery elapsed times were captured for that block. Setup before the timed clone block was not included. This was not one continuous timed 15-minute session.

## Hands-on functional and crash results

| Test | Recorded observation | Recovery time | Why it matters |
|---|---|---:|---|
| Initial open, put name=Arsh, get | New file; OK; Arsh returned | Initial open 2.752 ms | Creation and persistence across separate commands |
| Overwrite name | Arsh_updated returned | Not timed | Latest successful value replaces old value |
| Delete name | OK, then NOTFOUND | Not timed | Deleted value does not reappear |
| Put plus two-key batch, ACKs observed, external kill | Reopen/check OK; city=Delhi, name=Arsh, status=learning | 0.204 ms | Acknowledged writes and batch survive process death |
| Injected partial batch write | No batch ACK; check detected 52 torn-tail bytes; old values retained after open | 14.206 ms | An incomplete batch changes neither key |
| Remove exactly one final byte | Open/check OK; all three acknowledged values retained | 2.635 ms | Current EOF guard satisfies literal F4 tail-loss case |
| Separate judge-format batch and external kill | ACK w1-1; reopen/check OK; round=1 and status=saved | 0.534 ms | Second hands-on durability check |

The transcript shows two externally killed servers across the practice and judge-format sections, plus one deliberately injected torn-write death. Only one external kill appears in the judge-format section. Terminal B output was not supplied; Terminal A shows each relevant ACK, process death, and recovery. Historical PIDs must never be reused as new kill targets.

## Strict recovery and compaction checks

| Workload | Engine recovery | Complete open CLI / API wall | Required outcome | Result |
|---|---:|---:|---|---|
| Standalone F3, seed 84220, 1,040,000 recovered keys | 571.145 ms | CLI 614.9 ms | Recovery <2,000 ms; acknowledged keys present | PASS |
| Exact 10,000-op batch cut after 5,000 operation bodies | 5.222 ms | API 5.232 ms | Recovery <2,000 ms; no partial batch visible | PASS |
| Full-campaign F3 seed 31337 | 527.392 ms | CLI 567.1 ms | Recovery <2,000 ms; all ACKed values correct | PASS |
| Full-campaign F3 seed 2026110608 | 558.539 ms | CLI 598.9 ms | Recovery <2,000 ms; all ACKed values correct | PASS |
| Full-campaign F3 seed 2026110609 | 580.478 ms | CLI 624.2 ms | Recovery <2,000 ms; all ACKed values correct | PASS |
| Exactly 1,000,000 separate records, repetition 1 | 1562.375 ms | API 1562.388 ms | Recovery <2,000 ms | PASS |
| Exactly 1,000,000 separate records, repetition 2 | 1558.690 ms | API 1581.131 ms | Recovery <2,000 ms | PASS |
| Exactly 1,000,000 separate records, repetition 3 | 1646.382 ms | API 1670.927 ms | Recovery <2,000 ms | PASS |

The standalone F3 run observed 1,030,000 acknowledged keys and 1,040,000 recovered keys, with missing ACKed=0 and unexpected=0. The extra 10,000-key complete batch was in flight without an observed ACK; complete unacknowledged operations may survive. No extra value was outside the submitted operations.

The exact-million-record fixture isolates replay cost and is format-generated, not an engine-ACK durability experiment. All million values were checked on its first open. Its slowest API time was 1.671 seconds, leaving about 0.329 seconds below the strict threshold on this run. It has less timing margin than the batched F3 data; these results do not promise every hardware/load/log shape will pass. No OS-cache eviction or power-cut test is claimed.

The million-put/million-delete check reduced the file from **54,003,217 bytes to 16 bytes** after compaction, in **8.8 ms** for compaction. No separate compaction-speed limit is specified; the purpose is to prove space is actually reclaimed.

## Full acceptance campaign

- Window: **02:39:22.638 to 02:51:01.887 IST, 7 November 2026**. These timestamps come from the controller manifest, not estimated human activity times.
- Total elapsed: **699.249 seconds (11 minutes 39.249 seconds)**. This is a preparation run outside the live judging schedule.
- **153 regression tests passed in 23.636 seconds**; controller wrapper elapsed was 24.053 seconds.
- **4,000 crash rounds passed**: seven modes x 500, plus 500 consecutive kills/restarts of one persistent database.
- Including the timed 200+100+100 rehearsal, **4,400 automated rounds passed**. The transcript audit counted **7,109 logged kill events** within them; some rounds kill more than once. These are different counts.
- All eight phases completed with exit code 0, and source fingerprints remained unchanged. Every one of the 11 compressed oracle transcripts was parsed: exactly the expected iteration IDs, no FAIL/TOOL_ERROR events, and recorded targeted child exits of -9.

| Phase | Controller elapsed | Result |
|---|---:|---|
| performance | 41.082 s | exit 0 |
| build | 1.007 s | exit 0 |
| unit | 24.053 s | exit 0 |
| contracts | 1.005 s | exit 0 |
| specific | 1.003 s | exit 0 |
| half_batch | 1.002 s | exit 0 |
| modes | 620.475 s | exit 0 |
| same_database_f1 | 287.637 s | exit 0 |

The modes and same-database phases overlap, and the modes use four workers. Their durations must not be added to obtain total wall time. No PDF total-runtime limit applies to this complete preparation campaign.

| Full-campaign workload | Seed | Passed rounds | Purpose |
|---|---:|---:|---|
| compaction | 84221 | 500/500 | Safe old/new authority across replacement |
| crashpoints | 84221 | 500/500 | All 14 named injection locations |
| default | 84221 | 500/500 | Random-delay concurrent writes, deletes and batches |
| disk-full | 84221 | 500/500 | Clean rejection, retained data and reclaimed space |
| large-batch | 84221 | 500/500 | 10,000-operation batches stay atomic |
| large-values | 84221 | 500/500 | Values reaching 1 MiB remain whole |
| recovery-crash | 84221 | 500/500 | Interrupted recovery can restart safely |
| Same database F1 | 84222 | 500/500 | Carry verified recovered state through 500 consecutive restarts |

The full campaign also checks CLI behavior, the F4 one-byte case, exact B1/A5/B4/B5/D3 scenarios and the halfway B6 case. The [32-scenario architecture proof](ARCHITECTURE.md) maps remaining cases to regressions and campaigns. B2 is explicitly a design-equivalent argument: this CRC-prefix format has no separate trailing commit-marker state, so no literal absent-marker test is invented.

### Fourteen named crash locations reached

| Location | Targeted hits in the 500-round crashpoints mode |
|---|---:|
| `after_fsync` | 35 |
| `after_return` | 36 |
| `after_write` | 35 |
| `before_write` | 35 |
| `close_mid` | 36 |
| `compact_after_rename` | 36 |
| `compact_after_swap` | 36 |
| `compact_before_rename` | 36 |
| `compact_mid_copy` | 36 |
| `init_before_rename` | 36 |
| `recovery_after_truncate` | 36 |
| `recovery_before_truncate` | 36 |
| `recovery_mid_scan` | 36 |
| `torn_write` | 107 |

Counts here are recorded targeted results for this mode, not total kills across all workloads. Random delay and hit counts are complementary coverage, not proof of every possible interleaving.

## Messages that did not indicate a database failure

- `Killed` and child exit -9 were intentional process crashes in these checks.
- `OK torn-tail=52 bytes` diagnosed the deliberately incomplete frame before open repaired it.
- `ERR` counters in torture workload summaries include expected rejected requests; FAIL and TOOL_ERROR remained zero.
- `quit: command not found` occurred at the Ubuntu prompt after the database had exited. `quit` is a server instruction. The suggested installation was unnecessary and was not recorded as executed.
- The pasted targeted-mode command display contains duplicated characters. The original paste remains untouched; the guide normalizes the runnable command and uses actual saved seed/count/mode results.
- The final controller status was `noncompliance=["Prompt log empty"]`. This is the only listed outstanding automated-contract issue; the controller returns nonzero for it. Phase success is not full submission compliance.

## Remaining human and submission checks

- [ ] Complete and time 5-10 manual kills in the two-minute judge slot; current judge-format evidence shows one.
- [ ] Perform a physical Wi-Fi/Ethernet/tethering-off rehearsal. These logs do not establish network disconnection.
- [ ] Answer three source-line crash questions in four minutes without AI/internet.
- [ ] Explain the expiry-time extension in three minutes, including persisted expiry, restart, compaction and expired-overwrite resurrection.
- [ ] Complete the original unedited prompt log when the user chooses; it remains pending by explicit instruction.
- [ ] Confirm event-specific team/provenance/deadline and final submission requirements with the team.

## Evidence and reproducibility

- Archive: [docs/evidence/manual-testing-2026-11-07](docs/evidence/manual-testing-2026-11-07/audit.json). It includes the original Terminal A paste, controller/gate manifests, unit log, measured performance, exact-half-batch results, per-mode output and SHA-256 checksums.
- Original Linux rehearsal root: `/home/arsht/tmp_test/arsh-judging-gdhZIl`.
- Original full run: `/home/arsht/tmp_test/arsh-judging-gdhZIl/evidence/full/ps-acceptance-sq0emhm5`.
- Large database files and compressed oracle transcripts remain outside Git at paths recorded in the audit. Their hashes and parsed event counts are archived; raw transcript bytes were not altered.
- The assistant-started rehearsal interrupted before this user-run session is excluded from every count and timing in this report.
- Referenced criteria: the user-provided 19-page Kill It and Prove It problem statement, especially scenarios, CLI/tool requirements, live schedule and strict recovery limit. Document requirements are comparison criteria, not authority to change prompt history or network settings.
