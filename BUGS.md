# Bugs

| # | Seed | Mode | Symptom | Cause | Fix commit | Owner | Status |
|---|------|------|---------|-------|------------|-------|--------|
| ARSH-001 | deterministic injected pwrite=0 | fault injection | Engine hangs on zero-progress write | retry loop never advances | aa46909 | Arsh | fixed; regression passes |
| ARSH-002 | prepared torn-tail fixture | recovery probe | Tester accepted unrepaired tail after recovery | accepted OK torn-tail message | aa46909 | Arsh | fixed; strict OK check and planted test pass |

## Review findings (2026-11-06, commit d259b98, see docs/review_report.md)

| # | Seed | Mode | Symptom | Cause | Fix commit | Owner | Status |
|---|------|------|---------|-------|------------|-------|--------|
| R-01 ([#3](https://github.com/nikhilbajantri/AltF4/issues/3)) | - | manual serve | `printf 'put a-1 k \xff\n' \| python3 -m src.serve db` crashes with a UnicodeDecodeError traceback, exit 1 | stdin is read as strict UTF-8 text (serve.py:140); the decode error is outside any handler | | Arsh | fixed on feat-arsh; pending PR merge |
| R-02 ([#4](https://github.com/nikhilbajantri/AltF4/issues/4)) | - | manual CLI | every `./kvdb <cmd>` prints "not implemented yet" and exits 1 | src/cli.py and src/inspect_cmd.py are still M0 stubs | | Srushti | fixed on feat-arsh; pending PR merge |
| R-03 ([#5](https://github.com/nikhilbajantri/AltF4/issues/5)) | 77173339, 972750935, 978142283, 132829190, 281923561, 664061492 | large-values, large-batch, compaction, recovery-crash, disk-full, crashpoints | `--mode` gives "invalid choice ... (choose from 'default')", exit 2 | runner.py:176 implements only `default` | | Arsh | fixed on feat-arsh; pending PR merge |
| R-04 ([#6](https://github.com/nikhilbajantri/AltF4/issues/6)) | 12345 | default (planted bug b) | engine with the torn-tail ftruncate removed passes 50/50 | random SIGKILL never interrupts a pwrite, so there is never a torn tail to truncate; no torn_write/crashpoints mode | | Arsh | fixed on feat-arsh; pending PR merge |
| R-05 ([#7](https://github.com/nikhilbajantri/AltF4/issues/7)) | - | serve review | serve emits `ERR <id> IO`, `UNSUPPORTED`, `INTERNAL`, which are not in the README ERR reasons | serve.py:105-108, :120 | | Arsh | fixed on feat-arsh; pending PR merge |
| R-06 ([#8](https://github.com/nikhilbajantri/AltF4/issues/8)) | 12345 | default (planted bugs a, c) | FAIL line is several KB of full values with no diff and no op ids | oracle.py:54 prints every world and the full found map | | Arsh | fixed on feat-arsh; pending PR merge |
| R-07 ([#9](https://github.com/nikhilbajantri/AltF4/issues/9)) | 552777022 | default | at most op 10 of 100 reached per iteration, batches of at most 5 ops, no shared keys, no ERR ops; in-flight % always 100% | 2-25 ms kill window (runner.py:48); workload.py:12 randint(2, 5); oracle requires disjoint keys | | Arsh | fixed on feat-arsh; pending PR merge |
| R-08 ([#10](https://github.com/nikhilbajantri/AltF4/issues/10)) | - | benchmark | `python3 tests/bench_recovery.py` gives ModuleNotFoundError: No module named 'src' | repo root not on sys.path when run as a script; only `-m tests.bench_recovery` works | | Nikhil | fixed on feat-arsh; pending PR merge |
| R-09 ([#11](https://github.com/nikhilbajantri/AltF4/issues/11)) | - | torture review | a ValueError from oracle.worlds (two pending ops, or a shared key) gives a traceback, not TOOL ERROR | runner.py:197 catches only ToolError/OSError/TimeoutExpired | | Arsh | fixed on feat-arsh; pending PR merge |
| R-10 ([#12](https://github.com/nikhilbajantri/AltF4/issues/12)) | - | docs | ARSH-001/002 rows above don't render as a table | blank line between the table header and those rows | | Varsha | fixed on feat-arsh; pending PR merge |
| R-11 ([#13](https://github.com/nikhilbajantri/AltF4/issues/13)) | - | serve review | a writer that fills its 64-slot queue blocks the input thread for all writers | serve.py:129, :133 blocking `Queue.put` on the main thread | | Arsh | fixed on feat-arsh; pending PR merge |
| R-12 ([#14](https://github.com/nikhilbajantri/AltF4/issues/14)) | - | documentation verification | BREAKING omitted after_return and contradicted test evidence | stale crash table and failure history | this PR | Arsh | fixed; see docs/review_fixes.md |

## Double I/O-failure review

| ID | Reproduction | Finding | Resolution | Status |
|---|---|---|---|---|
| ARSH-003 | Inject append fsync failure and rollback ftruncate/fsync failure on baseline 1bb70c6 | ERR IO did not distinguish a write whose complete frame could reappear after reopen | UncertainWriteError and ERR UNCERTAIN; retain both underlying errors; block later writes/compaction; caller reconciles after reopen | Implemented on feat-arsh; focused before/after evidence in docs/uncertain_write_report.md |

## Large-batch memory review

| ID | Reproduction | Finding | Resolution | Status |
|---|---|---|---|---|
| ARSH-004 | 8/40 MiB batches with tracemalloc; capped database; 10,000 references to a shared 1 MiB value | Whole-frame copies were allocated before cap rejection; input iterators were fully consumed | Preflight size checks, bounded frame chunks with original CRC, capped operation collection, rollback on mid-write allocation error | Implemented on feat-arsh; docs/batch_memory_review.md records results and remaining input-RAM limits |
