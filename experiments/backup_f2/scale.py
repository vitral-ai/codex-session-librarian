"""Bounded local real-age memory/I/O probe. No remote store, real histories or keys on disk."""
import argparse
import json
import os
from pathlib import Path
import resource
import subprocess
import tempfile
import time
import tracemalloc
from types import SimpleNamespace
import uuid
from unittest.mock import patch

from csl_backup_core import canonical, hash_file, save
from csl_backup_crypto import Age
from csl_backup_engine import Backup
from experiments.backup_f0.profiles import fixture


def io_counts():
    return {k:int(v.strip()) for k,v in (line.split(':') for line in Path('/proc/self/io').read_text().splitlines())}


def rss_counts():
    values={}
    for line in Path('/proc/self/status').read_text().splitlines():
        if line.startswith(('VmRSS:', 'VmHWM:')):
            key,value=line.split(':'); values[key]=int(value.strip().split()[0])
    return values


def main():
    p=argparse.ArgumentParser(); p.add_argument('--out',type=Path,required=True)
    p.add_argument('--age-dir',type=Path,required=True); p.add_argument('--mib',type=int,default=32)
    args=p.parse_args(); os.umask(0o077)
    if not 1 <= args.mib <= 64: raise ValueError('Local bounded probe supports 1..64 MiB/member')
    age=Age(str(args.age_dir/'age')); keys=[]; recipients=[]
    for _ in range(2):
        key=subprocess.check_output([str(args.age_dir/'age-keygen')],stderr=subprocess.DEVNULL); keys.append(key)
        recipients.append(subprocess.check_output([str(args.age_dir/'age-keygen'),'-y'],input=key,stderr=subprocess.DEVNULL).decode().strip())
    with tempfile.TemporaryDirectory(prefix='csl-f2-scale-') as d:
        root=Path(d); home=root/'home'; folder=home/'sessions'; folder.mkdir(parents=True)
        originals=[]
        row=canonical({'type':'event_msg','payload':{'type':'agent_message','message':'SYNTHETIC '+('x'*16384)}})+b'\n'
        for i in range(3):
            sid=str(uuid.uuid4()); path=folder/('rollout-2026-11-10T00-00-00-'+sid+'.jsonl')
            with path.open('wb') as target:
                target.write(fixture('agent' if i==2 else 'text',sid))
                while target.tell() < args.mib*1024**2: target.write(row)
            originals.append({'path':path,'bytes':path.stat().st_size,'sha256':hash_file(path)})
        backup=Backup(SimpleNamespace(DEFAULT_CODEX_HOME=home),SimpleNamespace(),age)
        config={'repo_id':123,'set_id':str(uuid.uuid4()),'source_id':str(uuid.uuid4()),'profile':'native-age-v1',
                'secret_policy':'stop','recipients':recipients,'agent_forks':False}
        capture_dir=root/'capture'; capture_dir.mkdir()
        before=io_counts(); baseline=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss; rss_before=rss_counts()
        tracemalloc.start(); started=time.monotonic()
        entries,excluded,failures=backup._entries(config,capture_dir)
        packed=backup._pack(config,str(uuid.uuid4()),entries,capture_dir)
        for encrypted,manifest in packed:
            plain=capture_dir/(manifest['container_id']+'.verified.zip')
            age.decrypt(encrypted,plain,keys[0]); backup._verify_container(plain,manifest)
        elapsed=time.monotonic()-started; _,peak=tracemalloc.get_traced_memory(); tracemalloc.stop()
        after=io_counts(); maxrss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        budget_dir=root/'reduced-budget'; budget_dir.mkdir()
        with patch('csl_backup_engine.CAPTURE_BUDGET',args.mib*1024**2+32768):
            limited,limited_excluded,limited_failures=backup._entries(config,budget_dir)
        result={'scope':'local Linux real age; no transport/native install; logical /proc I/O includes warm page cache',
                'member_target_mib':args.mib,'fixture_bytes':sum(x['bytes'] for x in originals),
                'eligible_captured':len(entries),'excluded_before_copy':len(excluded),'failures':len(failures),
                'captured_bytes':sum(e['bytes'] for _,e in entries),'containers':len(packed),
                'final_ciphertext_bytes':sum(path.stat().st_size for path,_ in packed),'elapsed_milliseconds':round(elapsed*1000),
                'python_traced_peak_bytes':peak,'process_baseline_maxrss_kib':baseline,'process_maxrss_kib':maxrss,
                'io_delta':{k:after[k]-before[k] for k in before},
                'proc_status_before_kib':rss_before,'proc_status_after_kib':rss_counts(),
                'ru_maxrss_note':'Inherited high-water baseline can exceed current process /proc VmHWM; do not interpret ru_maxrss as probe allocation',
                'reduced_budget':{'captured':len(limited),'failed':len(limited_failures),
                                  'excluded':len(limited_excluded),'copied_bytes':sum(e['bytes'] for _,e in limited)},
                'source_hashes_intact':all(hash_file(x['path'])==x['sha256'] for x in originals),
                'fixtures':[{'bytes':x['bytes'],'sha256':x['sha256']} for x in originals],
                'detector_rules_version':__import__('csl_secrets').RULES_VERSION,
                'age_version':subprocess.check_output([str(args.age_dir/'age'),'--version']).decode().strip()}
        if len(entries)!=2 or len(excluded)!=1 or failures or len(limited)!=1 or len(limited_failures)!=1:
            raise RuntimeError('Scale probe coverage differs')
        save(args.out,result,exclusive=True)
    keys.clear(); print('Local scale probe:',args.out)


if __name__=='__main__': main()
