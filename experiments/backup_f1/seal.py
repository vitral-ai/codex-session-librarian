"""Hash F1 sources and private evidence without exposing credentials or histories."""

import argparse
import hashlib
from pathlib import Path
import subprocess

from experiments.backup_f0.profiles import REPO
from experiments.backup_f0.run import write


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--spec',type=Path,required=True)
    args=parser.parse_args()
    files=subprocess.check_output(['git','ls-files','-z'],cwd=REPO).decode().split('\0')
    selected=[name for name in files if name and (name.startswith(('csl_backup','experiments/backup_f1/','tests/test_backup','docs/BACKUP')) or
        name in ('codex_sessions.py','csl_capabilities.py','csl_secrets.py','csl_version.py','README.md','CHANGELOG.md','docs/PROVIDER_MATRIX.md'))]
    sources={name:hashlib.sha256((REPO/name).read_bytes()).hexdigest() for name in selected}
    root=args.evidence.resolve()
    artifacts={str(path.relative_to(root)):hashlib.sha256(path.read_bytes()).hexdigest()
               for path in root.rglob('*') if path.is_file() and path.name!='SEALED.json'}
    manifest={'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
        'runtime_tested_head':'3547d7b','base_f0':'32322850b7b341048448fd6d03cfacd82b3babd2',
        'sources':sources,'artifacts':artifacts,
        'spec':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in args.spec.glob('*.md')},
        'scope':'F1 manual; live pre-freeze working tree is not claimed to match final SHA; full final tests are fixed-SHA'}
    write(root,'SEALED.json',manifest)
    print('F1 sealed evidence:',root/'SEALED.json')


if __name__=='__main__':
    main()
