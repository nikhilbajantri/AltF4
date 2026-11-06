"""Bounded memory review; allocates at most 40 MiB of unique input values."""
import json
import os
from pathlib import Path
import sys
import tempfile
import tracemalloc
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.engine import KVDB
from src.errors import DiskFull
from tests.util import test_dir

results=[]
for mib in (8, 40):
    # Construct unique caller-owned data before measuring encoder overhead.
    ops=[('put', ('k%05d' % i).encode(), bytes([i%251])*65536) for i in range(mib*16)]
    for capped in (False, True):
        with tempfile.TemporaryDirectory(prefix='batch-memory-',dir=test_dir()) as directory:
            db=KVDB(str(Path(directory)/'data.db'),max_bytes=1024 if capped else None,auto_compact=False)
            tracemalloc.start()
            try:
                db.batch(ops)
                result='saved'
            except DiskFull:
                result='DISKFULL'
            current,peak=tracemalloc.get_traced_memory()
            tracemalloc.stop()
            db.close()
            if not capped:
                reopened=KVDB(str(Path(directory)/'data.db'))
                assert dict(reopened.items())=={op[1]:op[2] for op in ops}
                reopened.close()
            results.append(dict(input_mib=mib,capped=capped,result=result,
                                encoder_peak_bytes=peak,caller_values_excluded=True))
print(json.dumps(dict(python=sys.version.split()[0],results=results),indent=2))
