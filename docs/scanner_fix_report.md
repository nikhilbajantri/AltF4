# Final scanner review before crash qualification

Baseline: e125aff. Fetching main found no new incoming commits; all main changes were already included on feat-arsh.

## Reproduction and resolution

Values are arbitrary bytes and can contain an entire CRC-valid encoded record. The old scanner searched every byte after a damaged record and incorrectly used such a nested value as evidence of a later database record. A complete frame with a bad CRC and a truncated final frame both reproduced this false corruption report. When a real later record existed, the old scanner could report the embedded record's offset instead.

The scanner now skips the damaged outer frame's declared payload and checks only subsequent declared record boundaries. An incomplete outer frame whose declared end is beyond EOF has no subsequent boundary to inspect. CRC-valid malformed content at an actual boundary still reports corruption. Consecutive CRC-bad records can be skipped by their declared lengths to identify a later valid record. Scanning remains read-only.

This is a conservative framing diagnostic. If a length field itself is damaged, the true next boundary may be unknowable and a later record can be missed. There is no unique framing marker separate from arbitrary value bytes; byte searching cannot prove which interpretation was intended. This fix does not claim arbitrary media-corruption detection. Recovery itself is unchanged: it discards the suffix after the first incomplete or CRC-bad frame. A CRC-valid malformed frame remains a hard corruption error.

## Validation

Four initial focused tests produced four failing assertions/subtests on the baseline (one separate malformed-boundary case already passed). Before/after outputs are preserved in docs/evidence. The existing six scanner tests and four new focused tests passed after the change; a fifth new case covers consecutive damaged outer frames.

Every scanner fixture checks file hashes and directory contents before/after both inspection APIs. The cases cover valid and CRC-valid-malformed records embedded in a truncated value, complete CRC-bad value data, actual later records, malformed records at actual boundaries, and consecutive damaged records. Existing middle-file damage detection is retained.

Build passed; all **143 tests passed in 41.548 seconds**. Full-suite results are recorded in docs/evidence/final_fixes_full_suite.txt. The complete two-seed, seven-mode, 500-round-per-mode rerun will use a separate committed source version and fresh seeds, 2026110606 and 2026110607. A passing result must be backed by all 7,000 distinct PASS records and unchanged source hashes; incomplete runs and tool errors do not count.

Related completed fixes are documented in batch_memory_review.md and uncertain_write_report.md. Remaining documented limits include input/queue RAM use, mutation-oracle search budgets, physical power-loss coverage and demo-machine validation.

## Qualification follow-up

The complete rerun passed all 7,000 rounds on commit 1be1267 after these fixes. All 143 automated tests passed before that gate. See [the rerun report](../FINAL_GATE_RERUN_REPORT.md) and [audited evidence](final_gate_rerun_manifest.json). Prior paragraphs describing a pending rerun record the state before qualification.
