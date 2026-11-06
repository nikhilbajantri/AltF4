# Bugs

| # | Seed | Mode | Symptom | Cause | Fix commit | Owner | Status |
|---|------|------|---------|-------|------------|-------|--------|

| ARSH-001 | deterministic injected pwrite=0 | fault injection | Engine hangs on zero-progress write | retry loop never advances | uncommitted local fix | Arsh | fixed; regression passes |
| ARSH-002 | prepared torn-tail fixture | recovery probe | Tester accepted unrepaired tail after recovery | accepted OK torn-tail message | uncommitted local fix | Arsh | fixed; strict OK check and planted test pass |

## Review findings (2026-11-06, commit d259b98, see docs/review_report.md)

| # | Seed | Mode | Symptom | Cause | Fix commit | Owner | Status |
|---|------|------|---------|-------|------------|-------|--------|
| R-01 ([#3](https://github.com/nikhilbajantri/AltF4/issues/3)) | - | manual serve | `printf 'put a-1 k \xff\n' \| python3 -m src.serve db` crashes with a UnicodeDecodeError traceback, exit 1 | stdin is read as strict UTF-8 text (serve.py:140); the decode error is outside any handler | | Arsh | open |
| R-02 ([#4](https://github.com/nikhilbajantri/AltF4/issues/4)) | - | manual CLI | every `./kvdb <cmd>` prints "not implemented yet" and exits 1 | src/cli.py and src/inspect_cmd.py are still M0 stubs | | Srushti | open |
| R-03 ([#5](https://github.com/nikhilbajantri/AltF4/issues/5)) | 77173339, 972750935, 978142283, 132829190, 281923561, 664061492 | large-values, large-batch, compaction, recovery-crash, disk-full, crashpoints | `--mode` gives "invalid choice ... (choose from 'default')", exit 2 | runner.py:176 implements only `default` | | Arsh | open |
| R-04 ([#6](https://github.com/nikhilbajantri/AltF4/issues/6)) | 12345 | default (planted bug b) | engine with the torn-tail ftruncate removed passes 50/50 | random SIGKILL never interrupts a pwrite, so there is never a torn tail to truncate; no torn_write/crashpoints mode | | Arsh | open |
| R-05 ([#7](https://github.com/nikhilbajantri/AltF4/issues/7)) | - | serve review | serve emits `ERR <id> IO`, `UNSUPPORTED`, `INTERNAL`, which are not in the README ERR reasons | serve.py:105-108, :120 | | Arsh | open |
| R-06 ([#8](https://github.com/nikhilbajantri/AltF4/issues/8)) | 12345 | default (planted bugs a, c) | FAIL line is several KB of full values with no diff and no op ids | oracle.py:54 prints every world and the full found map | | Arsh | open |
| R-07 ([#9](https://github.com/nikhilbajantri/AltF4/issues/9)) | 552777022 | default | at most op 10 of 100 reached per iteration, batches of at most 5 ops, no shared keys, no ERR ops; in-flight % always 100% | 2-25 ms kill window (runner.py:48); workload.py:12 randint(2, 5); oracle requires disjoint keys | | Arsh | open |
| R-08 ([#10](https://github.com/nikhilbajantri/AltF4/issues/10)) | - | benchmark | `python3 tests/bench_recovery.py` gives ModuleNotFoundError: No module named 'src' | repo root not on sys.path when run as a script; only `-m tests.bench_recovery` works | | Nikhil | open |
| R-09 ([#11](https://github.com/nikhilbajantri/AltF4/issues/11)) | - | torture review | a ValueError from oracle.worlds (two pending ops, or a shared key) gives a traceback, not TOOL ERROR | runner.py:197 catches only ToolError/OSError/TimeoutExpired | | Arsh | open |
| R-10 ([#12](https://github.com/nikhilbajantri/AltF4/issues/12)) | - | docs | ARSH-001/002 rows above don't render as a table | blank line between the table header and those rows | | Varsha | open |
| R-11 ([#13](https://github.com/nikhilbajantri/AltF4/issues/13)) | - | serve review | a writer that fills its 64-slot queue blocks the input thread for all writers | serve.py:129, :133 blocking `Queue.put` on the main thread | | Arsh | open |
