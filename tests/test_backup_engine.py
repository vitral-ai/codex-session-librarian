"""Synthetic manual-engine integration; fake cipher/store are NOT E1 evidence."""

import copy
import contextlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from csl_backup_core import exclusive_output
from csl_backup_core import hash_bytes
from csl_backup_crypto import Age, BackupPolicyError
from csl_backup_engine import Backup
from csl_transfer import TransferError
from experiments.backup_f0.profiles import fixture


class FakeCipher:
    recipients = staticmethod(Age.recipients)
    def encrypt(self, source, target, recipients):
        with exclusive_output(target, source=source) as staging:
            staging.write_bytes(b'SYNTHETIC-NOT-CRYPTO\n' + source.read_bytes())
    def decrypt(self, source, target, identity):
        if identity != b'synthetic identity':
            raise BackupPolicyError('synthetic wrong key')
        with exclusive_output(target, source=source) as staging:
            staging.write_bytes(source.read_bytes().removeprefix(b'SYNTHETIC-NOT-CRYPTO\n'))


class FakeStore:
    repo, repo_id = 'synthetic/private', 123
    metadata = {'private':True,'permissions':{'push':True}}
    def __init__(self):
        self.releases_by_tag = {}
        self.bytes_by_id = {}
        self.next_id = 10
        self.downloaded = []
    def resolve_release(self, identifier, kind='c', release_id=None):
        release = self.releases_by_tag.get('cslb-v1-' + kind + '-' + identifier)
        if release_id is not None and release['id'] != release_id:
            raise TransferError('synthetic misbound release')
        return release
    def reserve(self, identifier, kind='c'):
        tag = 'cslb-v1-' + kind + '-' + identifier
        if tag not in self.releases_by_tag:
            self.next_id += 1
            self.releases_by_tag[tag] = {'id':self.next_id,'tag_name':tag,'assets':[],'draft':True}
        return self.releases_by_tag[tag]
    def finalize(self, identifier, kind, release_id):
        self.resolve_release(identifier,kind,release_id)['draft']=False
    def _descriptor(self, release, identifier, ciphertext, name='descriptor.json'):
        return None
    def publish(self, identifier, ciphertext, kind, *, release_id=None):
        release=self.reserve(identifier, 'c' if kind=='p' else kind)
        name={'o':'container.age','c':'catalog.age','p':'plan.age'}[kind]
        found=[a for a in release['assets'] if a['name']==name]
        if found:
            return {'release_id':release['id'],'asset':found[0],'tag':release['tag_name']}
        self.next_id += 1
        asset = {'id':self.next_id,'size':ciphertext.stat().st_size,'name':name}
        self.bytes_by_id[asset['id']] = ciphertext.read_bytes()
        release['assets'].append(asset)
        return {'release_id':release['id'],'asset':asset,'tag':release['tag_name']}
    def download(self, asset, target):
        self.downloaded.append(asset['id'])
        with exclusive_output(target) as staging:
            staging.write_bytes(self.bytes_by_id[asset['id']])
    def request(self, method, suffix, body=None):
        assert method == 'GET'
        return self.releases_by_tag[suffix.removeprefix('/releases/tags/')]
    def read_envelope(self, release, identifier, name='descriptor.json'):
        asset = next(a for a in release['assets'] if a['name']==('plan.age' if name.startswith('plan') else 'container.age' if '-o-' in release['tag_name'] else 'catalog.age'))
        return {'format':'csl-backup-envelope','schema_version':1,'object_id':identifier,
                'cipher':'age-v1-x25519','bytes':asset['size'],'sha256':hash_bytes(self.bytes_by_id[asset['id']])}
    def releases(self):
        return iter(self.releases_by_tag.values())


class FakeControl:
    def __init__(self):
        self.state = {'format':'csl-backup-control','schema_version':1,'repo_id':123,'sets':{}}
        self.clock = 100
    def read(self):
        return 'synthetic-sha', copy.deepcopy(self.state)
    def change(self, mutate):
        candidate = copy.deepcopy(self.state)
        mutate(candidate, self.clock)
        self.clock += 1
        self.state = candidate
        return copy.deepcopy(candidate)


def csl(home):
    def init_db(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.execute('CREATE TABLE IF NOT EXISTS sessions(session_id TEXT PRIMARY KEY,path TEXT)')
        return conn
    def register(conn, target, sid, title, stamp):
        conn.execute('INSERT INTO sessions VALUES(?,?)', (sid,str(target)))
        conn.commit()
    return SimpleNamespace(DEFAULT_CODEX_HOME=home, DEFAULT_DB=home/'index.sqlite',
                           init_db=init_db, register_native_session=register)


class BackupEngineTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.store, self.control = FakeStore(), FakeControl()
        self.a = Backup(csl(self.root/'A'), self.store, FakeCipher())
        self.a.control = self.control
        result = self.a.initialize(set_name='synthetic', source_name='A', profile='native-age-v1', policy='stop',
            recipients=['age1'+'a'*58,'age1'+'c'*58], key_reference='stdin')
        self.config = self.a.load(result['set_id'])
        self.sources = []
        for index, kind in enumerate(('text','archived','structured-agent')):
            sid = str(uuid.uuid4())
            data = fixture('text', sid)
            if kind == 'structured-agent':
                records = [json.loads(line) for line in data.splitlines()]
                records[0]['payload']['source'] = {'subagent':{'thread_spawn':{'parent_thread_id':str(uuid.uuid4()),'depth':1}}}
                data = b''.join((json.dumps(r)+'\n').encode() for r in records)
            folder = self.a.home/('archived_sessions' if kind=='archived' else 'sessions/2026/11/10')
            folder.mkdir(parents=True, exist_ok=True)
            source = folder/('rollout-2026-11-10T00-00-00-'+sid+'.jsonl')
            source.write_bytes(data)
            self.sources.append((source,data))
        self.cwd = self.root/'project'
        self.cwd.mkdir()
        self.b = Backup(csl(self.root/'B'), self.store, FakeCipher())
        self.b.control = self.control

    def run_backup(self):
        return self.a.run(self.config, b'synthetic identity')

    def test_native_metadata_only_is_backed_up_without_inventing_messages(self):
        sid=str(uuid.uuid4())
        path=self.a.home/'sessions'/('rollout-2026-11-10T00-00-00-'+sid+'.jsonl')
        content=fixture('text',sid).splitlines(keepends=True)[0]
        path.write_bytes(content)
        result=self.run_backup()
        self.assertEqual(result['sessions'],3)
        restored=self.b.restore('latest',b'synthetic identity',self.cwd)
        self.assertEqual(restored['quarantined'],1)
        self.assertEqual(len(list((self.b.root/'quarantine').glob('*.jsonl'))),1)
        self.assertEqual(next((self.b.root/'quarantine').glob('*.jsonl')).read_bytes(),content)

    def test_native_index_progress_cannot_pollute_structured_stdout(self):
        self.run_backup()
        self.b.csl.DEFAULT_SESSIONS_DIR=self.b.home/'sessions'
        output,error=io.StringIO(),io.StringIO()
        with patch('csl_backup_engine.refresh_native_picker',side_effect=lambda _:print('native index progress')), \
             contextlib.redirect_stdout(output),contextlib.redirect_stderr(error):
            self.b.restore('latest',b'synthetic identity',self.cwd)
        self.assertEqual(output.getvalue(),'')
        self.assertIn('native index progress',error.getvalue())

    def test_repeated_init_reuses_set_and_source_and_rejects_material_change(self):
        args = dict(set_name='synthetic',source_name='A',profile='native-age-v1',policy='stop',
                    recipients=['age1'+'a'*58,'age1'+'c'*58],key_reference='stdin')
        repeated = self.a.initialize(**args)
        self.assertEqual(repeated['set_id'],self.config['set_id'])
        self.assertEqual(repeated['source_id'],self.config['source_id'])
        self.assertEqual(len(list((self.a.root/'sets').glob('*.json'))),1)
        with self.assertRaises(TransferError):
            self.a.initialize(**{**args,'source_name':'different source'})

    def test_second_member_failure_only_records_first_logical_restore(self):
        self.run_backup()
        real_register = self.b.csl.register_native_session
        calls = []
        def second_fails(*args):
            calls.append(args[2])
            if len(calls)==2:
                raise RuntimeError('synthetic second install failure')
            return real_register(*args)
        with patch.object(self.b.csl,'register_native_session',side_effect=second_fails):
            with self.assertRaises(RuntimeError):
                self.b.restore('latest',b'synthetic identity',self.cwd)
        events = [json.loads(path.read_bytes()) for path in (self.b.root/'events').glob('*.json')]
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['installed_uuid'],calls[0])
        self.assertNotEqual(events[0]['object_id'],events[0]['container_id'])
        for key in ('member_id','version_key','installed_sha256','target_binding'):
            self.assertIn(key,events[0])
        self.b.restore('latest',b'synthetic identity',self.cwd)
        self.assertEqual(len(list(self.b.home.rglob('rollout-*.jsonl'))),2)

    def test_dry_run_no_remote_write_or_source_mutation(self):
        result = self.a.run(self.config, b'synthetic identity', dry_run=True)
        self.assertEqual(result['sessions'], 2)
        self.assertEqual(self.store.releases_by_tag,{})
        self.assertEqual(self.control.state['sets'],{})
        for source,data in self.sources:
            self.assertEqual(source.read_bytes(),data)

    def test_manual_cold_restore_archive_repeat_and_changed_copy_conflict(self):
        result = self.run_backup()
        self.assertEqual(result['sessions'],2)
        self.store.downloaded.clear()
        restored = self.b.restore('latest', b'synthetic identity', self.cwd)
        ids = [item['uuid'] for item in restored['sessions']]
        self.assertEqual(len(set(ids)),2)
        self.assertEqual(len(list((self.b.home/'sessions').rglob('rollout-*.jsonl'))),1)
        self.assertEqual(len(list((self.b.home/'archived_sessions').rglob('rollout-*.jsonl'))),1)
        self.assertEqual(len(self.store.downloaded),2)  # One catalog and one shared container.
        repeated = self.b.restore('latest', b'synthetic identity', self.cwd)
        self.assertEqual(ids,[item['uuid'] for item in repeated['sessions']])
        target = next((self.b.home/'sessions').rglob('rollout-*.jsonl'))
        target.write_bytes(target.read_bytes()+b'\n')
        with self.assertRaisesRegex(TransferError,'changed'):
            self.b.restore('latest', b'synthetic identity', self.cwd)
        self.assertFalse((self.b.root/'sets').exists())

    def test_optin_structured_agent_preserves_source_bytes_and_native_source(self):
        self.config['agent_forks'] = True
        result = self.run_backup()
        self.assertEqual(result['sessions'],3)
        restored = self.b.restore('latest', b'synthetic identity', self.cwd)
        agent = next(item for item in restored['sessions'] if item['state']=='agent')
        path = next((self.b.home/'sessions').rglob('*'+agent['uuid']+'.jsonl'))
        records = [json.loads(line) for line in path.read_bytes().splitlines()]
        self.assertIn('subagent',records[0]['payload']['source'])
        for source,data in self.sources:
            self.assertEqual(source.read_bytes(),data)

    def test_crash_after_intent_before_publication_reconciles_same_reserved_uuid(self):
        self.run_backup()
        with patch('csl_backup_engine.publish_session_file', side_effect=RuntimeError('synthetic crash')):
            with self.assertRaises(RuntimeError):
                self.b.restore('latest', b'synthetic identity', self.cwd)
        intents = list((self.b.root/'restore-intents').glob('*.json'))
        saved = json.loads(intents[0].read_bytes())
        restored = self.b.restore('latest', b'synthetic identity', self.cwd)
        self.assertIn(saved['installed_uuid'],[item['uuid'] for item in restored['sessions']])

    def test_crash_after_file_before_receipt_reuses_exact_published_target(self):
        self.run_backup()
        real_register = self.b.csl.register_native_session
        with patch.object(self.b.csl,'register_native_session',side_effect=RuntimeError('crash before receipt')):
            with self.assertRaises(RuntimeError):
                self.b.restore('latest', b'synthetic identity', self.cwd)
        prior = list(self.b.home.rglob('rollout-*.jsonl'))
        self.assertEqual(len(prior),1)
        existing_bytes = prior[0].read_bytes()
        self.b.restore('latest', b'synthetic identity', self.cwd)
        self.assertEqual(prior[0].read_bytes(),existing_bytes)
        self.assertEqual(len(list(self.b.home.rglob('rollout-*.jsonl'))),2)

    def test_wrong_key_installs_nothing_and_preserves_originals(self):
        self.run_backup()
        with self.assertRaises(BackupPolicyError):
            self.b.restore('latest', b'wrong key', self.cwd)
        self.assertFalse(list(self.b.home.rglob('rollout-*.jsonl')))
        for source,data in self.sources:
            self.assertEqual(source.read_bytes(),data)

    def test_stale_writer_cannot_reacquire_after_new_epoch_owner_finished(self):
        old=self.run_backup()['checkpoint_id']
        real_publish=self.store.publish
        real_pack=self.a._pack
        def separate(config,run_id,entries,temporary):
            return [packed for entry in entries for packed in real_pack(config,run_id,[entry],temporary)]
        new_pointer=str(uuid.uuid4())
        changed=[]
        def steal_then_finish(identifier,ciphertext,kind,**kwargs):
            value=real_publish(identifier,ciphertext,kind,**kwargs)
            if not changed:
                item=self.control.state['sets'][self.config['set_id']]
                item['epoch']+=1
                item['owner']=''
                item['expires']=self.control.clock-1
                item['sources'][self.config['source_id']]['latest_complete']=new_pointer
                changed.append(True)
            return value
        with patch.object(self.store,'publish',side_effect=steal_then_finish), patch.object(self.a,'_pack',side_effect=separate):
            with self.assertRaisesRegex(TransferError,'lease|Lease|epoch'):
                self.run_backup()
        item=self.control.state['sets'][self.config['set_id']]
        self.assertEqual(item['sources'][self.config['source_id']]['latest_complete'],new_pointer)


if __name__ == '__main__':
    unittest.main()
