"""Storage engine: KVDB class with put/get/delete/batch, recovery and index.

Owner: Nikhil

Append-only log of CRC'd frames (src/format.py). Write order and recovery follow
the README exactly. An in-memory index maps key -> (abs_value_offset, vlen);
values are read back with os.pread.
"""

import mmap
import os
import threading
import time

from src import crash
from src import format as fmt
from src.errors import CorruptError, DiskFull, LockedError, PoisonedError  # noqa: F401


def _fsync_dir(path):
    dfd = os.open(os.path.dirname(os.path.abspath(path)), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


def _pwrite_all(fd, data, offset):
    mv = memoryview(data)
    while mv:
        n = os.pwrite(fd, mv, offset)
        mv = mv[n:]
        offset += n


def _pread_all(fd, n, offset):
    parts = []
    while n:
        chunk = os.pread(fd, n, offset)
        if not chunk:
            raise OSError("short read at offset %d" % offset)
        parts.append(chunk)
        n -= len(chunk)
        offset += len(chunk)
    return b"".join(parts)


def _remove(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def _op_size(key, vlen):
    return fmt.OP_HDR_SIZE + len(key) + vlen


class KVDB:
    def __init__(self, path, max_bytes=None):
        self.path = path
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        self._index = {}
        self._dead_bytes = 0
        self._poisoned = False
        self._closed = False
        t0 = time.monotonic()
        self._fd = self._open_file()
        try:
            self.end = self._recover()
        except BaseException:
            os.close(self._fd)
            raise
        self.recovery_ms = (time.monotonic() - t0) * 1000

    # ---- open / recovery (README "Recovery" steps 2-7; flock comes later) ----

    def _open_file(self):
        _remove(self.path + ".compact")
        _remove(self.path + ".init")
        if not os.path.exists(self.path):
            self._create()
        return os.open(self.path, os.O_RDWR)

    def _create(self):
        init = self.path + ".init"
        fd = os.open(init, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        try:
            _pwrite_all(fd, fmt.encode_header(), 0)
            os.fsync(fd)
        finally:
            os.close(fd)
        crash.point("init_before_rename")  # disk: complete <path>.init, no <path>
        os.replace(init, self.path)
        _fsync_dir(self.path)

    def _recover(self):
        size = os.fstat(self._fd).st_size
        if size < fmt.HEADER_SIZE:
            raise CorruptError(0, "file shorter than header")
        with mmap.mmap(self._fd, size, access=mmap.ACCESS_READ) as m:
            if not fmt.check_header(m):
                raise CorruptError(0, "bad header")
            stop = self._scan(m, size)
        if stop < size:
            crash.point("recovery_before_truncate")  # disk: valid frames + torn tail
            os.ftruncate(self._fd, stop)
            os.fsync(self._fd)
            crash.point("recovery_after_truncate")  # disk: valid frames only, durable
        return stop

    def _scan(self, m, size):
        pos = fmt.HEADER_SIZE
        while True:
            crash.point("recovery_mid_scan")  # disk: unchanged, scan only reads
            r = fmt.decode_frame(m, pos, size)  # CorruptError propagates, no truncate
            if r is None:
                return pos
            ops, pos = r
            for typ, key, voff, vlen in ops:
                self._apply(typ == fmt.PUT, key, voff, vlen)

    def _apply(self, is_put, key, voff, vlen):
        old = self._index.pop(key, None)
        if old is not None:
            self._dead_bytes += _op_size(key, old[1])
        if is_put:
            self._index[key] = (voff, vlen)
        else:
            self._dead_bytes += _op_size(key, 0)

    # ---- write path (README "Write order") ----

    def put(self, key: bytes, value: bytes):
        self._commit([("put", key, value)])

    def delete(self, key):
        self._commit([("del", key)])

    def batch(self, ops):
        self._commit(list(ops))

    def _commit(self, ops):
        frame, offsets = fmt.encode_frame(ops)  # 1 validate, 2 encode
        with self._lock:  # 3
            self._check_open()
            if self._poisoned:  # 4
                raise PoisonedError("an earlier write or fsync failed")
            self._check_space(len(frame), all(op[0] == "del" for op in ops))  # 5
            self._write(frame)  # 6, 7
            for op, rel in zip(ops, offsets):  # 8
                is_put = op[0] == "put"
                self._apply(is_put, op[1], self.end + rel, len(op[2]) if is_put else 0)
            self.end += len(frame)

    def _check_space(self, frame_len, delete_only):
        if self.max_bytes is None:
            return
        reserve = 0 if delete_only else min(65536, self.max_bytes // 10)
        if self.end + frame_len > self.max_bytes - reserve:
            raise DiskFull("frame of %d bytes does not fit" % frame_len)

    def _write(self, frame):
        try:
            crash.point("before_write")  # disk: previous frames only
            prefix = crash.torn_write_prefix(frame)
            if prefix is not None:
                _pwrite_all(self._fd, prefix, self.end)
                crash.kill()  # disk: previous frames + partial frame
            _pwrite_all(self._fd, frame, self.end)
            crash.point("after_write")  # disk: full frame in page cache, not fsynced
            os.fsync(self._fd)
            crash.point("after_fsync")  # disk: frame durable, not yet indexed or ACKed
        except OSError:
            try:
                os.ftruncate(self._fd, self.end)
                os.fsync(self._fd)
            except OSError:
                pass
            self._poisoned = True
            raise

    # ---- reads ----

    def get(self, key):
        fmt.check_key(key)
        with self._lock:
            self._check_open()
            loc = self._index.get(key)
            if loc is None:
                return None
            return _pread_all(self._fd, loc[1], loc[0])

    def keys(self):
        with self._lock:
            self._check_open()
            return list(self._index)

    def items(self):
        with self._lock:
            self._check_open()
            return [(k, _pread_all(self._fd, n, off)) for k, (off, n) in self._index.items()]

    def compact(self):
        raise NotImplementedError("TODO M3: compaction")

    @property
    def stats(self):
        with self._lock:
            return {
                "keys": len(self._index),
                "file_bytes": self.end,
                "dead_bytes": self._dead_bytes,
                "recovery_ms": self.recovery_ms,
            }

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            crash.point("close_mid")  # disk: every committed frame already durable
            os.close(self._fd)

    def _check_open(self):
        if self._closed:
            raise ValueError("database is closed")
