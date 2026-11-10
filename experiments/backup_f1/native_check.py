"""Read-only native reader/picker check after a synthetic product restore in B."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--received',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    root=args.out.parent
    result=json.loads(args.received.read_bytes())
    schema=root/'protocol-schema'
    subprocess.run(['codex','app-server','generate-json-schema','--out',str(schema)],
                   env=dict(os.environ),check=True,capture_output=True,timeout=30)
    source_kinds=[]
    def walk(value):
        nonlocal source_kinds
        if isinstance(value,dict):
            for key,child in value.items():
                if key=='ThreadSourceKind' and isinstance(child,dict) and 'enum' in child:
                    source_kinds=child['enum']
                walk(child)
        elif isinstance(value,list):
            for child in value:
                walk(child)
    for path in schema.rglob('*.json'):
        walk(json.loads(path.read_bytes()))
    if not source_kinds:
        raise RuntimeError('Could not obtain native source filter enum from pinned CLI')
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tests'))
    from test_clone_visibility import app_server
    with app_server(root,dict(os.environ)) as call:
        reads=[]
        for entry in result['sessions']:
            if entry['validation']=='quarantined':
                home=Path(os.environ['CODEX_HOME'])
                path=home/'csl-backup/quarantine'/ (entry['uuid']+'.jsonl')
                receipts=[json.loads(p.read_bytes()) for p in (home/'csl-backup/receipts').glob('*.json')]
                receipt=next(row for row in receipts if row['installed_uuid']==entry['uuid'])
                import hashlib
                digest=hashlib.sha256(path.read_bytes()).hexdigest()
                if digest!=receipt['member_sha256'] or digest!=receipt['installed_sha256']:
                    raise RuntimeError('Quarantined evidence differs from validated source member')
                reads.append({'uuid':entry['uuid'],'state':entry['state'],'read_accepted':None,
                              'native':'not applicable: quarantined exact evidence'})
                continue
            reply=call('thread/read',{'threadId':entry['uuid'],'includeTurns':True})
            reads.append({'uuid':entry['uuid'],'state':entry['state'],'read_accepted':bool(reply)})
        common={'limit':100,'modelProviders':[],'sortKey':'recency_at','useStateDbOnly':False}
        active=call('thread/list',{**common,'archived':False,'sourceKinds':['cli','vscode']})
        all_active=call('thread/list',{**common,'archived':False,'sourceKinds':source_kinds})
        archived=call('thread/list',{**common,'archived':True,'sourceKinds':source_kinds})
    interactive={row['id'] for row in active['data']}
    every_active={row['id'] for row in all_active['data']}
    archives={row['id'] for row in archived['data']}
    for entry in result['sessions']:
        sid=entry['uuid']
        if entry['validation']=='quarantined':
            if sid in interactive or sid in every_active or sid in archives:
                raise RuntimeError('Quarantined metadata-only copy appeared in native picker')
            continue
        if entry['state']=='archived':
            if sid not in archives or sid in interactive:
                raise RuntimeError('Archived visibility not preserved by native reader')
        elif entry['state']=='agent':
            if sid not in every_active or sid in interactive:
                raise RuntimeError('Structured agent source visibility not preserved')
        elif sid not in interactive:
            raise RuntimeError('Interactive restored history not in native picker')
    args.out.write_text(json.dumps({'reads':reads,'source_enum':source_kinds,'visibility_passed':True,
        'network':'disabled by caller','generation':'not performed','model_recall':'not tested'},indent=2)+'\n')
    args.out.chmod(0o600)


if __name__=='__main__':
    main()
