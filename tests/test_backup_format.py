"""Semantic cold-read contract negatives, separate from synthetic F0 schemas."""

import copy
import unittest
from unittest.mock import patch

from csl_backup_core import canonical, hash_bytes
import csl_backup_format as fmt
from csl_transfer import TransferError

UUID = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'


def catalog():
    fp = fmt.fingerprint({'profile':'native-age-v1', 'secret_policy':'stop',
                          'recipients':['age1'+'a'*58, 'age1'+'c'*58]})
    origin = {'set_id':UUID, 'source_id':UUID, 'provider':'codex', 'source_uuid':OTHER}
    identity = {'origin':origin, 'source_sha256':'a'*64, 'state':'interactive', 'fingerprint':fp}
    item = {'member_id':OTHER, 'version_key':hash_bytes(canonical(identity)), 'sha256':'a'*64,
        'bytes':100, 'origin':origin, 'state':'interactive', 'fingerprint':fp,
        'source_sha256':'a'*64, 'file':'members/'+OTHER+'.jsonl', 'losses':[], 'pending_tool_calls':[]}
    manifest = {'format':'csl-backup-container', 'schema_version':1, 'repo_id':123, 'set_id':UUID,
        'source_id':UUID, 'container_id':OTHER, 'run_id':UUID, 'fingerprint':fp, 'layout':'normal', 'members':[item]}
    return {'format':'csl-backup-catalog', 'schema_version':1, 'repo_id':123, 'lease_epoch':1, 'set_id':UUID,
        'source_id':UUID, 'run_id':UUID, 'checkpoint_id':UUID, 'fingerprint':fp, 'status':'complete',
        'failures':[], 'exclusions':[], 'selection':{'provider':'codex','archives':True,'agent_forks':False},
        'counts':{'eligible':1,'succeeded':1,'failed':0,'excluded':0},
        'containers':[{'container_id':OTHER,'sha256':'c'*64,'bytes':500,'asset_id':10,'release_id':11,'manifest':manifest}]}


class BackupFormatTests(unittest.TestCase):
    def test_valid_cold_catalog(self):
        fmt.catalog(catalog())

    def test_software_and_rules_versions_change_identity_but_old_compatible_reads(self):
        value=catalog()
        config={'profile':'native-age-v1','secret_policy':'stop',
                'recipients':['age1'+'a'*58,'age1'+'c'*58]}
        original=fmt.fingerprint(config)
        for owner,name,replacement in ((fmt.csl_version,'__version__','0.0.1'),
                                       (fmt,'EXPORTER_VERSION',fmt.EXPORTER_VERSION+1),
                                       (fmt.csl_secrets,'RULES_VERSION',fmt.csl_secrets.RULES_VERSION+1)):
            with patch.object(owner,name,replacement):
                changed=fmt.fingerprint(config)
                self.assertNotEqual(hash_bytes(canonical(original)),hash_bytes(canonical(changed)))
                fmt.validate_fingerprint(changed)  # Producer version, not current-client equality.
        legacy={key:val for key,val in original.items() if key not in ('csl_version','exporter_version','detector_version')}
        fmt.validate_fingerprint(legacy)

    def test_native_source_member_hash_cannot_differ_even_with_recomputed_version(self):
        data = catalog()
        item = data['containers'][0]['manifest']['members'][0]
        item['source_sha256'] = 'f'*64
        item['version_key'] = hash_bytes(canonical({'origin':item['origin'], 'source_sha256':item['source_sha256'],
                                                  'state':item['state'], 'fingerprint':item['fingerprint']}))
        with self.assertRaisesRegex(TransferError,'checksums differ'):
            fmt.catalog(data)

    def test_counts_missing_inconsistent_boolean_and_schema_bool_rejected(self):
        for key, value in (('eligible',100),('succeeded',True),('failed',1),('excluded',1)):
            data = catalog()
            data['counts'][key] = value
            with self.assertRaises(TransferError):
                fmt.catalog(data)
        data = catalog()
        data['schema_version'] = True
        with self.assertRaises(TransferError):
            fmt.catalog(data)

    def test_arbitrary_matching_fingerprints_do_not_make_known_profile(self):
        for key, value in (('cipher','plaintext'),('profile','unknown'),('recipients',[]),
                           ('secret_policy','scrub'),('exporter','invented')):
            data = catalog()
            # Even all nested copies matching must not validate an unknown profile.
            fp = {**data['fingerprint'], key:value}
            data['fingerprint'] = fp
            data['containers'][0]['manifest']['fingerprint'] = fp
            data['containers'][0]['manifest']['members'][0]['fingerprint'] = fp
            with self.assertRaises(TransferError):
                fmt.catalog(data)

    def test_wrong_set_source_profile_and_member_binding(self):
        for mutate in ('source','path','hash','profile','container'):
            data = catalog()
            item = data['containers'][0]['manifest']['members'][0]
            if mutate == 'source':
                item['origin']['source_id'] = OTHER
            elif mutate == 'path':
                item['file'] = '../escape'
            elif mutate == 'hash':
                item['version_key'] = '0'*64
            elif mutate == 'profile':
                item['fingerprint'] = {**item['fingerprint'], 'secret_policy':'retain'}
            else:
                data['containers'][0]['container_id'] = UUID
            with self.assertRaises(TransferError):
                fmt.catalog(data)


if __name__ == '__main__':
    unittest.main()
