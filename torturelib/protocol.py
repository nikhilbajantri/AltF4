"""Black-box CLI access; no storage imports or file-format knowledge."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
STEP_TIMEOUT = 120  # each post-kill open/check/dump; recovery of 1M keys takes ~1 s


class ToolError(Exception):
    pass


def environment():
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1")
    env.pop("KVDB_CRASH", None)
    return env


def cli(*args, env=None, text=None, timeout=30):
    return subprocess.run([sys.executable, str(ROOT / "kvdb"), *map(str, args)],
                          cwd=ROOT, env=environment() if env is None else env,
                          input=text, text=True, capture_output=True, timeout=timeout)


def decode(token):
    return bytes.fromhex(token[4:]) if token.startswith("hex:") else token.encode("utf-8")


def recovered(path):
    outputs = {}
    for action in ("open", "check", "dump"):
        try:
            result = cli(action, path, timeout=STEP_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise ToolError("%s timed out after %d s on %s" % (action, STEP_TIMEOUT, path)) from None
        if result.returncode:
            raise AssertionError("%s failed: %s %s" % (action, result.stdout[:300], result.stderr[:300]))
        outputs[action] = result.stdout
    if outputs["check"].strip() != "OK":
        raise AssertionError("check after recovery: " + outputs["check"].strip())
    actual = {}
    for line in outputs["dump"].splitlines():
        key, value = line.split("\t")
        key = decode(key)
        if key in actual:
            raise ValueError("duplicate dump key")
        actual[key] = decode(value)
    return actual
