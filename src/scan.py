"""Read-only frame scanner for `kvdb check` and `kvdb inspect`.

Owner: Nikhil

Never takes <path>.lock, never truncates, never creates files: safe to run on a
database another process has open. Values are never returned, only their lengths.
"""

import mmap
import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from src import format as fmt
from src.errors import CorruptError

LATER_FRAME_SEARCH = 1024 * 1024


@dataclass
class Frame:
    offset: int
    length: int                     # total bytes: 12-byte frame header + payload
    status: str                     # "ok" | "torn" | "corrupt"
    nops: Optional[int] = None
    ops: List[Tuple[int, bytes, int]] = field(default_factory=list)  # (type, key, vlen)
    reason: str = ""


@dataclass
class Tail:
    """Always the last record: where the scan stopped and what is past it."""
    offset: int                     # clean physical EOF, or first damaged frame
    tail_bytes: int                 # bytes past offset
    later_frame: Optional[int] = None  # a CRC-valid frame found past the stop point
    header_prefix: bool = False     # file is an unfinished header (open rewrites it)
    bad_header: bool = False


def iter_frames(path):
    """Yield a Frame per frame in the file, then exactly one Tail."""
    with open(path, "rb") as f:
        size = os.fstat(f.fileno()).st_size
        if size < fmt.HEADER_SIZE:
            data = f.read()
            if data == fmt.encode_header()[:size]:
                yield Tail(0, size, header_prefix=True)
            else:
                yield Frame(0, size, "corrupt", reason="file shorter than header")
                yield Tail(0, size, bad_header=True)
            return
        with mmap.mmap(f.fileno(), size, access=mmap.ACCESS_READ) as m:
            yield from _scan(m, size)


def _scan(m, size):
    if not fmt.check_header(m):
        yield Frame(0, fmt.HEADER_SIZE, "corrupt", reason="bad header")
        yield Tail(0, size, bad_header=True)
        return
    pos = fmt.HEADER_SIZE
    while True:
        try:
            r = fmt.decode_frame(m, pos, size)
        except CorruptError as e:
            (length, _) = fmt.FRAME_HDR.unpack_from(m, pos)
            yield Frame(pos, fmt.FRAME_HDR_SIZE + length, "corrupt", reason=e.reason)
            break
        if r is None:
            if pos > fmt.HEADER_SIZE and size == pos + 1 and m[pos:size] == fmt.TAIL_GUARD:
                pos = size  # Optional expendable guard is a clean physical EOF.
            if pos < size:
                yield Frame(pos, size - pos, "torn")
            break
        ops, nxt = r
        yield Frame(pos, nxt - pos, "ok", len(ops), [(t, k, n) for t, k, _, n in ops])
        pos = nxt
    later = None
    if size - pos >= fmt.FRAME_HDR_SIZE:
        length, _ = fmt.FRAME_HDR.unpack_from(m, pos)
        later = _find_later_frame(m, pos + fmt.FRAME_HDR_SIZE + length, size)
    yield Tail(pos, size - pos, later)


def _find_later_frame(m, start, size):
    """Check declared outer-frame boundaries, never arbitrary value bytes.

    Damaged length fields can hide later records. With arbitrary binary values
    and no separate framing marker, byte-searching cannot resolve that ambiguity.
    This is a bounded diagnostic, not a general media-corruption detector.
    """
    position = start
    limit = min(size, start + LATER_FRAME_SEARCH)
    while position < limit and size - position >= fmt.FRAME_HDR_SIZE:
        try:
            if fmt.decode_frame(m, position, size) is not None:
                return position
        except CorruptError:
            return position  # CRC-valid malformed frame at an outer boundary
        length, _ = fmt.FRAME_HDR.unpack_from(m, position)
        position += fmt.FRAME_HDR_SIZE + length
    return None


def check_file(path):
    """Return (ok, message): "OK", "OK torn-tail=<n> bytes (open will truncate)",
    or "CORRUPT offset=<n> <reason>"."""
    tail = None
    for rec in iter_frames(path):
        if isinstance(rec, Tail):
            tail = rec
        elif rec.status == "corrupt":
            return False, "CORRUPT offset=%d %s" % (rec.offset, rec.reason)
    if tail.later_frame is not None:
        return False, ("CORRUPT offset=%d damaged frame followed by CRC-valid frame at %d"
                       % (tail.offset, tail.later_frame))
    if tail.tail_bytes:
        return True, "OK torn-tail=%d bytes (open will truncate)" % tail.tail_bytes
    return True, "OK"
