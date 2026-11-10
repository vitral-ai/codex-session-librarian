"""Output ownership and provider-bound transport tests without network."""

from pathlib import Path
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from csl_backup_store import GitHub
from csl_transfer import TransferError


class BackupDownloadOwnershipTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.client = object.__new__(GitHub)

    def test_existing_and_symlink_never_opened_or_removed(self):
        target = self.root / 'existing'
        target.write_bytes(b'sentinel')
        link = self.root / 'symlink'
        link.symlink_to(target)
        with patch.object(self.client, '_download_to', side_effect=AssertionError('must not download')):
            for path in (target, link):
                with self.assertRaises(TransferError):
                    self.client.download({}, path)
        self.assertEqual(target.read_bytes(), b'sentinel')
        self.assertTrue(link.is_symlink())

    def test_partial_download_only_cleans_owned_output(self):
        target = self.root / 'new'
        def fail(asset, temporary):
            temporary.write_bytes(b'partial')
            raise TransferError('synthetic interruption')
        with patch.object(self.client, '_download_to', side_effect=fail):
            with self.assertRaises(TransferError):
                self.client.download({}, target)
        self.assertFalse(target.exists())
        self.assertFalse(list(self.root.glob('.csl-output-*')))

    def test_racing_destination_kept(self):
        target = self.root / 'racing'
        def download(asset, temporary):
            temporary.write_bytes(b'complete')
            target.write_bytes(b'racing sentinel')
        with patch.object(self.client, '_download_to', side_effect=download):
            with self.assertRaises(TransferError):
                self.client.download({}, target)
        self.assertEqual(target.read_bytes(), b'racing sentinel')


class BackupDestinationRecheckTests(unittest.TestCase):
    def test_private_constructor_then_public_changed_id_or_revoked_write_sends_zero_posts(self):
        for alteration in ({'private':False},{'id':456},{'permissions':{'push':False}}):
            with self.subTest(alteration=alteration),tempfile.TemporaryDirectory() as directory:
                metadata={'id':123,'private':True,'full_name':'synthetic/private','default_branch':'main','permissions':{'push':True}}
                def response(value):
                    return SimpleNamespace(returncode=0,stdout=(
                        'HTTP/2.0 200 OK\nDate: Tue, 10 Nov 2026 00:00:00 GMT\n\n'+json.dumps(value)).encode())
                replies=[response(metadata),response({**metadata,**alteration})]
                with patch('csl_backup_store.shutil.which',return_value='/synthetic/gh'), \
                     patch('csl_backup_store.subprocess.run',side_effect=replies) as run:
                    client=GitHub('synthetic/private',expected_id=123)
                    cipher=Path(directory)/'synthetic.age'
                    cipher.write_bytes(b'synthetic ciphertext')
                    with self.assertRaises(TransferError):
                        client.publish('11111111-1111-4111-8111-111111111111',cipher,'o')
                self.assertEqual(len(run.call_args_list),2)
                self.assertTrue(all(call.args[0][call.args[0].index('--method')+1]=='GET' for call in run.call_args_list))


if __name__ == '__main__':
    unittest.main()
