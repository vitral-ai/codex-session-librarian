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


class MemoryReleaseAPI(GitHub):
    """HTTP state machine with accepted-write/lost-response boundaries, no network."""
    def __init__(self):
        self.rows=[]; self.contents={}; self.metadata={'default_branch':'main'}
        self.posts=[]; self.fail_after=set(); self.counter=1
    def revalidate(self,write=False):
        return None
    def releases(self):
        return iter(self.rows)
    def download(self,asset,target):
        from csl_backup_core import exclusive_output
        with exclusive_output(target) as staging:
            staging.write_bytes(self.contents[asset['id']])
    def request(self,method,suffix,body=None,*,upload=None):
        from csl_backup_store import RemoteError
        if method=='GET' and suffix.startswith('/git/ref/'):
            return {'object':{'sha':'synthetic-base'}}
        if method=='GET' and suffix.startswith('/releases/'):
            return next(r for r in self.rows if r['id']==int(suffix.split('/')[2]))
        if method=='POST' and suffix=='/releases':
            self.posts.append(suffix)
            self.counter+=1
            value={'id':self.counter,'assets':[],**body}; self.rows.append(value)
            key='release'
        elif method=='POST' and '/assets?name=' in suffix:
            self.posts.append(suffix)
            release=next(r for r in self.rows if r['id']==int(suffix.split('/')[2]))
            name=suffix.split('name=')[1]
            if any(a['name']==name for a in release['assets']): raise RemoteError(422)
            self.counter+=1
            value={'id':self.counter,'name':name,'size':Path(upload).stat().st_size}
            self.contents[value['id']]=Path(upload).read_bytes(); release['assets'].append(value)
            key=name
        elif method=='PATCH':
            value=next(r for r in self.rows if r['id']==int(suffix.split('/')[2]))
            value.update(body); key='finalize'
        else:
            raise AssertionError((method,suffix))
        if key in self.fail_after:
            self.fail_after.remove(key)
            raise RemoteError(0)
        return value


class DurablePublicationTests(unittest.TestCase):
    def test_every_accepted_post_lost_response_is_adopted_once_without_overwrite(self):
        for lost in ('release','container.age','descriptor.json'):
            with self.subTest(lost=lost),tempfile.TemporaryDirectory() as d:
                client=MemoryReleaseAPI(); client.fail_after.add(lost)
                ciphertext=Path(d)/'cipher.age'; ciphertext.write_bytes(b'SYNTHETIC ciphertext')
                first=client.publish('11111111-1111-4111-8111-111111111111',ciphertext,'o')
                ciphertext.write_bytes(b'DIFFERENT regenerated random ciphertext')
                second=client.publish('11111111-1111-4111-8111-111111111111',ciphertext,'o')
                self.assertEqual(first['asset']['id'],second['asset']['id'])
                self.assertEqual(len(client.rows),1)
                self.assertEqual(len(client.posts),3)
                self.assertEqual(client.contents[first['asset']['id']],b'SYNTHETIC ciphertext')
                self.assertTrue(client.rows[0]['draft'])
                client.fail_after.add('finalize')
                client.finalize('11111111-1111-4111-8111-111111111111','o',first['release_id'])
                self.assertFalse(client.rows[0]['draft'])

    def test_checkpoint_plan_and_catalog_use_same_draft_release_four_assets(self):
        with tempfile.TemporaryDirectory() as d:
            client=MemoryReleaseAPI(); path=Path(d)/'synthetic.age'; path.write_bytes(b'SYNTHETIC')
            identifier='11111111-1111-4111-8111-111111111111'
            reserved=client.reserve(identifier)
            plan=client.publish(identifier,path,'p',release_id=reserved['id'])
            catalog=client.publish(identifier,path,'c',release_id=reserved['id'])
            self.assertEqual(plan['release_id'],catalog['release_id'])
            self.assertEqual(len(client.rows),1)
            self.assertEqual({a['name'] for a in client.rows[0]['assets']},
                             {'plan.age','plan-descriptor.json','catalog.age','descriptor.json'})
            self.assertTrue(client.rows[0]['draft'])

    def test_recover_asset_accepted_without_descriptor_never_uses_new_random_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            client=MemoryReleaseAPI(); path=Path(d)/'synthetic.age'; path.write_bytes(b'SYNTHETIC original')
            identifier='11111111-1111-4111-8111-111111111111'
            result=client.publish(identifier,path,'o')
            client.rows[0]['assets']=[a for a in client.rows[0]['assets'] if a['name']!='descriptor.json']
            path.write_bytes(b'NEW random bytes')
            adopted=client.publish(identifier,path,'o')
            envelope=client.read_envelope(client.rows[0],identifier)
            from csl_backup_core import hash_bytes
            self.assertEqual(envelope['sha256'],hash_bytes(b'SYNTHETIC original'))
            self.assertEqual(adopted['asset']['id'],result['asset']['id'])
