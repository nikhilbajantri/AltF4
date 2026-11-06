"""Engine error classes shared by the real engine and the fake engine.

Owner: Nikhil
"""


class DiskFull(Exception):
    """The frame would push the file past max_bytes; nothing was written."""


class PoisonedError(Exception):
    """A write or fsync failed earlier; the handle refuses further writes."""


class LockedError(Exception):
    """Another process holds <path>.lock."""


class CorruptError(Exception):
    """A frame's CRC is valid but its content is malformed (not a torn tail)."""

    def __init__(self, offset, reason):
        super().__init__("offset %d: %s" % (offset, reason))
        self.offset = offset
        self.reason = reason
