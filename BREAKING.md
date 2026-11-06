# How I would break this

## 1. Crash points table

All locations below are under src/. The frame is the commit unit; the optional final 00 byte is expendable padding. Named hooks kill the process with SIGKILL. See docs/GAP_FIX_REPORT.md for seeds and counts.

| Hook and exact function | Disk at kill | Next open |
|---|---|---|
| init_before_rename: engine._create | Synced .init, no authoritative path yet | Remove temp; create header again |
| before_write: engine._write | Prior frames and guard | New operation absent |
| torn_write: engine._write | Incomplete frame overwrote old guard | Drop incomplete tail; restore guard |
| after_write: engine._write | Complete frame plus guard; not synced | Replay full CRC-valid frame |
| after_fsync: engine._write | Frame and guard synced; RAM stale | Rebuild index; include operation |
| after_return: serve.run/execute | Engine returned; ACK not printed | Include durable operation |
| recovery_mid_scan: engine._scan | File unchanged; RAM incomplete | Restart replay |
| recovery_before_truncate: engine._recover | Torn tail remains | Repeat repair |
| recovery_after_truncate: engine._recover | Valid prefix and guard synced | Replay clean file |
| compact_mid_copy: engine._copy_live | Old authority plus partial temp | Use old file; remove temp |
| compact_before_rename: engine._compact_locked | Old file plus synced new temp | Use old file; remove temp |
| compact_after_rename: engine._compact_locked | Path names complete new file | Recover new file |
| compact_after_swap: engine._compact_locked | New file/directory synced; handle swapped | Recover new file; append to it |
| close_mid: engine.close | Accepted frames already durable | Recover without close cleanup |

## 2. Ordering argument

Under the process-death model, os.pwrite loops until the frame is complete, then writes one EOF guard; os.fsync returns before index publication, engine success and serve ACK. The next append overwrites the guard, not earlier frame bytes. A partial frame is discarded as a whole. Removing one trailing byte from an acknowledged file removes only the guard. The guard is not a commit marker.

Recovery uses os.ftruncate, restores the guard when space permits, then os.fsync. Compaction copies live data and guard, fsyncs/closes the temp, calls os.replace, fsyncs the parent directory, then reopens/swaps the descriptor and index. Directory fsync also follows initial-file replacement. Atomic rename is assumed on the tested Linux ext4 filesystem.

On append failure, rollback truncates the attempted append, restores the old guard and syncs. The handle is poisoned. Failed rollback reports UNCERTAIN: reopen and reconcile before retrying; absence is not promised.

## 3. Known weaknesses

1. Replay is O(log size). Million-record measurements pass on this laptop, but a sufficiently long log, slower storage or different CPU load can exceed two seconds.
2. One mutex blocks readers/writers during compaction. Encoding is chunked, but retained input values, queued batches and the index still consume RAM. The 10,000 distinct 1 MiB value combination is not qualified.
3. Evidence covers process kills on ext4, not power loss, lying hardware, NTFS or arbitrary middle-file damage. CRC32 is not cryptographic authentication.
4. Legacy files at a cap with no spare byte remain readable without migration growth. Their unguarded tails need room and a current write/compaction before the guard guarantee applies. Older engines can remove the guard.
5. OS scheduling is not reproduced exactly by a seed. Full transcripts and deterministic hooks supplement seeded plans. The exact shared-batch oracle has a 250,000-state budget; exhaustion is a tool error, never PASS.

## 4. What we tried that failed

A zero-progress pwrite once hung the engine; a progress guard now rejects it. Early-ACK and partial-batch planted defects are detected by negative regressions. Skipped tail truncation previously escaped random kills; deliberate torn-write trials now expose it. Invalid UTF-8 once killed serve; malformed lines now get errors. The literal one-byte test previously lost acknowledged data; the EOF guard fixes that without accepting partial frames. A test also incorrectly required global reply order across writers; it now checks exact responses without that unsupported order. Raw pre-fix evidence is retained.

## 5. If we had 24 more hours

1. Add a byte-based admission budget for retained batch inputs/queues; stress distinct maximum-sized values under a stated RAM budget.
2. Add a crash-safe checkpoint or bounded replay strategy, then benchmark 10 million records and cache/load variations with a hard two-second gate.
3. Compare the concurrent oracle against a separate bounded reference model, and expand adversarial shared-key histories without silently raising its search budget.

The original prompt log remains pending by the user's choice. Physical Wi-Fi-off rehearsal and live source-line answers need human sign-off; automated counts do not certify them. Printable two-page layout: output/pdf/BREAKING.pdf.
