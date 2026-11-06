# Final gate interruption — qualification not complete

The shared-batch fix is committed and pushed as 2a9c3c3. Six before-fix regressions errored on baseline 4c80833; all six passed afterward. The full suite passed 110 tests, and a fresh Linux-home clone also built and passed 110 tests.

The 7,000-round gate started with seeds 2026110601 and 2026110602. Six complete first-seed runs were reported as 500/500 passing: default, large-values, large-batch, recovery-crash, compaction and crashpoints. Partial runs and unverified results are not counted as completed qualification.

The gate driver then raised OSError [Errno 5] while reading a run log. Host inspection showed C: had 0.00 GB free, although the dynamically growing Linux disk had previously reported 951 GB available. Ubuntu subsequently returned I/O errors for system binaries and user-account lookup. The gate is incomplete, and no final success report or report commit has been made.

The raw per-operation evidence expanded inside Ubuntu's virtual disk on C:. The harness did not preflight Windows-host free space or bound evidence growth. This is a test-infrastructure failure and must be included in the eventual final report.

Ubuntu disk location: C:\Users\arsht\AppData\Local\wsl\{d5af0740-93ff-4a6b-ae87-180f6030128e}. No virtual disk files were manually moved or modified. D: has approximately 344 GB free.

Direct UNC and Linux-process backup attempts could not access the damaged running distro. The original evidence remains inside that virtual disk; its completeness is unverified. Recovery/report scripts were copied to D:\ALT F4\qualification-evidence\recovery-scripts. No user files were deleted.

## Recovery and prevention

The user approved restarting Ubuntu and moving it to D:. The first supported move returned ERROR_SHARING_VIOLATION. After a full WSL shutdown, `wsl --manage Ubuntu-24.04 --move D:\WSL\Ubuntu-24.04` succeeded. Registry state confirmed the new location; Ubuntu restarted as the original user and passed a file read/write check. C: had approximately 26 GiB free afterward, and D: approximately 323 GiB. Linux reported about 936 GiB, demonstrating why the virtual filesystem figure alone is insufficient.

The original 16 GiB campaign directory remains intact inside Ubuntu. Its manifest was recovered with six completed 500-round successes. Small logs and the manifest were additionally copied to D:\ALT F4\qualification-evidence\interrupted-gate-summaries. No raw evidence or unrelated user files were deleted. Systemd replaced journals it reported as corrupted or uncleanly shut down; this health check does not certify every file in the distro.

The harness now supports lossless gzip transcripts and checks free space before each round. The new final-gate driver requires an explicit host storage directory on WSL, checks both the evidence filesystem and supplied host volumes before launch and once per second, and reserves 20 GiB by default. On low space, timeout or another task failure, it stops its own process groups and records the error instead of counting a pass. Atomic manifest replacement preserves the last completed results. This reserve is a safety margin, not a strict disk quota, and other programs can still consume storage.

Two regression tests verify that low host space prevents a round from starting and that compressed transcripts retain real submitted operations, SIGKILL records and PASS events. A seven-mode smoke run (one round per mode, seed 2026110699) passed. The complete qualification will be rerun with fresh seeds 2026110603 and 2026110604 against the updated harness. The interrupted campaign is historical evidence and is not added to that qualification's 7,000-round total.

## Completed rerun

The rerun completed successfully on commit 508121f using seeds 2026110603 and 2026110604: all 14 runs passed 500/500 rounds, for 7,000 total. Independent transcript auditing verified 11,342 SIGKILL exits, 5,135 submitted shared batches, all 14 named crash points, and unchanged source hashes. The full suite had passed 112 tests before this rerun. See [FINAL_TEST_REPORT.md](../FINAL_TEST_REPORT.md) and [the audited manifest](final_gate_manifest.json). This outcome does not change the original campaign's incomplete status.
