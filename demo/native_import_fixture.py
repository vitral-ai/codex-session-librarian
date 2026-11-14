#!/usr/bin/env python3
"""Create synthetic Claude history for manual native/CSL comparison; runs no CLI."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

SOURCE_ID = '22222222-2222-4222-8222-222222222222'
TOOL_ID = 'synthetic-read-1'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True, help='New private directory; existing paths are refused.')
    parser.add_argument('--pairs', type=int, default=0, help='Optional inert user/assistant pairs (0..600).')
    parser.add_argument('--age-days', type=int, default=0, help='Fixture timestamps and mtime age (0..90 days).')
    args = parser.parse_args()
    if not 0 <= args.pairs <= 600 or not 0 <= args.age_days <= 90:
        parser.error('pairs must be 0..600 and age-days 0..90')
    os.umask(0o077)
    root = args.out.expanduser().absolute()
    root.mkdir(mode=0o700, parents=False, exist_ok=False)
    project = root/'project'; project.mkdir()
    for folder in ('home', 'native-codex', 'csl-codex', 'csl-claude'):
        (root/folder).mkdir()
    stamp = (dt.datetime.now(dt.UTC) - dt.timedelta(days=args.age_days)).isoformat()
    records, parent = [], None
    def message(role, content):
        nonlocal parent
        key = str(uuid.uuid5(uuid.UUID(SOURCE_ID), str(len(records))))
        payload = {'role': role, 'content': content}
        if role == 'assistant':
            payload.update(id='msg_synthetic_'+str(len(records)), type='message', model='synthetic-no-generation',
                stop_reason='tool_use' if isinstance(content, list) and any(b.get('type')=='tool_use' for b in content) else 'end_turn',
                stop_sequence=None, usage={'input_tokens':0, 'output_tokens':0})
        records.append({'type':role,'uuid':key,'parentUuid':parent,'sessionId':SOURCE_ID,
            'cwd':str(project),'timestamp':stamp,'version':'2.1.308','isSidechain':False,'userType':'external','message':payload})
        parent = key
    message('user', 'Synthetic draft: copper17 and MySQL.')
    message('assistant', [{'type':'text','text':'Draft only, not the final decision.'}])
    for number in range(args.pairs):
        message('user', 'Inert note '+str(number)+': '+'bounded synthetic history. '*30)
        message('assistant', [{'type':'text','text':'Recorded '+str(number)}])
    message('user', 'Current decision: jade83 and SQLite, superseding the draft.')
    message('assistant', [{'type':'text','text':'Reading a historical fixture, not running a command.'},
        {'type':'tool_use','id':TOOL_ID,'name':'Bash','input':{'command':'touch HISTORICAL_NEVER_EXECUTE'}}])
    message('user', [{'type':'tool_result','tool_use_id':TOOL_ID,
        'content':'SYNTHETIC-TOOL-7392; historical error E_SYNTH_44. No command ran.','is_error':True}])
    message('assistant', [{'type':'text','text':'Current jade83/SQLite decision and historical error recorded.'}])
    content = ''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in records).encode()
    # Both readers get identical synthetic bytes. No account/auth/settings files
    # are collected. The native copy is discoverable under this lab's own HOME.
    native_dir = root/'home/.claude/projects'/str(project).replace('/','-')
    native_dir.mkdir(parents=True)
    source = root/'source.jsonl'; native = native_dir/(SOURCE_ID+'.jsonl')
    for path in (source, native):
        with path.open('xb') as stream: stream.write(content)
        path.chmod(0o600)
        if args.age_days:
            age = time.time() - args.age_days*86400
            os.utime(path,(age,age))
    report = {'kind':'synthetic-only','source_id':SOURCE_ID,'records':len(records),
        'bytes':len(content),'sha256':hashlib.sha256(content).hexdigest(),'age_days':args.age_days,
        'source':'source.jsonl','native_source':str(native.relative_to(root)),
        'CLI_or_model_calls':0,'limits':['Only a text/completed error-tool fixture, no media or opaque compaction.',
            'Fresh lab only; native discovery, CLI loading and model continuation are separate checks.']}
    with (root/'fixture.json').open('x') as stream:json.dump(report,stream,indent=2)
    print(json.dumps(report))


if __name__=='__main__':main()
