"""Storage engine: KVDB class with put/get/delete/batch, recovery and index.

Owner: Nikhil

Append-only log of CRC'd frames (src/format.py). Write order and recovery follow
the README exactly. An in-memory index maps key -> (abs_value_offset, vlen);
values are read back with os.pread. Compaction rewrites live keys to
<path>.compact and renames it over <path> (README "Compaction").
"""

import fcntl
import mmap
import os
import threading
import time

from src import crash
from src import format as fmt
from src.errors import CorruptError, DiskFull, LockedError, PoisonedError, UncertainWriteError  # noqa: F401


def _fsync_dir(path):
    dfd = os.open(os.path.dirname(os.path.abspath(path)), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


def _pwrite_all(fd, data, offset):
    if isinstance(data, fmt.FrameParts):
        for chunk in data.chunks():
            _pwrite_all(fd, chunk, offset)
            offset += len(chunk)
        return
    mv = memoryview(data)
    while mv:
        n = os.pwrite(fd, mv, offset)
        if n <= 0:
            raise OSError(5, "pwrite made no progress")
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


COMPACT_FRAME_PAYLOAD = 4 * 1024 * 1024
AUTO_COMPACT_MIN_BYTES = 4 * 1024 * 1024


def _op_size(key, vlen):
    return fmt.OP_HDR_SIZE + len(key) + vlen


class KVDB:
    def __init__(self, path, max_bytes=None, auto_compact=True):
        self.path = path
        self.max_bytes = max_bytes
        self.auto_compact = auto_compact
        self._lock = threading.Lock()
        self._index = {}
        self._dead_bytes = 0
        self._poisoned = False
        self._closed = False
        t0 = time.monotonic()
        self._lock_fd = self._flock()
        try:
            self._fd = self._open_file()
            try:
                self.end = self._recover()
            except BaseException:
                os.close(self._fd)
                raise
        except BaseException:
            os.close(self._lock_fd)
            raise
        self.recovery_ms = (time.monotonic() - t0) * 1000

    # ---- open / recovery (README "Recovery" steps 1-7) ----

    def _flock(self):
        fd = os.open(self.path + ".lock", os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise LockedError("%s is open in another KVDB" % self.path) from None
        except BaseException:
            os.close(fd)
            raise
        return fd

    def _open_file(self):
        _remove(self.path + ".compact")
        _remove(self.path + ".init")
        if not os.path.exists(self.path) or self._is_header_prefix():
            self._create()
        return os.open(self.path, os.O_RDWR)

    def _is_header_prefix(self):
        # F4: a file shorter than the header that holds exactly the start of a
        # valid header (incl. 0 bytes) is a header write that never finished.
        with open(self.path, "rb") as f:
            data = f.read(fmt.HEADER_SIZE)
        return len(data) < fmt.HEADER_SIZE and data == fmt.encode_header()[:len(data)]

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
        self._commit(fmt.collect_ops(ops))

    def _commit(self, ops):
        size = fmt.frame_size(ops)  # validate before allocating encoded data
        with self._lock:  # 3
            self._check_open()
            if self._poisoned:  # 4
                raise PoisonedError("an earlier write or fsync failed")
            delete_only = all(op[0] == "del" for op in ops)
            try:
                self._check_space(size, delete_only)  # 5
            except DiskFull:
                if not self._dead_bytes:
                    raise
                self._compact_locked()  # E5: reclaim dead bytes, retry once
                self._check_space(size, delete_only)
            frame, offsets = fmt.prepare_frame(ops)
            self._write(frame)  # 6, 7: one frame, one final fsync
            for op, rel in zip(ops, offsets):  # 8
                is_put = op[0] == "put"
                self._apply(is_put, op[1], self.end + rel, len(op[2]) if is_put else 0)
            self.end += len(frame)
            self._maybe_auto_compact()

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
        except (OSError, MemoryError) as write_error:
            self._poisoned = True
            try:
                os.ftruncate(self._fd, self.end)
                os.fsync(self._fd)
            except OSError as rollback_error:
                # A complete frame may still be replayable. Never promise that
                # this operation is absent when rollback was not confirmed.
                raise UncertainWriteError(write_error, rollback_error) from write_error
            if isinstance(write_error, MemoryError):
                raise OSError(12, "frame chunk allocation failed") from write_error
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

    # ---- compaction (README "Compaction"); caller holds self._lock ----

    def compact(self):
        with self._lock:
            self._check_open()
            if self._poisoned:
                raise PoisonedError("an earlier write or fsync failed")
            self._compact_locked()

    def _maybe_auto_compact(self):
        # P1: the frame is already committed, so a failed compaction must not
        # turn the write into an error; the old file stays fully usable.
        if (self.auto_compact and self.end > AUTO_COMPACT_MIN_BYTES
                and self._dead_bytes > 0.5 * self.end):
            try:
                self._compact_locked()
            except (DiskFull, OSError):
                pass

    def _compact_locked(self):
        tmp = self.path + ".compact"
        _remove(tmp)
        fd = os.open(tmp, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o644)
        try:
            try:
                new_index, new_end = self._copy_live(fd)
                os.fsync(fd)
            finally:
                os.close(fd)
            crash.point("compact_before_rename")  # disk: old <path> + complete, durable .compact
            os.replace(tmp, self.path)
        except BaseException:
            _remove(tmp)  # E4: old file, fd and index untouched
            raise
        crash.point("compact_after_rename")  # disk: <path> is the compacted file
        try:
            _fsync_dir(self.path)
            new_fd = os.open(self.path, os.O_RDWR)
        except BaseException:
            # rename happened but cannot be made durable or reopened: our fd now
            # points at the unlinked old inode, so further writes would be lost
            self._poisoned = True
            raise
        os.close(self._fd)
        self._fd, self._index, self.end, self._dead_bytes = new_fd, new_index, new_end, 0
        crash.point("compact_after_swap")  # disk: compacted file, rename durable

    def _copy_live(self, fd):
        header = fmt.encode_header()
        _pwrite_all(fd, header, 0)
        pos = len(header)
        keys = sorted(self._index)
        new_index, ops, payload, copied, mid_hit = {}, [], fmt.NOPS_SIZE, 0, False
        for i, key in enumerate(keys):
            voff, vlen = self._index[key]
            ops.append(("put", key, _pread_all(self._fd, vlen, voff)))
            payload += _op_size(key, vlen)
            last = i + 1 == len(keys)
            if not last:
                nkey = keys[i + 1]
                nsize = _op_size(nkey, self._index[nkey][1])
            if last or payload + nsize > COMPACT_FRAME_PAYLOAD or len(ops) == fmt.MAX_OPS:
                pos = self._write_compact_frame(fd, ops, pos, new_index)
                copied += len(ops)
                ops, payload = [], fmt.NOPS_SIZE
                if not mid_hit and 2 * copied >= len(keys):
                    mid_hit = True
                    crash.point("compact_mid_copy")  # disk: old <path> + partial .compact
        return new_index, pos

    def _write_compact_frame(self, fd, ops, pos, new_index):
        frame, offsets = fmt.encode_frame(ops)
        if self.max_bytes is not None and pos + len(frame) > self.max_bytes:
            raise DiskFull("compacted file does not fit in max_bytes")
        _pwrite_all(fd, frame, pos)
        for (_, key, value), rel in zip(ops, offsets):
            new_index[key] = (pos + rel, len(value))
        return pos + len(frame)

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
            os.close(self._lock_fd)  # releases the flock

    def _check_open(self):
        if self._closed:
            raise ValueError("database is closed")
