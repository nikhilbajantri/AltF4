"""Capture real demo evidence without modifying the database implementation."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import tempfile
import threading

if sys.platform != 'linux':
    raise SystemExit('Run this capture in Ubuntu/WSL on Linux storage.')
if not __debug__:
    raise SystemExit('Run without -O so all evidence assertions remain enabled.')
repo=Path(__file__).resolve().parents[1]
base=Path.home()/'tmp_test'
base.mkdir(exist_ok=True)
directory=Path(tempfile.mkdtemp(prefix='demo-evidence-',dir=base))
env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONUNBUFFERED='1')
env.pop('KVDB_CRASH',None)
metadata={'started_utc':datetime.now(timezone.utc).isoformat(),
          'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),
          'python':sys.version.split()[0],'directory':str(directory)}
prior=json.loads((repo/'docs/final_gate_rerun_manifest.json').read_text())
metadata['qualified_source_hashes_match']=all(hashlib.sha256((repo/name).read_bytes()).hexdigest()==digest
    for name,digest in prior['sources'].items())
assert metadata['qualified_source_hashes_match'], 'Source differs from the qualified implementation'
metadata['filesystem']=subprocess.check_output(['findmnt','-n','-o','FSTYPE','-T',str(directory)],text=True).strip()
assert metadata['filesystem']=='ext4'

def capture(args, name, *, data=None, child_env=None, expected=0, timeout=60):
    result=subprocess.run(args,cwd=repo,env=env if child_env is None else child_env,
        input=data,capture_output=True,text=True,timeout=timeout)
    (directory/name).write_text(result.stdout+result.stderr)
    assert result.returncode==expected,(args,result.returncode,result.stdout,result.stderr)
    return result

capture(['make','build'],'build.txt')
print('Build passed; capturing 25 real default crash rounds.',flush=True)
capture([sys.executable,'-B','./torture','--iterations','25','--seed','12345','--mode','default',
         '--compress-log','--host-storage-dir','/mnt/d','--min-free-gib','20',
         '--data-dir',str(directory/'torture')],'torture.txt',timeout=180)
summary=next(line for line in (directory/'torture.txt').read_text().splitlines() if line.startswith('SUMMARY '))
assert 'PASS=25/25 ' in summary and 'TOOL_ERROR=0 ' in summary and 'FAIL=0 ' in summary
metadata['torture_summary']=summary

path=directory/'demo.db'
launcher=['bash','-c','echo "SERVER_PID=$$"; exec python3 -B -m src.serve "$1"','_',str(path)]
manual=[]
with (directory/'serve.stderr.txt').open('w') as error:
    proc=subprocess.Popen(launcher,cwd=repo,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                          stderr=error,text=True,bufsize=1)
    lines=queue.Queue()
    def read():
        for line in proc.stdout:
            lines.put(line.rstrip('\n'))
        lines.put(None)
    reader=threading.Thread(target=read,daemon=True)
    reader.start()
    def receive():
        line=lines.get(timeout=15)
        assert line is not None,'server exited unexpectedly'
        manual.append('OUT '+line)
        return line
    try:
        assert receive()=='SERVER_PID='+str(proc.pid)
        ready=receive()
        assert ready.startswith('READY keys=0 ')
        cases=[('put w1-1 color blue\n','ACK w1-1'),
               ('get w1-2 color\n','VAL w1-2 blue'),
               ('batch w1-3\nput city Delhi\nput status ready\nend\n','ACK w1-3'),
               ('put w1-4 obsolete temporary\n','ACK w1-4'),
               ('del w1-5 obsolete\n','ACK w1-5'),
               ('get w1-6 obsolete\n','NOTFOUND w1-6')]
        for command,expected in cases:
            manual.extend('IN  '+line for line in command.rstrip('\n').splitlines())
            proc.stdin.write(command)
            proc.stdin.flush()
            assert receive()==expected
        manual.append('ACTION kill -KILL '+str(proc.pid))
        os.kill(proc.pid,signal.SIGKILL)
        proc.wait(timeout=10)
        assert proc.returncode==-9
        metadata['server_pid']=proc.pid
        metadata['server_exit']=proc.returncode
        metadata['ready']=ready
        manual.append('OBSERVED subprocess returncode=-9 (SIGKILL)')
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
        proc.stdin.close()
        reader.join(timeout=5)
        proc.stdout.close()
(directory/'manual_transcript.txt').write_text('\n'.join(manual)+'\n')

def verification(prefix):
    output=[]
    expected={'check':'OK\n','dump':'city\tDelhi\ncolor\tblue\nstatus\tready\n',
              'get':'NOTFOUND\n'}
    for command in ('open','check','dump','get'):
        args=[sys.executable,'-B','./kvdb',command,str(path)]
        if command=='get':
            args+=['obsolete']
        result=capture(args,prefix+'_'+command+'.txt')
        if command=='open':
            assert result.stdout.startswith('keys=3 recovery_ms=')
        else:
            assert result.stdout==expected[command],(command,result.stdout)
        output.append('$ python3 -B ./kvdb '+command+' "$DEMO_DIR/demo.db"'+(' obsolete' if command=='get' else ''))
        output.append(result.stdout.rstrip('\n'))
    (directory/(prefix+'.txt')).write_text('\n'.join(output)+'\n')

verification('reopen')
hook_env=dict(env,KVDB_CRASH='torn_write:1')
result=capture([sys.executable,'-B','-m','src.serve',str(path)],'torn_write.txt',
    data='batch w2-1\nput city Mumbai\nput status broken\nend\n',child_env=hook_env,expected=-9)
assert 'ACK w2-1' not in result.stdout
check=capture([sys.executable,'-B','./kvdb','check',str(path)],'torn_before_open.txt')
assert check.stdout.startswith('OK torn-tail=')
metadata['torn_write_exit']=-9
metadata['torn_before_open']=check.stdout.strip()
verification('repaired')
metadata['ended_utc']=datetime.now(timezone.utc).isoformat()
(directory/'metadata.json').write_text(json.dumps(metadata,indent=2))
print('All demo assertions passed.',flush=True)
print('DEMO_EVIDENCE='+str(directory),flush=True)
print(json.dumps(metadata,indent=2),flush=True)
