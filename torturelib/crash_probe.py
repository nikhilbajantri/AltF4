"""Temporary subprocess adapter until the top-level CLI is implemented.

Only this adapter touches the engine: open, read-only check, then final dump.
The runner and expected-state oracle do not import storage code.
"""
import json
import sys
from src.engine import KVDB
from src.scan import check_file


def main():
    path = sys.argv[1]
    db = KVDB(path)
    db.close()
    ok, message = check_file(path)
    if not ok or message != "OK":
        # Recovery must remove a torn tail, not merely tolerate one. Accepting
        # "OK torn-tail=..." here would hide a broken truncation step.
        raise RuntimeError("check: " + message)
    db = KVDB(path)
    try:
        print(json.dumps({"check": message,
                          "items": [[k.hex(), v.hex()] for k, v in sorted(db.items())]}))
    finally:
        db.close()


if __name__ == "__main__":
    main()
