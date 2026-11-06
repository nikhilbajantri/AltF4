import os
import struct
import zlib
from pathlib import Path
from src import format as fmt
from src.engine import KVDB
from src.scan import check_file, iter_frames
from tests import test_scan
from tests.test_engine import EngineTestCase


class BoundaryScanTests(EngineTestCase):
    scan = test_scan.ScanTest.scan
    seed = test_scan.ScanTest.seed
    append = test_scan.ScanTest.append
    def nested(self, malformed=False):
        if not malformed:
            return fmt.encode_frame([('put',b'inner',b'value')])[0]
        payload=fmt.NOPS.pack(1)+fmt.OP_HDR.pack(9,1,0)+b'k'
        length=fmt.LEN.pack(len(payload))
        return length+struct.pack('<I',zlib.crc32(payload,zlib.crc32(length)))+payload

    def test_truncated_value_containing_frame_is_a_torn_tail(self):
        for malformed in (False, True):
            with self.subTest(malformed=malformed):
                db=KVDB(self.path)
                db.put(b'anchor',b'saved')
                good=db.end
                db.put(b'outer',b'x'*100+self.nested(malformed)+b'y'*100)
                db.close()
                os.truncate(self.path,self.size()-50)
                records,(ok,message)=self.scan()
                self.assertTrue(ok,message)
                self.assertIn('torn-tail=',message)
                self.assertIsNone(records[-1].later_frame)
                reopened=KVDB(self.path)
                self.assertEqual(dict(reopened.items()),{b'anchor':b'saved'})
                self.assertEqual(reopened.end,good)
                reopened.close()
                # Reset only the database created by this test before its next subcase.
                Path(self.path).unlink()

    def test_bad_crc_value_containing_frame_is_not_midfile_proof(self):
        db=KVDB(self.path)
        db.put(b'anchor',b'saved')
        good=db.end
        db.put(b'outer',b'x'*100+self.nested()+b'y'*100)
        db.close()
        with open(self.path,'r+b') as f:
            f.seek(good+fmt.FRAME_HDR_SIZE+30)
            f.write(b'!')
        records,(ok,message)=self.scan()
        self.assertTrue(ok,message)
        self.assertIsNone(records[-1].later_frame)

    def test_actual_later_frame_wins_over_embedded_frame(self):
        db=KVDB(self.path)
        db.put(b'anchor',b'saved')
        bad=db.end
        db.put(b'outer',b'x'*100+self.nested()+b'y'*100)
        actual_later=db.end
        db.put(b'last',b'saved')
        db.close()
        with open(self.path,'r+b') as f:
            f.seek(bad+fmt.FRAME_HDR_SIZE+30)
            f.write(b'!')
        records,(ok,message)=self.scan()
        self.assertFalse(ok,message)
        self.assertEqual(records[-1].later_frame,actual_later)

    def test_crc_valid_malformed_frame_at_real_boundary_is_corrupt(self):
        self.seed()
        broken,_=fmt.encode_frame([('put',b'bad',b'value')])
        broken=bytearray(broken)
        broken[-1]^=1
        self.append(broken)
        actual_later=self.size()
        self.append(self.nested(malformed=True))
        records,(ok,message)=self.scan()
        self.assertFalse(ok,message)
        self.assertEqual(records[-1].later_frame,actual_later)

    def test_follows_multiple_damaged_outer_frames(self):
        self.seed()
        for n in range(2):
            frame,_=fmt.encode_frame([('put',str(n).encode(),b'x'*100+self.nested())])
            broken=bytearray(frame)
            broken[fmt.FRAME_HDR_SIZE+20]^=1
            self.append(broken)
        actual_later=self.size()
        self.append(fmt.encode_frame([('put',b'last',b'saved')])[0])
        records,(ok,message)=self.scan()
        self.assertFalse(ok,message)
        self.assertEqual(records[-1].later_frame,actual_later)
