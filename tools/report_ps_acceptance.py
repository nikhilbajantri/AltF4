"""Audit completed PS evidence and write a truthful acceptance report (no database writes)."""
import argparse, collections, gzip, hashlib, json, re, shutil
from datetime import datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()

def transcript(path, expected):
    counts = collections.Counter(); points = collections.Counter(); passes = []; kills = 0
    with gzip.open(path, 'rt') as source:
        for line in source:
            row = json.loads(line); event = row.get('event'); counts[event] += 1
            if event == 'PASS': passes.append(row['iteration'])
            if event == 'KILL': kills += 1
            if event == 'RESULT' and row.get('point'):
                assert row.get('returncode') == -9, row
                points[row['point']] += 1; kills += 1
            assert event not in ('FAIL', 'TOOL_ERROR'), row
    assert len(passes) == expected and sorted(passes) == list(range(1, expected+1)), (path,len(passes))
    return dict(path=str(path), sha256=digest(path), bytes=path.stat().st_size,
                pass_rounds=len(passes), kill_records=kills, events=dict(counts), points=dict(points))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--failed-run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); run=args.run
    state=json.loads((run/'manifest.json').read_text())
    assert state['active_phase']=='complete', 'Campaign is still running'
    assert state['sources_unchanged'], 'Sources changed during the campaign'
    for name, value in state['sources'].items():
        assert digest(ROOT/name)==value, 'Source changed since campaign: '+name
    args.output.mkdir(parents=True,exist_ok=True)
    perf=json.loads((run/'performance/results.json').read_text())
    contracts=json.loads((run/'contracts/results.json').read_text())
    specific=json.loads((run/'specific/results.json').read_text())
    half=json.loads((run/'half_batch/results.json').read_text())
    assert half['status']=='PASS' and half['complete_operation_prefix']==5000
    assert digest(ROOT/'tools/check_ps_half_batch.py')==half['source_sha256']
    audits=[]
    gate_dirs=list((run/'modes').glob('gate-*'))
    assert len(gate_dirs)==1, gate_dirs
    gate=gate_dirs[0]; manifest=json.loads((gate/'manifest.json').read_text())
    assert len(manifest['results'])==7, 'Not all seven modes finished'
    assert manifest['success'] and manifest['sources_unchanged'], manifest
    for item in sorted(manifest['results'],key=lambda row:row['mode']):
        assert item['pass'] and item['exit']==0, item
        name='%s-%s'%(item['mode'],item['seed'])
        files=list((gate/name).rglob('oracle.log.gz'))
        assert len(files)==1, (name,files)
        audit=transcript(files[0],500)
        audit.update(mode=item['mode'],seed=item['seed'],summary=item['summary'])
        if item['mode']=='crashpoints': assert len(audit['points'])==14, audit
        if item['mode']=='compaction': assert len(audit['points'])==4 and set(audit['points'].values())=={125}, audit
        audits.append(audit)
    f1=json.loads((run/'same_database_f1/result.json').read_text())
    assert f1['success'] and f1['passed']==f1['iterations']==500, f1
    audit=transcript(run/'same_database_f1/oracle.log.gz',500)
    audit.update(mode='F1 one persistent database',seed=f1['seed']); audits.append(audit)
    unit=(run/'unit.txt').read_text()
    found=re.search(r'Ran (\d+) tests in ([0-9.]+)s\s+OK\s*$',unit)
    assert found, 'Regression suite did not pass'
    assert all(row['status']=='PASS' for row in specific), specific
    assert all(row['under_two_seconds'] and row['wall_under_two_seconds'] for row in perf['f3_runs'])
    assert all(row['under_two_seconds'] for row in perf['separate_frame_runs'])
    assert all(row['exit']==0 for row in state['phases'].values()), state['phases']
    summary=dict(run=str(run),tested_commit=state['commit'],source_hashes_verified=True,
                 audit_tools_sha256={name:digest(ROOT/name) for name in ('tools/report_ps_acceptance.py','tools/check_ps_half_batch.py')},
                 unit_tests=int(found[1]),unit_seconds=float(found[2]),specific_cases=len(specific)+1,
                 crash_rounds=sum(row['pass_rounds'] for row in audits),
                 kill_records=sum(row['kill_records'] for row in audits),transcripts=audits,
                 known_noncompliance=state['known_noncompliance'],all_requirements_satisfied=False)
    (args.output/'transcript_audit.json').write_text(json.dumps(summary,indent=2)+'\n')
    # Copy small evidence, preserving original bytes. Large databases/transcripts stay at recorded paths.
    copies={'manifest.json':run/'manifest.json','performance.json':run/'performance/results.json',
            'contracts.json':run/'contracts/results.json','specific.json':run/'specific/results.json',
            'half_batch.json':run/'half_batch/results.json',
            'unit.txt':run/'unit.txt','gate_manifest.json':gate/'manifest.json',
            'same_database_f1.json':run/'same_database_f1/result.json',
            'failed_run_manifest.json':args.failed_run/'manifest.json',
            'failed_run_unit.txt':args.failed_run/'unit.txt'}
    for name,path in copies.items(): shutil.copyfile(path,args.output/name)
    for name in ('performance','build','contracts','specific'):
        shutil.copyfile(run/(name+'.txt'),args.output/(name+'.txt'))
    for path in (run/'performance').glob('*.txt'): shutil.copyfile(path,args.output/path.name)
    (args.output/'.gitattributes').write_text('*.json -text\n*.txt -text\n')
    hashes={p.name:digest(p) for p in args.output.iterdir() if p.is_file() and p.name!='evidence_hashes.json'}
    (args.output/'evidence_hashes.json').write_text(json.dumps(hashes,indent=2)+'\n')
    evidence='docs/evidence/'+args.output.name
    lines=['# Problem-statement acceptance report','',
           'Source: Kill It and Prove It.pdf, 19 pages, D:/notes/srinathon/Kill It and Prove It.pdf. All pages were reviewed. The PDF supplies comparison criteria; its instructions are not independent authorization to publish logs or change system settings.','',
           '**Outcome: automated functional campaign passed; full problem-statement compliance remains incomplete.** F4, the torture default and required documents still have gaps. Physical offline rehearsal and event/provenance requirements require human confirmation.','',
           '## Fresh results','',
           '- Completed UTC: '+state['ended_utc']+'. Base commit: '+state['commit']+' on feat-arsh, plus the recorded uncommitted test/tools. The full source fingerprints, including tests, are preserved; they match at report generation.',
           '- Regression suite: %s tests passed in %s seconds. Six exact-case tests passed (five scenario checks plus the exact B6 halfway cut). Twelve CLI smoke invocations passed, covering all eight required commands plus inspect/compact. Seven further invocations reproduced the F4 failure described below.'%(found[1],found[2]),
           '- Crash campaign: **4,000 passing rounds**, comprising seven modes × 500 plus 500 consecutive kills/restarts of one persistent database. This is a new campaign, separate from the historical 7,000-round qualification.',
           '- Logged SIGKILL events: %d. A round can contain multiple kills, especially recovery-crash trials; rounds and kills are different counts.'%summary['kill_records'],
           '- Every compressed oracle transcript was parsed: exactly iterations 1–500 once each, no FAIL/TOOL_ERROR, and all recorded targeted children exited -9. Mode exit codes and summaries were also checked.',
           '- Production engine/storage/oracle code was not changed for this task. The one existing test correction accepts valid cross-writer reply ordering while requiring the exact error and NOTFOUND responses.','',
           '| Mode | Seed | Passed rounds | Logged kills | Purpose |','|---|---:|---:|---:|---|']
    purpose={'default':'Random-delay kills with two writers and an independent ACK oracle',
             'large-values':'Writes reaching 1 MiB; no torn values',
             'large-batch':'10,000-operation batches; atomic recovery',
             'recovery-crash':'Repeated kills during scan and tail repair',
             'compaction':'All four replacement/copy interruption points',
             'disk-full':'Clean cap rejection, readability, recovery and reuse',
             'crashpoints':'All 14 named hooks; sampled hit counts',
             'F1 one persistent database':'500 random kills while carrying recovered state into the next round'}
    for row in audits: lines.append('| %s | %s | %s | %s | %s |'%(row['mode'],row['seed'],row['pass_rounds'],row['kill_records'],purpose[row['mode']]))
    hook_details = {
      'init_before_rename':('engine.py _create','Synced .init before path replacement','Remove stale temp; create/recover authoritative path'),
      'before_write':('engine.py _write','Only prior frames','New operation absent'),
      'torn_write':('engine.py _write','Prior frames plus incomplete prefix','Discard tail; preserve prior operations'),
      'after_write':('engine.py _write','Complete frame, fsync not yet returned','Replay whole valid frame; no partial batch'),
      'after_fsync':('engine.py _write','Frame durable; index not yet updated','Replay frame into rebuilt index'),
      'after_return':('serve.py run/execute','Engine returned; ACK not printed','Durable operation survives without observed ACK'),
      'recovery_mid_scan':('engine.py _scan','Original log unchanged','Restart scan from beginning'),
      'recovery_before_truncate':('engine.py _recover','Torn tail remains','Retry repair'),
      'recovery_after_truncate':('engine.py _recover','Tail removed and file synced','Reopen valid prefix'),
      'compact_mid_copy':('engine.py _copy_live','Old authority plus partial temp','Use old file; discard temp'),
      'compact_before_rename':('engine.py _compact_locked','Old authority plus complete synced temp','Use old file; discard temp'),
      'compact_after_rename':('engine.py _compact_locked','Path names complete replacement','Recover new complete file'),
      'compact_after_swap':('engine.py _compact_locked','Replacement synced; descriptor/index swapped','Recover new file; later writes use replacement'),
      'close_mid':('engine.py close','Accepted writes already durable','Reopen independently of close cleanup')}
    named=next(row['points'] for row in audits if row['mode']=='crashpoints')
    lines+=['','## Fourteen named crash locations','',
            'These are deliberate test hooks, distinct from random-delay kills. Counts below are recorded SIGKILL results in the crashpoints mode; repair cases can include an extra torn-write kill used to prepare their input. All paths are under src/.','',
            '| Hook | Recorded kills | File / function | Disk state | Next recovery |',
            '|---|---:|---|---|---|']
    for point,details in hook_details.items():lines.append('| %s | %s | %s | %s | %s |'%(point,named[point],*details))
    lines+=['','## Strict recovery and shrink checks','',
            'All thresholds are strictly less than 2,000 ms, not less-than-or-equal. Recovery was measured before the concurrent crash campaign. These measurements do not establish timing on another laptop or after evicting OS caches.','',
            '| Real engine F3 seed | Engine recovery ms | Complete open CLI ms | Result |',
            '|---|---:|---:|---|']
    for row in perf['f3_runs']:lines.append('| %s | %.3f | %.3f | PASS |'%(row['seed'],row['engine_recovery_ms'],row['cli_wall_ms']))
    lines+=['','F3 uses real serve ACKs, SIGKILL and verification of all recovered data. Its million keys are written in large batch frames. Separately, the format-generated diagnostic has **exactly one million independent one-operation frames**, with every value checked on the first timed open. This diagnostic is not an ACK/crash durability test.','',
            '| Diagnostic repeat | Engine recovery ms | API wall ms | Keys | Result |','|---|---:|---:|---:|---|']
    for row in perf['separate_frame_runs']:lines.append('| %s | %.3f | %.3f | %s | PASS |'%(row['repetition'],row['engine_recovery_ms'],row['api_wall_ms'],row['keys']))
    lines+=['','The new diagnostic measurements above are API opens, not complete CLI startup times. Historical separate-record CLI samples are retained in docs/PDF_REQUIREMENTS_AUDIT.md and must not be relabelled as this run.',
            '', 'B6 exact halfway recovery: %.3f ms; the first 5,000 of 10,000 operations were written, the child exited -9 without ACK, and none of the batch was visible. The earlier random-prefix B6 measured %.3f ms.'%(half['engine_recovery_ms'],perf['B6']['engine_recovery_ms']),'',
            'Million-put/million-delete benchmark output:','', '```text',perf['million_delete_compaction']['output'].rstrip(),'```','',
            '## Failure retained and corrected','',
            'The first campaign stopped at the regression prerequisite: 143 tests ran, and test_malformed_batch_header_does_not_execute_body failed because it required NOTFOUND to be the final reply. A header without an ID gets operation ID "-" and an empty writer prefix; the later get uses prefix "w1". The server promises order within each writer, while replies between writers can interleave. The test now checks the exact error and NOTFOUND responses without imposing an unsupported order. Its existing no-ACK assertion remains. No engine fault was demonstrated by that failure.',
            '', 'The failed manifest and unit output are retained alongside the successful run. Four thousand crash rounds were started only after the corrected full suite passed. Exact-case test development also had a test-only launcher setup error; its corrected preflight is not counted as an engine failure or as extra campaign rounds.','',
            '## Exact 32 scenario checklist','',
            'PASS means the stated automated experiment passed under the process-kill model; it is evidence, not an exhaustive proof of all instruction interleavings. DESIGN EQUIVALENT means the PDF describes a commit-marker arrangement this format does not implement. W/C/R below refer to the named regression tests in tests/test_crash_campaign.py; their results are in unit.txt.','',
            '- W: test_all_write_points_for_put_delete_batch_large_value_and_large_batch.',
            '- C: test_all_compaction_points_with_multiple_frames.',
            '- R: test_repeated_crashes_during_recovery.',
            '', '| ID | PDF scenario / page | Result | Mechanism, code and fresh evidence |','|---|---|---|---|']
    scenarios=[
    ('A1','Kill before put bytes / 5','PASS','src/engine.py _write: before_write; W preserves prior state.'),
    ('A2','Torn put / 5','PASS','_write torn_write; _scan discards incomplete frame; W and every-byte tail regression.'),
    ('A3','Full put before fsync / 5','PASS','_write after_write; complete CRC-valid frame may recover; W checks exact map.'),
    ('A4','After fsync before put return / 5','PASS','_write after_fsync; frame is synced before index publication; W verifies value.'),
    ('A5','Immediately after successful put / 6','PASS','specific A5_acknowledged_put: real serve ACK then SIGKILL; full map verified.'),
    ('A6','During delete / 6','PASS','_commit/_write; W delete at all five write points; deletion remains whole.'),
    ('A7','During 1 MB value / 6','PASS','W exact 1 MiB value and 500 large-values rounds; no partial value.'),
    ('B1','First 3 of 10 operations written / 6','PASS','specific B1_exact_three_of_ten cuts real frame at operation-three boundary; SIGKILL; none visible.'),
    ('B2','Ten ops written, commit marker absent / 6','DESIGN EQUIVALENT','src/format.py frame CRC is in the prefix; no separately appended commit marker exists. All bytes plus valid CRC is already a complete commit unit. Incomplete-frame cuts expose none. Exact absent-trailing-marker state is not representable; judge explanation needed.'),
    ('B3','Marker written before fsync / 6','PASS (equivalent)','Complete CRC-valid batch frame before fsync maps to _write after_write; W accepts whole frame, never subset.'),
    ('B4','Successful ten-operation batch / 6','PASS','specific B4_acknowledged_ten_op_batch: ten ops ACK then SIGKILL; all survive.'),
    ('B5','Put X then delete X in batch / 6','PASS','specific B5_put_then_delete_after_crash; _commit applies list order; X absent after crash. README documents order.'),
    ('B6','10,000 ops torn halfway, recovery <2s / 6','PASS','half_batch.json: exact prefix through operation 5,000 of 10,000, real write and SIGKILL; no ACK, prior anchor only; strict timed recovery. Random-prefix B6 and W also pass.'),
    ('C1','Kill replay scan / 6','PASS','_scan recovery_mid_scan; R and 500 recovery-crash rounds.'),
    ('C2','Kill torn-tail repair / 6','PASS','_recover recovery_before_truncate/recovery_after_truncate; R and targeted mode.'),
    ('C3','Compaction before replacement / 6','PASS','_copy_live/_compact_locked compact_mid_copy and compact_before_rename; C and compaction mode.'),
    ('C4','Compaction rename/swap / 6','PASS','_compact_locked os.replace boundary hooks; C and compaction mode. OS rename atomicity is assumed, not an injection inside kernel rename.'),
    ('C5','After swap before cleanup / 7','PASS','_compact_locked compact_after_swap; C checks old data, leftover temp removal and later writes.'),
    ('C6','During close / 7','PASS','close_mid; test_initial_creation_and_close_crashes and crashpoints mode.'),
    ('D1','Two writers different keys killed randomly / 7','PASS','runner.iteration independent sent/ACK histories; 500 default rounds plus 500 same-file F1 rounds.'),
    ('D2','Two writers same key killed randomly / 7','PASS','Shared-key histories checked by torturelib/oracle.py match; shared batch regression detects impossible maps.'),
    ('D3','Long batch racing single puts / 7','PASS','specific D3_long_batch_with_single_put: both entry markers observed; real engine, test-only delay and unchanged independent oracle; random kill.'),
    ('D4','Reader during same-key batch / 7','PASS','test_reader_cannot_observe_half_applied_batch and test_reader_sees_batch_all_or_nothing; get/_commit share lock.'),
    ('E1','Cap during put / 7','PASS','_check_space rejects before append; test_max_bytes and 500 disk-full rounds.'),
    ('E2','Cap during batch / 7','PASS','_check_space reserves full frame; cap and memory-preflight tests, disk-full mode; rejected batch absent.'),
    ('E3','Cap then kill / 7','PASS','disk-full mode close_mid SIGKILL; recovered full map compared against prior accepted writes.'),
    ('E4','Cap during compaction / 7','PASS','test_tiny_cap_during_compaction and failed-compaction preservation regressions; old/new complete state retained.'),
    ('E5','Delete, reclaim, write again / 7','PASS','test_compact_and_retry_on_disk_full, cap campaign and million-delete shrink check.'),
    ('F1','500 consecutive random kills/restarts / 8','PASS','ps_f1_same_database.py: all 500 use persistent.db, carrying the independently checked recovered state forward. Does not reset every three rounds.'),
    ('F2','Kill recovery repeatedly / 8','PASS','R and recovery-crash mode repeat three interrupted recovery attempts before final complete-map check.'),
    ('F3','Million keys, kill, open <2s, ACKs preserved / 8','PASS','Three fresh real-engine F3 seeds, strict recovery and complete CLI thresholds, all recovered values checked.'),
    ('F4','Remove one trailing byte; lose at most unACKed / 8','FAIL (literal)','contracts.json: a,b,c each returned OK; truncate one byte; open succeeds but c is missing. Existing test expects this loss and therefore does not prove literal PDF compliance.')]
    assert len(scenarios)==32
    for row in scenarios:lines.append('| '+' | '.join(row)+' |')
    lines+=['','## Every other requirement and rule','',
            'Repeated statements are grouped with all relevant pages. PASS (inspection) means source/document review, not a new independent runtime test. MANUAL and PARTIAL are not passes. Advisory schedules and explicit exclusions are identified separately.','',
            '| Requirement / PDF page(s) | Status | Finding / evidence |','|---|---|---|']
    requirements=[
    ('Single-process embedded library; six operations / 1–2,8','PASS','src/engine.py KVDB exposes put/get/delete/batch/open via constructor/close; unit and real CLI checks.'),
    ('Durable overwrite and successful delete; missing delete allowed / 2,4','PASS','Regression suite and independent ACK oracle include overwrite, existing/missing deletes, crash recovery.'),
    ('Batch wholly present or absent; no garbage values / 2,4','PASS','One checked frame, lock-protected publication, whole-map oracle and planted-corruption detector tests.'),
    ('Byte keys 1–1,024 and values 0–1 MB / 2','PASS (boundaries)','format constants/validation and exact boundary regressions; binary/empty values via hex tokens. Maximum is 1 MiB, at least the decimal MB requirement.'),
    ('At least one million keys / 2','PASS','Three real-engine runs exceed one million; diagnostic has exactly one million individually verified keys.'),
    ('Batches up to 10,000 ops / 2','PASS (count boundary)','10,000 accepted, 10,001 rejected; exact large-batch recovery and gate coverage.'),
    ('Simultaneous 10,000 distinct maximum-sized values / 2','PARTIAL / NOT RUN','Independent size/count limits pass, but their ~10 GiB distinct-input combination is not qualified. Bounded encoding does not bound caller inputs, index or queues; no unsafe 10 GiB allocation was attempted.'),
    ('Two concurrent writers incl. delete/batch; concurrent get / 2','PASS','Two writer prefixes, shared/private histories, explicit D3 overlap and D4 reader tests; allowed global lock.'),
    ('One authoritative data file; temp/lock exceptions / 2–3','PASS (inspection)','One append-only file, in-memory index; .lock/.init/.compact are auxiliary, never a second independent authority.'),
    ('Compaction shrinks and survives crashes / 3','PASS','Million-delete shrink, four compaction hooks, C3–C5 regressions.'),
    ('Configurable maximum; clear error; rejected writes preserve data / 3','PASS','--max-bytes, DiskFull and DISKFULL responses, preflight and disk-full campaign. I/O UNCERTAIN path is explicitly distinct from clean cap rejection.'),
    ('Honest fsync; abrupt process death not cleanup / 4–5,18','PASS','_pwrite_all + os.fsync before success; children exit SIGKILL (-9). ext4 disk-backed test files; not a RAM disk.'),
    ('open remains recoverable after own process crashes / 4–5','PASS (tested states)','Recovery and compaction campaigns cover named and random states; not a mathematical proof of every possible schedule.'),
    ('open under two seconds with million keys / 2,8,19','PASS (measured)','Strict fresh F3 and million-record results above; future timing depends on log length, cache, CPU and judging laptop.'),
    ('Eight exact CLI behaviours; sorted dump, check, timed open / 8–9','PASS','Twelve smoke calls cover all eight names and output checks; seven additional calls reproduce F4. Binary-safe sorted dump. Extra inspect/compact also work.'),
    ('Serve ACK only after durability / 9','PASS','serve execute ACK follows engine return; source ordering, hook tests and planted-early-ACK regression.'),
    ('Torture child serve, random ops and >=2 writers / 9','PASS','runner.iteration with w1/w2, random puts/deletes/batches; independent log.'),
    ('Independent ACK oracle, not dump-derived expected truth / 9–10','PASS','SENT/RESPONSE history is checked against dump via oracle.match. Negative detector regressions remain enabled.'),
    ('Genuine random millisecond-delay SIGKILL / 9','PASS','Seeded logarithmic delays; actual proc.kill, -9 required. Targeted modes separately force exact boundaries.'),
    ('Restart open/check/dump and verify complete map / 10','PASS','protocol.recovered and oracle.match; no success based only on opening.'),
    ('Default 500 rounds / 10','FAIL','runner parser still defaults to 25. Explicit --iterations 500 passes but does not satisfy the default requirement.'),
    ('Per-round and final pass/fail summaries / 10','PASS','Gate logs contain 500 per-round passes plus exact zero-error summaries; transcripts independently counted.'),
    ('Stop first invariant failure with expected/found/op IDs / 10','PASS (inspection/tests)','Assertions stop the runner; oracle provides mismatch/history. Tool errors are separate, never PASS; tool-error continuation is documented, low space stops.'),
    ('Five minimum targeted modes / 10','PASS','large-values, large-batch, recovery-crash, compaction, disk-full; each freshly passed 500 rounds.'),
    ('Mandatory seed; unfamiliar seeds; reproduction / 10','PASS (qualified scope)','Workloads, delays and hook choices are seeded and regression-tested. OS thread scheduling is not deterministic; retain full transcript for exact history.'),
    ('No rigged checker; kills during writes / 10,17','PASS (tested detector)','Forced write boundaries plus random kills; early-ACK/partial-batch negative tests. Pending request alone is not proof a write was executing.'),
    ('README one documented build command; clean toolchain / 9,14','PASS (tested setup)','make build and fresh committed local clone pass with installed Python/make/git; Windows native real engine is not supported.'),
    ('README all commands and plain-English recovery / 9','PASS (inspection)','Existing README documents commands and replay/tail repair; fresh CLI checks validate them.'),
    ('README one-page accurate format with diagram / 9','PARTIAL','Byte fields/checksum text matches format.py; README itself lacks the requested on-disk diagram; one-page rendering not verified.'),
    ('ARCHITECTURE all components/format/locks/numbered order/recovery in one diagram / 12','FAIL / PARTIAL','Broad diagram omits detailed byte layout/numbered ordering/cap guard; existing PNG describes obsolete stubs. It needs replacement.'),
    ('ARCHITECTURE exactly 32 correct proof rows, disk/code/verification columns / 12–13','FAIL','41 rows, 32 unique IDs, nine duplicate IDs; multiple IDs map to wrong scenarios. This report supplies a correct audit checklist, but does not silently repair that deliverable.'),
    ('Honest Not verified rows / 13','ALLOWED','The PDF explicitly allows Not verified. Wrong scenario IDs/mechanisms are the actual problem; no blanket PASS labels were inserted.'),
    ('ARCHITECTURE three guarantee arguments naming calls/order / 13','PARTIAL','Arguments exist; reconcile their evidence and claims with the corrected diagram/table and literal F4 limitation.'),
    ('BREAKING <=2 pages; five required sections / 10–11','PARTIAL','Substantive sections exist, but two-page rendered limit is not verified and final priorities are stale.'),
    ('BREAKING crash table exact functions, disk state, recovery; 8–15 rows / 11','PARTIAL','14 hook rows but no explicit source function/line per row; add exact function locations.'),
    ('BREAKING syscall ordering, >=3 weaknesses, failed attempts / 11','PASS / PARTIAL','Weaknesses and failed attempts are honest; ordering is present but should explicitly name pwrite, fsync, replace and directory fsync.'),
    ('BREAKING three concrete prioritized 24-hour improvements / 11','PARTIAL','Three priorities exist but need concrete remaining-development scope rather than completed qualification.'),
    ('Original chronological unedited prompts, tool and approx time / 11–12','FAIL','PROMPTS.md is an empty log template. User requested a later prompt report; no fabricated dates, sanitized substitutions or false no-AI claim were inserted.'),
    ('Standard library only; no storage/ORM/WAL libraries / 3,17','PASS (static check)','Runtime imports found no non-stdlib dependencies outside project packages; provenance cannot be certified by an import scan.'),
    ('No copied DB code, no pre-event code, fresh event repo / 3,17','MANUAL','Requires event start/end and source provenance review. Do not infer from passing tests.'),
    ('Meaningful commits throughout / 4','PASS (history present) / MANUAL','History contains incremental changes. Team must verify those commits fall inside actual event window.'),
    ('Team 2–4; no inter-team code sharing / 1,4,17','MANUAL','Repository cannot establish team count or conduct.'),
    ('All runs offline on own laptop / 4,14–15','PARTIAL / MANUAL','Fresh local committed clone built and put/get under a verified Python socket guard. Radios were not physically turned off; see OFFLINE_TEST_PLAN.md.'),
    ('Official 15-minute fixed schedule / 14–15','PARTIAL / MANUAL','Offline plan follows exact schedule; existing DEMO.md run-of-show differs. Rehearse actual elapsed time.'),
    ('Build 0–1; default200 1–4; targeted 4–6 / 14–15','MANUAL','Full preparation campaign is not proof these steps fit live windows. Judge chooses seeds/counts.'),
    ('Human 5–10 manual kills/check/dump 6–8 / 15','MANUAL','Automated repeated SIGKILL is distinct from a human rehearsal; prior demo capture has two controlled kills.'),
    ('Three source-line answers 8–12; every member can explain / 13,15','MANUAL','Use the exact 32 rows to rehearse disk state and next-open action without running code.'),
    ('TTL design answer 12–15, including subtle issue / 15','DESIGN ONLY / MANUAL','Existing demo labels TTL proposed. No implemented TTL required; rehearse format/recovery/compaction and clock/batch edge case.'),
    ('No AI or internet during official demo / 15,17','MANUAL','This preparation session is not the official judging session. Human team must comply during judging.'),
    ('One repo URL/zip incl .git; deliverables present / 14','PARTIAL / MANUAL','Core files/history exist but documents have gaps; new acceptance files remain uncommitted until explicitly finalized.'),
    ('Final push/submission before deadline, charged laptop / 14','MANUAL','No push or submission performed by this audit; confirm event deadline and charger/battery.'),
    ('Scoring/penalties/spot checks / 16–17','INFORMATION','No self-awarded score. Missing prompt log and incorrect proof rows can cost points despite passing crash runs.'),
    ('Suggested 24-hour timeline / 17–18','ADVISORY','The PDF explicitly permits a different working order; it is not another runtime test.'),
    ('Power loss, OS crash, bit rot, network, sharding, MVCC, extra speed / 5,8','NOT REQUIRED','Process death with honest fsync is the required fault model. Do not list optional features as mandatory unfinished work.'),
    ('Strict million-record FAQ, no language penalty / 18–19','PASS (measured) / INFORMATION','Exactly million-record diagnostic measured separately; Python is allowed. Recovery is strict on the judging laptop; slow writes alone do not fail.')]
    for row in requirements:lines.append('| '+' | '.join(row)+' |')
    lines+=['','## Remaining actions in order','',
            '1. Resolve literal F4: either implement recoverable redundancy for the acknowledged truncated record or obtain an explicit organizer interpretation. Current evidence is a literal failure; do not weaken the test.',
            '2. Set the torture default to 500 with a regression; enforce the strict threshold in the standalone F3 benchmark as well as the acceptance wrapper.',
            '3. Repair the architecture diagram and exact proof table, README format diagram, BREAKING function locations/length/priorities and fixed demo schedule.',
            '4. Assemble actual original prompt history with tool names and honest approximate times. A polished report can supplement it, but cannot replace the PDF’s unedited log.',
            '5. Freeze/commit the intended checkout, run the physical offline rehearsal from OFFLINE_TEST_PLAN.md, complete human sign-off and submit before the actual deadline.','',
            '## Evidence and reproduction','',
            '- [Transcript audit]('+evidence+'/transcript_audit.json), [source/phase manifest]('+evidence+'/manifest.json), [raw performance results]('+evidence+'/performance.json), [CLI/contracts]('+evidence+'/contracts.json), [exact cases]('+evidence+'/specific.json), [regression output]('+evidence+'/unit.txt).',
            '- [Failed prerequisite evidence]('+evidence+'/failed_run_unit.txt) and [its manifest]('+evidence+'/failed_run_manifest.json) are retained; checksums cover the copied artifacts.',
            '- Original large databases and gzipped transcripts remain at '+str(run)+'. Their exact paths, lengths and SHA-256 hashes are in transcript_audit.json. Small evidence is copied into the repository; large raw transcripts are not falsely claimed to be included in Git.',
            '- Re-run online/preparation: python3 -B tools/run_ps_acceptance.py --host-storage-dir /mnt/c --host-storage-dir /mnt/d, then python3 -B tools/check_ps_half_batch.py --output NEW_OUTPUT_DIRECTORY. Known noncompliance deliberately produces nonzero exit even when functional campaigns pass.',
            '- [Physical offline plan](OFFLINE_TEST_PLAN.md) includes clean-clone commands, evidence capture, fixed 15-minute schedule and human sign-off. Physical network isolation is not claimed as completed.',
            '', 'This report completes the requested requirements audit, test campaign and offline plan. It does not declare the project fully compliant, modify the prompt log, or certify event conduct.']
    (ROOT/'PS_ACCEPTANCE_REPORT.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k!='transcripts'},indent=2))
    print('Report: '+str(ROOT/'PS_ACCEPTANCE_REPORT.md'))

if __name__=='__main__':main()
