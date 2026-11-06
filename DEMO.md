# Demo
This document is the plan for a 15-minute demonstration of the database. It covers building the project, running tests, showing a server session, explaining crash recovery, and discussing the proposed TTL design.

## Build
For the clean-clone demo, get a fresh copy of the repository and build it:

```bash
git clone [PASTE THE TEAM'S REPOSITORY URL HERE]
cd [THE NEW PROJECT FOLDER]
make build
```

Actual build output:

```text
[PASTE THE OUTPUT FROM THE DEMO RUN]
```

## Torture commands
Use the agreed team seed so the test can be repeated:

```bash
./torture --iterations 200 --seed [TEAM_SEED]
./torture --iterations 200 --seed [TEAM_SEED] --mode compaction
./torture --iterations 200 --seed [TEAM_SEED] --mode recovery-crash
```

Replace `[TEAM_SEED]` with the number chosen by your team. Run these commands before the demo to confirm they work.

During the first test, point out the in-flight percentage once. During the compaction and recovery-crash tests, explain which test is running.

Actual results:

```text
[PASTE THE OUTPUT FROM THE DEMO RUN]
```
## Manual kill session
Start the server and type a batch by hand:

```bash
./kvdb serve demo.db
```

At the server prompt, enter:

```text
batch w1-1
put color blue
put animal cat
end
```

Then enter:

```text
quit
```

For the crash demonstrations, use the exact crash commands supported by the current branch. Examples from the project plan are:

```bash
KVDB_CRASH=torn_write:1 ./kvdb batch db.ops.txt
KVDB_CRASH=compact_before_rename:1 ./kvdb compact db
KVDB_CRASH=compact_after_rename:1 ./kvdb compact db
```

After each crash, reopen and check the database using the commands supported by this branch. The project plan mentions:

```bash
./kvdb open db
./kvdb check db
./kvdb dump db
./kvdb inspect db
```

Actual commands and results from my rehearsal:

```text
[PASTE WHAT YOU REALLY RAN AND WHAT IT PRINTED]
```

## Crash-here answers
1. **During a frame write:** The file may contain earlier frames and part of a new frame → recovery detects an incomplete frame, truncates it, and syncs the file → an incomplete frame is not committed.
2. **After writing, before `fsync`:** A full frame may be in the operating system’s cache → recovery replays it if its length and CRC are valid → no ACK has been sent yet, so the request may still be uncertain to the client.
3. **After `fsync`, before the engine returns:** A complete frame is durable → recovery replays it → saved data does not depend on the old in-memory index.
4. **After the engine returns, before ACK:** The frame is durable, but the client did not receive confirmation → recovery replays it → a request without an ACK may have completed.
5. **Halfway through a 10,000-operation batch:** The batch is one frame, and that frame is incomplete → recovery applies none of its operations → a batch is all-or-nothing.
6. **During recovery’s scan:** The database file has not been changed by the scan → the next open performs the scan again → scanning is read-only.
7. **During `ftruncate`:** The damaged tail may or may not have been cut off → the next open scans again and truncates to the same valid stopping point → recovery can safely repeat this repair.
8. **During compaction, before rename:** The old database is still at the database path; a `.compact` file may be incomplete → the next open uses the old database and removes the temporary file → a temporary file does not replace the database.
9. **After rename, before directory `fsync`:** The database path names the new compacted file → reopening checks that file; directory syncing is needed for power-loss durability → rename and directory sync are separate steps.
10. **During header creation:** A `.init` file may exist without the database path → the next open removes the temporary file and creates the header again → an incomplete initialization is not treated as a database.
11. **During `close()`:** All acknowledged frames should already have been synced → reopening reads those saved frames → closing should not be needed to make an ACKed write durable.
12. **When `fsync` fails:** The engine tries to truncate back to the previous end, sync the rollback, mark itself poisoned, and return an error → later writes are refused → the engine does not acknowledge a failed write.

## TTL answer

TTL means “time to live”: a key becomes absent after its expiry time.

The proposed design stores an absolute expiry time in milliseconds in each PUT. An expiry value of `0` means “never expires.” Reads and dumps treat a key as absent when the current time reaches its expiry. Compaction skips expired keys. Recovery replays the log without deleting records.

The design must use absolute times, not “seconds from now,” so a restart does not restart every timer. The team should also explain how it handles a clock moving backward. The torture oracle needs a controllable clock so expiry tests can be repeated.

[Confirm whether TTL is implemented in this branch. If it is only a proposal, label it as a proposed design, not a working feature.]
