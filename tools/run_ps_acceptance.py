"""Run the full PDF acceptance campaign; known failures remain failures."""
import argparse,hashlib,json,os,shutil,signal,subprocess,sys,tempfile,time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--data-dir',type=Path,default=Path.home()/'tmp_test')
 p.add_argument('--host-storage-dir',action='append',type=Path,required=True)
 p.add_argument('--seed',type=int,default=2026110612)
 p.add_argument('--f1-seed',type=int,default=2026110613)
 p.add_argument('--additional-seeds',type=int,nargs='*',default=[])
 p.add_argument('--workers',type=int,default=4)
 a=p.parse_args()
 if a.workers<1:p.error('Workers must be positive')
 seeds=[a.seed,*a.additional_seeds]
 if len(set(seeds))!=len(seeds):p.error('Seeds must be unique')
 if sys.platform!='linux':p.error('Run in Linux/WSL.')
 a.data_dir.mkdir(parents=True,exist_ok=True)
 directory=Path(tempfile.mkdtemp(prefix='ps-acceptance-',dir=a.data_dir))
 volumes=[directory,*a.host_storage_dir]
 def space():
  for v in volumes:
   if shutil.disk_usage(v).free<20*1024**3:raise OSError('Low space on '+str(v))
 space()
 files=list((ROOT/'tests').glob('*.py'))+list((ROOT/'src').glob('*.py'))+list((ROOT/'torturelib').glob('*.py'))+list((ROOT/'tools').glob('ps_*.py'))+[Path(__file__),ROOT/'tools/run_final_gate.py',ROOT/'tools/check_ps_half_batch.py']
 state={'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'started_utc':datetime.now(timezone.utc).isoformat(),'directory':str(directory),'sources':{str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in files},'phases':{}}
 def save():
  tmp=directory/'manifest.tmp';tmp.write_text(json.dumps(state,indent=2));tmp.replace(directory/'manifest.json')
 save();print('PS_EVIDENCE='+str(directory),flush=True)
 env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONUNBUFFERED='1');env.pop('KVDB_CRASH',None)
 def execute(name,command,timeout):
  log=directory/(name+'.txt');start=time.monotonic();proc=None;row={'command':command,'log':str(log)}
  try:
   space()
   with log.open('w') as output:
    proc=subprocess.Popen(command,cwd=ROOT,env=env,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
    while proc.poll() is None:
     space()
     if time.monotonic()-start>timeout:raise TimeoutError('Phase timeout')
     time.sleep(1)
   row.update(exit=proc.returncode,completed=True)
  except Exception as e:row.update(exit=None,completed=False,error=type(e).__name__+': '+str(e))
  finally:
   if proc is not None and proc.poll() is None:
    try:os.killpg(proc.pid,signal.SIGKILL)
    except ProcessLookupError:pass
    proc.wait(timeout=60)
   row['seconds']=round(time.monotonic()-start,3)
  return row
 commands=[('performance',[sys.executable,'-B','tools/ps_measure_recovery.py','--output',str(directory/'performance')],600),('build',['make','build'],120),('unit',[sys.executable,'-B','-m','unittest','-v'],600),('contracts',[sys.executable,'-B','tools/ps_check_contracts.py','--output',str(directory/'contracts')],180),('specific',[sys.executable,'-B','tools/ps_specific_scenarios.py','--output',str(directory/'specific')],120),('half_batch',[sys.executable,'-B','tools/check_ps_half_batch.py','--output',str(directory/'half_batch')],120)]
 for name,command,timeout in commands:
  state['active_phase']=name;save();print('Starting '+name,flush=True)
  state['phases'][name]=execute(name,command,timeout);save();print(name+' exit='+str(state['phases'][name]['exit']),flush=True)
 if all(state['phases'][n].get('exit')==0 for n in ('build','unit','specific','half_batch')):
  common=[item for v in a.host_storage_dir for item in ('--host-storage-dir',str(v))]
  gate=[sys.executable,'-B','tools/run_final_gate.py','--iterations','500','--seeds',*map(str,seeds),'--workers',str(a.workers),'--data-dir',str(directory/'modes'),*common]
  f1=[sys.executable,'-B','tools/ps_f1_same_database.py','--output',str(directory/'same_database_f1'),'--iterations','500','--seed',str(a.f1_seed),*common]
  state['active_phase']='%d mode rounds plus 500 same-database rounds'%(3500*len(seeds));save()
  with ThreadPoolExecutor(max_workers=2) as pool:
   jobs={name:pool.submit(execute,name,cmd,7200) for name,cmd in [('modes',gate),('same_database_f1',f1)]}
   while not all(job.done() for job in jobs.values()):
    print('Crash campaigns running; evidence='+str(directory),flush=True);time.sleep(30)
   for name,job in jobs.items():state['phases'][name]=job.result();save()
 else:state['campaign_skipped']='Build/unit/specific prerequisite failed'
 state['sources_unchanged']=all(hashlib.sha256((ROOT/n).read_bytes()).hexdigest()==v for n,v in state['sources'].items())
 reasons=[]
 if (directory/'contracts/results.json').exists():
  c=json.loads((directory/'contracts/results.json').read_text())
  if c['F4_acknowledged_last_key_lost']:reasons.append('F4: acknowledged last record lost after manual byte truncation')
  if c['torture_default_iterations']!='500':reasons.append('Torture default is not 500')
  if not c['prompt_log_has_entries']:reasons.append('Prompt log empty')
 for n,r in state['phases'].items():
  if r.get('exit')!=0:reasons.append('Phase failed: '+n)
 if not state['sources_unchanged']:reasons.append('Sources changed during acceptance')
 state.update(known_noncompliance=reasons,all_requirements_satisfied=False,ended_utc=datetime.now(timezone.utc).isoformat(),active_phase='complete');save()
 print('PS_ACCEPTANCE_COMPLETE; noncompliance='+json.dumps(reasons),flush=True)
 return 1 if reasons else 2
if __name__=='__main__':raise SystemExit(main())
