"""F2 synthetic fault injection. Fake cipher/store do not establish E1."""
import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
from unittest.mock import patch
import uuid
import unittest

import csl_backup_format as fmt
from csl_backup_core import BackupBusy, hash_bytes, hash_file, json_read
from csl_backup_engine import Backup
from csl_transfer import TransferError
import test_backup_engine as engine_fixtures
from test_backup_engine import csl, FakeCipher


class IncrementalTests(unittest.TestCase):
    setUp = engine_fixtures.BackupEngineTests.setUp
    run_backup = engine_fixtures.BackupEngineTests.run_backup
    def catalog(self, checkpoint):
        with tempfile.TemporaryDirectory() as d:
            return self.a._read_checkpoint(checkpoint, b'synthetic identity', Path(d),
                                           metadata_only=True, allow_partial=True)[0]

    def change(self, index=0):
        path, content = self.sources[index]
        changed = content.replace(b'synthetic', b'SYNTHETIC')
        if changed == content:
            changed = content.replace(b'hello', b'HELLO')
        if changed == content:
            records=[json.loads(line) for line in content.splitlines()]
            records.append({'type':'event_msg','payload':{'type':'agent_message','message':'changed'}})
            changed=b''.join((json.dumps(r)+'\n').encode() for r in records)
        path.write_bytes(changed)
        return path

    def pending_run(self):
        real = self.store.publish
        def crash(identifier, ciphertext, kind, **kwargs):
            if kind == 'o':
                raise RuntimeError('synthetic power loss before object POST')
            return real(identifier, ciphertext, kind, **kwargs)
        with patch.object(self.store, 'publish', side_effect=crash):
            with self.assertRaises(RuntimeError):
                self.run_backup()
        return next((self.a.root/'runs').glob('*/journal.json')).parent.name

    def test_unchanged_mtime_reuse_keeps_integrity_and_capture_dates(self):
        first=self.run_backup(); c1=self.catalog(first['checkpoint_id'])
        self.store.downloaded.clear()
        for path,_ in self.sources:
            os.utime(path,(1,1))
        second=self.run_backup(); c2=self.catalog(second['checkpoint_id'])
        self.assertEqual(second['counts']['reused'],2)
        self.assertEqual(second['counts']['captured'],0)
        self.assertEqual(c1['containers'][0]['manifest'],c2['containers'][0]['manifest'])
        self.assertEqual(c1['containers'][0]['integrity_verified_at'],c2['containers'][0]['integrity_verified_at'])
        self.assertEqual([h['captured_at'] for h in c1['heads']],[h['captured_at'] for h in c2['heads']])
        self.assertNotIn(c1['containers'][0]['asset_id'],self.store.downloaded)
        self.assertEqual(c2['containers'][0]['evidence_level'],'available')

    def test_p1_a1_b1_then_p2_a2_restores_exact_heads(self):
        first=self.run_backup(); old=self.catalog(first['checkpoint_id'])
        before=copy.deepcopy(old['containers'][0])
        self.change()
        second=self.run_backup(); catalog=self.catalog(second['checkpoint_id'])
        self.assertEqual(second['counts']['reused'],1)
        self.assertEqual(second['counts']['captured'],1)
        self.assertEqual(len(catalog['containers']),2)
        self.assertEqual(len(catalog['heads']),2)
        self.assertEqual(sum(len(c['manifest']['members']) for c in catalog['containers']),3)
        self.assertEqual(self.catalog(first['checkpoint_id'])['containers'][0],before)
        restored=self.b.restore('latest',b'synthetic identity',self.cwd)
        self.assertEqual(len(restored['sessions']),2)
        self.assertEqual(len(list(self.b.home.rglob('rollout-*.jsonl'))),2)
        self.assertEqual(len(self.b.restore(first['checkpoint_id'],b'synthetic identity',self.cwd)['sessions']),2)
        self.assertEqual(len(list(self.b.home.rglob('rollout-*.jsonl'))),3)

    def test_same_size_changed_hash_never_reuses(self):
        self.run_backup()
        path,content=self.sources[0]
        # Relocate whitespace, preserving size and JSON semantics.
        path.write_bytes(b' '+content.rstrip(b'\n'))
        self.assertEqual(path.stat().st_size,len(content))
        result=self.run_backup()
        self.assertEqual(result['counts']['captured'],1)
        self.assertEqual(result['counts']['reused'],1)

    def test_full_30d_due_does_not_download_or_rejuvenate(self):
        first=self.run_backup(); catalog=self.catalog(first['checkpoint_id'])
        cid=catalog['containers'][0]['asset_id']
        future='2099-01-01T00:00:00Z'
        self.store.downloaded.clear()
        with patch('csl_backup_incremental.now',return_value=future):
            second=self.run_backup()
        self.assertEqual(second['verification_due'],1)
        self.assertNotIn(cid,self.store.downloaded)
        newer=self.catalog(second['checkpoint_id'])
        self.assertEqual(newer['containers'][0]['integrity_verified_at'],catalog['containers'][0]['integrity_verified_at'])
        self.b.verify(second['checkpoint_id'],b'synthetic identity')
        self.assertIn(cid,self.store.downloaded)

    def test_deleted_local_is_retained_and_not_observed_fresh(self):
        first=self.run_backup(); prior=self.catalog(first['checkpoint_id'])
        self.sources[0][0].unlink()
        result=self.run_backup(); catalog=self.catalog(result['checkpoint_id'])
        self.assertEqual(result['counts']['missing_local'],1)
        self.assertEqual(result['counts']['eligible'],1)
        self.assertEqual(result['counts']['protected'],2)
        missing=next(h for h in catalog['heads'] if h['state']=='missing_local')
        old=next(h for h in prior['heads'] if h['member_id']==missing['member_id'])
        self.assertEqual(old['last_observed_at'],missing['last_observed_at'])
        self.assertEqual(len(self.b.restore('latest',b'synthetic identity',self.cwd)['sessions']),2)

    def test_bad_source_partial_keeps_complete_and_explicit_restore_gate(self):
        first=self.run_backup()
        self.sources[0][0].write_bytes(self.sources[0][1]+b'{broken}\n')
        result=self.run_backup()
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['counts']['stale'],1)
        source=self.control.state['sets'][self.config['set_id']]['sources'][self.config['source_id']]
        self.assertEqual(source['latest_complete'],first['checkpoint_id'])
        self.assertEqual(source['latest_partial'],result['checkpoint_id'])
        with self.assertRaisesRegex(TransferError,'allow-partial'):
            self.b.restore(result['checkpoint_id'],b'synthetic identity',self.cwd)
        restored=self.b.restore(result['checkpoint_id'],b'synthetic identity',self.cwd,allow_partial=True)
        self.assertEqual(len(restored['omissions']),1)
        self.assertEqual(len(restored['sessions']),2)

    def test_altered_remote_never_reuses_and_missing_source_cannot_fake_good(self):
        first=self.run_backup(); catalog=self.catalog(first['checkpoint_id'])
        container=catalog['containers'][0]
        self.store.bytes_by_id[container['asset_id']]+=b'tamper'
        result=self.run_backup()
        self.assertEqual(result['counts']['reused'],0)
        self.assertEqual(result['counts']['captured'],2)
        self.assertNotEqual(self.catalog(result['checkpoint_id'])['containers'][0]['container_id'],container['container_id'])

    def test_resume_exact_cut_after_source_changed_without_recapture(self):
        run_id=self.pending_run()
        plan=json_read(self.a.root/'runs'/run_id/'plan.json')
        self.change()
        with patch.object(self.a,'_entries',side_effect=AssertionError('resume recaptured source')):
            result=self.a.run(self.config,b'synthetic identity',resume=run_id)
        self.assertFalse(result['fresh_capture'])
        self.assertEqual(result['cut_at'],plan['cut_at'])
        catalog=self.catalog(result['checkpoint_id'])
        self.assertEqual(catalog['containers'][0]['manifest'],plan['pending'][0]['manifest'])

    def test_resume_remote_plan_no_local_journal_adopts_uploaded_object(self):
        real=self.store.finalize
        def crash(identifier,kind,release_id):
            value=real(identifier,kind,release_id)
            if kind=='o':
                raise RuntimeError('lost journal after verified object accepted')
            return value
        with patch.object(self.store,'finalize',side_effect=crash):
            with self.assertRaises(RuntimeError):
                self.run_backup()
        run_dir=next((self.a.root/'runs').iterdir()); run_id=run_dir.name
        release_count=len(self.store.releases_by_tag)
        shutil.rmtree(run_dir)
        self.change()
        result=self.a.run(self.config,b'synthetic identity',resume=run_id)
        self.assertEqual(result['status'],'complete')
        self.assertEqual(len(self.store.releases_by_tag),release_count)
        self.assertEqual(result['costs']['uploaded_container_bytes'],0)

    def test_resume_remote_plan_missing_bytes_is_failed_not_invented(self):
        run_id=self.pending_run()
        shutil.rmtree(self.a.root/'runs'/run_id)
        with self.assertRaisesRegex(TransferError,'No protected'):
            self.a.run(self.config,b'synthetic identity',resume=run_id)
        source=self.control.state['sets'][self.config['set_id']]['sources'][self.config['source_id']]
        self.assertIsNone(source['latest_complete'])
        self.assertTrue(all(r.get('draft') for r in self.store.releases_by_tag.values()))

    def test_resume_expired_same_epoch_and_stale_after_other_writer(self):
        run_id=self.pending_run()
        self.control.clock+=1000
        result=self.a.run(self.config,b'synthetic identity',resume=run_id)
        self.assertEqual(result['status'],'complete')
        self.change(); newer=self.run_backup()
        with self.assertRaises(BackupBusy):
            self.a.run(self.config,b'synthetic identity',resume=run_id)
        self.assertEqual(self.a.latest()[2]['latest_complete'],newer['checkpoint_id'])

    def test_crash_after_catalog_publish_resume_commits_same_id(self):
        real=self.a._lease
        def crash(*args,**kwargs):
            if kwargs.get('checkpoint'):
                raise RuntimeError('crash before pointer')
            return real(*args,**kwargs)
        with patch.object(self.a,'_lease',side_effect=crash):
            with self.assertRaises(RuntimeError):
                self.run_backup()
        run_id=next((self.a.root/'runs').iterdir()).name
        count=len(self.store.bytes_by_id)
        result=self.a.run(self.config,b'synthetic identity',resume=run_id)
        self.assertEqual(result['status'],'complete')
        self.assertEqual(len(self.store.bytes_by_id),count)
        self.assertEqual(self.a.run(self.config,b'synthetic identity',resume=run_id)['status'],'already_committed')

    def test_heads_reject_invented_member_duplicate_source_cross_binding(self):
        result=self.run_backup(); value=self.catalog(result['checkpoint_id'])
        for mutate in (lambda c:c['heads'][0].update(member_id=str(uuid.uuid4())),
                       lambda c:c['heads'].append(copy.deepcopy(c['heads'][0])),
                       lambda c:c['containers'][0]['manifest'].update(source_id=str(uuid.uuid4())),
                       lambda c:c['counts'].update(reused=True),
                       lambda c:c['heads'][0].update(sha256='0'*64)):
            changed=copy.deepcopy(value); mutate(changed)
            with self.assertRaises(TransferError):
                fmt.catalog(changed)

    def test_second_source_same_uuid_stays_independent_and_latest_ambiguous(self):
        first=self.run_backup()
        other=Backup(csl(self.root/'C'),self.store,FakeCipher()); other.control=self.control
        args=dict(set_name='synthetic',source_name='C',profile='native-age-v1',policy='stop',
                  recipients=self.config['recipients'],key_reference='stdin',set_id=self.config['set_id'])
        configured=other.initialize(**args); config=other.load(configured['set_id'],configured['source_id'])
        source=self.sources[0][0]
        destination=other.home/'sessions'/source.name
        destination.parent.mkdir(); destination.write_bytes(source.read_bytes())
        second=other.run(config,b'synthetic identity')
        with self.assertRaisesRegex(TransferError,'unambiguous'):
            self.a.latest()
        self.assertNotEqual(self.catalog(first['checkpoint_id'])['heads'][0]['version_key'],
                            self.catalog(second['checkpoint_id'])['heads'][0]['version_key'])
        self.assertEqual(len(self.b.restore('latest',b'synthetic identity',self.cwd,
            set_id=config['set_id'],source_id=config['source_id'])['sessions']),1)

    def test_excluded_agent_is_classified_before_copy(self):
        real=__import__('csl_backup_engine').capture
        observed=[]
        def capture(source,target):
            observed.append(source)
            return real(source,target)
        with patch('csl_backup_engine.capture',side_effect=capture):
            self.run_backup()
        self.assertNotIn(self.sources[2][0],observed)

    def test_same_run_resume_fences_the_paused_original_execution(self):
        real=self.store.publish
        original_epoch=[]
        completed=[]
        def pause_after_post(identifier,ciphertext,kind,**kwargs):
            published=real(identifier,ciphertext,kind,**kwargs)
            if kind=='o' and not completed:
                item=self.control.state['sets'][self.config['set_id']]
                run_id=item['owner']; original_epoch.append(item['epoch'])
                self.control.clock+=1000
                other=Backup(csl(self.root/'resumer'),self.store,FakeCipher())
                other.control=self.control
                completed.append(other.run(self.config,b'synthetic identity',resume=run_id))
            return published
        with patch.object(self.store,'publish',side_effect=pause_after_post):
            with self.assertRaises(BackupBusy):
                self.run_backup()
        item=self.control.state['sets'][self.config['set_id']]
        self.assertGreater(item['epoch'],original_epoch[0])
        source=item['sources'][self.config['source_id']]
        self.assertEqual(source['latest_complete'],completed[0]['checkpoint_id'])
        self.assertEqual(source['catalog']['commit_epoch'],item['epoch'])
        self.assertEqual(source['catalog']['lease_epoch'],original_epoch[0])
        self.assertEqual(len(self.b.restore('latest',b'synthetic identity',self.cwd)['sessions']),2)

    def test_admission_budget_precedes_capture_and_discovery_never_truncates(self):
        with patch('csl_backup_engine.CAPTURE_BUDGET',1), \
             patch('csl_backup_engine.capture',side_effect=AssertionError('budget copied bytes')):
            with self.assertRaisesRegex(TransferError,'No protected'):
                self.run_backup()
        self.assertFalse(self.store.releases_by_tag)
        with patch('csl_backup_engine.SOURCE_ENTRY_BUDGET',1):
            with self.assertRaisesRegex(TransferError,'discovery exceeds'):
                self.run_backup()
        self.assertFalse(self.store.releases_by_tag)

    def test_rule_version_change_creates_new_keys_and_preserves_old_checkpoint(self):
        first=self.run_backup(); previous=self.catalog(first['checkpoint_id'])
        with patch('csl_backup_format.EXPORTER_VERSION',3):
            result=self.run_backup()
        self.assertEqual(result['counts']['captured'],2)
        self.assertEqual(result['counts']['reused'],0)
        changed=self.catalog(result['checkpoint_id'])
        self.assertNotEqual(previous['heads'][0]['version_key'],changed['heads'][0]['version_key'])
        self.assertEqual(len(self.b.restore(first['checkpoint_id'],b'synthetic identity',self.cwd)['sessions']),2)

    def test_archive_transition_creates_new_key_without_rewriting_old_pack(self):
        first=self.run_backup()
        path=self.sources[0][0]
        moved=self.a.home/'archived_sessions'/path.name
        path.rename(moved)
        result=self.run_backup()
        self.assertEqual(result['counts']['captured'],1)
        self.assertEqual(result['counts']['reused'],1)
        restored=self.b.restore('latest',b'synthetic identity',self.cwd)
        self.assertTrue(all(m['state']=='archived' for m in restored['sessions']))
        self.assertEqual(len(self.b.restore(first['checkpoint_id'],b'synthetic identity',self.cwd)['sessions']),2)

    def test_partial_new_pack_failure_reuses_verified_last_good_with_original_dates(self):
        first=self.run_backup(); old=self.catalog(first['checkpoint_id']); self.change()
        real=self.store.publish
        def fail(identifier,ciphertext,kind,**kwargs):
            if kind=='o': raise TransferError('synthetic unavailable')
            return real(identifier,ciphertext,kind,**kwargs)
        with patch.object(self.store,'publish',side_effect=fail): result=self.run_backup()
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['counts']['stale'],1)
        current=self.catalog(result['checkpoint_id'])
        stale=next(h for h in current['heads'] if h['state']=='stale')
        original=next(h for h in old['heads'] if h['member_id']==stale['member_id'])
        self.assertEqual(stale['last_observed_at'],original['last_observed_at'])

    def test_draft_cannot_be_restored_or_presented_as_complete(self):
        run_id=self.pending_run()
        plan=json_read(self.a.root/'runs'/run_id/'plan.json')
        with self.assertRaisesRegex(TransferError,'Draft'):
            self.b.restore(plan['checkpoint_id'],b'synthetic identity',self.cwd)
        self.assertFalse(list(self.b.home.rglob('rollout-*.jsonl')))

    def test_source_profile_change_resume_rejected_before_publication(self):
        run_id=self.pending_run()
        other={**self.config,'recipients':['age1'+'a'*58,'age1'+'d'*58]}
        before=len(self.store.bytes_by_id)
        with self.assertRaisesRegex(TransferError,'binding differs'):
            self.a.run(other,b'synthetic identity',resume=run_id)
        self.assertEqual(len(self.store.bytes_by_id),before)

    def test_duplicate_native_uuid_never_selects_arbitrary_good_candidate(self):
        self.run_backup()
        source=self.sources[0][0]
        duplicate=self.a.home/'sessions'/'duplicate'/source.name
        duplicate.parent.mkdir(); duplicate.write_bytes(source.read_bytes())
        result=self.run_backup()
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['counts']['reused'],1)
        self.assertEqual(result['counts']['stale'],1)

    def test_resume_pending_source_after_other_source_finished_same_set(self):
        run_id=self.pending_run()
        self.control.clock+=1000
        other_config={**self.config,'source_id':str(uuid.uuid4())}
        other=Backup(csl(self.root/'source-B'),self.store,FakeCipher()); other.control=self.control
        source=self.sources[0][0]; target=other.home/'sessions'/source.name
        target.parent.mkdir(parents=True); target.write_bytes(source.read_bytes())
        other.run(other_config,b'synthetic identity')
        prior_epoch=self.control.state['sets'][self.config['set_id']]['epoch']
        resumed=self.a.run(self.config,b'synthetic identity',resume=run_id)
        self.assertEqual(resumed['status'],'complete')
        self.assertGreater(self.control.state['sets'][self.config['set_id']]['epoch'],prior_epoch)
        self.assertEqual(len(self.control.state['sets'][self.config['set_id']]['sources']),2)

    def test_resume_pending_source_rejects_other_active_writer_or_retired_run(self):
        run_id=self.pending_run(); self.control.clock+=1000
        other_config={**self.config,'source_id':str(uuid.uuid4())}
        other_id=str(uuid.uuid4())
        epoch=self.a._lease(other_config,other_id,acquire=True)
        with self.assertRaises(BackupBusy):
            self.a.run(self.config,b'synthetic identity',resume=run_id)
        item=self.control.state['sets'][self.config['set_id']]
        self.assertEqual(item['epoch'],epoch)
        item['owner']=''; item['expires']=self.control.clock-1
        item['runs'][run_id]['retired']=True
        with self.assertRaises(BackupBusy):
            self.a.run(self.config,b'synthetic identity',resume=run_id)

    def test_schema_one_reader_compatibility_and_old_reader_rejects_two(self):
        result=self.run_backup(); catalog=self.catalog(result['checkpoint_id'])
        with self.assertRaises(TransferError): fmt.base(catalog,'catalog')
        old=copy.deepcopy(catalog)
        old['schema_version']=1
        old.pop('heads')
        old['counts']={'eligible':2,'succeeded':2,'failed':0,'excluded':1}
        self.assertEqual(fmt.catalog(old)['schema_version'],1)
        self.assertEqual(len(fmt.heads(old)),2)
        self.assertEqual(len(fmt.selected(old,old['containers'][0])),2)

    def test_recovered_plan_reserved_ids_and_bases_cannot_drift_even_with_valid_envelope(self):
        run_id=self.pending_run()
        item=self.control.state['sets'][self.config['set_id']]
        binding=copy.deepcopy(item['runs'][run_id]); original_epoch=item['epoch']
        release=self.store.resolve_release(binding['checkpoint_id'],'c')
        asset=next(a for a in release['assets'] if a['name']=='plan.age')
        original=self.store.bytes_by_id[asset['id']]
        plan=json.loads(original.removeprefix(b'SYNTHETIC-NOT-CRYPTO\n'))
        shutil.rmtree(self.a.root/'runs'/run_id)
        for field,value in (('checkpoint_id',str(uuid.uuid4())),('base_checkpoint',str(uuid.uuid4())),
                            ('base_source_checkpoint',str(uuid.uuid4())),('artifact_epoch',plan['artifact_epoch']+1)):
            changed=copy.deepcopy(plan); changed[field]=value
            payload=b'SYNTHETIC-NOT-CRYPTO\n'+json.dumps(changed).encode()
            self.store.bytes_by_id[asset['id']]=payload; asset['size']=len(payload)
            with self.subTest(field=field), \
                 patch.object(self.store,'publish',side_effect=AssertionError('unexpected asset POST')), \
                 patch.object(self.control,'change',side_effect=AssertionError('unexpected control mutation')):
                with self.assertRaisesRegex(TransferError,'intention binding'):
                    self.a.run(self.config,b'synthetic identity',resume=run_id)
            self.assertEqual(item['epoch'],original_epoch)
        self.store.bytes_by_id[asset['id']]=original; asset['size']=len(original)

    def test_local_plan_checkpoint_drift_is_rejected_before_acquire(self):
        run_id=self.pending_run(); plan_path=self.a.root/'runs'/run_id/'plan.json'
        plan=json_read(plan_path); plan['checkpoint_id']=str(uuid.uuid4()); plan_path.write_text(json.dumps(plan))
        with patch.object(self.control,'change',side_effect=AssertionError('unexpected control mutation')):
            with self.assertRaisesRegex(TransferError,'intention binding'):
                self.a.run(self.config,b'synthetic identity',resume=run_id)

    def test_new_partial_of_same_source_fences_old_pending_run_without_complete_change(self):
        complete=self.run_backup(); self.change()
        real=self.store.publish
        def crash(identifier,ciphertext,kind,**kwargs):
            if kind=='o': raise RuntimeError('old run interrupted')
            return real(identifier,ciphertext,kind,**kwargs)
        with patch.object(self.store,'publish',side_effect=crash):
            with self.assertRaises(RuntimeError): self.run_backup()
        item=self.control.state['sets'][self.config['set_id']]; old_run=item['owner']
        self.control.clock+=1000
        self.sources[0][0].write_bytes(self.sources[0][1]+b'BROKEN\n')
        partial=self.run_backup()
        source=item['sources'][self.config['source_id']]
        # FakeControl changes state via copy; re-read actual committed state.
        source=self.control.state['sets'][self.config['set_id']]['sources'][self.config['source_id']]
        self.assertEqual(partial['status'],'partial')
        self.assertEqual(source['latest_complete'],complete['checkpoint_id'])
        self.assertEqual(source['latest_partial'],partial['checkpoint_id'])
        with self.assertRaisesRegex(BackupBusy,'Source checkpoint changed'):
            self.a.run(self.config,b'synthetic identity',resume=old_run)
        self.assertEqual(self.a.latest()[2]['latest_partial'],partial['checkpoint_id'])

    def test_resume_rechecks_reused_reference_instead_of_committing_old_availability(self):
        complete=self.run_backup(); catalog=self.catalog(complete['checkpoint_id'])
        real=self.store.publish
        def crash(identifier,ciphertext,kind,**kwargs):
            if kind=='c': raise RuntimeError('before catalog')
            return real(identifier,ciphertext,kind,**kwargs)
        with patch.object(self.store,'publish',side_effect=crash):
            with self.assertRaises(RuntimeError): self.run_backup()
        run_id=self.control.state['sets'][self.config['set_id']]['owner']
        del self.store.releases_by_tag['cslb-v1-o-'+catalog['containers'][0]['container_id']]
        with self.assertRaisesRegex(TransferError,'No protected'):
            self.a.run(self.config,b'synthetic identity',resume=run_id)
        self.assertEqual(self.a.latest()[2]['latest_complete'],complete['checkpoint_id'])
