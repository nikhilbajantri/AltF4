from pathlib import Path
import ast,hashlib,json,os,re,subprocess,sys,tempfile
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
base=Path.home()/'tmp_test'
import argparse
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();directory=a.output;directory.mkdir(parents=True,exist_ok=True)
env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1')
env.pop('KVDB_CRASH',None)
results={'directory':str(directory),'cli':[]}
path=directory/'cli.db'
def cli(*args,expected=0,data=None):
 p=subprocess.run([sys.executable,'-B','./kvdb',*map(str,args)],cwd=root,env=env,input=data,capture_output=True,text=True,timeout=30)
 row=dict(args=list(map(str,args)),exit=p.returncode,stdout=p.stdout,stderr=p.stderr)
 results['cli'].append(row)
 assert p.returncode==expected,row
 return p.stdout
assert cli('open',path).startswith('keys=0 ')
assert cli('put',path,'a','1')=='OK\n'
assert cli('get',path,'a')=='1\n'
assert cli('del',path,'missing')=='OK\n'
assert cli('del',path,'a')=='OK\n'
assert cli('get',path,'a')=='NOTFOUND\n'
batch=directory/'ops.txt';batch.write_text('put city New Delhi\nput color blue\ndel color\n')
assert cli('batch',path,batch)=='OK\n'
assert cli('dump',path)=='city\thex:4e65772044656c6869\n'
assert cli('check',path)=='OK\n'
out=cli('serve',path,data='put w1-1 color blue\nget w1-2 color\nquit\n')
assert 'ACK w1-1\n' in out and 'VAL w1-2 blue\n' in out
assert 'crc=OK' in cli('inspect',path)
assert cli('compact',path).startswith('before=')
# Literal F4: each write returned OK before manually removing the last byte.
f4=directory/'f4.db'
for key in ('a','b','c'): assert cli('put',f4,key,key)=='OK\n'
os.truncate(f4,f4.stat().st_size-1)
results['F4_before_open']=cli('check',f4)
results['F4_open']=cli('open',f4)
results['F4_after_dump']=cli('dump',f4)
results['F4_acknowledged_last_key_lost']=cli('get',f4,'c')=='NOTFOUND\n'
# Fresh local clone, with normal runtime network access actively blocked by a startup hook.
clone=directory/'clean-clone'
p=subprocess.run(['git','clone','--no-hardlinks','--quiet',str(root),str(clone)],capture_output=True,text=True,timeout=60)
assert p.returncode==0,p.stderr
hook=directory/'network-block';hook.mkdir()
(hook/'sitecustomize.py').write_text("import socket\ndef denied(*args, **kwargs):\n    raise RuntimeError('network disabled for this validation process')\nsocket.socket=denied\nsocket.create_connection=denied\n")
offline_env=dict(env,PYTHONPATH=str(hook))
p=subprocess.run([sys.executable,'-c','import socket; socket.socket()'],cwd=clone,env=offline_env,capture_output=True,text=True)
assert p.returncode!=0 and 'network disabled' in p.stderr
results['network_guard_verified']=True
p=subprocess.run(['make','build'],cwd=clone,env=offline_env,capture_output=True,text=True,timeout=60)
results['clean_clone_build']=dict(exit=p.returncode,stdout=p.stdout,stderr=p.stderr)
assert p.returncode==0,p.stderr
p=subprocess.run([sys.executable,'-B','./kvdb','put',str(directory/'offline.db'),'offline','works'],cwd=clone,env=offline_env,capture_output=True,text=True,timeout=30)
assert p.returncode==0 and p.stdout=='OK\n'
results['offline_guarded_put']=p.stdout
p=subprocess.run([sys.executable,'-B','./kvdb','get',str(directory/'offline.db'),'offline'],cwd=clone,env=offline_env,capture_output=True,text=True,timeout=30)
assert p.returncode==0 and p.stdout=='works\n'
results['offline_guarded_get']=p.stdout
results['offline_scope']='Python process-level socket guard; Wi-Fi adapter was not switched off; local Git clone, not a network clone'
architecture=(root/'ARCHITECTURE.md').read_text()
ids=re.findall(r'^\| ([A-F][1-7]) \|',architecture,re.M)
results['architecture_ids']={'rows':len(ids),'unique':len(set(ids)),'duplicates':sorted({i for i in ids if ids.count(i)>1}),'not_verified_rows':architecture.count('Not verified')}
imports=set()
for folder in ('src','torturelib'):
 for f in (root/folder).glob('*.py'):
  for n in ast.walk(ast.parse(f.read_text())):
   if isinstance(n,ast.Import): imports.update(x.name.split('.')[0] for x in n.names)
   elif isinstance(n,ast.ImportFrom) and n.module: imports.add(n.module.split('.')[0])
results['non_stdlib_runtime_imports']=sorted(imports-set(sys.stdlib_module_names)-{'src','torturelib'})
results['torture_default_iterations']=re.search(r'add_argument\("--iterations", type=int, default=(\d+)',(root/'torturelib/runner.py').read_text())[1]
results['prompt_log_has_entries']=bool(re.search(r'^\[\d\d:\d\d\]',(root/'PROMPTS.md').read_text(),re.M))
(directory/'results.json').write_text(json.dumps(results,indent=2))
print(json.dumps({k:v for k,v in results.items() if k!='cli'},indent=2),flush=True)
print('CLI checks:',len(results['cli']),flush=True)

