# Kill It and Prove It

A Python key-value database that keeps successful writes after its process is killed. Keys and values are bytes. Put saves a value, get reads it, delete removes it, and batch commits several changes together. The companion torture tool kills the server and checks recovered data against an independent request/ACK history.

## Start here

Use Ubuntu/Linux on a real ext4 filesystem, including Ubuntu in WSL. Required installed tools: Python 3.10+, make and Git. Runtime code uses Python's standard library; no pip packages or network downloads are required. Native Windows needs WSL for the real engine. The fake engine is only a practice stub and supplies no durability evidence.

From the repository root, the single build command is:

```bash
make build
```

Expected final line: BUILD OK. The build checks Python, compiles src/torturelib and marks kvdb/torture executable. Run the regression suite with make test. See OFFLINE_TEST_PLAN.md for a fresh local-clone rehearsal with connectivity physically disconnected.

## Try the database

Run these shell commands from the repository root in Ubuntu. The unique folder prevents overwriting an earlier test. Keep the data on Linux storage rather than /mnt/c, /mnt/d or a RAM disk.

```bash
mkdir -p "$HOME/tmp_test"
DEMO_DIR=$(mktemp -d "$HOME/tmp_test/kvdb-readme-XXXXXX")
DB="$DEMO_DIR/demo.db"
./kvdb open "$DB"
./kvdb put "$DB" name Arsh
./kvdb get "$DB" name
cat > "$DEMO_DIR/batch.txt" <<'OPS'
put city Delhi
put status ready
del name
OPS
./kvdb batch "$DB" "$DEMO_DIR/batch.txt"
./kvdb dump "$DB"
./kvdb del "$DB" status
./kvdb check "$DB"
./kvdb serve "$DB"
```

The read returns Arsh. The batch returns OK and dump contains city=Delhi and status=ready, with name absent. The final check says OK. After serve prints READY, type the server requests below; they are not shell commands:

```text
put w1-1 name Arsh
get w1-2 name
batch w1-3
put city Mumbai
put status saved
end
quit
```

Expected replies: ACK w1-1, VAL w1-2 Arsh and ACK w1-3. quit drains queued work and returns to the shell. It is not a Bash command. For manual SIGKILL testing with two terminals, use [the complete command guide](docs/MANUAL_TEST_COMMANDS.md).

## Which document to use

| Document | Purpose |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | One current architecture diagram, all 32 scenario arguments, and durability/atomicity/recovery guarantees |
| [BREAKING.md](BREAKING.md) | Fourteen crash locations, syscall ordering, known weaknesses, failures found and three next priorities |
| [MANUAL_TEST_REPORT.md](MANUAL_TEST_REPORT.md) | Measured results, timing limits and original evidence |
| [DEMO.md](DEMO.md) | The 15-minute judging sequence and source-question preparation |
| [OFFLINE_TEST_PLAN.md](OFFLINE_TEST_PLAN.md) | Offline setup checklist |
| [docs/EOF_GUARD.md](docs/EOF_GUARD.md) | the 1-byte EOF guard: why, how, edge cases |

## On-disk format (one-page specification)

All integers are unsigned little endian. One authoritative append-only data file; the index is RAM-only. Lock and temporary files are auxiliary.

```text
FILE = HEADER | FRAME ... FRAME | optional EOF GUARD
HEADER (16): magic "KVDB0001" (8) | version=1 u32 (4) | hcrc u32 (4)
             hcrc = CRC32(first 12 header bytes)
FRAME: payload_length u64 (8) | crc u32 (4) | PAYLOAD (payload_length)
       crc = CRC32(the 8 length bytes followed by all payload bytes)
PAYLOAD: operation_count u32 (4) | OP ... OP
OP: type u8 (1) | key_length u16 (2) | value_length u32 (4) | key | value
    type=1 PUT; type=2 DELETE (value_length=0, no value bytes)
GUARD: 00 (1), only at EOF after complete frames; outside frame/CRC
```

Keys: 1..1,024 bytes; values: 0..1,048,576 bytes; batch: 1..10,000 operations. A complete valid frame is the commit unit, with no separate trailing commit marker. Batch operations apply first to last; put X then delete X leaves X absent. A parser validates the header, then each declared frame length, CRC and payload. It accepts an optional single 00 byte after the last full frame. Empty databases are just the 16-byte header. A missing guard does not invalidate a full frame. Other incomplete tails are discarded on open; CRC-valid malformed payloads raise CorruptError without truncation.

The guard costs one byte per nonempty file and is overwritten by the next frame. It protects a successful current write from literal one-byte tail removal. Legacy version-1 logs remain readable; open adds the guard if space allows. A legacy log already at/over a new cap stays readable without growth; make room and use the current writer/compactor before relying on tail protection. Older engines may remove the guard. [Current architecture and write/recovery diagram](ARCHITECTURE.md).

## Write order

1. Validate all operations and calculate the complete frame size.
2. Take the engine mutex; reject a poisoned/closed handle and check the cap, including the guard and delete reserve. Reclaim dead data and retry once if necessary.
3. Prepare the CRC encoding, then loop on os.pwrite until the whole frame is written over the old guard. Large encodings use bounded 4 MiB chunks.
4. Write the new final guard and call os.fsync on the database file.
5. Publish the complete batch to the RAM index, finish any triggered compaction, release the mutex and return. Serve prints and flushes ACK afterward.

If append/sync fails, restore the old end and guard, sync the rollback, poison the handle and return an error. If rollback also fails, UNCERTAIN means the operation may be present or absent on reopen; reconcile state before retrying. An ACK is never an error response.

## Recovery

1. Acquire flock on path.lock, excluding another process handle.
2. Remove stale .init/.compact files. If missing, create the synced header through .init, os.replace and parent-directory fsync. A short exact header prefix can be recreated as an unfinished empty initialization; other bad headers raise corruption.
3. Validate the header, then scan declared frame boundaries and CRCs with mmap.
4. Replay each complete valid frame in operation order to rebuild the RAM index.
5. Stop at an incomplete/bad-CRC frame. CRC-valid malformed payloads raise CorruptError rather than being silently removed.
6. Truncate a torn tail, restore the nonempty file's guard when the cap permits, and fsync the repair. Restore a missing guard on an otherwise complete log too. A crash during repair can be retried.
7. Return ready with the recovered key count and recovery_ms. The internal logical end excludes the guard; physical file_bytes includes it.

## Compaction and concurrency

Compaction holds the same mutex as reads and writes. It copies live keys into path.compact using frames with at most 4 MiB payload and 10,000 operations, checks the cap including the guard, adds the guard if nonempty, fsyncs/closes the temporary file, replaces the database with os.replace, fsyncs the parent directory, then swaps the descriptor/index. Empty compaction leaves the 16-byte header.

It runs explicitly, on a cap retry with reclaimable data, or when dead bytes exceed half of a log larger than 4 MiB. Readers and writers wait during it. One get or items call cannot see a half-published batch; separate get calls do not form a multi-key snapshot.

## API

`KVDB(path, max_bytes=None, auto_compact=True)` exposes put(bytes, bytes), get(bytes) -> bytes/None, delete(bytes), batch([("put", key, value), ("del", key)]), close(), compact(), keys(), items(), stats. Success is durable under honest fsync and abrupt process death. stats reports physical file_bytes including the guard; internal end excludes it. Delete reserve: min(65,536, max_bytes // 10). New writes must fit frame + guard + applicable reserve.

## CLI (run from repository root)

```bash
./kvdb open PATH [--max-bytes N]  # create/recover; keys and recovery_ms
./kvdb put PATH KEY VALUE         # OK, or ERR reason (exit 1)
./kvdb get PATH KEY               # value, or NOTFOUND
./kvdb del PATH KEY               # missing key is allowed
./kvdb batch PATH OPERATIONS_FILE # lines: put key value / del key
./kvdb dump PATH                  # every key/value, sorted by key
./kvdb check PATH                 # read-only integrity/tail diagnostic
./kvdb serve PATH [--max-bytes N]  # stdin commands; durable ACKs
./kvdb inspect PATH               # extra: read-only frame layout
./kvdb compact PATH               # extra: physical before/after bytes
```

Use hex:HEX_BYTES for binary, empty or whitespace-containing tokens; get/dump apply the same encoding when necessary. Batch-file put values retain spaces. get/del/dump/check/inspect/compact on a missing database fail without creating it. open/put/batch/serve may create it. check/inspect never lock or repair a live file and do not promise a consistent snapshot during concurrent mutation.

## Serve protocol

```text
READY keys=N recovery_ms=M
put w1-1 key value       -> ACK w1-1
get w1-2 key             -> VAL w1-2 value / NOTFOUND w1-2
del w1-3 key             -> ACK w1-3
batch w1-4
put city Delhi
del old
end                     -> ACK w1-4
compact w1-5             -> ACK w1-5
quit
```

The prefix before '-' names a writer. Each has its own worker/queue; responses are FIFO within a writer and may interleave between writers. Up to 64 workers and 64 queued requests per worker; BUSY rejects a saturated queue. Errors: INVALID, DISKFULL, POISONED, IO, UNCERTAIN, UNSUPPORTED, INTERNAL, BUSY; startup can report LOCKED/CORRUPT/IO/INVALID without an ID. Error responses are not ACKs. EOF/quit drains workers before close.

## Torture and qualification

```bash
./torture --iterations 500 --seed 12345 --mode default
./torture --iterations 100 --seed 7 --mode compaction
./torture --iterations 100 --seed 42 --mode recovery-crash
python3 -B -m tests.bench_f3_kill --seed 31337
```

Default: 500 rounds. Modes: default, large-values, large-batch, recovery-crash, compaction, disk-full, crashpoints. The tool owns the independent sent/ACK log, kills with SIGKILL, then open/check/dump and whole-history checks. Seeded plans/delays do not reproduce OS scheduling exactly. Oracle mismatches stop immediately and print expected/found values and operation IDs. Some malformed-output cases, including duplicate dump keys, are currently classified as tool errors and allow later rounds to continue; the final exit remains nonzero. Tool errors never count as PASS. This first-failure limitation is documented in BREAKING.md. WSL runs should add `--host-storage-dir /mnt/d --min-free-gib 20` for the Windows volume hosting the VHD; check the system drive too. See [full offline preparation](OFFLINE_TEST_PLAN.md).

The maintained F3 benchmark now fails if reported recovery is >=2,000 ms or unavailable. Physical power loss, arbitrary bit rot, networking, sharding and MVCC are outside the required crash model. TTL is a proposed demo design only. Input retention and very long logs remain real limits; no claim covers the roughly 10 GiB combination of 10,000 distinct maximum-sized values.

## Verification scope and live demonstrations

The ordinary torture command does not enforce the two-second recovery limit and reuses each default database for three rounds. Use tools/ps_f1_same_database.py for 500 consecutive restarts of one file, and the strict F3/performance helpers for million-key and million-record recovery. tools/run_ps_acceptance.py orchestrates the wider suite; see [its command guide](tools/README.md).

The [manual report](MANUAL_TEST_REPORT.md) records 153 tests and 4,400 crash rounds on f1a1c0c, with 200 default rounds in 103.159 seconds and 100+100 targeted rounds in 37.069 seconds. These are historical measurements with identified source, not a guarantee for every future seed, dataset or laptop. The required recovery threshold is strictly less than 2,000 ms; setup, writes and full-data verification take additional time.

```bash
python3 ./prove --list
python3 ./prove A2
```

The live proof helper demonstrates selected scenarios and prints file/check/recovery output. It keeps files under ~/tmp_test/prove (or KVDB_PROVE_DIR); a repeated scenario replaces its own demonstration files. It is not the complete acceptance gate: B1/B6 use random torn prefixes, B6 does not enforce its printed timing, and F4 permits last-record loss in its assertion. Use the exact-prefix helpers, strict benchmarks and tail-guard regressions for those requirements.

Seeded torture plans and delays aid reproduction; OS scheduling still varies, and the injected torn-prefix byte count is not currently controlled by the runner seed. The independent oracle has a 250,000-state search budget and reports a tool error if it cannot decide. Automated storage tests do not cover physical Wi-Fi-off operation or live explanations.
