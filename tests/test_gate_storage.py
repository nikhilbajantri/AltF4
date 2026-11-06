import contextlib
import gzip
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
from torturelib import runner


class StorageTests(unittest.TestCase):
    def test_low_host_space_stops_before_starting_round(self):
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(sys, 'platform', 'linux'), \
             mock.patch.object(runner.shutil, 'disk_usage', side_effect=[SimpleNamespace(free=10**12), SimpleNamespace(free=1)]), \
             mock.patch.object(runner, 'iteration') as iteration, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            code = runner.main(['--iterations','1','--data-dir',directory,'--host-storage-dir',directory])
            self.assertEqual(code, 2)
            iteration.assert_not_called()
            self.assertIn('low free space', output.getvalue())
            self.assertNotIn('SUMMARY PASS', output.getvalue())

    @unittest.skipUnless(sys.platform == 'linux', 'real engine needs Linux')
    def test_compressed_evidence_preserves_real_crash_events(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable,'-B','./torture','--iterations','2','--seed','777',
                                     '--compress-log','--data-dir',directory], cwd=root,
                                    capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            with gzip.open(next(Path(directory).glob('*/oracle.log.gz')), 'rt') as f:
                events = [json.loads(line) for line in f]
            self.assertEqual(sum(e['event']=='PASS' for e in events),2)
            self.assertEqual(sum(e['event']=='KILL' for e in events),2)
            self.assertTrue(any(e['event']=='SENT' and len(e['ops'])>1 for e in events))
