"""Local real-age epoch recovery. In-memory fake transport/control: zero GitHub calls."""
import argparse
import copy
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

from csl_backup_core import hash_file, json_read, save
from csl_backup_crypto import Age, BackupPolicyError
from csl_backup_engine import Backup
from csl_backup_keys import apply_rotation, list_epochs, plan_rotation
from experiments.backup_f0.profiles import fixture


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--age-dir',type=Path,required=True)
    args=parser.parse_args(); os.umask(0o077)
    out=args.out.resolve(); out.mkdir(parents=True,mode=0o700,exist_ok=False)
    repo=Path(__file__).resolve().parents[2]
    sys.path.insert(0,str(repo/'tests'))
    from test_backup_engine import FakeStore, FakeControl, csl
    age=Age(str(args.age_dir/'age')); keys=[]; recipients=[]
    for _ in range(4):
        key=subprocess.check_output([str(args.age_dir/'age-keygen')],stderr=subprocess.DEVNULL)
        keys.append(key)
        recipients.append(subprocess.check_output([str(args.age_dir/'age-keygen'),'-y'],input=key,stderr=subprocess.DEVNULL).decode().strip())
    before_sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
    clean=not subprocess.check_output(['git','status','--porcelain'],cwd=repo).strip()
    with tempfile.TemporaryDirectory(prefix='csl-f3-local-') as directory:
        root=Path(directory); a=root/'A'
        store,control=FakeStore(),FakeControl()
        backup=Backup(csl(a),store,age); backup.control=control
        for state in ('interactive','archived'):
            sid=str(uuid.uuid4())
            folder=a/('archived_sessions' if state=='archived' else 'sessions')
            folder.mkdir(parents=True,exist_ok=True)
            (folder/('rollout-2026-11-10T00-00-00-'+sid+'.jsonl')).write_bytes(fixture('text',sid))
        initialized=backup.initialize(set_name='F3 synthetic local',source_name='Synthetic A',profile='native-age-v1',
            policy='stop',recipients=recipients[:2],key_reference='stdin')
        config=backup.load(initialized['set_id'])
        sources={str(p.relative_to(a)):hash_file(p) for p in a.rglob('rollout-*.jsonl')}
        first=backup.run(config,keys[0]); save(out/'01-old-run.json',first)
        originals=dict(store.bytes_by_id)
        control_before=copy.deepcopy(control.state)
        try:
            plan_rotation(backup,config,['age1'+'a'*58,'age1'+'c'*58])
        except BackupPolicyError:
            pass
        else:
            raise RuntimeError('Invalid public-recipient checksum accepted by real age')
        if control_before!=control.state:
            raise RuntimeError('Invalid recipients mutated remote state')
        planned=plan_rotation(backup,config,recipients[2:]); save(out/'02-plan-result.json',planned)
        save(out/'public-plan.json',json_read(planned['plan']))
        applied=apply_rotation(backup,config,Path(planned['plan'])); save(out/'03-apply.json',applied)
        if store.bytes_by_id!=originals: raise RuntimeError('Rotation modified historical ciphertext')
        current=backup.load(config['set_id'])
        second=backup.run(current,keys[2]); save(out/'04-new-run.json',second)
        if second['counts']['reused'] or second['counts']['captured']!=2:
            raise RuntimeError('Rotation reused objects encrypted only for old recipients')
        # Two isolated empty destination homes receive only the corresponding
        # external identity. Neither operational identity is passed to restore.
        old_b=Backup(csl(root/'B-old'),store,age); old_b.control=control
        new_b=Backup(csl(root/'B-new'),store,age); new_b.control=control
        project=root/'project'; project.mkdir()
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            old_result=old_b.restore(first['checkpoint_id'],keys[1],project)
            new_result=new_b.restore(second['checkpoint_id'],keys[3],project)
            old_again=old_b.restore(first['checkpoint_id'],keys[1],project)
            new_again=new_b.restore(second['checkpoint_id'],keys[3],project)
        if old_result['sessions']!=old_again['sessions'] or new_result['sessions']!=new_again['sessions']:
            raise RuntimeError('Repeat recovery changed installed UUIDs')
        rejected=[]
        for checkpoint,key,target in ((first['checkpoint_id'],keys[3],old_b),
                                      (second['checkpoint_id'],keys[1],new_b),
                                      (second['checkpoint_id'],b'',new_b)):
            installed={str(p):hash_file(p) for p in target.home.rglob('rollout-*.jsonl')}
            try: target.restore(checkpoint,key,project)
            except BackupPolicyError: pass
            else: raise RuntimeError('Incorrect/missing epoch identity did not block')
            if installed!={str(p):hash_file(p) for p in target.home.rglob('rollout-*.jsonl')}:
                raise RuntimeError('Wrong epoch identity changed installed copies')
            rejected.append({'checkpoint_id':checkpoint,'blocked':True,'existing_copies_unchanged':True})
        save(out/'05-recovery.json',{'old_epoch_external_only':old_result,'new_epoch_external_only':new_result,
            'repeat_same_uuids':True,'two_initially_empty_B_homes':True,'operational_private_in_restore':False,
            'negative_cases':rejected,'native_validation':'structural/native_unverified; no native client invoked',
            'source_access_boundary':'isolated destination modules; no filesystem sandbox claim'})
        save(out/'06-epoch-map.json',list_epochs(backup,current))
        after={str(p.relative_to(a)):hash_file(p) for p in a.rglob('rollout-*.jsonl')}
        if after!=sources: raise RuntimeError('Rotation/capture/restore modified original source bytes')
        save(out/'source-hashes.json',{'before':sources,'after':after,'unchanged':True})
        old_catalog=None; new_catalog=None
        for label,cp,identity in (('old',first['checkpoint_id'],keys[1]),('new',second['checkpoint_id'],keys[3])):
            temp=root/('inspect-'+label); temp.mkdir()
            catalog,_=backup._read_checkpoint(cp,identity,temp,metadata_only=True)
            save(out/(label+'-catalog.json'),catalog)
            if label=='old': old_catalog=catalog
            else: new_catalog=catalog
        if old_catalog['heads'][0]['version_key']==new_catalog['heads'][0]['version_key']:
            raise RuntimeError('Epoch rotation failed to change logical version identity')
        save(out/'result.json',{'passed':True,'real_age':True,'age_version':subprocess.check_output([str(args.age_dir/'age'),'--version']).decode().strip(),
            'transport':'in-memory synthetic fake; not live GitHub','github_calls':0,'remote_releases_assets_created':0,
            'source_head':before_sha,'clean_checkout_at_start':clean,'paid_inference':False,
            'historical_ciphertext_unchanged':all(store.bytes_by_id[k]==v for k,v in originals.items()),
            'invalid_public_recipient_checksum_blocked_without_mutation':True,
            'old_and_new_external_epochs_restored':True,'all_private_identities_discarded':True})
    keys.clear(); print('F3 local real-age evidence:',out)


if __name__=='__main__': main()
