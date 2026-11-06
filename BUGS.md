# Bugs

| # | Seed | Mode | Symptom | Cause | Fix commit | Owner | Status |
|---|------|------|---------|-------|------------|-------|--------|

| ARSH-001 | deterministic injected pwrite=0 | fault injection | Engine hangs on zero-progress write | retry loop never advances | uncommitted local fix | Arsh | fixed; regression passes |
| ARSH-002 | prepared torn-tail fixture | recovery probe | Tester accepted unrepaired tail after recovery | accepted OK torn-tail message | uncommitted local fix | Arsh | fixed; strict OK check and planted test pass |
