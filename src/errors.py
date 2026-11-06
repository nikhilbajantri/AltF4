"""Engine error classes shared by the real engine and the fake engine.

Owner: Nikhil
"""


class DiskFull(Exception):
    """The frame would push the file past max_bytes; nothing was written."""


class PoisonedError(Exception):
    """A write or fsync failed earlier; the handle refuses further writes."""


class LockedError(Exception):
    """Another process holds <path>.lock."""
