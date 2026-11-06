"""Serve commands over stdin/stdout. Owner: Arsh.

Supports put, get, del, atomic batches, quit, and invalid-input handling.
Use --fake to practise without the Linux storage engine.
"""

import argparse
import sys

from src.errors import CorruptError, DiskFull, LockedError, PoisonedError
from src.format import validate_ops


def decode_token(token):
    """Turn a command token into the bytes expected by the engine."""
    if token.startswith("hex:"):
        return bytes.fromhex(token[4:])
    return token.encode("utf-8")


def encode_token(value):
    """Keep binary, empty, or whitespace-containing values on one output line."""
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError:
        return "hex:" + value.hex()
    if (not text or text.startswith("hex:")
            or any(c.isspace() or not c.isprintable() for c in text)):
        return "hex:" + value.hex()
    return text


def read_batch(lines):
    """Collect a whole batch before writing; drain invalid batches through end."""
    ops = []
    invalid = False
    for line in lines:
        parts = line.split()
        if parts == ["end"]:
            if invalid or not ops:
                raise ValueError("invalid batch")
            return ops
        if invalid:
            continue
        try:
            if len(ops) >= 10_000:
                raise ValueError("too many operations")
            if len(parts) == 3 and parts[0] == "put":
                ops.append(("put", decode_token(parts[1]), decode_token(parts[2])))
            elif len(parts) == 2 and parts[0] == "del":
                ops.append(("del", decode_token(parts[1])))
            else:
                raise ValueError("invalid batch operation")
            validate_ops([ops[-1]])
        except ValueError:
            invalid = True
            ops.clear()
    raise ValueError("batch missing end")


def run(db, input_stream=None, output_stream=None):
    """Run one session using an already-open engine (real or fake)."""
    input_stream = sys.stdin if input_stream is None else input_stream
    output_stream = sys.stdout if output_stream is None else output_stream

    def reply(message):
        print(message, file=output_stream, flush=True)

    try:
        stats = db.stats
        reply("READY keys=%d recovery_ms=%.3f" %
              (stats["keys"], stats["recovery_ms"]))
        lines = iter(input_stream)
        for line in lines:
            parts = line.split()
            if parts == ["quit"]:
                break
            op_id = parts[1] if len(parts) > 1 else "-"
            try:
                if parts and parts[0] == "batch":
                    ops = read_batch(lines)
                    if len(parts) != 2:
                        raise ValueError("batch requires one operation id")
                    # One engine call makes the entire group one operation.
                    db.batch(ops)
                    reply("ACK " + op_id)
                elif len(parts) == 4 and parts[0] == "put":
                    key, value = decode_token(parts[2]), decode_token(parts[3])
                    db.put(key, value)
                    # Never acknowledge before the engine returns successfully.
                    reply("ACK " + op_id)
                elif len(parts) == 3 and parts[0] == "del":
                    db.delete(decode_token(parts[2]))
                    reply("ACK " + op_id)
                elif len(parts) == 2 and parts[0] == "compact":
                    db.compact()
                    reply("ACK " + op_id)
                elif len(parts) == 3 and parts[0] == "get":
                    value = db.get(decode_token(parts[2]))
                    if value is None:
                        reply("NOTFOUND " + op_id)
                    else:
                        reply("VAL %s %s" % (op_id, encode_token(value)))
                else:
                    reply("ERR %s INVALID" % op_id)
            except ValueError:
                reply("ERR %s INVALID" % op_id)
            except DiskFull:
                reply("ERR %s DISKFULL" % op_id)
            except PoisonedError:
                reply("ERR %s POISONED" % op_id)
            except OSError:
                reply("ERR %s IO" % op_id)
            except NotImplementedError:
                reply("ERR %s UNSUPPORTED" % op_id)
    finally:
        db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    parser.add_argument("--max-bytes", type=int)
    parser.add_argument("--fake", action="store_true",
                        help="practice engine: data is lost when the session ends")
    args = parser.parse_args(argv)
    if args.max_bytes is not None and args.max_bytes < 16:
        parser.error("--max-bytes must be at least 16 (the database header size)")
    if args.fake:
        from src.engine_fake import KVDB
    else:
        if sys.platform == "win32":
            print("ERR PLATFORM: use WSL/Linux for the real engine, or --fake for practice",
                  file=sys.stderr, flush=True)
            return 1
        from src.engine import KVDB
    try:
        db = KVDB(args.path, max_bytes=args.max_bytes)
    except (LockedError, CorruptError, OSError, ValueError) as exc:
        reason = ("LOCKED" if isinstance(exc, LockedError) else
                  "CORRUPT" if isinstance(exc, CorruptError) else
                  "IO" if isinstance(exc, OSError) else "INVALID")
        print("ERR " + reason, flush=True)
        return 1
    run(db)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
