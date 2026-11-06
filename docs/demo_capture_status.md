# Demo capture checkpoint — 2026-11-06

The implementation is merged into main at c5497b1. Its recorded qualification is 143 passing automated tests and a complete 7,000-round rerun; see FINAL_GATE_RERUN_REPORT.md. DEMO.md still contains placeholders for a fresh demonstration.

## Prepared work

Run from the repository root in Ubuntu/WSL after the environment starts normally:

```bash
python3 -B tools/record_demo_results.py
```

The script creates a fresh demo-evidence-* directory under ~/tmp_test and prints its path after successful completion. It checks that implementation hashes match the qualified sources and that the evidence directory is on ext4. It captures:

1. The actual make build output.
2. Twenty-five default crash rounds with seed 12345, compressed transcripts, zero failures/tool errors, and a 20 GiB reserve on /mnt/d (the host volume containing this machine's WSL disk).
3. A real server session that acknowledges puts, a two-key batch, and a delete; the script then SIGKILLs that exact server process.
4. Reopen, check, dump and get output verifying all acknowledged state survived and the deleted key stayed absent.
5. An interrupted two-key batch using torn_write:1, no ACK, the read-only torn-tail check, and recovery proving the earlier values stayed intact.

No existing database is overwritten or deleted. The script's kill targets are processes that it creates. Output files and assertions are prepared, but this capture has not yet run successfully.

## Environment blocker

Ubuntu-24.04 was reported Stopped, but starting it failed with ERROR_SHARING_VIOLATION while attaching its virtual disk. A normal WSL shutdown, an administrator-approved WSL service restart, and the supported forced WSL shutdown did not clear the attachment lock. No virtual disk was manually modified or detached. Windows restart is the next recovery step.

## Resume after restarting Windows

1. Confirm Ubuntu starts, then run the capture command above.
2. Inspect every saved output and metadata.json. A partial run is not a successful demo.
3. Replace DEMO.md placeholders with the captured outputs and reproducible two-terminal commands. Preserve the actual paths, timestamps and varying recovery timings as evidence rather than inventing results.
4. Complete the crash-here explanations from BREAKING.md. State that TTL/automatic expiry is not implemented in the current API; describe any extension as a design answer, not an existing feature.

Only syntax and repository formatting checks were possible for the capture helper before this checkpoint. No new live demo or fresh test success is claimed by this preparation commit.

## Completed after Windows restart

Ubuntu started normally after the restart. Capture finished at 2026-11-06 22:22:56 IST on commit 5c2ed535fafaed659d3c82a15fc372a3af273091. Build passed; 25/25 rounds passed with zero tool errors/failures; both controlled demo kills returned SIGKILL and all recovered-state assertions passed. DEMO.md now contains actual results, two-terminal steps, crash-here answers and the current TTL scope. Small outputs/checksums are in docs/evidence/demo-2026-11-06; full evidence remains at /home/arsht/tmp_test/demo-evidence-f8om2wag.

Earlier blocked and pending notes above record the pre-reboot checkpoint and are resolved for this capture.
