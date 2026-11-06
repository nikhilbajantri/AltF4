"""Run 7 modes x 2 seeds x 500 rounds, retaining evidence and storage reserves."""
import argparse
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

MODES = ('default', 'large-values', 'large-batch', 'recovery-crash',
         'compaction', 'disk-full', 'crashpoints')


def check_space(paths, reserve):
    for path in paths:
        free = shutil.disk_usage(path).free
        if free < reserve * 1024**3:
            raise OSError('Low space on %s: %.2f GiB; reserve %.2f GiB' %
                          (path, free / 1024**3, reserve))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path.home()/'tmp_test/final_gate')
    parser.add_argument('--host-storage-dir', type=Path, action='append', default=[])
    parser.add_argument('--reserve-gib', type=float, default=20)
    parser.add_argument('--iterations', type=int, default=500)
    parser.add_argument('--seeds', nargs='+', type=int, default=[2026110603, 2026110604])
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args(argv)
    if sys.platform != 'linux':
        parser.error('Run in Linux/Ubuntu.')
    if min(args.iterations, args.workers) < 1 or not 0 < args.reserve_gib < float('inf'):
        parser.error('Iterations, workers and reserve must be positive and finite.')
    if len(set(args.seeds)) != len(args.seeds):
        parser.error('Seeds must be unique.')
    if 'microsoft' in os.uname().release.lower() and not args.host_storage_dir:
        parser.error('WSL needs --host-storage-dir for the Windows volume containing its virtual disk.')
    root = Path(__file__).resolve().parents[1]
    args.data_dir.mkdir(parents=True, exist_ok=True)
    volumes = [args.data_dir, *args.host_storage_dir]
    check_space(volumes, args.reserve_gib)
    directory = Path(tempfile.mkdtemp(prefix='gate-', dir=args.data_dir))
    print('GATE_EVIDENCE=' + str(directory), flush=True)
    source_files = [p for package in ('src', 'torturelib') for p in (root/package).glob('*.py')]
    source_files += [root/'tools/run_final_gate.py', root/'kvdb', root/'torture']
    sources = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}
    manifest = dict(start=datetime.now(timezone.utc).isoformat(), iterations=args.iterations,
                    seeds=args.seeds, sources=sources, results=[], reserve_gib=args.reserve_gib,
                    checked_volumes=[str(v) for v in volumes], workers=args.workers,
                    commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip())
    def save():
        temp = directory/'manifest.tmp'
        with temp.open('w') as f:
            json.dump(manifest, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        temp.replace(directory/'manifest.json')
    save()
    abort = threading.Event()

    def run(mode, seed):
        label = '%s-%d' % (mode, seed)
        log = directory/(label+'.log')
        started = time.monotonic()
        result = dict(mode=mode, seed=seed, log=str(log), **{'pass': False, 'exit': None})
        proc = None
        try:
            if abort.is_set():
                raise RuntimeError('Cancelled because another task failed.')
            check_space(volumes, args.reserve_gib)
            command = [sys.executable, '-B', str(root/'torture'), '--mode', mode, '--seed', str(seed),
                       '--iterations', str(args.iterations), '--data-dir', str(directory/label),
                       '--compress-log', '--min-free-gib', str(args.reserve_gib)]
            for v in args.host_storage_dir:
                command += ['--host-storage-dir', str(v)]
            with log.open('w') as output:
                proc = subprocess.Popen(command, cwd=root, stdout=output, stderr=subprocess.STDOUT,
                                        start_new_session=True)
                while proc.poll() is None:
                    if abort.wait(1):
                        raise RuntimeError('Stopped because another task failed.')
                    check_space(volumes, args.reserve_gib)
                    if time.monotonic()-started > max(300, args.iterations*15):
                        raise TimeoutError('Gate task exceeded its time limit.')
            result['exit'] = proc.returncode
            with log.open() as f:
                tail = list(deque(f, maxlen=6))
            result['last_lines'] = [s.rstrip() for s in tail]
            result['summary'] = next((s.rstrip() for s in tail if s.startswith('SUMMARY ')), '')
            result['pass'] = proc.returncode == 0 and ('PASS=%d/%d ' % (args.iterations,args.iterations)) in result['summary']
            if not result['pass']:
                abort.set()
        except Exception as exc:
            abort.set()
            result['error'] = '%s: %s' % (type(exc).__name__, exc)
        finally:
            if proc is not None:
                # Kill the owned process group, including children left by a failed runner.
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
                result['exit'] = proc.returncode
            result['seconds'] = round(time.monotonic()-started, 2)
        return result

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run, mode, seed) for seed in args.seeds for mode in MODES]
        for future in as_completed(futures):
            result = future.result()
            manifest['results'].append(result)
            save()
            print(json.dumps(result), flush=True)
    manifest['end'] = datetime.now(timezone.utc).isoformat()
    manifest['sources_unchanged'] = all(hashlib.sha256((root/n).read_bytes()).hexdigest()==d for n,d in sources.items())
    manifest['success'] = manifest['sources_unchanged'] and all(r['pass'] for r in manifest['results'])
    save()
    print('GATE_RESULT=' + str(manifest['success']), flush=True)
    return 0 if manifest['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
