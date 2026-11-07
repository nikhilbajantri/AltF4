# Kill It and Prove It

Crash-safe embedded key-value storage in Python. Linux/ext4; Python 3.10+ standard library. Install Python, make and Git before an offline rehearsal. Run the real engine in Linux/WSL; --fake is only a practice stub.

## Build and test

From the repository root: `make build`. Run regression tests with `make test`. Keep database/test files on real Linux storage, for example ~/tmp_test, not a RAM disk. See [the latest gap-fix report](docs/GAP_FIX_REPORT.md) and [offline plan](OFFLINE_TEST_PLAN.md) for measured results and remaining human checks.

## Hands-on testing

See [Arsh's measured manual rehearsal report](MANUAL_TEST_REPORT.md) for actual results and timing limits, and the [complete two-terminal command guide](docs/MANUAL_TEST_COMMANDS.md) for setup, commands, expected outputs and explanations.

## Live proof

`./prove <ID>` replays one crash scenario live through the public `./kvdb` CLI: it builds a fresh database, SIGKILLs a command at a named crash point (`KVDB_CRASH=name:n`), then shows inspect, check, open and get output and prints PASS or FAIL with the invariant.
Databases are kept in `~/tmp_test/prove/<ID>.db` (or `$KVDB_PROVE_DIR`) so they can be inspected afterwards.
Covered IDs: A1 A2 A3 A4 A6 A7 B1 B5 B6 C1 C2 C3 C4 C6 E1 F4.

    ./prove --list
    ./prove A2
    ./prove --all

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

## Write, recovery and compaction

Validate/calculate size; acquire the engine mutex; reject poisoned handles; check full frame plus guard against max_bytes before allocating encoded data. Reclaim dead data and retry once if needed. Prepare CRC encoding (large encodings use bounded 4 MiB chunks). Loop on os.pwrite at the logical end, replacing the old guard; append the new guard; os.fsync; publish the whole batch/index/end; finish any automatic compaction; release lock and return. serve prints ACK only afterward.

On write/fsync error, truncate the attempted append, restore the guard, sync rollback and poison the handle. UNCERTAIN means rollback could not be confirmed: the operation can be present or absent on reopen. Reconcile application state before retrying.

Open locks path.lock with flock, removes stale .init/.compact files and creates a synced header through temp-file replacement if missing. It validates the header and replays complete checked frames to rebuild the index. It truncates an incomplete tail, restores the guard when space allows and syncs before readiness. A crash during scan/repair can be retried. get/items and writes share one mutex; separate get calls are not a multi-key snapshot.

Compaction holds that mutex, copies live keys into <=4 MiB/<=10,000-op frames in path.compact, checks the cap including the final guard, appends the guard if nonempty, fsyncs/closes, os.replace's the authoritative file, fsyncs the directory, then reopens/swaps descriptor/index/end. Empty compaction leaves 16 bytes. Triggers: explicit compact; cap retry with dead data; >50% dead bytes in a >4 MiB file.

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

Default: 500 rounds. Modes: default, large-values, large-batch, recovery-crash, compaction, disk-full, crashpoints. The tool owns the independent sent/ACK log, kills with SIGKILL, then open/check/dump and whole-history checks. Seeded plans/delays do not reproduce OS scheduling exactly. It stops on invariant failure; tool errors never count as PASS. WSL runs should add `--host-storage-dir /mnt/d --min-free-gib 20` for the Windows volume hosting the VHD; check the system drive too. See [full offline preparation](OFFLINE_TEST_PLAN.md).

The maintained F3 benchmark now fails if reported recovery is >=2,000 ms or unavailable. Physical power loss, arbitrary bit rot, networking, sharding and MVCC are outside the required crash model. TTL is a proposed demo design only. Input retention and very long logs remain real limits; no claim covers the roughly 10 GiB combination of 10,000 distinct maximum-sized values.
