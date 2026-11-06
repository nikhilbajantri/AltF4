"""I/O failures whose rollback cannot be confirmed must have an unknown outcome."""
import contextlib
import io
import os
from pathlib import Path
import random
import subprocess
import sys
from unittest import mock

from src import cli, serve
from src.engine import KVDB
from src.errors import PoisonedError
from tests.test_engine import EngineTestCase
from torturelib import runner


class UncertainWriteTests(EngineTestCase):
    def seeded(self):
        db = KVDB(self.path, auto_compact=False)
        self.addCleanup(db.close)
        db.batch([('put', b'anchor', b'saved'), ('put', b'victim', b'old')])
        return db

    def assert_uncertain(self, error):
        self.assertEqual(type(error).__name__, 'UncertainWriteError')
        self.assertIsInstance(error, OSError)
        self.assertIsInstance(error.write_error, OSError)
        self.assertIsInstance(error.rollback_error, OSError)

    def test_complete_put_can_survive_failed_sync_and_failed_rollback(self):
        db = self.seeded()
        with mock.patch('os.fsync', side_effect=OSError(5, 'write sync failed')), \
             mock.patch('os.ftruncate', side_effect=OSError(5, 'rollback truncate failed')):
            with self.assertRaises(OSError) as caught:
                db.put(b'new', b'value')
        with self.assertRaises(PoisonedError):
            db.put(b'later', b'blocked')
        with self.assertRaises(PoisonedError):
            db.compact()
        db.close()
        recovered = KVDB(self.path)
        self.addCleanup(recovered.close)
        self.assertEqual(dict(recovered.items()),
                         {b'anchor': b'saved', b'victim': b'old', b'new': b'value'})
        self.assert_uncertain(caught.exception)

    def test_complete_batch_survives_as_a_whole_when_rollback_fails(self):
        db = self.seeded()
        with mock.patch('os.fsync', side_effect=OSError(5, 'write sync failed')), \
             mock.patch('os.ftruncate', side_effect=OSError(5, 'rollback truncate failed')):
            with self.assertRaises(OSError) as caught:
                db.batch([('put', b'left', b'new'), ('put', b'right', b'new'), ('del', b'victim')])
        db.close()
        recovered = KVDB(self.path)
        self.addCleanup(recovered.close)
        self.assertEqual(dict(recovered.items()),
                         {b'anchor': b'saved', b'left': b'new', b'right': b'new'})
        self.assert_uncertain(caught.exception)

    def test_delete_can_survive_failed_rollback(self):
        db = self.seeded()
        with mock.patch('os.fsync', side_effect=OSError(5, 'write sync failed')), \
             mock.patch('os.ftruncate', side_effect=OSError(5, 'rollback truncate failed')):
            with self.assertRaises(OSError) as caught:
                db.delete(b'victim')
        db.close()
        recovered = KVDB(self.path)
        self.addCleanup(recovered.close)
        self.assertEqual(dict(recovered.items()), {b'anchor': b'saved'})
        self.assert_uncertain(caught.exception)

    def test_rollback_sync_failure_is_uncertain_even_after_truncation(self):
        db = self.seeded()
        with mock.patch('os.fsync', side_effect=OSError(5, 'sync failed')):
            with self.assertRaises(OSError) as caught:
                db.put(b'new', b'value')
        db.close()
        recovered = KVDB(self.path)
        self.addCleanup(recovered.close)
        # Process-only reopen sees the truncation; its durability was not confirmed.
        self.assertEqual(dict(recovered.items()), {b'anchor': b'saved', b'victim': b'old'})
        self.assert_uncertain(caught.exception)

    def test_partial_write_and_failed_rollback_preserve_earlier_data(self):
        db = self.seeded()
        real_write = os.pwrite
        calls = []
        def failing_write(fd, data, offset):
            calls.append(offset)
            if len(calls) == 1:
                return real_write(fd, bytes(data[:len(data)//2]), offset)
            raise OSError(5, 'append failed')
        with mock.patch('os.pwrite', side_effect=failing_write), \
             mock.patch('os.ftruncate', side_effect=OSError(5, 'rollback truncate failed')):
            with self.assertRaises(OSError) as caught:
                db.batch([('put', b'left', b'x'*100), ('del', b'victim')])
        db.close()
        recovered = KVDB(self.path)
        self.addCleanup(recovered.close)
        self.assertEqual(dict(recovered.items()), {b'anchor': b'saved', b'victim': b'old'})
        self.assert_uncertain(caught.exception)

    def test_serve_reports_uncertain_then_poisoned_without_ack(self):
        db = self.seeded()
        output = io.StringIO()
        with mock.patch('os.fsync', side_effect=OSError(5, 'write sync failed')), \
             mock.patch('os.ftruncate', side_effect=OSError(5, 'rollback truncate failed')):
            serve.run(db, io.StringIO('put w1-1 new value\nput w1-2 later blocked\nquit\n'), output)
        self.assertEqual(output.getvalue().splitlines()[1:],
                         ['ERR w1-1 UNCERTAIN', 'ERR w1-2 POISONED'])

    def test_cli_reports_uncertain_and_exits_unsuccessfully(self):
        db = self.seeded()
        with mock.patch('src.engine.KVDB', return_value=db), \
             mock.patch('os.fsync', side_effect=OSError(5, 'write sync failed')), \
             mock.patch('os.ftruncate', side_effect=OSError(5, 'rollback truncate failed')), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            code = cli.main(['put', self.path, 'new', 'value'])
        self.assertEqual(code, 1)
        self.assertEqual(output.getvalue(), 'ERR UNCERTAIN\n')

    def test_crash_runner_rejects_uncertain_response(self):
        script = '''
import sys
from unittest import mock
from src.engine import KVDB
from src.serve import run
db = KVDB(sys.argv[1])
with mock.patch('os.fsync', side_effect=OSError(5, 'sync failed')), \\
     mock.patch('os.ftruncate', side_effect=OSError(5, 'rollback failed')):
    run(db)
'''
        real_popen = subprocess.Popen
        def launch(args, **kwargs):
            return real_popen([sys.executable, '-c', script, args[3]], **kwargs)
        seed = next(s for s in range(1000)
                    if 10**random.Random('kill:%s:1' % s).uniform(-2.7, 0) > .5)
        with mock.patch.object(runner.subprocess, 'Popen', side_effect=launch):
            with self.assertRaisesRegex(AssertionError, 'unexpected error: ERR .* UNCERTAIN'):
                runner.iteration(seed, 1, Path(self.dir), io.StringIO())
