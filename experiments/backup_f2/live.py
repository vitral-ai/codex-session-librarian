"""Bounded authorized F2 synthetic live trial; never uses personal histories."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid
from unittest.mock import patch

from csl_backup_core import hash_file, save
from csl_backup_crypto import Age
from csl_backup_engine import Backup
from experiments.backup_f0.profiles import fixture
from experiments.backup_f1.live import BudgetStore, cold_phase, inventory, isolated_csl


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--age-dir',type=Path,required=True)
    parser.add_argument('--identity-helper',type=Path,required=True)
    args=parser.parse_args()
    os.umask(0o077)
    out=args.out.resolve(); out.mkdir(parents=True,mode=0o700,exist_ok=False)
    age=Age(str(args.age_dir/'age'))
    keys=[]; recipients=[]
    for _ in range(2):
        key=subprocess.check_output([str(args.age_dir/'age-keygen')],stderr=subprocess.DEVNULL)
        keys.append(key)
        recipients.append(subprocess.check_output([str(args.age_dir/'age-keygen'),'-y'],input=key,stderr=subprocess.DEVNULL).decode().strip())
    spec=importlib.util.spec_from_file_location('own_f2_transport',args.identity_helper)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    own=module.Client()
    inventory_checks=[]
    # Every wrapper invocation adds its independent GET/user. BudgetStore also
    # reads BOTH repositories before each release/asset POST, counted separately.
    import experiments.backup_f1.live as f1
    real_inventory=f1.inventory
    def counted_inventory():
        result=real_inventory(); inventory_checks.append(2)
        return result
    try:
        save(out/'before.json',{'inventory':counted_inventory()})
        with tempfile.TemporaryDirectory(prefix='csl-f2-') as runtime_string, patch.object(f1,'inventory',side_effect=counted_inventory):
            runtime=Path(runtime_string)
            a,b=runtime/'A',runtime/'B'; a.mkdir(mode=0o700); b.mkdir(mode=0o700)
            (b/'home').mkdir(); (b/'project').mkdir()
            originals=[]
            for case in ('text','archived'):
                sid=str(uuid.uuid4()); data=fixture('text',sid)
                folder=a/('archived_sessions' if case=='archived' else 'sessions/2026/11/10')
                folder.mkdir(parents=True,exist_ok=True)
                path=folder/('rollout-2026-11-10T00-00-00-'+sid+'.jsonl')
                path.write_bytes(data); originals.append(path)
            store=BudgetStore(out); backup=Backup(isolated_csl(a),store,age)
            configured=backup.initialize(set_name='F2 synthetic heads and recovery',source_name='Synthetic A',
                profile='native-age-v1',policy='stop',recipients=recipients,key_reference='stdin')
            config=backup.load(configured['set_id'])
            first=backup.run(config,keys[0]); save(out/'01-bootstrap.json',first)
            for path in originals: os.utime(path,(1,1))
            second=backup.run(config,keys[0]); save(out/'02-reuse.json',second)
            if second['counts']['reused']!=2 or second['counts']['captured']!=0:
                raise RuntimeError('Live unchanged content did not reuse')
            data=originals[0].read_bytes()
            originals[0].write_bytes(data.replace(b'SYNTHETIC USER',b'SYNTHETIC A002'))
            hashes_before={str(p.relative_to(a)):hash_file(p) for p in originals}
            third=backup.run(config,keys[0]); save(out/'03-changed-head.json',third)
            if third['counts']['reused']!=1 or third['counts']['captured']!=1:
                raise RuntimeError('Live changed head coverage differs')
            # Interruption after the backend accepted the object. Delete ONLY
            # this synthetic local run journal/staging, preserving remote plan.
            originals[0].write_bytes(originals[0].read_bytes().replace(b'SYNTHETIC A002',b'SYNTHETIC A003'))
            real_publish=store.publish
            interrupted=[]
            def interrupt(identifier,ciphertext,kind,**kwargs):
                result=real_publish(identifier,ciphertext,kind,**kwargs)
                if kind=='o':
                    interrupted.append(identifier)
                    raise RuntimeError('synthetic interruption after object POST accepted')
                return result
            try:
                with patch.object(store,'publish',side_effect=interrupt): backup.run(config,keys[0])
            except RuntimeError as error:
                if not interrupted: raise
                save(out/'04-interruption.json',{'reason':str(error),'accepted_object_id':interrupted[0]})
            else: raise RuntimeError('Fault was not injected')
            _,control=backup.control.read(); run_id=control['sets'][config['set_id']]['owner']
            shutil.rmtree(backup.root/'runs'/run_id)
            originals[0].write_bytes(originals[0].read_bytes().replace(b'SYNTHETIC A003',b'SYNTHETIC A004'))
            resume_hashes={str(p.relative_to(a)):hash_file(p) for p in originals}
            before_resume=inventory()
            fourth=backup.run(config,keys[0],resume=run_id); save(out/'05-resume-no-journal.json',fourth)
            after_resume=inventory()
            if fourth['fresh_capture'] or len(after_resume)!=len(before_resume) or fourth['costs']['uploaded_container_bytes']:
                raise RuntimeError('Resume duplicated releases/uploaded object or claimed fresh capture')
            if resume_hashes!={str(p.relative_to(a)):hash_file(p) for p in originals}:
                raise RuntimeError('Resume changed synthetic source bytes')
            # One truly cold B. It receives external identity over stdin and its
            # own authorized GET-only transport. A is hidden with bubblewrap.
            recovered=cold_phase(out,runtime,b,args.age_dir,keys[1],own._token,fourth['checkpoint_id'])
            if len(recovered['sessions'])!=2: raise RuntimeError('Retained pack resurrected obsolete A1')
            restored_bytes=b''.join(p.read_bytes() for p in (b/'codex').rglob('rollout-*.jsonl'))
            if b'SYNTHETIC A003' not in restored_bytes or b'SYNTHETIC A004' in restored_bytes or b'SYNTHETIC A002' in restored_bytes:
                raise RuntimeError('Resume did not restore the exact interrupted cut')
            save(out/'source-hashes.json',{'after_changed_capture':hashes_before,'resume_before_after_equal':True,
                'before_after_resume':resume_hashes,'restored_interrupted_A003_not_current_A004':True,
                'restored_logical_heads':2,'old_container_members_not_resurrected':True})
            save(out/'costs.json',{'product_transport':store.metrics,'product_cli_invocations':store.calls,
                'wrapper_identity_GET_user':store.calls+sum(inventory_checks),
                'inventory_metadata_GET':sum(inventory_checks),'inventory_observations':len(inventory_checks),
                'extra_identity_helper_initial_GET_user':1,
                'note':'Cold B broker calls/bytes recorded separately in cold.json; network redirects add CDN GETs.'})
    finally:
        own.close(); keys.clear()
        try:
            rows=counted_inventory()
            save(out/'ledger.json',{'phase':'F2','inventory':rows,'releases':len(rows),
                'assets':sum(len(r['assets']) for r in rows),'bytes':sum(a['size'] for r in rows for a in r['assets']),
                'limits':{'releases':40,'assets':80,'bytes':50*1024**2},'no_delete':True,
                'note':'Final observation including prior phases; does not itself imply test success'})
        except Exception as error:
            save(out/'inventory-failed.json',{'reason_code':type(error).__name__})
    save(out/'result.json',{'passed':True,'real_age':True,'real_private_GitHub':True,'synthetic_only':True,
                          'cold_B_once':True,'no_paid_inference':True,'keys_discarded':True})
    print('F2 evidence:',out)


if __name__=='__main__': main()
