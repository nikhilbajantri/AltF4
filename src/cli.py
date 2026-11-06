"""Command-line interface for the crash-safe key-value database."""
import argparse
import os
import sys

from src.errors import CorruptError, DiskFull, LockedError, PoisonedError
from src.serve import decode_token, encode_token

# These commands read an existing database; they must not create one.
NEEDS_EXISTING = ("get", "del", "dump", "check", "inspect", "compact")


def parse_batch_line(line):
    """"put <key> <value>" (the value is the rest of the line, spaces kept) or "del <key>"."""
    line = line.rstrip("\r\n")
    if line.startswith("put "):
        fields = line.split(" ", 2)
        if len(fields) == 3:
            return ("put", decode_token(fields[1]), decode_token(fields[2]))
    fields = line.split()
    if len(fields) == 2 and fields[0] == "del":
        return ("del", decode_token(fields[1]))
    raise ValueError("invalid batch line")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="kvdb")
    subs = parser.add_subparsers(dest="command", required=True)
    for name in ("open", "put", "get", "del", "batch", "dump", "check", "serve", "inspect", "compact"):
        sub = subs.add_parser(name)
        sub.add_argument("path")
        sub.add_argument("--max-bytes", type=int)
        if name in ("put", "get", "del"):
            sub.add_argument("key")
        if name == "put":
            sub.add_argument("value")
        if name == "batch":
            sub.add_argument("file")
    args = parser.parse_args(argv)
    if args.max_bytes is not None and args.max_bytes < 16:
        parser.error("--max-bytes must be at least 16")
    if args.command in NEEDS_EXISTING and not os.path.exists(args.path):
        print("ERR not found")
        return 1
    try:
        if args.command == "serve":
            from src.serve import main as serve_main
            options = [args.path]
            if args.max_bytes is not None:
                options += ["--max-bytes", str(args.max_bytes)]
            return serve_main(options)
        if args.command == "check":
            from src.scan import check_file
            ok, message = check_file(args.path)
            print(message)
            return 0 if ok else 1
        if args.command == "inspect":
            from src.inspect_cmd import inspect
            return inspect(args.path)
        from src.engine import KVDB
        ops = None
        if args.command == "batch":
            with open(args.file, encoding="utf-8") as source:
                ops = [parse_batch_line(line) for line in source if line.strip()]
            from src.format import validate_ops
            validate_ops(ops)
        db = KVDB(args.path, max_bytes=args.max_bytes)
        try:
            if args.command == "open":
                stats = db.stats
                print("keys=%d recovery_ms=%.3f" % (stats["keys"], stats["recovery_ms"]))
            elif args.command == "put":
                db.put(decode_token(args.key), decode_token(args.value))
                print("OK")
            elif args.command == "get":
                value = db.get(decode_token(args.key))
                print("NOTFOUND" if value is None else encode_token(value))
            elif args.command == "del":
                db.delete(decode_token(args.key))
                print("OK")
            elif args.command == "batch":
                db.batch(ops)
                print("OK")
            elif args.command == "dump":
                for key, value in sorted(db.items()):
                    print(encode_token(key) + "\t" + encode_token(value))
            elif args.command == "compact":
                before = db.stats["file_bytes"]
                db.compact()
                print("before=%d after=%d" % (before, db.stats["file_bytes"]))
        finally:
            db.close()
        return 0
    except (ValueError, UnicodeError):
        print("ERR INVALID")
    except (DiskFull, LockedError, PoisonedError, CorruptError, OSError) as exc:
        reason = {DiskFull: "DISKFULL", LockedError: "LOCKED", PoisonedError: "POISONED",
                  CorruptError: "CORRUPT"}.get(type(exc), "IO")
        print("ERR " + reason)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
