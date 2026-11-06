"""F1: 500 real random SIGKILL/restarts of one database, using the unchanged oracle."""
import argparse,gzip,json,shutil,sys,time
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from torturelib import runner

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--seed',type=int,default=2026110613);p.add_argument('--iterations',type=int,default=500);p.add_argument('--host-storage-dir',type=Path,action='append',required=True)
 a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
 previous={};passed=0;state={'success':False,'passed':0,'iterations':a.iterations,'seed':a.seed,'one_database':str(a.output/'persistent.db')};start=time.monotonic()
 def save(): (a.output/'result.json').write_text(json.dumps(state,indent=2))
 save()
 try:
  with gzip.open(a.output/'oracle.log.gz','wt') as log, mock.patch.object(runner,'database_path',return_value=a.output/'persistent.db'):
   for number in range(1,a.iterations+1):
    for volume in [a.output,*a.host_storage_dir]:
     if shutil.disk_usage(volume).free<20*1024**3:raise OSError('Low free space: '+str(volume))
    result=runner.iteration(a.seed,number,a.output,log,'default',previous)
    previous=result[-1];passed+=1
    log.write(json.dumps({'iteration':number,'event':'PASS'})+'\n');log.flush()
    state.update(passed=passed,seconds=round(time.monotonic()-start,2));save()
    print('F1 iteration=%d PASS'%number,flush=True)
  state['success']=passed==a.iterations
 except Exception as e:
  state['error']=type(e).__name__+': '+str(e);print(state['error'],flush=True)
 state.update(seconds=round(time.monotonic()-start,2));save()
 return 0 if state['success'] else 1
if __name__=='__main__':raise SystemExit(main())
