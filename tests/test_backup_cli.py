"""CLI safety checks without remote writes, auth or personal histories."""

import contextlib
import io
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import csl_backup
from csl_backup_crypto import BackupPolicyError
from csl_backup_store import RemoteError
from csl_backup_core import save
import codex_sessions


class BackupCLITests(unittest.TestCase):
    def test_preparatory_failures_replace_old_passed_attempt(self):
        for failure in ('stdin','age','keyring','transport'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                home=Path(directory)
                sid='11111111-1111-4111-8111-111111111111'
                origin='22222222-2222-4222-8222-222222222222'
                config={'format':'csl-backup-config','schema_version':1,'repo':'synthetic/private','repo_id':123,
                    'set_id':sid,'source_id':origin,'profile':'native-age-v1','secret_policy':'stop',
                    'recipients':['age1'+'a'*58,'age1'+'c'*58],
                    'key_reference':'keyring:'+sid if failure=='keyring' else 'stdin'}
                root=home/'csl-backup'
                save(root/'sets'/(sid+'.json'),config)
                save(root/'attempts/old.json',{'started_at':'2020-01-01T00:00:00Z','set_id':sid,'source_id':origin,'result':'passed'})
                args=codex_sessions.build_parser().parse_args(['backup','run','--set',sid])
                gh=SimpleNamespace(repo_id=123)
                with patch.object(csl_backup,'GitHub',return_value=gh) as remote, \
                     patch.object(csl_backup,'Age') as age, contextlib.redirect_stderr(io.StringIO()):
                    if failure=='transport':
                        remote.side_effect=RemoteError(0)
                    if failure=='age':
                        age.side_effect=BackupPolicyError('synthetic missing age')
                    keyring = patch('csl_backup_crypto.shutil.which',return_value=None) if failure=='keyring' else contextlib.nullcontext()
                    with keyring:
                        with self.assertRaises(SystemExit):
                            csl_backup.command(args,SimpleNamespace(DEFAULT_CODEX_HOME=home))
                latest=csl_backup.last_attempt(root,sid,origin)
                self.assertEqual(latest['result'],'failed')
                self.assertEqual(latest['stage'],'preparing')
                self.assertNotEqual(latest['started_at'],'2020-01-01T00:00:00Z')

    def test_failed_attempt_persistence_blocks_operation_explicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            args=codex_sessions.build_parser().parse_args(['backup','run','--set','11111111-1111-4111-8111-111111111111'])
            error=io.StringIO()
            with patch.object(csl_backup,'save',side_effect=OSError('synthetic disk failure')), \
                 patch.object(csl_backup,'GitHub') as remote,contextlib.redirect_stderr(error):
                with self.assertRaises(SystemExit):
                    csl_backup.command(args,SimpleNamespace(DEFAULT_CODEX_HOME=Path(directory)))
                remote.assert_not_called()
            self.assertIn('operation not started',error.getvalue())
            self.assertIn('cached status may be stale',error.getvalue())

    def test_explicit_wrong_source_rejected_before_remote_client(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory)
            config={'format':'csl-backup-config','schema_version':1,'repo':'synthetic/private','repo_id':123,
                'set_id':'11111111-1111-4111-8111-111111111111','source_id':'22222222-2222-4222-8222-222222222222',
                'profile':'native-age-v1','secret_policy':'stop','recipients':['age1'+'a'*58,'age1'+'c'*58],
                'key_reference':'stdin'}
            save(home/'csl-backup/sets'/ (config['set_id']+'.json'),config)
            args=codex_sessions.build_parser().parse_args(['backup','run','--set',config['set_id'],
                '--source','33333333-3333-4333-8333-333333333333'])
            with patch.object(csl_backup,'GitHub') as remote, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    csl_backup.command(args,SimpleNamespace(DEFAULT_CODEX_HOME=home))
                self.assertEqual(error.exception.code,2)
                remote.assert_not_called()

    def test_cached_status_does_not_construct_network_or_crypto(self):
        with tempfile.TemporaryDirectory() as directory:
            args=codex_sessions.build_parser().parse_args(['backup','status','--cached','--json'])
            with patch.object(csl_backup,'GitHub') as remote, patch.object(csl_backup,'Age') as age, contextlib.redirect_stdout(io.StringIO()):
                result=csl_backup.command(args,SimpleNamespace(DEFAULT_CODEX_HOME=Path(directory)))
            remote.assert_not_called()
            age.assert_not_called()
            self.assertEqual(result['remote'],'unknown; not queried')


if __name__=='__main__':
    unittest.main()
