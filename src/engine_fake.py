"""Temporary stand-in so CLI and serve can be built before the real engine lands. Owner: Nikhil.

FakeKVDB has the same API as src/engine.py KVDB (see README "Engine API"), but data
lives in a dict and nothing touches disk. file_bytes and dead_bytes are simulated
from the README frame sizes so DISKFULL and compaction paths can be exercised.
"""

import threading
from src.format import collect_ops

from src.errors import DiskFull, LockedError, PoisonedError  # noqa: F401 (re-exported)

HEADER_SIZE = 16
FRAME_HEADER = 12
NOPS_SIZE = 4
OP_HEADER = 7
MAX_KEY = 1024
MAX_VALUE = 1_048_576
MAX_BATCH = 10_000


def _check_key(key):
    if not isinstance(key, bytes) or not 1 <= len(key) <= MAX_KEY:
        raise ValueError("key must be 1..1024 bytes")


def _check_value(value):
    if not isinstance(value, bytes) or len(value) > MAX_VALUE:
        raise ValueError("value must be 0..1048576 bytes")


def _op_size(key, value=b""):
    return OP_HEADER + len(key) + len(value)


class FakeKVDB:
    def __init__(self, path, max_bytes=None):
        self.path = path
        self.max_bytes = max_bytes
        self._data = {}
        self._file_bytes = HEADER_SIZE
        self._dead_bytes = 0
        self._lock = threading.Lock()
        self._closed = False

    def put(self, key: bytes, value: bytes):
        self.batch([("put", key, value)])

    def get(self, key):
        _check_key(key)
        with self._lock:
            self._check_open()
            return self._data.get(key)

    def delete(self, key):
        self.batch([("del", key)])

    def batch(self, ops):
        ops = collect_ops(ops)
        if not 1 <= len(ops) <= MAX_BATCH:
            raise ValueError("batch must be 1..10000 ops")
        frame = FRAME_HEADER + NOPS_SIZE
        for op in ops:
            if op[0] == "put" and len(op) == 3:
                _check_key(op[1])
                _check_value(op[2])
                frame += _op_size(op[1], op[2])
            elif op[0] == "del" and len(op) == 2:
                _check_key(op[1])
                frame += _op_size(op[1])
            else:
                raise ValueError("bad op: %r" % (op[0],))
        with self._lock:
            self._check_open()
            self._check_space(frame, all(op[0] == "del" for op in ops))
            for op in ops:
                old = self._data.get(op[1])
                if old is not None:
                    self._dead_bytes += _op_size(op[1], old)
                if op[0] == "put":
                    self._data[op[1]] = op[2]
                else:
                    self._data.pop(op[1], None)
                    self._dead_bytes += _op_size(op[1])
            self._file_bytes += frame

    def compact(self):
        with self._lock:
            self._check_open()
            self._compact_locked()

    def keys(self):
        with self._lock:
            return list(self._data)

    def items(self):
        with self._lock:
            return list(self._data.items())

    def close(self):
        self._closed = True

    @property
    def stats(self):
        with self._lock:
            return {
                "keys": len(self._data),
                "file_bytes": self._file_bytes,
                "dead_bytes": self._dead_bytes,
                "recovery_ms": 0.0,
            }

    def _check_open(self):
        if self._closed:
            raise ValueError("database is closed")

    def _check_space(self, frame, is_delete):
        if self.max_bytes is None:
            return
        reserve = 0 if is_delete else min(65536, self.max_bytes // 10)
        limit = self.max_bytes - reserve
        if self._file_bytes + frame > limit and self._dead_bytes:
            self._compact_locked()
        if self._file_bytes + frame > limit:
            raise DiskFull("frame of %d bytes does not fit" % frame)

    def _compact_locked(self):
        live = sum(FRAME_HEADER + NOPS_SIZE + _op_size(k, v) for k, v in self._data.items())
        self._file_bytes = HEADER_SIZE + live
        self._dead_bytes = 0


KVDB = FakeKVDB  # drop-in alias: `from src.engine_fake import KVDB`
