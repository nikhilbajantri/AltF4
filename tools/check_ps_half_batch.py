"""B6 exact halfway cut: 5,000 of 10,000 operations, with a strict recovery clock."""
import argparse, hashlib, json, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src import format as fmt
from src.engine import KVDB
from torturelib import protocol, workload

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    path=a.output/'halfway.db'
    seed=protocol.cli('put',path,'anchor','saved')
    assert seed.returncode==0 and seed.stdout=='OK\n'
    before=path.stat().st_size-len(fmt.TAIL_GUARD)
    ops=[('put',('key%05d'%i).encode(),b'value') for i in range(10000)]
    frame,offsets=fmt.encode_frame(ops)
    cut=offsets[4999]+len(ops[4999][2])
    child="import sys;from src import crash;crash.torn_write_prefix=lambda frame:frame[:%d];from src.serve import main;raise SystemExit(main([sys.argv[1]]))"%cut
    result=subprocess.run([sys.executable,'-B','-c',child,str(path)],cwd=ROOT,
                          env=protocol.environment(),input=workload.command('w1-half',ops),
                          capture_output=True,text=True,timeout=60)
    assert result.returncode==-9 and 'ACK w1-half' not in result.stdout
    torn_bytes=path.stat().st_size
    assert torn_bytes==before+cut,(torn_bytes,before,cut)
    start=time.monotonic();db=KVDB(str(path));wall=(time.monotonic()-start)*1000
    recovery=db.recovery_ms
    try: assert dict(db.items())=={b'anchor':b'saved'}
    finally: db.close()
    assert recovery<2000 and wall<2000,(recovery,wall)
    row=dict(status='PASS',batch_ops=10000,complete_operation_prefix=5000,
             exact_prefix_bytes=cut,full_frame_bytes=len(frame),torn_file_bytes=torn_bytes,
             child_exit=result.returncode,child_stdout=result.stdout,
             engine_recovery_ms=recovery,api_wall_ms=wall,partial_batch_visible=False,
             source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             instrumentation='test-only prefix selector; real engine write and actual SIGKILL')
    (a.output/'results.json').write_text(json.dumps(row,indent=2)+'\n')
    print(json.dumps(row,indent=2))
if __name__=='__main__':main()
