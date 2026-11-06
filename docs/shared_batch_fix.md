# Shared-batch checker: before and after

Baseline: 4c80833. On 2026-11-06, six new regression tests were run before the fix. All six errored with `ValueError: unsupported shared key; use shared/status`, including valid whole-batch outcomes, mixed outcomes, timing order, optional pending batches, delete order, and the exhaustive-reference comparison. These were checker coverage errors; they did not demonstrate a storage-engine data-loss bug.

## Fix

The oracle now checks a complete serialization of whole operations over arbitrary overlapping keys. Each writer's operation order is preserved. A response observed before another operation was sent creates a real-time precedence constraint. ACKed operations are mandatory; rejected operations are absent; at most one unanswered operation per stop-and-wait writer is optional as a whole batch. Within a batch, operations apply in listed order.

The search interns values, collapses repeated writes within a batch to their final effects, memoizes equivalent prefix states, and checks finalized keys early against the actual complete map. It does not choose shared-key results independently. Search beyond 250,000 distinct states fails explicitly as a tool error with no correctness verdict, rather than accepting approximately. It checks the recorded mutation history; general read-linearizability checking is not included.

Default workloads now start both writer streams with four-operation shared batches, and later batches and the large-batch mode also mutate shared keys. The large-value boundary remains exactly 1 MiB.

## Post-fix validation

- All six before-fix regressions pass.
- Small generated two-writer histories are compared against an independent brute-force permutation reference: 30 histories x 16 candidate recovered maps (480 accept/reject comparisons).
- Whole A and whole B outcomes are accepted when operations overlap; mixed A/B pairs are rejected as Mismatch, not a tool error.
- Real-time ordering, rejected operations, optional pending whole batches, initial values and ordered deletes are checked.
- Existing planted partial-batch and early-ACK detector trials remain part of the full suite.

The code fix is committed before the final crash gate. The final qualification results and source identity are recorded separately in FINAL_TEST_REPORT.md after the gate completes. Earlier reports remain historical evidence against their stated versions.
