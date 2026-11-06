from datetime import datetime, timezone
import hashlib,json,os,re,subprocess,sys,tempfile,time
from pathlib import Path
repo=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(repo))
from src.engine import KVDB
from src import format as fmt
base=Path.home()/'tmp_test'
base.mkdir(exist_ok=True)
import argparse
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();evidence=a.output;evidence.mkdir(parents=True,exist_ok=True)
result={'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),
 'started_utc':datetime.now(timezone.utc).isoformat(),'python':sys.version.split()[0],
 'evidence':str(evidence),'f3_runs':[],'separate_frame_runs':[]}
def save():
 (evidence/'results.json').write_text(json.dumps(result,indent=2))

save()
env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONUNBUFFERED='1')
env.pop('KVDB_CRASH',None)
print('Evidence directory:',evidence,flush=True)
for seed in (31337,2026110608,2026110609):
 p=subprocess.run([sys.executable,'-B','-m','tests.bench_f3_kill','--seed',str(seed)],cwd=repo,env=env,capture_output=True,text=True,timeout=300)
 (evidence/('f3-%s.txt'%seed)).write_text(p.stdout+p.stderr)
 found=re.search(r'recovery_ms=([0-9.]+)',p.stdout)
 wall=re.search(r'wall ([0-9.]+) ms',p.stdout)
 row=dict(seed=seed,exit=p.returncode,output=p.stdout,engine_recovery_ms=float(found[1]) if found else None,
          cli_wall_ms=float(wall[1]) if wall else None)
 row['under_two_seconds']=p.returncode==0 and row['engine_recovery_ms'] is not None and row['engine_recovery_ms']<2000
 row['wall_under_two_seconds']=row['cli_wall_ms'] is not None and row['cli_wall_ms']<2000
 result['f3_runs'].append(row); save()
 print('F3',seed,'engine_ms=',row['engine_recovery_ms'],'CLI_wall_ms=',row['cli_wall_ms'],'strict_pass=',row['under_two_seconds'],flush=True)
# Diagnostic fixture: exactly one million independent one-op frames, not 100 large batches.
# This isolates replay cost. It is not an engine-issued-ACK durability test.
path=evidence/'million-single-records.db'
N=1_000_000
started=time.monotonic()
with path.open('wb',buffering=1024*1024) as f:
 f.write(fmt.encode_header())
 for i in range(N):
  frame,_=fmt.encode_frame([('put',('key%07d'%i).encode(),('v%07d'%i).encode())])
  f.write(frame)
 f.flush(); os.fsync(f.fileno())
result['separate_frame_fixture']=dict(frames=N,keys=N,file_bytes=path.stat().st_size,
 construction_seconds=round(time.monotonic()-started,3),kind='format-generated diagnostic; not an ACK/kill test')
save(); print('Prepared exactly 1,000,000 one-op frames.',flush=True)
for repetition in range(1,4):
 start=time.monotonic(); db=KVDB(str(path),auto_compact=False); elapsed=(time.monotonic()-start)*1000
 row=dict(repetition=repetition,engine_recovery_ms=db.recovery_ms,api_wall_ms=elapsed,
          keys=db.stats['keys'],under_two_seconds=db.recovery_ms<2000 and elapsed<2000)
 assert row['keys']==N
 if repetition==1:
  for i in range(N):
   assert db.get(('key%07d'%i).encode())==('v%07d'%i).encode()
  row['all_million_values_verified']=True
 db.close(); result['separate_frame_runs'].append(row);save()
 print('One-million-frame replay',repetition,'engine_ms=',round(row['engine_recovery_ms'],3),'strict_pass=',row['under_two_seconds'],flush=True)
# Direct B6: a genuine 10,000-op batch is torn by the engine's own hook.
path=evidence/'b6.db'; db=KVDB(str(path)); db.put(b'anchor',b'saved'); db.close()
commands='batch w1-b6\n'+''.join('put k%d v%d\n'%(i,i) for i in range(10000))+'end\n'
p=subprocess.run([sys.executable,'-B','./kvdb','serve',str(path)],cwd=repo,env=dict(env,KVDB_CRASH='torn_write:1'),input=commands,capture_output=True,text=True,timeout=60)
assert p.returncode==-9 and 'ACK w1-b6' not in p.stdout
start=time.monotonic(); db=KVDB(str(path)); wall=(time.monotonic()-start)*1000
assert dict(db.items())=={b'anchor':b'saved'}
result['B6']=dict(batch_ops=10000,serve_exit=p.returncode,output=p.stdout,engine_recovery_ms=db.recovery_ms,
 api_wall_ms=wall,under_two_seconds=db.recovery_ms<2000 and wall<2000,partial_batch_visible=False)
db.close();save(); print('B6 recovery_ms=',result['B6']['engine_recovery_ms'],flush=True)
# Existing real-engine million-put/million-delete compaction benchmark.
p=subprocess.run([sys.executable,'-B','-m','tests.bench_recovery'],cwd=repo,env=env,capture_output=True,text=True,timeout=300)
(evidence/'million-delete-compaction.txt').write_text(p.stdout+p.stderr)
result['million_delete_compaction']=dict(exit=p.returncode,output=p.stdout)
result['ended_utc']=datetime.now(timezone.utc).isoformat();save()
print(p.stdout,flush=True)
print('AUDIT_RESULTS='+str(evidence/'results.json'),flush=True)

raise SystemExit(0 if all(r['under_two_seconds'] and r['wall_under_two_seconds'] for r in result['f3_runs']) and all(r['under_two_seconds'] for r in result['separate_frame_runs']) and result['B6']['under_two_seconds'] and result['million_delete_compaction']['exit']==0 else 1)

