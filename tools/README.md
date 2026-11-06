# Acceptance tools

Current preparation run (Linux/ext4, installed Python/make/git):

```bash
python3 -B tools/run_ps_acceptance.py --host-storage-dir /mnt/c --host-storage-dir /mnt/d --seed 2026110701 --additional-seeds 2026110702 --f1-seed 2026110703 --workers 4
```

This runs strict recovery measurements, build, regression tests, CLI/contracts, five direct scenarios, exact halfway B6, 7,000 mode rounds and 500 same-database rounds. It prints PS_EVIDENCE. The final nonzero status still reflects the deliberately pending prompt log; read every phase and invariant summary.

- `report_gap_fixes.py QUALIFICATION_ROOT`: current post-fix evidence audit/report for a frozen two-seed run. Checks every compressed transcript, source identity (raw and CRLF/LF), proof-table IDs and document layout.
- `record_demo_results.py --qualification-manifest docs/gap_fixes_gate_manifest.json`: refresh actual demo evidence after successful qualification; verifies portable source identity. Human offline and manual-kill sign-off remain separate.
- `run_final_gate.py`: mode-only qualification; explicitly choose iterations, seeds, workers and checked host volumes.
- `ps_f1_same_database.py`: 500 random SIGKILL/restarts of one persistent database with the independent oracle.
- `ps_measure_recovery.py`: real million-key F3, exactly-million-record diagnostic, torn B6 and million-delete compaction.
- `ps_specific_scenarios.py` and `check_ps_half_batch.py`: exact B1/A5/B4/B5/D3 and halfway B6 checks.
- `ps_check_contracts.py`: real CLI, literal F4, document/default inspection and supplementary socket-guard checks. It does not certify physical network disconnection.

`report_ps_acceptance.py` is the historical pre-fix report generator. Its narrative describes the old failures and must not be used as the current status report. Its transcript reader is reused by the current gap-fix auditor; original pre-fix evidence remains preserved.

Raw transcript SHA-256 values remain byte-exact. The additional canonical source map only normalizes CRLF to LF for portable Python/text checkout verification; it does not replace the original raw qualification manifest. Generated database files and large raw logs stay outside Git.
