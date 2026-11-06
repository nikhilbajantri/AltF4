
"""Command-line interface for ./kvdb.

Owner: Srushti
"""

import argparse
from src.engine import KVDB
from src.scan import check_file


def main():
    parser = argparse.ArgumentParser(
        description="AltF4 Key-Value Database"
    )

    subparsers = parser.add_subparsers(
        dest="command", required=True
    )

    # OPEN command
    open_parser = subparsers.add_parser("open")
    open_parser.add_argument("path")
    open_parser.add_argument("--max-bytes", type=int, default=None)

    # PUT command
    put_parser = subparsers.add_parser("put")
    put_parser.add_argument("path")
    put_parser.add_argument("key")
    put_parser.add_argument("value")
    get_parser = subparsers.add_parser("get")
    get_parser.add_argument("path")
    get_parser.add_argument("key")

    # DELETE command
    del_parser = subparsers.add_parser("del")
    del_parser.add_argument("path")
    del_parser.add_argument("key")

    # DUMP command
    dump_parser = subparsers.add_parser("dump")
    dump_parser.add_argument("path")
    check_parser = subparsers.add_parser("check")
    check_parser.add_argument("path")
    dump_parser = subparsers.add_parser("dump")
    dump_parser.add_argument("path")
    
    batch_parser = subparsers.add_parser("batch")
    batch_parser.add_argument("path")
    batch_parser.add_argument("file") 

    args = parser.parse_args()


    if args.command == "open":
        db = None
        try:
            db = KVDB(args.path, max_bytes=args.max_bytes)
            stats = db.stats
            print(
                f"keys={stats['keys']} "
                f"recovery_ms={stats['recovery_ms']}"
            )
        except Exception as e:
            print(f"ERR {e}")
            raise SystemExit(1)
        finally:
            if db is not None:
                db.close()

    elif args.command == "put":
        db = None
        try:
            db = KVDB(args.path)
            db.put(args.key.encode(), args.value.encode())
            print("OK")
        except Exception as e:
            print(f"ERR {e}")
            raise SystemExit(1)
        finally:
            if db is not None:
                db.close()

    elif args.command == "get":
        db = None
        try:
            db = KVDB(args.path)
            value = db.get(args.key.encode())

            if value is None:
                print("NOTFOUND")
            else:
                print(value.decode())

        except Exception as e:
            print(f"ERR {e}")
            raise SystemExit(1)

        finally:
            if db is not None:
                db.close()

    elif args.command == "del":
        db = None
        try:
            db = KVDB(args.path)
            db.delete(args.key.encode())
            print("OK")

        except Exception as e:
            print(f"ERR {e}")
            raise SystemExit(1)

        finally:
            if db is not None:
                db.close()

    elif args.command == "dump":
        db = None
        try:
            db = KVDB(args.path)

            for key, value in sorted(db.items()):
                print(f"{key.decode()}\t{value.decode()}")

        except Exception as e:
            print(f"ERR {e}")
            raise SystemExit(1)

        finally:
            if db is not None:
                db.close()

    elif args.command == "batch":
        db = None
        try:
            ops = []

            with open(args.file, "r", encoding="utf-8") as f:
                for line_number, line in enumerate(f, start=1):
                    parts = line.strip().split()

                    if not parts:
                        continue

                    if parts[0] == "put" and len(parts) == 3:
                        ops.append((
                            "put",
                            parts[1].encode(),
                            parts[2].encode()
                        ))

                    elif parts[0] == "del" and len(parts) == 2:
                        ops.append((
                            "del",
                            parts[1].encode()
                        ))

                    else:
                        raise ValueError(
                            f"Invalid batch instruction at line {line_number}"
                        )

            # Validate the complete batch before opening the database.
            from src.format import validate_ops
            validate_ops(ops)

            db = KVDB(args.path)
            db.batch(ops)
            print("OK")

        except Exception as e:
            print(f"ERR {e}")
            raise SystemExit(1)

        finally:
            if db is not None:
                db.close()
    

    elif args.command == "check":
        try:
            ok, message = check_file(args.path)
            print(message)

            if not ok:
                raise SystemExit(1)

        except Exception as e:
            print(f"CORRUPT {e}")
            raise SystemExit(1)


if __name__ == "__main__":
    main()
