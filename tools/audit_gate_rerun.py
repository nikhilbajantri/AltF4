"""Audit a completed gate before publishing its rerun report."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path

MODES={'default','large-values','large-batch','recovery-crash','compaction','disk-full','crashpoints'}
POINTS={'torn_write','before_write','after_write','after_fsync','after_return','init_before_rename',
        'recovery_mid_scan','recovery_before_truncate','recovery_after_truncate','compact_mid_copy',
        'compact_before_rename','compact_after_rename','compact_after_swap','close_mid'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def audit(directory, root):
    manifest=json.loads((directory/'manifest.json').read_text())
    require(manifest.get('success') and manifest.get('sources_unchanged'), 'Gate is incomplete or failed')
    require(manifest.get('iterations')==500, 'Expected 500 iterations')
    seeds=manifest['seeds']
    require(len(seeds)==2 and len(set(seeds))==2,'Expected two distinct seeds')
    results=manifest['results']
    require(len(results)==14 and {(r['mode'],r['seed']) for r in results}==
            {(m,s) for m in MODES for s in seeds},'Missing, extra or duplicate mode/seed results')
    for name,digest in manifest['sources'].items():
        require(hashlib.sha256((root/name).read_bytes()).hexdigest()==digest,'Source changed: '+name)
    for result in results:
        require(result['pass'] and result['exit']==0 and 'PASS=500/500 ' in result['summary'],
                'Unsuccessful result: '+str(result))
        logs=list((directory/('%s-%d'%(result['mode'],result['seed']))).glob('*/oracle.log.gz'))
        require(len(logs)==1,'Expected exactly one transcript for '+str(result))
        path=logs[0]
        passed=[]; kills=shared=0; point_counts=Counter(); hit_counts=Counter()
        with gzip.open(path,'rt') as source:
            for line in source:
                header=line[:160]
                if '"event": "SENT"' in header:
                    operations=line.count('["put",')+line.count('["del",')
                    shared+=operations>1 and ('"'+b'shared/'.hex()) in line
                    continue
                if '"event": "SUBMIT"' in header:
                    event=json.loads(line)
                    if event.get('point'):
                        hit_counts['%s:%s'%(event['point'],event.get('hits',1))]+=1
                    continue
                event=json.loads(line)
                require(event['event'] not in ('FAIL','TOOL_ERROR'),'Error record in '+str(path))
                if event['event']=='PASS':
                    passed.append(event['iteration'])
                elif event['event']=='KILL':
                    kills+=1
                elif event['event']=='RESULT' and event.get('returncode')==-9:
                    kills+=1
                    point_counts[event['point']]+=1
        require(len(passed)==500 and set(passed)==set(range(1,501)), 'Incomplete round records: '+str(path))
        if result['mode']=='crashpoints':
            require(set(point_counts)==POINTS,'Incomplete named crash-point coverage')
        if result['mode']=='compaction':
            require(point_counts==Counter({p:125 for p in POINTS if p.startswith('compact_')}),
                    'Incorrect compaction hook counts')
        digest=hashlib.sha256()
        with path.open('rb') as source:
            for block in iter(lambda:source.read(1024*1024),b''):
                digest.update(block)
        result['transcript_audit']=dict(path=str(path),sha256=digest.hexdigest(),
            compressed_bytes=path.stat().st_size,pass_records=len(passed),kill_records=kills,
            shared_batches_sent=shared,crashpoint_kills=dict(point_counts),submitted_hooks=dict(hit_counts))
        print('Audited %s seed=%d: 500 PASS records'%(result['mode'],result['seed']),flush=True)
    manifest['audited_at']=datetime.now(timezone.utc).isoformat()
    return manifest


def publish(manifest, directory, root):
    results=sorted(manifest['results'],key=lambda r:(r['mode'],r['seed']))
    kills=sum(r['transcript_audit']['kill_records'] for r in results)
    shared=sum(r['transcript_audit']['shared_batches_sent'] for r in results)
    rows=['| %s | %s | 500/500 | %s | %.1f |'%(r['mode'],r['seed'],
           r['transcript_audit']['kill_records'],r['seconds']) for r in results]
    report=f'''# Final crash-gate rerun after memory, error and scanner fixes

All **7,000 rounds passed**, with zero failed or missing rounds. All 14 transcripts independently contain exactly 500 distinct PASS records for iterations 1 through 500. No TOOL_ERROR or FAIL records were accepted. Source hashes remained unchanged during the gate and matched the checkout during this audit.

Tested commit: `{manifest['commit']}`. Seeds: {manifest['seeds']}. Build and the pre-gate full automated suite passed; exact suite output is in [the evidence](docs/evidence/final_fixes_full_suite.txt).

## Fixes included

- [Large-batch memory](docs/batch_memory_review.md): size preflight, bounded encoding chunks, bounded operation collection, rollback after allocation failure. Controlled 40 MiB batch: roughly 80 MiB to 8.1 MiB extra encoding memory.
- [Uncertain writes](docs/uncertain_write_report.md): double I/O failures now report UNCERTAIN and block later mutations; callers reconcile after reopening. Unknown outcomes are never counted as passing crash checks.
- [Scanner boundaries](docs/scanner_fix_report.md): embedded payload records no longer become false evidence of later records. Tests retain actual later-record detection and read-only inspection.

Main was fetched and reviewed before the final fix; it had no incoming changes beyond those already in feat-arsh. The fix commit preceded this run. This report is a later documentation change.

## Gate results

Seven modes x two seeds x 500 rounds = 7,000 rounds. Default, large-values and large-batch use two stop-and-wait writers with random kill delays. Recovery-crash, compaction, disk-full and crashpoints use targeted scenarios. Crashpoints uses the current seeded hook/hit selection. All 14 named hooks were verified for each seed; compaction exercised its four locations 125 times per seed.

| Mode | Seed | Passed | Verified SIGKILL exits | Seconds |
|---|---|---|---|---|
'''+ '\n'.join(rows)+f'''

Verified SIGKILL exits: **{kills}**. Submitted shared batches: **{shared}**. Some rounds contain multiple kills, so the kill count exceeds the round count. Submission does not prove that a request reached disk; observed ACKs and the full recovered-map check determine the required outcome.

## Evidence and reproduction

Raw evidence directory: `{directory}`. The [audited manifest](docs/final_gate_rerun_manifest.json) contains source hashes, timestamps, per-run summaries, compressed transcript checksums, round counts and hook counts. Files remain on the Linux filesystem in Ubuntu's virtual disk on D:. Lossless gzip transcripts and actual host-volume free-space monitoring preserve a 20 GiB reserve. No earlier campaign rounds were added to this total.

Gate start (UTC): {manifest['start']}. End (UTC): {manifest['end']}.

```bash
make build
python3 -B -m unittest -q
python3 -B tools/run_final_gate.py --seeds {' '.join(map(str,manifest['seeds']))} --host-storage-dir /mnt/d --host-storage-dir /mnt/c
python3 -B tools/audit_gate_rerun.py /path/printed/by/gate
```

The audit validates the entire campaign before writing either report file. Reusing a seed reproduces planned operations and delays; thread scheduling may produce different histories. Adapt host volumes to the actual location of the WSL disk.

## Limits and remaining release work

These are process-crash, configured-cap and injected-failure checks. Physical power cuts, arbitrary media failures and dishonest hardware are outside this evidence. Damaged length fields can still hide later records from the read-only scanner. Caller inputs and queued batches still require RAM; the encoding improvement is not a global memory quota. Pathological oracle searches fail qualification rather than approximate a pass.

Remaining release tasks are demo-machine/offline validation, final proof/document reconciliation and rehearsal. The earlier [test-history report](FINAL_TEST_REPORT.md) remains historical evidence for its own source version, including the first interrupted campaign and storage recovery.
'''
    (root/'docs/final_gate_rerun_manifest.json').write_text(json.dumps(manifest,indent=2))
    (root/'FINAL_GATE_RERUN_REPORT.md').write_text(report)
    print('Verified 7000 rounds, %d kills, %d shared batches'%(kills,shared),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    manifest=audit(args.directory.resolve(),root)
    publish(manifest,args.directory.resolve(),root)
