"""Audit the completed two-seed gap-fix qualification and write its review report."""
import argparse,hashlib,json,re,shutil
from pathlib import Path
from report_ps_acceptance import transcript
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('qualification',type=Path);a=p.parse_args()
 snapshot=json.loads((a.qualification/'source_snapshot.json').read_text())
 runs=list((a.qualification/'results').glob('ps-acceptance-*'));assert len(runs)==1
 run=runs[0];state=json.loads((run/'manifest.json').read_text())
 assert state['active_phase']=='complete' and state['sources_unchanged'],state
 frozen=Path(snapshot['repository'])
 def canonical(path):return path.read_bytes().replace(b'\r\n',b'\n')
 normalized=[]
 for name,value in snapshot['sources'].items():
  assert sha(frozen/name)==value, 'Frozen file changed: '+name
  if name=='tools/record_demo_results.py':continue  # Capture-only hash portability fix; executed separately after qualification.
  assert canonical(ROOT/name)==canonical(frozen/name), 'Code differs beyond line endings: '+name
  if sha(ROOT/name)!=value:normalized.append(name)
 for name,value in state['sources'].items():
  assert sha(frozen/name)==value and canonical(ROOT/name)==canonical(frozen/name), 'Qualification mismatch: '+name
 assert all(v.get('exit')==0 for v in state['phases'].values()),state['phases']
 perf=json.loads((run/'performance/results.json').read_text());c=json.loads((run/'contracts/results.json').read_text())
 assert not c['F4_acknowledged_last_key_lost'] and c['torture_default_iterations']=='500',c
 assert c['architecture_ids']['rows']==c['architecture_ids']['unique']==32 and not c['architecture_ids']['duplicates'],c
 assert all(r['under_two_seconds'] and r['wall_under_two_seconds'] for r in perf['f3_runs'])
 assert all(r['under_two_seconds'] for r in perf['separate_frame_runs'])
 unit=(run/'unit.txt').read_text();u=re.search(r'Ran (\d+) tests in ([0-9.]+)s\s+OK\s*$',unit);assert u and int(u[1])>=153
 specific=json.loads((run/'specific/results.json').read_text());assert len(specific)==5 and all(r['status']=='PASS' for r in specific)
 half=json.loads((run/'half_batch/results.json').read_text());assert half['status']=='PASS' and half['complete_operation_prefix']==5000 and half['child_exit']==-9
 gate=next((run/'modes').glob('gate-*'));m=json.loads((gate/'manifest.json').read_text())
 assert m['success'] and m['sources_unchanged'] and m['iterations']==500 and len(m['seeds'])==2
 expected={(mode,seed) for seed in m['seeds'] for mode in ('default','large-values','large-batch','recovery-crash','compaction','disk-full','crashpoints')}
 assert {(r['mode'],r['seed']) for r in m['results']}==expected and len(m['results'])==14
 audits=[]
 for row in sorted(m['results'],key=lambda r:(r['seed'],r['mode'])):
  assert row['pass'] and row['exit']==0 and 'TOOL_ERROR=0 ' in row['summary'] and 'FAIL=0 ' in row['summary'],row
  paths=list((gate/('%s-%d'%(row['mode'],row['seed']))).rglob('oracle.log.gz'));assert len(paths)==1
  audit=transcript(paths[0],500);audit.update(mode=row['mode'],seed=row['seed']);audits.append(audit)
  if row['mode']=='crashpoints':assert len(audit['points'])==14
  if row['mode']=='compaction':assert len(audit['points'])==4 and set(audit['points'].values())=={125}
 f1=json.loads((run/'same_database_f1/result.json').read_text());assert f1['success'] and f1['passed']==500
 assert [p.name for p in (run/'same_database_f1').glob('*.db')]==['persistent.db']
 audit=transcript(run/'same_database_f1/oracle.log.gz',500);audit.update(mode='F1 one persistent database',seed=f1['seed']);audits.append(audit)
 assert sum(r['pass_rounds'] for r in audits)==7500
 architecture=(ROOT/'ARCHITECTURE.md').read_text();ids=re.findall(r'^\| ([A-F][1-7]) \|',architecture,re.M)
 assert len(ids)==len(set(ids))==32
 diagram=architecture.split('```mermaid\n',1)[1].split('```',1)[0]
 assert diagram==(ROOT/'diagrams/architecture.mmd').read_text()
 breaking=(ROOT/'BREAKING.md').read_text();assert len(re.findall(r'^## [1-5]\. ',breaking,re.M))==5
 pdf=ROOT/'output/pdf/BREAKING.pdf';pages=len(re.findall(rb'/Type\s*/Page\b',pdf.read_bytes()));assert pages==2
 evidence=ROOT/'docs/evidence/gap-fixes-2026-11-07';evidence.mkdir(parents=True,exist_ok=True)
 copies={'manifest.json':run/'manifest.json','source_snapshot.json':a.qualification/'source_snapshot.json','performance.json':run/'performance/results.json','contracts.json':run/'contracts/results.json','specific.json':run/'specific/results.json','half_batch.json':run/'half_batch/results.json','gate_manifest.json':gate/'manifest.json','same_database_f1.json':run/'same_database_f1/result.json'}
 for name,path in copies.items():shutil.copyfile(path,evidence/name)
 for path in run.glob('*.txt'):shutil.copyfile(path,evidence/path.name)
 for path in (run/'performance').glob('*.txt'):shutil.copyfile(path,evidence/path.name)
 portable=dict(m,canonical_sources={name:hashlib.sha256(canonical(frozen/name)).hexdigest() for name in m['sources']},canonical_source_rule='Only CRLF-to-LF normalization; original raw sources and original manifest are preserved in evidence')
 (ROOT/'docs/gap_fixes_gate_manifest.json').write_text(json.dumps(portable,indent=2)+'\n')
 docs={name:sha(ROOT/name) for name in ('README.md','ARCHITECTURE.md','BREAKING.md','DEMO.md','OFFLINE_TEST_PLAN.md','diagrams/architecture.mmd','output/pdf/BREAKING.pdf')}
 audit=dict(base_commit=state['commit'],qualified_directory=str(run),original_sources_match_after_line_ending_normalization=True,line_ending_only_paths=normalized,capture_tool_sha256=sha(ROOT/'tools/record_demo_results.py'),unit_tests=int(u[1]),unit_seconds=float(u[2]),crash_rounds=7500,kill_records=sum(r['kill_records'] for r in audits),transcripts=audits,document_sha256=docs,breaking_pages=pages,architecture_unique_rows=32,prompt_log_pending_by_user_choice=True,physical_offline_rehearsal='not performed',report_tool_sha256=sha(Path(__file__)))
 (evidence/'audit.json').write_text(json.dumps(audit,indent=2)+'\n')
 (evidence/'.gitattributes').write_text('*.json -text\n*.txt -text\n')
 checks={path.name:sha(path) for path in evidence.iterdir() if path.is_file() and path.name!='checksums.json'}
 (evidence/'checksums.json').write_text(json.dumps(checks,indent=2)+'\n')
 lines=['# Gap fixes and fresh qualification','',
 'Completed UTC: '+state['ended_utc']+'. Base commit: '+state['commit']+'; the qualified working-tree source hashes are recorded separately. The intended source matches the tested Linux ext4 snapshot after CRLF-to-LF normalization only. Original raw hashes remain untouched; normalized hashes make clean-checkout verification portable. The capture-only hash checker was updated separately and is exercised by the refreshed demo capture.','',
 '**Result: code and documentation fixes below passed fresh automated qualification. The original prompt log remains pending by explicit user choice; physical offline rehearsal and event/demo sign-off remain human tasks. No claim of complete submission compliance is made.**','',
 '## Gaps explained and fixed','',
 '| Gap | Why it mattered | Fix / evidence |','|---|---|---|',
 '| One-byte truncation lost an acknowledged final record | The PDF F4 case failed even though normal process-kill tests passed | One expendable 00 byte follows the complete log. It is synced with each write and overwritten at the next append. Truncating one byte removes padding, not saved payload. Puts/deletes/batches/compaction and repeated/interrupted restoration have regressions. |',
 '| Default torture count was 25 | Explicit 500-round runs did not fix the required default | Parser default is now 500; regression verifies default and overrides. |',
 '| Standalone F3 benchmark could print PASS above two seconds | A slow recovery could be reported as successful | strict_recovery_ok is part of the benchmark PASS condition; tests reject 2,000 ms, slower, missing, negative and NaN timing. |',
 '| Architecture had wrong/duplicate scenarios and stale diagram | Judges could select a row describing a different failure | Exactly 32 correct IDs, disk state, mechanism, exact functions and test references; current diagram includes byte layout, numbered ordering, index, cap, locks and recovery/compaction. B2 is honestly explained as design equivalent. |',
 '| README, BREAKING and demo schedule were incomplete | Build/parser/source questions and the fixed demo would be hard to verify | README has a parser-level format diagram and prerequisites; BREAKING has all five sections and exact hook functions, rendered and visually checked as two pages; demo uses the fixed 15-minute schedule. Old captured timings are labelled historical. |','',
 '## How the tail fix works','',
 'Frame encoding and version-1 headers remain unchanged. The file contains contiguous complete frames and, for a nonempty current-writer log, one final guard byte outside the frame CRC. It is not a commit marker. Internal end excludes this byte; physical stats/cap include it. _write overwrites the prior guard with the next frame, writes a new guard, fsyncs, then permits index publication/return/ACK. Thus the overhead is one byte per file, not per record. A complete frame killed before guard creation can still recover (allowed before ACK); a frame missing even its final payload byte is still discarded, preserving the torn-write rule.','',
 'Recovery recognizes a present guard or restores a missing one after replay, and can recover again if that restoration is killed. Compaction writes/syncs its guard before replacement. Rejected cap writes reserve the guard in advance. Legacy files migrate when there is room: an imported file already at/over a newly configured cap stays readable without growth, but its old unguarded tail requires room and a current write/compaction before this guarantee applies. Older program versions can strip the guard.','',
 '## Fresh automated results','',
 '- %s regression tests passed in %s seconds; ten new default/timing/tail-guard tests are included.'%(u[1],u[2]),
 '- Five direct scenarios plus the exact halfway 10,000-operation B6 case passed. B6 recovery was %.3f ms, with no batch operations visible.'%half['engine_recovery_ms'],
 '- 12 real CLI smoke calls cover all eight required commands plus inspect/compact. Seven additional calls now reproduce F4 with all acknowledged keys retained.',
 '- **7,500 crash rounds passed:** 7 modes Ã— 2 seeds Ã— 500 = 7,000, plus 500 consecutive restarts of one persistent database. No invariant failures or tool errors.',
 '- %d SIGKILL events were recorded within those rounds. Recovery trials can kill multiple times per round. All compressed transcripts were parsed, with exactly 1â€“500 PASS entries per workload and no FAIL/TOOL_ERROR; targeted exits were -9.'%audit['kill_records'],
 '- Frozen source fingerprints match before/after the run; current source differs only in verified line-ending normalization (apart from the separately executed capture-only portability fix); all 14 named hooks were exercised for each seed.','',
 '| Workload | Seed | Passed rounds | Logged kills |','|---|---:|---:|---:|']
 for row in audits:lines.append('| %s | %s | %s | %s |'%(row['mode'],row['seed'],row['pass_rounds'],row['kill_records']))
 lines+=['','## Recovery and compaction measurements','',
 '| Real-engine million-key SIGKILL seed | Engine recovery ms | Complete open CLI ms | Result |','|---|---:|---:|---|']
 for row in perf['f3_runs']:lines.append('| %s | %.3f | %.3f | PASS |'%(row['seed'],row['engine_recovery_ms'],row['cli_wall_ms']))
 lines+=['','These F3 runs use actual engine ACKs and verify all recovered keys/values. A separate diagnostic contains exactly one million one-operation frames; it is not an engine-ACK/crash experiment. First diagnostic open checked all million values.','',
 '| Million separate records: repetition | Engine recovery ms | API wall ms | Result |','|---|---:|---:|---|']
 for row in perf['separate_frame_runs']:lines.append('| %s | %.3f | %.3f | PASS |'%(row['repetition'],row['engine_recovery_ms'],row['api_wall_ms']))
 lines+=['','The strict limit is less than 2,000 ms. Measurements ran before the concurrent campaign on this laptop, with no OS-cache eviction; these are measured conditions, not guarantees for every device/log size.','',
 '```text',perf['million_delete_compaction']['output'].rstrip(),'```','',
 '## Before/after and test-development record','',
 'Pre-fix evidence is retained in docs/evidence/ps-acceptance-2026-11-07 and docs/evidence/pdf-requirements-2026-11-06. Before: F4 lost c after three successful writes; torture default was 25; the standalone recovery benchmark did not enforce its printed time. After: contracts.json reports no lost acknowledged key and default 500; the maintained benchmark enforces the strict threshold.','',
 'The first new cap-boundary test incorrectly required byte-for-byte unchanged storage after a rejected write that was allowed to compact dead records. Its assertion was corrected to require unchanged logical state and cap compliance; a separate live-data case verifies byte-for-byte rejection without compaction. This was a test expectation error, not evidence of storage corruption. The earlier cross-writer reply-order test correction and failed-run evidence are also retained.','',
 '## Still pending and real limits','',
 '- PROMPTS.md: deliberately unchanged and pending, per the user reply. An edited summary cannot be claimed as the PDFâ€™s original unedited prompt history.',
 '- Physical Wi-Fi-off clean-clone rehearsal, 5â€“10 human kills, source-line answers, every-member readiness, event provenance/deadline and final submission need human sign-off. The process-level socket guard is supplementary, not proof of physical network disconnection.',
 '- The 10,000 distinct maximum-sized values combination is roughly 10 GiB of input and is not qualified. Chunked encoding bounds encoding overhead, not retained inputs, queues or the index.',
 '- Recovery is linear in log size, and compaction holds the global mutex. Power loss, arbitrary media corruption and filesystems other than tested ext4 are outside these results.',
 '- Legacy at-cap migration and older writers have the guard limitations described above. B2 has no separate trailing marker state in this allowed CRC-frame design; its proof table explains the equivalence without inventing a test.','',
 '## Evidence and reproduction','',
 '- [Fresh source/phase manifest](evidence/gap-fixes-2026-11-07/manifest.json), [independent transcript audit](evidence/gap-fixes-2026-11-07/audit.json), [unit output](evidence/gap-fixes-2026-11-07/unit.txt), [performance](evidence/gap-fixes-2026-11-07/performance.json), [CLI/contracts](evidence/gap-fixes-2026-11-07/contracts.json), [halfway B6](evidence/gap-fixes-2026-11-07/half_batch.json). Checksums cover the copied small artifacts.',
 '- Large raw transcripts/databases remain at '+str(run)+'. Their paths, lengths and SHA-256 hashes are in audit.json. The frozen source checkout is '+snapshot['repository']+'.',
 '- Reproduce: python3 -B tools/run_ps_acceptance.py --host-storage-dir /mnt/c --host-storage-dir /mnt/d --seed 2026110701 --additional-seeds 2026110702 --f1-seed 2026110703 --workers 4. Use a fresh Linux evidence directory. A nonzero final exit still records the pending prompt requirement; it does not disguise failed tests as passes.',
 '- [Offline plan](../OFFLINE_TEST_PLAN.md); [current architecture](../ARCHITECTURE.md); [two-page printable breaking document](../output/pdf/BREAKING.pdf).',
 '', 'The commit is made only after this qualification and report verification. No push or PR is part of this request.']
 (ROOT/'docs/GAP_FIX_REPORT.md').write_text('\n'.join(lines)+'\n')
 print(json.dumps({k:v for k,v in audit.items() if k not in ('transcripts','document_sha256')},indent=2))
if __name__=='__main__':main()
