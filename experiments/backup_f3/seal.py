"""Seal F3 source/spec/evidence hashes; never reads keys or personal histories."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--spec',type=Path,required=True)
    parser.add_argument('--runtime-sha',required=True)
    args=parser.parse_args(); os.umask(0o077)
    repo=Path(__file__).resolve().parents[2]
    runtime=subprocess.check_output(['git','rev-parse',args.runtime_sha+'^{commit}'],cwd=repo,text=True).strip()
    paths=subprocess.check_output(['git','ls-files','-z'],cwd=repo).decode().split('\0')
    selected=[p for p in paths if p and (p.startswith(('csl_backup','experiments/backup_f3/',
        'tests/test_backup','docs/BACKUP')) or p in ('csl_secrets.py','tests/test_secrets.py',
        'csl_capabilities.py','codex_sessions.py','csl_version.py','README.md','docs/PROVIDER_MATRIX.md'))]
    # Runtime files must still be exactly the tested Git blobs, even when a
    # following documentation/seal utility commit names the final handoff.
    runtime_files=[p for p in selected if p.startswith('csl_backup') or p in ('csl_secrets.py','csl_capabilities.py')]
    for name in runtime_files:
        blob=subprocess.check_output(['git','show',runtime+':'+name],cwd=repo)
        if hashlib.sha256(blob).hexdigest()!=digest(repo/name):
            raise RuntimeError('Runtime differs from fixed tested commit: '+name)
    root=args.evidence.resolve()
    value={'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),
        'runtime_tested_head':runtime,'base_f2':'6003a723097134988eec85ea1ad07c0befb1c084',
        'sources':{p:digest(repo/p) for p in selected},
        'artifacts':{str(p.relative_to(root)):digest(p) for p in sorted(root.rglob('*'))
                     if p.is_file() and p.name!='SEALED.json'},
        'spec':{str(p.relative_to(args.spec)):digest(p) for p in sorted(args.spec.glob('*.md'))},
        'scope':'F3 future-only candidate, owner review pending. Final real-age local probe and full suite fixed SHA; in-memory fake transport/control, zero GitHub calls. No historical re-encryption/native-sanitized/F4+.'}
    target=root/'SEALED.json'; target.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n'); target.chmod(0o600)
    print('F3 sealed:',target,'sources:',len(value['sources']),'artifacts:',len(value['artifacts']))


if __name__=='__main__': main()
