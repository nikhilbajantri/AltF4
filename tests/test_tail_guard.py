"""End-of-file guard: saved data survives one-byte tail loss, torn frames do not."""
import os
from pathlib import Path
import signal
import subprocess
import sys
from unittest import mock
from src import format as fmt
from src.engine import KVDB
from src.errors import DiskFull, PoisonedError
from src.scan import check_file
from tests.test_engine import EngineTestCase, ROOT
from torturelib import runner
from tests.bench_f3_kill import strict_recovery_ok

class TailGuardTests(EngineTestCase):
    def read(self):
        with KVDBContext(self.path) as db:
            return dict(db.items())

    def test_put_delete_and_batch_survive_one_byte_tail_loss(self):
        for kind in ('put','delete','batch'):
            with self.subTest(kind=kind):
                path=str(Path(self.dir)/(kind+'.db'))
                db=KVDB(path,auto_compact=False)
                db.put(b'victim',b'old')
                if kind=='put':db.put(b'new',b'new')
                elif kind=='delete':db.delete(b'victim')
                else:db.batch([('put',b'left',b'1'),('put',b'right',b'2'),('del',b'victim')])
                expected=dict(db.items());length=db.stats['file_bytes'];db.close()
                self.assertEqual(Path(path).read_bytes()[-1:],fmt.TAIL_GUARD)
                os.truncate(path,length-1)
                self.assertEqual(check_file(path),(True,'OK'))
                db=KVDB(path)
                self.assertEqual(dict(db.items()),expected)
                self.assertEqual(Path(path).stat().st_size,length)
                db.put(b'after',b'repaired');db.close()
                db=KVDB(path);self.assertEqual(db.get(b'after'),b'repaired');db.close()

    def test_repeated_guard_loss_reopen_and_compaction(self):
        db=KVDB(self.path)
        db.put(b'key',b'old');db.put(b'key',b'new');db.compact()
        expected={b'key':b'new'};length=db.stats['file_bytes'];db.close()
        for _ in range(5):
            os.truncate(self.path,length-1)
            self.assertEqual(self.read(),expected)
            self.assertEqual(self.size(),length)

    def test_last_payload_byte_missing_is_still_a_torn_write(self):
        db=KVDB(self.path);db.put(b'anchor',b'saved');end=db.end;db.close()
        frame,_=fmt.encode_frame([('put',b'left',b'new'),('put',b'right',b'new')])
        with open(self.path,'r+b') as file:
            file.truncate(end);file.seek(end);file.write(frame[:-1])
        self.assertEqual(self.read(),{b'anchor':b'saved'})
        self.assertEqual(check_file(self.path),(True,'OK'))

    def test_cap_accounts_for_guard_and_rejection_changes_nothing(self):
        for cap,accepted in ((40,False),(41,True)):
            path=str(Path(self.dir)/('cap%d.db'%cap));db=KVDB(path,max_bytes=cap)
            try:
                if accepted:
                    db.delete(b'k');self.assertEqual(db.stats['file_bytes'],cap)
                else:
                    with self.assertRaises(DiskFull):db.delete(b'k')
                    self.assertEqual(Path(path).stat().st_size,fmt.HEADER_SIZE)
                before=Path(path).read_bytes()
                with self.assertRaises(DiskFull):db.delete(b'another')
                # Failed writes may reclaim dead records, but never apply the rejected operation.
                self.assertEqual(dict(db.items()),{})
                self.assertLessEqual(Path(path).stat().st_size,cap)
            finally:db.close()
        db=KVDB(str(Path(self.dir)/'live.db'),max_bytes=45)
        try:
            db.put(b'k',b'');before=Path(db.path).read_bytes()
            with self.assertRaises(DiskFull):db.put(b'another',b'')
            self.assertEqual(Path(db.path).read_bytes(),before)
            self.assertEqual(db.get(b'k'),b'')
        finally:db.close()

    def test_legacy_frames_migrate_and_tight_cap_does_not_grow(self):
        frame,_=fmt.encode_frame([('put',b'key',b'value')])
        raw=fmt.encode_header()+frame;Path(self.path).write_bytes(raw)
        db=KVDB(self.path,max_bytes=len(raw));self.assertEqual(db.get(b'key'),b'value');db.close()
        self.assertEqual(Path(self.path).read_bytes(),raw)
        self.assertEqual(self.read(),{b'key':b'value'})
        self.assertEqual(Path(self.path).read_bytes(),raw+fmt.TAIL_GUARD)

    def test_guard_write_failure_has_no_success_and_rolls_back(self):
        db=KVDB(self.path);self.addCleanup(db.close)
        db.put(b'anchor',b'saved');before=Path(self.path).read_bytes()
        real=os.pwrite;failed=[]
        def write(fd,data,offset):
            if bytes(data)==fmt.TAIL_GUARD and not failed:
                failed.append(True);raise OSError(5,'guard write failed')
            return real(fd,data,offset)
        with mock.patch('os.pwrite',side_effect=write):
            with self.assertRaises(OSError):db.put(b'new',b'value')
        self.assertEqual(Path(self.path).read_bytes(),before)
        with self.assertRaises(PoisonedError):db.put(b'later',b'blocked')

    def test_process_kill_between_frame_and_guard_recovers_whole_frame(self):
        db=KVDB(self.path);db.put(b'anchor',b'saved');db.close()
        code='''
import os,signal,sys
from src import engine,format as fmt
real=engine._pwrite_all
def write(fd,data,offset):
 if data==fmt.TAIL_GUARD:os.kill(os.getpid(),signal.SIGKILL)
 return real(fd,data,offset)
db=engine.KVDB(sys.argv[1]);engine._pwrite_all=write
db.batch([('put',b'left',b'new'),('put',b'right',b'new')])
'''
        child=subprocess.run([sys.executable,'-B','-c',code,self.path],cwd=ROOT,timeout=30)
        self.assertEqual(child.returncode,-signal.SIGKILL)
        self.assertEqual(self.read(),{b'anchor':b'saved',b'left':b'new',b'right':b'new'})

    def test_process_kill_during_guard_restoration_is_idempotent(self):
        db=KVDB(self.path);db.put(b'key',b'value');db.close()
        for when in ('before','after'):
            os.truncate(self.path,self.size()-1)
            code='''
import os,signal,sys
from src.engine import KVDB
real=KVDB._restore_tail_guard
def restore(self,end):
 if sys.argv[2]=='before':os.kill(os.getpid(),signal.SIGKILL)
 result=real(self,end)
 os.kill(os.getpid(),signal.SIGKILL)
KVDB._restore_tail_guard=restore
KVDB(sys.argv[1])
'''
            child=subprocess.run([sys.executable,'-B','-c',code,self.path,when],cwd=ROOT,timeout=30)
            self.assertEqual(child.returncode,-signal.SIGKILL)
            self.assertEqual(self.read(),{b'key':b'value'})

class AcceptanceDefaultsTests(EngineTestCase):
    def test_default_is_500_with_seed_and_override_preserved(self):
        self.assertEqual(runner.argument_parser().parse_args([]).iterations,500)
        args=runner.argument_parser().parse_args(['--iterations','7','--seed','987'])
        self.assertEqual((args.iterations,args.seed),(7,987))

    def test_f3_threshold_cannot_report_a_slow_open_as_pass(self):
        for output,expected in [('keys=1000000 recovery_ms=1999.999',True),
                                ('keys=1000000 recovery_ms=2000',False),
                                ('keys=1000000 recovery_ms=3500',False),
                                ('keys=1000000 recovery_ms=nan',False),
                                ('keys=1000000 recovery_ms=-1',False),('ERROR',False)]:
            with self.subTest(output=output):self.assertEqual(strict_recovery_ok(output),expected)

class KVDBContext:
    def __init__(self,path):self.path=path
    def __enter__(self):self.db=KVDB(self.path);return self.db
    def __exit__(self,*args):self.db.close()
