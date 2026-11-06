"""First serve milestone: protocol, error handling, and response ordering."""

import io
import unittest
import threading
from unittest import mock

from src.engine_fake import FakeKVDB
from src.serve import main, run
from src.errors import LockedError


class ServeTests(unittest.TestCase):
    def session(self, commands, db=None):
        db = FakeKVDB("unused") if db is None else db
        output = io.StringIO()
        run(db, io.StringIO(commands), output)
        self.assertTrue(db._closed)
        return output.getvalue().splitlines()

    def test_put_get_delete(self):
        self.assertEqual(self.session(
            "put w1-1 name Arsh\nget w1-2 name\ndel w1-3 name\n"
            "get w1-4 name\nquit\nput ignored name nope\n"), [
                "READY keys=0 recovery_ms=0.000", "ACK w1-1",
                "VAL w1-2 Arsh", "ACK w1-3", "NOTFOUND w1-4"])

    def test_invalid_input_does_not_end_session(self):
        lines = self.session("garbage\nput w1-1 hex:zz value\n"
                             "put w1-2 name Arsh\n")
        self.assertCountEqual(lines[1:], ["ERR - INVALID", "ERR w1-1 INVALID",
                                     "ACK w1-2"])

    def test_binary_and_empty_values(self):
        lines = self.session("put w1-1 hex:ff hex:000aff\n"
                             "get w1-2 hex:ff\nput w1-3 empty hex:\n"
                             "get w1-4 empty\n")
        self.assertIn("VAL w1-2 hex:000aff", lines)
        self.assertIn("VAL w1-4 hex:", lines)

    def test_disk_full_never_acknowledges(self):
        lines = self.session("put w1-1 name Arsh\nget w1-2 name\n",
                             FakeKVDB("unused", max_bytes=16))
        self.assertEqual(lines[1:], ["ERR w1-1 DISKFULL", "NOTFOUND w1-2"])

    def test_batch_applies_in_order_with_one_ack(self):
        lines = self.session("batch w1-1\nput name Arsh\nput city Delhi\n"
                             "del name\nend\nget w1-2 name\nget w1-3 city\n")
        self.assertEqual(lines[1:], ["ACK w1-1", "NOTFOUND w1-2",
                                     "VAL w1-3 Delhi"])

    def test_invalid_batch_changes_nothing_and_session_continues(self):
        lines = self.session("batch w1-1\nput name Arsh\ngarbage\n"
                             "put city Delhi\nend\nget w1-2 name\n"
                             "get w1-3 city\n")
        self.assertEqual(lines[1:], ["ERR w1-1 INVALID", "NOTFOUND w1-2",
                                     "NOTFOUND w1-3"])

    def test_empty_and_unterminated_batches_are_rejected(self):
        for commands in ("batch w1-1\nend\n", "batch w1-1\nput a b\n"):
            with self.subTest(commands=commands):
                self.assertEqual(self.session(commands)[1:], ["ERR w1-1 INVALID"])

    def test_batch_validates_all_operations_before_writing(self):
        lines = self.session("batch w1-1\nput name Arsh\nput hex: bad\n"
                             "end\nget w1-2 name\n")
        self.assertEqual(lines[1:], ["ERR w1-1 INVALID", "NOTFOUND w1-2"])

    def test_disk_full_batch_changes_nothing(self):
        lines = self.session("batch w1-1\nput a b\nput c d\nend\n"
                             "get w1-2 a\n", FakeKVDB("unused", max_bytes=50))
        self.assertEqual(lines[1:], ["ERR w1-1 DISKFULL", "NOTFOUND w1-2"])

    def test_batch_size_limit(self):
        for count, response in ((10_000, "ACK w1-1"), (10_001, "ERR w1-1 INVALID")):
            with self.subTest(count=count):
                commands = "batch w1-1\n" + "put a b\n" * count + "end\n"
                self.assertEqual(self.session(commands)[1:], [response])

    def test_malformed_batch_header_does_not_execute_body(self):
        for header in ("batch", "batch w1-1 extra"):
            with self.subTest(header=header):
                lines = self.session(header + "\nput name Arsh\nend\nget w1-2 name\n")
                # Different writer prefixes may reply in either order.
                op_id = header.split()[1] if len(header.split()) > 1 else "-"
                self.assertCountEqual(lines[1:],
                                      [f"ERR {op_id} INVALID", "NOTFOUND w1-2"])
                self.assertFalse(any(line.startswith("ACK") for line in lines))

    def test_compact_routes_to_engine(self):
        db = FakeKVDB("unused")
        with mock.patch.object(db, "compact", wraps=db.compact) as compact:
            self.assertEqual(self.session("compact w1-1\n", db)[1:], ["ACK w1-1"])
            compact.assert_called_once_with()

    def test_unfinished_compaction_does_not_crash_session(self):
        db = FakeKVDB("unused")
        with mock.patch.object(db, "compact", side_effect=NotImplementedError):
            self.assertEqual(self.session("compact w1-1\nget w1-2 a\n", db)[1:],
                             ["ERR w1-1 UNSUPPORTED", "NOTFOUND w1-2"])

    def test_startup_error_has_no_ready_or_traceback(self):
        with mock.patch("src.engine_fake.KVDB", side_effect=LockedError), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(main(["unused", "--fake"]), 1)
            self.assertEqual(output.getvalue(), "ERR LOCKED\n")

    def test_invalid_cap_is_rejected_before_open(self):
        with mock.patch("src.engine_fake.KVDB") as engine, \
                mock.patch("sys.stderr", new_callable=io.StringIO):
            with self.assertRaises(SystemExit) as error:
                main(["unused", "--fake", "--max-bytes", "0"])
            self.assertEqual(error.exception.code, 2)
            engine.assert_not_called()

    def test_two_writers_enter_engine_concurrently(self):
        barrier = threading.Barrier(2, timeout=3)
        threads = set()
        guard = threading.Lock()

        class Engine(FakeKVDB):
            def put(self, key, value):
                with guard:
                    threads.add(threading.current_thread().name)
                barrier.wait()
                super().put(key, value)

        lines = self.session("put w1-1 a one\nput w2-1 b two\nquit\n", Engine("unused"))
        self.assertCountEqual(lines[1:], ["ACK w1-1", "ACK w2-1"])
        self.assertEqual(threads, {"serve-w1", "serve-w2"})

    def test_each_writer_keeps_order_and_quit_drains_work(self):
        commands = "".join("put %s-%d %s %d\n" % (w, n, w, n)
                           for n in range(20) for w in ("w1", "w2"))
        lines = self.session(commands + "get w1-20 w1\nget w2-20 w2\nquit\n")
        for w in ("w1", "w2"):
            self.assertEqual([line for line in lines if line.startswith("ACK " + w)],
                             ["ACK %s-%d" % (w, n) for n in range(20)])
            self.assertIn("VAL %s-20 19" % w, lines)

    def test_ack_is_written_only_after_engine_returns(self):
        events = []

        class Engine(FakeKVDB):
            def put(self, key, value):
                events.append("put started")
                super().put(key, value)
                events.append("put completed")

        class Output(io.StringIO):
            def write(self, text):
                if text.startswith("ACK"):
                    events.append("ack")
                return super().write(text)

        run(Engine("unused"), io.StringIO("put w1-1 name Arsh\n"), Output())
        self.assertEqual(events, ["put started", "put completed", "ack"])


if __name__ == "__main__":
    unittest.main()
