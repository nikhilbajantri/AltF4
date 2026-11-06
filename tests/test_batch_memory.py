import io
import os
from pathlib import Path
import tracemalloc
from unittest import mock
from src import format as fmt
from src.engine import KVDB
from src.errors import DiskFull, PoisonedError
from src.serve import read_batch
from tests.test_engine import EngineTestCase
from torturelib import protocol, workload


class BatchMemoryTests(EngineTestCase):
    def test_large_batch_encoder_overhead_is_bounded(self):
        db=KVDB(self.path, auto_compact=False)
        self.addCleanup(db.close)
        # 32 MiB logical payload, with caller-owned values excluded from tracking.
        value=b'x'*(1024*1024)
        ops=[('put', ('key%d'%i).encode(), value) for i in range(32)]
        tracemalloc.start()
        try:
            db.batch(ops)
            peak=tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertLess(peak,12*1024*1024)
        db.close()
        reopened=KVDB(self.path)
        self.addCleanup(reopened.close)
        self.assertEqual(dict(reopened.items()),{op[1]:op[2] for op in ops})

    def test_disk_cap_rejects_before_encoding_a_frame(self):
        db=KVDB(self.path,max_bytes=1024,auto_compact=False)
        self.addCleanup(db.close)
        value=b'x'*(1024*1024)
        ops=[('put', ('key%d'%i).encode(),value) for i in range(10000)]
        tracemalloc.start()
        try:
            with self.assertRaises(DiskFull):
                db.batch(ops)
            peak=tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertLess(peak,2*1024*1024)
        self.assertEqual(Path(self.path).stat().st_size,fmt.HEADER_SIZE)
        self.assertEqual(db.items(),[])
        db.put(b'small',b'still usable')

    def test_generator_stops_at_operation_limit(self):
        db=KVDB(self.path)
        self.addCleanup(db.close)
        consumed=[]
        def operations():
            for i in range(10002):
                consumed.append(i)
                yield ('put',b'k',b'v')
        with self.assertRaises(ValueError):
            db.batch(operations())
        self.assertEqual(len(consumed),10001)
        self.assertEqual(db.items(),[])

    def test_chunked_bytes_and_offsets_match_existing_format(self):
        ops=[('put',b'left',b'a'*fmt.MAX_VALUE),('del',b'gone'),
             ('put',b'right',b'b'*fmt.MAX_VALUE)]
        expected, offsets=fmt.encode_frame(ops)
        with mock.patch.object(fmt,'STREAM_THRESHOLD',1):
            frame, actual=fmt.prepare_frame(ops)
        self.assertEqual(actual,offsets)
        self.assertEqual(b''.join(frame.chunks()),expected)
        for cut in (1,12,17,len(expected)//2,len(expected)-1):
            self.assertEqual(b''.join(frame[:cut].chunks()),expected[:cut])

    def test_serve_still_drains_an_excessive_batch(self):
        lines=iter(['put k v\n']*10001+['end\n','put w1-next good value\n'])
        with self.assertRaises(ValueError):
            read_batch(lines)
        self.assertEqual(next(lines),'put w1-next good value\n')

    def test_streamed_frames_recover_at_write_crash_points(self):
        ops=[('put',('big%d'%i).encode(),bytes([i])*fmt.MAX_VALUE) for i in range(5)]
        for point in ('before_write','torn_write','after_write','after_fsync','after_return'):
            with self.subTest(point=point):
                path=str(Path(self.dir)/(point+'.db'))
                db=KVDB(path)
                db.put(b'anchor',b'saved')
                db.close()
                env=protocol.environment()
                env['KVDB_CRASH']=point+':1'
                result=protocol.cli('serve',path,env=env,text=workload.command('w1-large',ops))
                self.assertEqual(result.returncode,-9,result.stderr)
                self.assertNotIn('ACK w1-large',result.stdout)
                expected={b'anchor':b'saved'}
                if point in ('after_write','after_fsync','after_return'):
                    expected.update({op[1]:op[2] for op in ops})
                self.assertEqual(protocol.recovered(path),expected)

    def test_prepared_frame_snapshots_mutable_inputs(self):
        key,value=bytearray(b'key'),bytearray(b'value')
        with mock.patch.object(fmt,'STREAM_THRESHOLD',1):
            frame,offsets=fmt.prepare_frame([('put',key,value)])
        key[:]=b'bad'
        value[:]=b'other'
        encoded=b''.join(frame.chunks())
        decoded,end=fmt.decode_frame(encoded,0,len(encoded))
        self.assertEqual(decoded[0][1],b'key')
        self.assertEqual(encoded[offsets[0]:end],b'value')

    def test_chunk_allocation_failure_rolls_back_and_poisons_handle(self):
        db=KVDB(self.path,auto_compact=False)
        self.addCleanup(db.close)
        db.put(b'anchor',b'saved')
        before=Path(self.path).read_bytes()
        original=fmt.FrameParts.chunks
        def fail_after_first_chunk(frame):
            chunks=original(frame)
            yield next(chunks)
            raise MemoryError('injected chunk allocation failure')
        with mock.patch.object(fmt.FrameParts,'chunks',fail_after_first_chunk):
            with self.assertRaises(OSError) as caught:
                db.batch([('put',str(i).encode(),b'x'*fmt.MAX_VALUE) for i in range(5)])
        self.assertEqual(caught.exception.errno,12)
        self.assertEqual(Path(self.path).read_bytes(),before)
        with self.assertRaises(PoisonedError):
            db.put(b'later',b'blocked')
        db.close()
        reopened=KVDB(self.path)
        self.addCleanup(reopened.close)
        self.assertEqual(dict(reopened.items()),{b'anchor':b'saved'})
