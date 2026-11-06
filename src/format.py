"""On-disk format: header, frame and op encoding/decoding (crc32, little-endian).

Owner: Nikhil

Layout (README "On-disk format"):
  HEADER  magic "KVDB0001" (8) | version u32 (4) | hcrc u32 (4) = crc32(first 12 bytes)
  FRAME   len u64 (8) | crc u32 (4) | payload (len bytes); crc = crc32(len bytes + payload)
  PAYLOAD nops u32 (4) | OP...
  OP      type u8 | klen u16 | vlen u32 | key | value   (DEL: vlen = 0, no value)
"""

import struct
import zlib

MAGIC = b"KVDB0001"
VERSION = 1
HEADER_SIZE = 16
FRAME_HDR_SIZE = 12
OP_HDR_SIZE = 7
NOPS_SIZE = 4
PUT = 1
DEL = 2
MAX_KEY = 1024
MAX_VALUE = 1048576
MAX_OPS = 10000

HEADER = struct.Struct("<8sII")
FRAME_HDR = struct.Struct("<QI")
LEN = struct.Struct("<Q")
NOPS = struct.Struct("<I")
OP_HDR = struct.Struct("<BHI")


def encode_header():
    head = HEADER.pack(MAGIC, VERSION, 0)[:12]
    return head + struct.pack("<I", zlib.crc32(head))


def check_header(buf):
    if len(buf) < HEADER_SIZE:
        return False
    magic, version, hcrc = HEADER.unpack_from(buf, 0)
    return (magic == MAGIC and version == VERSION
            and hcrc == zlib.crc32(bytes(buf[:12])))


def _check_bytes(name, b, lo, hi):
    if not isinstance(b, (bytes, bytearray)):
        raise ValueError("%s must be bytes" % name)
    if not lo <= len(b) <= hi:
        raise ValueError("%s must be %d..%d bytes, got %d" % (name, lo, hi, len(b)))


def validate_ops(ops):
    if not 1 <= len(ops) <= MAX_OPS:
        raise ValueError("batch must be 1..%d ops, got %d" % (MAX_OPS, len(ops)))
    for op in ops:
        if not isinstance(op, tuple) or not op:
            raise ValueError("op must be a tuple")
        if op[0] == "put" and len(op) == 3:
            _check_bytes("key", op[1], 1, MAX_KEY)
            _check_bytes("value", op[2], 0, MAX_VALUE)
        elif op[0] == "del" and len(op) == 2:
            _check_bytes("key", op[1], 1, MAX_KEY)
        else:
            raise ValueError("bad op %r" % (op[0],))


def encode_frame(ops):
    """Validate and encode ops as one frame.

    Returns (frame_bytes, value_offsets); value_offsets[i] is where op i's value
    starts relative to the frame start (for DEL: just past the key, vlen 0).
    """
    validate_ops(ops)
    parts = [NOPS.pack(len(ops))]
    offsets = []
    off = FRAME_HDR_SIZE + NOPS_SIZE
    for op in ops:
        key = op[1]
        if op[0] == "put":
            value = op[2]
            parts += (OP_HDR.pack(PUT, len(key), len(value)), key, value)
        else:
            value = b""
            parts += (OP_HDR.pack(DEL, len(key), 0), key)
        offsets.append(off + OP_HDR_SIZE + len(key))
        off += OP_HDR_SIZE + len(key) + len(value)
    payload = b"".join(parts)
    len_bytes = LEN.pack(len(payload))
    crc = zlib.crc32(payload, zlib.crc32(len_bytes))
    return len_bytes + struct.pack("<I", crc) + payload, offsets


def decode_frame(buf, pos, size):
    """Decode the frame at pos. Returns (ops, next_pos) or None to stop the scan.

    ops: list of (type, key_bytes, abs_value_offset, vlen). Values are not
    copied; read them later as buf[off:off + vlen]. buf may be bytes, mmap or
    memoryview; size is the number of valid bytes in buf.
    """
    # F4 truncated tail / A2 torn write: the frame header itself is incomplete.
    if size - pos < FRAME_HDR_SIZE:
        return None
    length, crc = FRAME_HDR.unpack_from(buf, pos)
    start = pos + FRAME_HDR_SIZE
    end = start + length
    # A2 torn write / B1/B2 partial batch: header landed but not every payload byte.
    if end > size:
        return None
    with memoryview(buf) as mv:
        # A2 torn write / B1/B2 partial batch: all bytes present but some are
        # stale or garbage (out-of-order page writeback, bit rot, zero fill).
        if zlib.crc32(mv[start:end], zlib.crc32(mv[pos:pos + 8])) != crc:
            return None
        ops = _parse_payload(mv, start, end)
    # Payload must parse exactly to its declared length (CRC-valid but malformed).
    if ops is None:
        return None
    return ops, end


def _parse_payload(mv, p, end):
    if end - p < NOPS_SIZE:
        return None
    (nops,) = NOPS.unpack_from(mv, p)
    if not 1 <= nops <= MAX_OPS:
        return None
    p += NOPS_SIZE
    ops = []
    for _ in range(nops):
        if end - p < OP_HDR_SIZE:
            return None
        typ, klen, vlen = OP_HDR.unpack_from(mv, p)
        p += OP_HDR_SIZE
        if typ not in (PUT, DEL) or not 1 <= klen <= MAX_KEY or vlen > MAX_VALUE:
            return None
        if typ == DEL and vlen:
            return None
        if end - p < klen + vlen:
            return None
        key = bytes(mv[p:p + klen])
        p += klen
        ops.append((typ, key, p, vlen))
        p += vlen
    if p != end:
        return None
    return ops
