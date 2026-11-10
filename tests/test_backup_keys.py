"""Synthetic F3 public plans, stale-state and crash-fence tests; fake cipher is not crypto evidence."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

import csl_backup_format as fmt
from csl_backup_core import BackupBusy, BackupStale, canonical, json_read, save
from csl_backup_keys import (apply_rotation, configuration_path, epoch_id, epochs, key_binding,
                             list_epochs, plan_rotation)
from csl_transfer import TransferError
import test_backup_engine as fixtures


class KeyRotationTests(unittest.TestCase):
    setUp = fixtures.BackupEngineTests.setUp
    run_backup = fixtures.BackupEngineTests.run_backup
    recipients = ['age1'+'d'*58, 'age1'+'e'*58]

    def plan(self):
        return plan_rotation(self.a,self.config,self.recipients)

    def apply(self,planned):
        result=apply_rotation(self.a,self.config,Path(planned['plan']))
        self.config=self.a.load(self.config['set_id'])
        return result

    def test_future_rotation_changes_keys_preserves_historical_assets_and_does_not_inherit_evidence(self):
        first=self.run_backup()
        before=copy.deepcopy(self.store.bytes_by_id)
        events=list((self.a.root/'events').glob('*.json'))
        planned=self.plan(); result=self.apply(planned)
        self.assertTrue(result['future_only'])
        self.assertEqual(self.store.bytes_by_id,before)
        self.assertEqual(list((self.a.root/'events').glob('*.json')),events)
        self.assertEqual(self.config['recipients'],self.recipients)
        self.assertEqual(self.config['profile_epoch'],planned['new_epoch'])
        self.assertEqual(len(epochs(self.config)),2)
        self.assertIn(first['checkpoint_id'],epochs(self.config)[0]['known_checkpoints'])
        second=self.run_backup()
        self.assertEqual(second['counts']['captured'],2)
        self.assertEqual(second['counts']['reused'],0)
        with tempfile.TemporaryDirectory() as d:
            new=self.a._read_checkpoint(second['checkpoint_id'],b'synthetic identity',Path(d),metadata_only=True)[0]
        self.assertEqual(new['fingerprint']['profile_epoch'],planned['new_epoch'])
        self.assertFalse(any('restored' in c for c in new['containers']))
        self.assertEqual(len(self.b.restore(first['checkpoint_id'],b'synthetic identity',self.cwd)['sessions']),2)
        self.assertEqual(len(self.b.restore(second['checkpoint_id'],b'synthetic identity',self.cwd)['sessions']),2)

    def test_plan_is_public_only_bound_and_has_zero_remote_mutations(self):
        self.run_backup()
        before=copy.deepcopy(self.control.state)
        with patch.object(self.control,'change',side_effect=AssertionError('planning wrote control')):
            result=self.plan()
        self.assertEqual(before,self.control.state)
        value=json_read(result['plan'])
        self.assertEqual(value['scope'],'future-only-one-source')
        self.assertEqual(value['affected_sources'],[self.config['source_id']])
        self.assertNotIn('AGE-SECRET-KEY',Path(result['plan']).read_text())
        self.assertEqual(value['new_recipients'],self.recipients)
        self.assertEqual(value['profile'],'native-age-v1')
        self.assertEqual(value['secret_policy'],'stop')

    def test_changed_plan_rejected_before_control_write_even_public_recipient(self):
        self.run_backup(); planned=self.plan(); path=Path(planned['plan'])
        value=json_read(path); value['new_epoch']=str(uuid.uuid4()); save(path,value)
        with patch.object(self.control,'change',side_effect=AssertionError('unexpected write')):
            with self.assertRaises(BackupStale): self.apply(planned)

    def test_changed_config_or_producer_or_remote_generation_makes_plan_stale(self):
        self.run_backup(); planned=self.plan()
        path=configuration_path(self.a.root,self.config['set_id'])
        original=json_read(path)
        changed={**original,'source_name':'changed public label'}; save(path,changed)
        with self.assertRaises(BackupStale): self.apply(planned)
        save(path,original)
        with patch('csl_backup_format.EXPORTER_VERSION',fmt.EXPORTER_VERSION+1):
            with self.assertRaises(BackupStale): self.apply(planned)
        self.control.state['sets'][self.config['set_id']]['epoch']+=1
        with self.assertRaises(BackupStale): self.apply(planned)
        self.assertEqual(json_read(path),original)

    def test_active_writer_blocks_and_expired_writer_is_fenced(self):
        self.run_backup()
        run_id=str(uuid.uuid4())
        base=self.a.latest()[2]['latest_complete']
        epoch=self.a._lease(self.config,run_id,acquire=True,base_checkpoint=base)
        planned=self.plan()
        with self.assertRaises(BackupBusy): self.apply(planned)
        self.control.clock+=1000
        old=copy.deepcopy(self.config)
        self.apply(planned)
        with self.assertRaises(BackupStale):
            self.a._lease(old,run_id,expected_epoch=epoch,base_checkpoint=base)
        with self.assertRaises(BackupStale):
            self.a.run(old,b'synthetic identity')

    def test_apply_crash_after_remote_commit_retries_without_second_control_mutation(self):
        self.run_backup(); planned=self.plan(); original=copy.deepcopy(self.config)
        real=__import__('csl_backup_keys').save
        config_path=configuration_path(self.a.root,self.config['set_id'])
        def fail(path,value,**kwargs):
            if Path(path)==config_path: raise OSError('synthetic disk failure after remote commit')
            return real(path,value,**kwargs)
        with patch('csl_backup_keys.save',side_effect=fail):
            with self.assertRaises(OSError): self.apply(planned)
        self.assertEqual(json_read(config_path),original)
        with patch.object(self.control,'change',side_effect=AssertionError('duplicate control mutation')):
            result=self.apply(planned)
        self.assertEqual(result['status'],'applied')
        with patch.object(self.control,'change',side_effect=AssertionError('repeat control mutation')):
            repeated=self.apply(planned)
        self.assertEqual(repeated['profile_epoch'],result['profile_epoch'])

    def test_lost_control_success_response_and_local_journal_reconcile_stable_result(self):
        self.run_backup(); planned=self.plan()
        real=self.control.change
        def lost(mutate):
            real(mutate)
            raise TransferError('synthetic accepted CAS response lost')
        with patch.object(self.control,'change',side_effect=lost):
            with self.assertRaises(TransferError): self.apply(planned)
        for path in (self.a.root/'key-rotations').glob('*.json'): path.unlink()
        with patch.object(self.control,'change',side_effect=AssertionError('duplicate remote change')):
            self.apply(planned)
        self.assertEqual(len(epochs(self.config)),2)

    def test_old_plan_never_rolls_back_a_later_rotation(self):
        self.run_backup(); first=self.plan(); self.apply(first)
        second=plan_rotation(self.a,self.config,['age1'+'f'*58,'age1'+'g'*58])
        self.apply(second)
        before=copy.deepcopy(self.config)
        with self.assertRaises(BackupStale): self.apply(first)
        self.assertEqual(self.a.load(self.config['set_id']),before)

    def test_old_pending_resume_cannot_publish_after_rotation(self):
        self.run_backup()
        source=self.sources[0][0]; source.write_bytes(source.read_bytes()+b'\n')
        real=self.store.publish
        def stop(identifier,ciphertext,kind,**kwargs):
            if kind=='o': raise RuntimeError('old writer paused')
            return real(identifier,ciphertext,kind,**kwargs)
        with patch.object(self.store,'publish',side_effect=stop):
            with self.assertRaises(RuntimeError): self.run_backup()
        old=copy.deepcopy(self.config)
        run_id=self.control.state['sets'][self.config['set_id']]['owner']
        self.control.clock+=1000
        self.apply(self.plan())
        with self.assertRaises(BackupStale): self.a.run(old,b'synthetic identity',resume=run_id)
        with self.assertRaisesRegex(TransferError,'profile/rules'):
            self.a.run(self.config,b'synthetic identity',resume=run_id)

    def test_native_scrub_private_recipients_unchanged_and_unsafe_reference_rejected(self):
        self.run_backup()
        for config,recipients,reference in ((self.config,self.config['recipients'],None),
                (self.config,['AGE-SECRET-KEY-SYNTHETIC','age1'+'d'*58],None),
                (self.config,self.recipients,'/private-key-file'),
                ({**self.config,'secret_policy':'scrub'},self.recipients,None),
                ({**self.config,'secret_policy':'retain','retain_accepted':False},self.recipients,None)):
            with self.subTest(reference=reference):
                with self.assertRaises(TransferError): plan_rotation(self.a,config,recipients,key_reference=reference)

    def test_configuration_selection_is_explicit_when_multiple_origins_exist(self):
        self.run_backup()
        other={**self.config,'source_id':str(uuid.uuid4()),'source_name':'other'}
        save(self.a.root/'sets'/self.config['set_id']/(other['source_id']+'.json'),other)
        with self.assertRaises(TransferError): configuration_path(self.a.root,self.config['set_id'])
        selected=configuration_path(self.a.root,self.config['set_id'],other['source_id'])
        self.assertEqual(json_read(selected)['source_id'],other['source_id'])
        self.assertEqual(list_epochs(self.a,self.config)['active_epoch'],epoch_id(self.config))

    def test_cli_plan_apply_list_and_stale_exit_have_no_private_identity_argument(self):
        import contextlib
        import io
        import csl_backup
        import codex_sessions
        self.run_backup()
        def invoke(parts):
            args=codex_sessions.build_parser().parse_args(['backup','keys',*parts,'--set',self.config['set_id'],'--json'])
            with patch.object(csl_backup,'GitHub',return_value=self.store), \
                 patch.object(csl_backup,'Age',return_value=self.a.age), \
                 patch.object(csl_backup,'Backup',return_value=self.a), contextlib.redirect_stdout(io.StringIO()):
                return csl_backup.command(args,self.a.csl)
        planned=invoke(['plan','--recipient',self.recipients[0],'--recipient',self.recipients[1]])
        result=invoke(['apply','--plan',planned['plan']])
        self.assertEqual(result['status'],'applied')
        listed=invoke(['list'])
        self.assertEqual(len(listed['epochs']),2)
        self.assertEqual(listed['active_epoch'],planned['new_epoch'])
        plan=json_read(planned['plan']); plan['new_epoch']=str(uuid.uuid4()); save(planned['plan'],plan)
        with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit) as error:
            invoke(['apply','--plan',planned['plan']])
        self.assertEqual(error.exception.code,5)
        self.assertEqual(csl_backup.last_attempt(self.a.root)['result'],'failed')

    def test_bad_recipient_probe_or_age_failure_leaves_old_config_and_control_unchanged(self):
        self.run_backup(); original=copy.deepcopy(self.config); before=copy.deepcopy(self.control.state)
        with patch.object(self.a.age,'encrypt',side_effect=TransferError('synthetic age failure')):
            with self.assertRaises(TransferError): self.plan()
        planned=self.plan()
        with patch.object(self.a.age,'encrypt',side_effect=TransferError('synthetic age failure')):
            with self.assertRaises(TransferError): self.apply(planned)
        self.assertEqual(self.control.state,before)
        self.assertEqual(self.a.load(self.config['set_id']),original)

    def test_epoch_identity_is_stable_across_producer_upgrade_but_new_versions_are_not(self):
        self.run_backup(); self.apply(self.plan())
        binding=key_binding(self.config)
        with patch('csl_backup_format.EXPORTER_VERSION',fmt.EXPORTER_VERSION+1):
            self.assertEqual(key_binding(self.config),binding)
            result=self.run_backup()
        self.assertEqual(result['counts']['captured'],2)

    def test_unknown_private_field_in_epoch_map_is_rejected(self):
        self.run_backup(); self.apply(self.plan())
        changed=copy.deepcopy(self.config); changed['key_epochs'][0]['private_key']='SYNTHETIC-NEVER-ACCEPT'
        with self.assertRaises(TransferError): epochs(changed)

    def test_failure_after_local_config_before_receipt_keeps_same_epoch_on_retry(self):
        self.run_backup(); planned=self.plan()
        real=__import__('csl_backup_keys').save
        def fail(path,value,**kwargs):
            if Path(path).parent.name=='key-rotations' and value.get('state')=='applied':
                raise OSError('synthetic receipt failure after config write')
            return real(path,value,**kwargs)
        with patch('csl_backup_keys.save',side_effect=fail):
            with self.assertRaises(OSError): self.apply(planned)
        changed=self.a.load(self.config['set_id'])
        self.assertEqual(changed['profile_epoch'],planned['new_epoch'])
        with patch.object(self.control,'change',side_effect=AssertionError('duplicate rotation')):
            self.apply(planned)
        self.assertEqual(len(epochs(self.config)),2)

    def test_local_edit_after_remote_commit_is_a_conflict_not_overwritten(self):
        self.run_backup(); planned=self.plan()
        real=__import__('csl_backup_keys').save
        path=configuration_path(self.a.root,self.config['set_id'])
        def fail(target,value,**kwargs):
            if Path(target)==path: raise OSError('synthetic local install failure')
            return real(target,value,**kwargs)
        with patch('csl_backup_keys.save',side_effect=fail):
            with self.assertRaises(OSError): self.apply(planned)
        changed={**self.config,'source_name':'user edit retained'}; save(path,changed)
        with self.assertRaises(BackupStale): self.apply(planned)
        self.assertEqual(json_read(path),changed)

    def test_remote_result_id_drift_cannot_reconcile_even_after_local_install(self):
        self.run_backup(); planned=self.plan(); self.apply(planned)
        record=self.control.state['sets'][self.config['set_id']]['key_rotations'][planned['plan_id']]
        record['from_checkpoint']=str(uuid.uuid4())
        with patch.object(self.control,'change',side_effect=AssertionError('unexpected control change')):
            with self.assertRaises(BackupStale): self.apply(planned)

    def test_portable_scrub_and_accepted_retain_remain_explicit_during_rotation(self):
        self.run_backup()
        for profile,policy,accepted in (('portable-age-v1','scrub',False),('native-age-v1','retain',True)):
            changed={**self.config,'profile':profile,'secret_policy':policy,'retain_accepted':accepted}
            path=configuration_path(self.a.root,changed['set_id'])
            save(path,changed)
            planned=plan_rotation(self.a,changed,self.recipients)
            result=apply_rotation(self.a,changed,Path(planned['plan']))
            active=self.a.load(changed['set_id'])
            self.assertEqual(active['profile'],profile)
            self.assertEqual(active['secret_policy'],policy)
            self.assertEqual(active['retain_accepted'],accepted)
            # Isolate the next scenario by restoring the synthetic pre-rotation
            # control/config, not by mutating real provider state.
            self.control.state['sets'][changed['set_id']]['sources'][changed['source_id']].pop('key_profile_binding',None)
            save(path,self.config)

    def test_offline_epoch_list_constructs_neither_transport_nor_cipher(self):
        import contextlib
        import io
        import csl_backup
        import codex_sessions
        args=codex_sessions.build_parser().parse_args(['backup','keys','list','--set',self.config['set_id']])
        with patch.object(csl_backup,'GitHub') as remote, patch.object(csl_backup,'Age') as age, \
             contextlib.redirect_stdout(io.StringIO()):
            value=csl_backup.command(args,self.a.csl)
        remote.assert_not_called(); age.assert_not_called()
        self.assertEqual(value['active_epoch'],epoch_id(self.config))

    def test_restore_pointer_key_epoch_is_bound_to_immutable_catalog_profile(self):
        self.run_backup(); self.apply(self.plan()); self.run_backup()
        source=self.control.state['sets'][self.config['set_id']]['sources'][self.config['source_id']]
        source['catalog']['profile_epoch']=str(uuid.uuid4())
        with self.assertRaisesRegex(TransferError,'key epoch differs'):
            self.b.restore('latest',b'synthetic identity',self.cwd)
        self.assertFalse(list(self.b.home.rglob('rollout-*.jsonl')))

    def test_reduced_plan_config_budgets_fail_before_remote_mutation(self):
        self.run_backup(); before=copy.deepcopy(self.control.state); original=copy.deepcopy(self.config)
        with patch('csl_backup_keys.MAX_MANIFEST',1):
            with self.assertRaisesRegex(TransferError,'metadata budget'): self.plan()
        planned=self.plan()
        with patch('csl_backup_keys.MAX_MANIFEST',1):
            with self.assertRaisesRegex(TransferError,'metadata budget'): self.apply(planned)
        self.assertEqual(self.control.state,before)
        self.assertEqual(self.a.load(self.config['set_id']),original)

    def test_boolean_control_generation_is_not_a_valid_rotation_baseline(self):
        self.run_backup()
        self.control.state['sets'][self.config['set_id']]['epoch']=True
        with patch.object(self.control,'change',side_effect=AssertionError('malformed baseline wrote control')):
            with self.assertRaises(TransferError): self.plan()
