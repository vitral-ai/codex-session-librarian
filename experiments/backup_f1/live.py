"""Bounded synthetic F1/E1 validation. Never a general real-history backup runner."""

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

from csl_backup_core import canonical, hash_file, save
from csl_transfer import TransferError
from csl_backup_crypto import Age, BackupPolicyError
from csl_backup_engine import Backup
from csl_backup_store import GitHub
from experiments.backup_f0.profiles import REPO, fixture
from experiments.backup_f1.transport import reader_broker

DESTINATION = 'manunruks/csl-backup-e2e-20261109'
REPO_ID = 1452127356
F0_REPO = 'manunruks/csl-backup-validation-20261109'


def inventory():
    result=[]
    for repo in (F0_REPO,DESTINATION):
        rows=json.loads(subprocess.check_output(['gh-manunruks','api','repos/'+repo+'/releases?per_page=100']))
        result.extend({'repo':repo,'id':r['id'],'tag':r['tag_name'],
                       'assets':[{'id':a['id'],'name':a['name'],'size':a['size']} for a in r['assets']]} for r in rows)
    return result


class BudgetStore(GitHub):
    def __init__(self,out):
        self.out=out
        super().__init__(DESTINATION,expected_id=REPO_ID,executable='gh-manunruks')
    def request(self,method,suffix,body=None,*,upload=None):
        if method=='POST' and (suffix=='/releases' or upload is not None):
            rows=inventory()
            assets=[a for r in rows for a in r['assets']]
            if (len(rows)+(suffix=='/releases')>40 or len(assets)+(upload is not None)>80 or
                    sum(a['size'] for a in assets)+(Path(upload).stat().st_size if upload else 0)>50*1024**2):
                raise RuntimeError('Accumulated laboratory budget exceeded before mutation')
            save(self.out/'ledger.json',{'phase':'F1','total_limits':{'releases':40,'assets':80,'bytes':50*1024**2},
                                        'before':rows,'next':{'method':method,'suffix':suffix}})
        return super().request(method,suffix,body,upload=upload)


def isolated_csl(home):
    name='synthetic_csl_'+uuid.uuid4().hex
    previous=os.environ.get('CODEX_HOME')
    os.environ['CODEX_HOME']=str(home)
    try:
        spec=importlib.util.spec_from_file_location(name,REPO/'codex_sessions.py')
        module=importlib.util.module_from_spec(spec)
        sys.modules[name]=module
        spec.loader.exec_module(module)
        return module
    finally:
        if previous is None:
            os.environ.pop('CODEX_HOME',None)
        else:
            os.environ['CODEX_HOME']=previous


def cli(module,arguments,identity=None):
    output=io.StringIO()
    stream=io.TextIOWrapper(io.BytesIO(identity or b''))
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdin(stream) if hasattr(contextlib,'redirect_stdin') else contextlib.nullcontext():
        old=sys.stdin
        sys.stdin=stream
        try:
            args=module.build_parser().parse_args(arguments)
            args.func(args)
        finally:
            sys.stdin=old
    return json.loads(output.getvalue())


def cold_phase(out,a,b,age_dir,external_key,token,expected_checkpoint):
    base=['bwrap','--die-with-parent','--ro-bind','/','/','--dev-bind','/dev','/dev','--proc','/proc',
        '--tmpfs','/tmp','--tmpfs',str(a),'--bind',str(b),str(b),
        '--setenv','HOME',str(b/'home'),'--setenv','CODEX_HOME',str(b/'codex'),
        '--setenv','CSL_BACKUP_TEST_SOCKET',str(b/'transport.sock')]
    common=['--repo',DESTINATION,'--age-bin',str(age_dir/'age'),
            '--github-cli',str(REPO/'experiments/backup_f1/gh_reader.py'),'--json']
    env={'PATH':os.environ['PATH'],'LANG':'C.UTF-8'}
    def invoke(arguments,identity=None):
        command=base+[sys.executable,str(REPO/'codex_sessions.py'),'backup',*arguments,*common]
        result=subprocess.run(command,input=identity,capture_output=True,env=env,timeout=300)
        if result.returncode:
            save(out/'cold-failure.json',{'exit':result.returncode,'arguments':arguments,
                 'stderr':result.stderr.decode(errors='replace')[-1500:]})
            raise RuntimeError('F1 cold CLI failed; no blind retry of writes')
        try:
            return json.loads(result.stdout)
        except ValueError:
            save(out/'cold-invalid-output.json',{'exit':result.returncode,
                'stdout':result.stdout.decode(errors='replace')[:4096],
                'reason':'structured stdout invalid; synthetic output only, no identity echoed'})
            raise RuntimeError('CLI --json stdout was not one JSON value') from None
    with reader_broker(b/'transport.sock',token,DESTINATION) as counts:
        discovered=invoke(['discover'])
        choices=[(source['committed_at'],set_id,source_id,source['latest_complete'])
                 for set_id,info in discovered['sets'].items() for source_id,source in info['sources'].items()
                 if source.get('latest_complete')]
        # Test driver selects an explicit source FROM REMOTE metadata. The CLI
        # never implements a global latest across sources, and no A IDs are input.
        _,set_id,source_id,checkpoint=max(choices)
        if checkpoint!=expected_checkpoint:
            raise RuntimeError('Concurrent test checkpoint changed; select explicitly rather than guessing')
        selection=['--set',set_id,'--source',source_id]
        arguments=['restore','latest',*selection,'--cwd',str(b/'project'),'--identity-stdin']
        recovered=invoke(arguments,external_key)
        again=invoke(arguments,external_key)
        if [v['uuid'] for v in recovered['sessions']]!=[v['uuid'] for v in again['sessions']]:
            raise RuntimeError('Repeated restore changed UUIDs')
        save(b/'received.json',recovered)
        native_command=base+['--unshare-net',sys.executable,'-m','experiments.backup_f1.native_check',
            '--received',str(b/'received.json'),'--out',str(b/'native.json')]
        native=subprocess.run(native_command,capture_output=True,env=env,timeout=90)
        if native.returncode:
            save(out/'native-failure.json',{'exit':native.returncode,
                                           'stderr':native.stderr.decode(errors='replace')[-2000:]})
            raise RuntimeError('Native reader/visibility check failed; no paid inference performed')
        save(out/'native.json',json.loads((b/'native.json').read_bytes()))
        # An invalid identity is a read-only failure; no existing installed copy changes.
        before={str(p):hash_file(p) for p in (b/'codex').rglob('*.jsonl')}
        wrong=base+[sys.executable,str(REPO/'codex_sessions.py'),'backup',*arguments,*common]
        rejected=subprocess.run(wrong,input=b'NOT-A-PRIVATE-IDENTITY\n',capture_output=True,env=env,timeout=90)
        after={str(p):hash_file(p) for p in (b/'codex').rglob('*.jsonl')}
        if rejected.returncode!=3 or before!=after:
            raise RuntimeError('Wrong key affected copies or did not fail as policy error')
        cached=invoke(['status','--cached',*selection])
        if cached['last_attempt']['result']!='failed' or cached['remote']!='unknown; not queried':
            raise RuntimeError('Cached status hid the recent failed attempt')
        save(out/'cold.json',{'result':recovered,'repeat_same_uuids':True,'A_hidden':True,'new_HOME_CODEX_HOME':True,
            'source_selected_from_remote_discovery':True,'external_only_identity':True,'operational_private_in_B':False,
            'transport':dict(counts),'wrong_key_exit':rejected.returncode,'wrong_key_preserved_existing_copies':True,
            'cached_recent_failure_visible':True,'installed_sessions':len(recovered['sessions']),
            'protected_jsonl_files':len(before),
            'backup_config_adopted':(b/'codex/csl-backup/sets').exists()})
        return recovered


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--age-dir',type=Path,required=True)
    parser.add_argument('--identity-helper',type=Path,required=True)
    parser.add_argument('--portable',action='store_true',help='Also test explicit portable scrub on the controlled fixture set.')
    args=parser.parse_args()
    os.umask(0o077)
    out=args.out.resolve()
    out.mkdir(parents=True,mode=0o700,exist_ok=False)
    age=Age(str(args.age_dir/'age'))
    keys,recipients=[],[]
    for _ in range(2):
        identity=subprocess.check_output([str(args.age_dir/'age-keygen')],stderr=subprocess.DEVNULL)
        keys.append(identity)
        recipients.append(subprocess.check_output([str(args.age_dir/'age-keygen'),'-y'],input=identity,stderr=subprocess.DEVNULL).decode().strip())
    spec=importlib.util.spec_from_file_location('own_transport',args.identity_helper)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    own=module.Client()
    try:
        with tempfile.TemporaryDirectory(prefix='csl-f1-') as runtime:
            runtime=Path(runtime)
            a,b=runtime/'A',runtime/'B'
            a.mkdir(mode=0o700)
            b.mkdir(mode=0o700)
            (b/'home').mkdir(mode=0o700)
            (b/'project').mkdir(mode=0o700)
            originals=[]
            parent=str(uuid.uuid4())
            for case in ('text','pending','opaque','compaction','archived','structured-agent','metadata-only'):
                sid=parent if case=='text' else str(uuid.uuid4())
                data=fixture(case if case in ('pending','opaque','compaction') else 'text',sid)
                if case=='metadata-only':
                    data=data.splitlines(keepends=True)[0]
                if case=='structured-agent':
                    rows=[json.loads(line) for line in data.splitlines()]
                    rows[0]['payload']['source']={'subagent':{'thread_spawn':{'parent_thread_id':parent,'depth':1,
                                                                          'agent_nickname':'Synthetic','agent_role':'worker'}}}
                    data=b''.join((json.dumps(row)+'\n').encode() for row in rows)
                folder=a/('archived_sessions' if case=='archived' else 'sessions/2026/11/10')
                folder.mkdir(parents=True,exist_ok=True)
                path=folder/('rollout-2026-11-10T00-00-00-'+sid+'.jsonl')
                path.write_bytes(data)
                originals.append((path,hash_file(path),case))
            source=isolated_csl(a)
            store=BudgetStore(out)
            backup=Backup(source,store,age)
            initialized=backup.initialize(set_name='F1 synthetic native',source_name='Synthetic A',profile='native-age-v1',
                policy='stop',recipients=recipients,key_reference='stdin',include_agents=True)
            config=backup.load(initialized['set_id'])
            # This is the product engine and real GitHub/age, not the F0 fake adapter.
            result=backup.run(config,keys[0])
            save(out/'run.json',result)
            save(out/'source-hashes.json',{'unchanged':all(hash_file(path)==digest for path,digest,_ in originals),
                'fixtures':[{'case':case,'sha256':digest,'bytes':path.stat().st_size} for path,digest,case in originals]})
            cold_phase(out,runtime,b,args.age_dir,keys[1],own._token,result['checkpoint_id'])
            if args.portable:
                marker='SYNTHETIC-F1-PASSWORD-DO-NOT-USE'
                path=originals[0][0]
                addition={'timestamp':'2026-11-10T00:00:00Z','type':'response_item','payload':{
                    'type':'message','role':'user','content':[{'type':'input_text','text':'password="'+marker+'"'}]}}
                with path.open('ab') as stream:
                    stream.write(canonical(addition)+b'\n')
                before=inventory()
                try:
                    backup.run(config,keys[0],dry_run=True)
                except BackupPolicyError:
                    pass
                else:
                    raise RuntimeError('stop policy failed to block controlled secret')
                if inventory()!=before:
                    raise RuntimeError('Blocked stop policy mutated remote inventory')
                phase=out/'portable'
                phase.mkdir(mode=0o700)
                portable=backup.initialize(set_name='F1 synthetic portable',source_name='Synthetic portable A',
                    profile='portable-age-v1',policy='scrub',recipients=recipients,key_reference='stdin',include_agents=True)
                portable_config=backup.load(portable['set_id'])
                before=inventory()
                try:
                    backup.run(portable_config,keys[0],dry_run=True)
                except TransferError:
                    pass
                else:
                    raise RuntimeError('Portable profile silently represented unsupported empty source')
                if inventory()!=before:
                    raise RuntimeError('Nonrepresentable portable dry-run wrote remotely')
                # Explicit separate representable fixture set, not an exclusion in
                # the product or a silent change to native's coverage.
                ap=runtime/'AP'
                for source_path,_,case in originals:
                    if case=='metadata-only':
                        continue
                    target=ap/source_path.relative_to(a)
                    target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(source_path,target)
                portable_backup=Backup(isolated_csl(ap),store,age)
                portable=portable_backup.initialize(set_name='F1 portable representable subset',source_name='Synthetic AP',
                    profile='portable-age-v1',policy='scrub',recipients=recipients,key_reference='stdin',include_agents=True)
                portable_config=portable_backup.load(portable['set_id'])
                hashes={str(p):hash_file(p) for p,_,_ in originals}
                portable_result=portable_backup.run(portable_config,keys[0])
                save(phase/'run.json',portable_result)
                recovered=cold_phase(phase,runtime,b,args.age_dir,keys[1],own._token,portable_result['checkpoint_id'])
                for item in recovered['sessions']:
                    files=list((b/'codex').rglob('*'+item['uuid']+'.jsonl'))
                    if len(files)!=1 or marker.encode() in files[0].read_bytes():
                        raise RuntimeError('Portable scrub retained the controlled secret or lost its installed copy')
                save(phase/'policy.json',{'stop_blocked_before_remote_write':True,'scrub_output_removed_marker':True,
                    'sources_intact_after_scrub':all(hash_file(Path(p))==digest for p,digest in hashes.items()),
                    'metadata_only_explicitly_nonrepresentable_before_write':True,
                    'portable_scope':'separate six-source representable synthetic dataset; native set retains all seven',
                    'note':'fixture intentionally gained a synthetic credential AFTER native trial; no real secrets'})
            rows=inventory()
            save(out/'ledger.json',{'phase':'F1','total_limits':{'releases':40,'assets':80,'bytes':50*1024**2},
                'inventory':rows,'releases':len(rows),'assets':sum(len(r['assets']) for r in rows),
                'bytes':sum(asset['size'] for row in rows for asset in row['assets']),'no_delete':True})
    finally:
        own.close()
        keys.clear()
        try:
            rows=inventory()
            save(out/'ledger.json',{'phase':'F1','total_limits':{'releases':40,'assets':80,'bytes':50*1024**2},
                'inventory':rows,'releases':len(rows),'assets':sum(len(r['assets']) for r in rows),
                'bytes':sum(asset['size'] for row in rows for asset in row['assets']),'no_delete':True,
                'scope':'final remote inventory; NOT a declaration that validation passed'})
        except Exception as error:
            save(out/'inventory-observation-failed.json',{'reason':type(error).__name__,'remote_state':'unknown'})
    print('F1 live evidence:',out)


if __name__=='__main__':
    main()
