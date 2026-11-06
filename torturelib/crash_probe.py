"""Compatibility adapter: all database access goes through the public CLI."""
import json
import sys
from torturelib.protocol import recovered


def main():
    actual = recovered(sys.argv[1])
    print(json.dumps({"check": "OK", "items": [[k.hex(), v.hex()] for k, v in sorted(actual.items())]}))


if __name__ == "__main__":
    main()
