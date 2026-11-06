"""Read-only, frame-by-frame inspection."""
import argparse
from src.scan import Frame, iter_frames
from src.serve import encode_token


def inspect(path):
    status = 0
    for record in iter_frames(path):
        if isinstance(record, Frame):
            print("offset=%d length=%d crc=%s ops=%s keys=%s" %
                  (record.offset, record.length, "OK" if record.status == "ok" else "BAD",
                   record.nops, ",".join(encode_token(k) for _, k, _ in record.ops[:5])))
            status |= record.status == "corrupt"
        else:
            print("end=%d torn_tail_bytes=%d" % (record.offset, record.tail_bytes))
            status |= record.bad_header or record.later_frame is not None
    return int(status)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    return inspect(parser.parse_args(argv).path)
