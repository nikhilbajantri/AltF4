"""Direct PDF boundary and post-ACK checks; timing instrumentation is test-only."""
import argparse,io,json,os,queue,signal,subprocess,sys,threading,random
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src import format as fmt
from torturelib import protocol,runner,workload
ROOT=Path(__file__).resolve().parents[1]

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True);rows=[]
 def trial(name,fn):
  try: evidence=fn();row={'name':name,'status':'PASS','evidence':evidence}
  except Exception as e:row={'name':name,'status':'FAIL','error':type(e).__name__+': '+str(e)}
  rows.append(row);(a.output/'results.json').write_text(json.dumps(rows,indent=2));print(name,row['status'],flush=True)
 def torn_three():
  path=a.output/'b1.db';assert protocol.cli('put',path,'anchor','saved').stdout=='OK\n'
  ops=[('put',('ten%d'%i).encode(),('value%d'%i).encode()) for i in range(10)]
  frame,offsets=fmt.encode_frame(ops);cut=offsets[2]+len(ops[2][2])
  script="import sys;from src import crash;crash.torn_write_prefix=lambda frame:frame[:%d];from src.serve import main;raise SystemExit(main([sys.argv[1]]))"%cut
  r=subprocess.run([sys.executable,'-B','-c',script,str(path)],cwd=ROOT,env=protocol.environment(),input=workload.command('w1-ten',ops),capture_output=True,text=True,timeout=30)
  assert r.returncode==-9 and 'ACK w1-ten' not in r.stdout
  assert protocol.recovered(path)=={b'anchor':b'saved'}
  return dict(ops=10,completed_op_bytes=3,cut=cut,frame_bytes=len(frame),exit=r.returncode,stdout=r.stdout)
 trial('B1_exact_three_of_ten',torn_three)
 def acknowledged(name,commands,expected):
  path=a.output/(name+'.db');stderr=(a.output/(name+'.stderr')).open('w');proc=subprocess.Popen([sys.executable,'-B','./kvdb','serve',str(path)],cwd=ROOT,env=protocol.environment(),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=stderr,text=True,bufsize=1);q=queue.Queue();output=[]
  def read():
   for line in proc.stdout:q.put(line.rstrip())
   q.put(None)
  t=threading.Thread(target=read,daemon=True);t.start()
  try:
   ready=q.get(timeout=15);assert ready and ready.startswith('READY ');output.append(ready)
   for opid,text in commands:
    proc.stdin.write(text);proc.stdin.flush();line=q.get(timeout=15);assert line=='ACK '+opid,line;output.append(line)
   proc.kill();proc.wait(timeout=60);assert proc.returncode==-9
  finally:
   if proc.poll() is None:proc.kill();proc.wait(timeout=60)
   proc.stdin.close();t.join(timeout=5);proc.stdout.close();stderr.close()
  actual=protocol.recovered(path);assert actual==expected,(actual,expected)
  return dict(exit=proc.returncode,stdout=output,recovered={k.hex():v.hex() for k,v in actual.items()})
 trial('A5_acknowledged_put',lambda:acknowledged('a5',[('w1-a','put w1-a key saved\n')],{b'key':b'saved'}))
 trial('B4_acknowledged_ten_op_batch',lambda:acknowledged('b4',[('w1-ten',workload.command('w1-ten',[('put',('k%d'%i).encode(),b'saved') for i in range(10)]))],{('k%d'%i).encode():b'saved' for i in range(10)}))
 trial('B5_put_then_delete_after_crash',lambda:acknowledged('b5',[('w1-order','batch w1-order\nput X value\ndel X\nend\n')],{}))
 def mixed():
  script="""
import sys,time,threading
from src.engine import KVDB
from src.serve import run
entered=threading.Event();old_write=KVDB._write;old_put=KVDB.put
 def_placeholder=0
""".replace(' def_placeholder=0','')
  script+='''
def slow(self,frame):
 if len(frame)>50000:
  print('LONG_WRITE_ENTERED',file=sys.stderr,flush=True);entered.set();time.sleep(1)
 return old_write(self,frame)
def single(self,key,value):
 assert entered.wait(5)
 print('SINGLE_PUT_CALLED_DURING_LONG_WRITE',file=sys.stderr,flush=True)
 return old_put(self,key,value)
KVDB._write=slow;KVDB.put=single
run(KVDB(sys.argv[1]))
'''
  real=subprocess.Popen
  def launch(args,**kwargs):
   if len(args)>3 and args[2]=='serve':return real([sys.executable,'-B','-c',script,args[3]],**kwargs)
   return real(args,**kwargs)
  def plans(seed,number,writer,**kwargs):
   if writer=='w1':return [('w1-long',[('put',('batch%d'%i).encode(),b'value') for i in range(10000)])]
   return [('w2-single',[('put',b'single',b'value')])]
  seed=next(s for s in range(1000) if .18<10**random.Random('kill:%s:2'%s).uniform(-2.7,0)<.3)
  directory=a.output/'d3';directory.mkdir()
  with (directory/'oracle.log').open('w') as log,mock.patch.object(runner.subprocess,'Popen',side_effect=launch),mock.patch.object(runner.workload,'generate',side_effect=plans):
   runner.iteration(seed,2,directory,log,'default',{})
  marker=(directory/'stderr-0002.log').read_text();assert 'LONG_WRITE_ENTERED' in marker and 'SINGLE_PUT_CALLED_DURING_LONG_WRITE' in marker,marker
  return dict(seed=seed,markers=marker,instrumentation='test-only scheduling delay; real CLI, unchanged writes/fsync and independent oracle')
 trial('D3_long_batch_with_single_put',mixed)
 (a.output/'results.json').write_text(json.dumps(rows,indent=2));return 0 if all(r['status']=='PASS' for r in rows) else 1
if __name__=='__main__':raise SystemExit(main())
