"""Reviewed, future-only recipient rotation. No private keys or historical rewrites."""
import copy
import re
from pathlib import Path
import tempfile
import uuid

import csl_backup_format as fmt
from csl_backup_core import (BackupBusy, BackupStale, MAX_MANIFEST, NAMESPACE, canonical, hash_bytes,
                             json_read, locked, now, save, uid)
from csl_backup_crypto import Age, BackupPolicyError
from csl_transfer import TransferError


def configuration_path(root, set_id, source_id=None):
    uid(set_id)
    if source_id:
        uid(source_id)
    primary = root / 'sets' / (set_id + '.json')
    candidates = ([primary] if primary.exists() else []) + list((root / 'sets' / set_id).glob('*.json'))
    selected = []
    for path in candidates:
        config = fmt.config(json_read(path))
        if config['set_id'] == set_id and (source_id is None or config['source_id'] == source_id):
            selected.append(path)
    if len(selected) != 1:
        raise TransferError('Select one existing local set/source configuration; rotation never adopts a lost source')
    return selected[0]


def rotation_config(config):
    fmt.config(config)
    allowed = {'format', 'schema_version', 'repo', 'repo_id', 'set_id', 'source_id', 'set_name', 'source_name',
               'profile', 'secret_policy', 'recipients', 'key_reference', 'retain_accepted', 'agent_forks',
               'created_at', 'profile_epoch', 'key_epochs'}
    if set(config) - allowed:
        raise BackupPolicyError('Unknown rotation configuration fields; no private material accepted')
    return config


def crypto_profile(config):
    return {'profile': config['profile'], 'cipher': 'age-v1-x25519',
            'recipients': Age.recipients(config['recipients']), 'secret_policy': config['secret_policy']}


def epoch_id(config):
    if 'profile_epoch' in config:
        return uid(config['profile_epoch'])
    return str(uuid.uuid5(NAMESPACE, canonical({'repo_id': config['repo_id'], 'set_id': config['set_id'],
        'source_id': config['source_id'], **crypto_profile(config)}).decode()))


def key_binding(config):
    return hash_bytes(canonical({**crypto_profile(config), 'profile_epoch': epoch_id(config)}))


def config_hash(config):
    return hash_bytes(canonical(config))


def epochs(config):
    history = config.get('key_epochs')
    if 'key_epochs' not in config:
        return [{'epoch_id': epoch_id(config), **crypto_profile(config),
                 'activated_at': config['created_at'], 'known_checkpoints': [],
                 'custody_reference': config['key_reference'], 'provenance': 'legacy-config; not proof of key custody'}]
    if not isinstance(history, list) or not 0 < len(history) <= 10000:
        raise TransferError('Unknown/oversize public key epoch map')
    seen = set()
    for entry in history:
        fields = {'epoch_id', 'profile', 'cipher', 'recipients', 'secret_policy', 'activated_at',
                  'known_checkpoints', 'custody_reference', 'provenance'}
        if not isinstance(entry, dict) or set(entry) != fields or uid(entry.get('epoch_id')) in seen:
            raise TransferError('Duplicate/invalid key epoch identity')
        seen.add(entry['epoch_id'])
        Age.recipients(entry.get('recipients'))
        if entry.get('profile') not in ('native-age-v1', 'portable-age-v1') or entry.get('cipher') != 'age-v1-x25519':
            raise TransferError('Unknown epoch profile/cipher')
        fmt.timestamp(entry.get('activated_at'))
        reference = entry['custody_reference']
        if not isinstance(reference, str) or not (reference == 'stdin' or re.fullmatch(r'keyring:[0-9a-f-]{36}', reference)):
            raise TransferError('Unknown epoch custody reference; no private material allowed')
        if entry['provenance'] not in ('legacy-config; not proof of key custody',
                'future rotation; verification/restored evidence is per new object, not inherited'):
            raise TransferError('Unknown epoch provenance')
        if entry.get('secret_policy') not in ('stop', 'retain', 'scrub'):
            raise TransferError('Unknown epoch secret policy')
        if entry['profile'] == 'native-age-v1' and entry['secret_policy'] == 'scrub':
            raise BackupPolicyError('Native byte-exact epochs cannot scrub')
        if not isinstance(entry.get('known_checkpoints'), list):
            raise TransferError('Missing epoch checkpoint dependencies')
        for checkpoint in entry['known_checkpoints']:
            uid(checkpoint)
    if history[-1]['epoch_id'] != epoch_id(config) or any(history[-1].get(k) != v for k, v in crypto_profile(config).items()):
        raise TransferError('Active epoch map differs from current configuration')
    return copy.deepcopy(history)


def _snapshot(backup, config):
    _, state = backup.control.read()
    item = state['sets'].get(config['set_id'])
    if not isinstance(item, dict) or not isinstance(item.get('sources'), dict) or config['source_id'] not in item['sources']:
        raise TransferError('Rotation requires an already registered remote source')
    fmt.integer(item.get('epoch'))
    fmt.integer(item.get('expires'))
    if item.get('owner') != '':
        uid(item.get('owner'))
    for source_id in item['sources']:
        uid(source_id)
    source = item['sources'][config['source_id']]
    if not isinstance(source, dict):
        raise TransferError('Unknown source control shape')
    for key in ('latest_complete', 'latest_partial', 'latest_checkpoint', 'profile_epoch'):
        if source.get(key) is not None:
            uid(source[key])
    if source.get('key_profile_binding') is not None:
        fmt.checksum(source['key_profile_binding'])
    return item, source


def _probe(backup, recipients):
    # This proves the pinned CLI accepts PUBLIC recipients, not possession of
    # either private identity or unattended keyring availability.
    with tempfile.TemporaryDirectory(prefix='key-probe-', dir=backup.root) as directory:
        plain, encrypted = Path(directory) / 'public-probe.txt', Path(directory) / 'public-probe.age'
        plain.write_bytes(b'CSL synthetic public-recipient validation; no history\n')
        backup.age.encrypt(plain, encrypted, recipients)


def plan_rotation(backup, config, recipients, *, key_reference=None, output=None):
    rotation_config(config)
    if config['repo_id'] != backup.github.repo_id:
        raise TransferError('Configured rotation repository identity differs')
    recipients = Age.recipients(recipients)
    if recipients == Age.recipients(config['recipients']):
        raise BackupStale('Recipients are unchanged; no future key rotation to apply')
    proposed = {**config, 'recipients': recipients, 'key_reference': key_reference or config['key_reference'],
                'profile_epoch': str(uuid.uuid4())}
    proposed.pop('key_epochs', None)  # New map is built atomically only during apply.
    fmt.config(proposed)
    with locked(backup.root):
        path = configuration_path(backup.root, config['set_id'], config['source_id'])
        if config_hash(json_read(path)) != config_hash(config):
            raise BackupStale('Local configuration changed before planning')
        item, source = _snapshot(backup, config)
        if source.get('key_profile_binding') not in (None, key_binding(config)):
            raise BackupStale('Local key profile is superseded; reconcile its existing rotation first')
        history = epochs(config)
        _probe(backup, recipients)
        plan_id = str(uuid.uuid4())
        value = {'format': 'csl-backup-key-plan', 'schema_version': 1, 'plan_id': plan_id,
            'repo_id': config['repo_id'], 'set_id': config['set_id'], 'source_id': config['source_id'],
            'scope': 'future-only-one-source', 'affected_sources': [config['source_id']],
            'unaffected_sources': sorted(set(item['sources']) - {config['source_id']}),
            'created_at': now(), 'current_config_sha256': config_hash(config),
            'producer_fingerprint': fmt.fingerprint(config), 'current_key_binding': key_binding(config),
            'current_epoch': epoch_id(config), 'new_epoch': proposed['profile_epoch'],
            'current_recipients': Age.recipients(config['recipients']), 'new_recipients': recipients,
            'new_key_reference': proposed['key_reference'], 'profile': config['profile'],
            'secret_policy': config['secret_policy'], 'retain_accepted': config['retain_accepted'],
            'expected_set_epoch': item['epoch'], 'expected_remote_key_binding': source.get('key_profile_binding'),
            'base_complete': source.get('latest_complete'),
            'base_source_checkpoint': source.get('latest_checkpoint', source.get('latest_complete')),
            'base_partial': source.get('latest_partial'),
            'retained_epochs': history,
            'recovery_dependency': 'Keep external identities for every retained epoch; test each checkpoint before retiring any operational identity.',
            'limitations': ['No historical re-encryption or deletion', 'Downloaded ciphertext cannot be revoked',
                           'Public-recipient acceptance is not private-key custody or native recovery evidence']}
        if len(canonical(value)) > MAX_MANIFEST:
            raise TransferError('Rotation plan exceeds metadata budget; no truncation')
        reservation = {'plan_id': plan_id, 'plan_sha256': hash_bytes(canonical(value)),
                       'repo_id': config['repo_id'], 'set_id': config['set_id'], 'source_id': config['source_id']}
        save(backup.root / 'key-plans' / (plan_id + '.reservation.json'), reservation, exclusive=True)
        target = Path(output) if output is not None else backup.root / 'key-plans' / (plan_id + '.plan.json')
        save(target, value, exclusive=True)
        return {'status': 'planned', 'plan_id': plan_id, 'plan': str(target), 'scope': value['scope'],
                'affected_sources': value['affected_sources'], 'current_epoch': value['current_epoch'],
                'new_epoch': value['new_epoch'], 'remote_writes': 0,
                'recovery_dependency': value['recovery_dependency'], 'private_key_custody': 'not established by planning'}


def _plan(backup, config, path):
    value = json_read(path)
    if not isinstance(value, dict) or value.get('format') != 'csl-backup-key-plan' or type(value.get('schema_version')) is not int or value['schema_version'] != 1:
        raise BackupStale('Unknown key rotation plan')
    plan_id = uid(value.get('plan_id'))
    reservation = json_read(backup.root / 'key-plans' / (plan_id + '.reservation.json'))
    if reservation.get('plan_id') != plan_id or reservation.get('plan_sha256') != hash_bytes(canonical(value)):
        raise BackupStale('Rotation plan differs from its reviewed local reservation')
    for field in ('repo_id', 'set_id', 'source_id'):
        if value.get(field) != config[field] or reservation.get(field) != config[field]:
            raise BackupStale('Rotation plan repository/set/source binding differs')
    if value.get('scope') != 'future-only-one-source' or value.get('affected_sources') != [config['source_id']]:
        raise BackupStale('Unknown rotation scope')
    return value, reservation['plan_sha256']


def _new_config(config, plan, activated_at):
    history = epochs(config)
    if history != plan['retained_epochs']:
        raise BackupStale('Retained epoch map changed since planning')
    known = {cp for cp in (plan['base_complete'], plan['base_source_checkpoint'], plan['base_partial']) if cp is not None}
    history[-1]['known_checkpoints'] = sorted(set(history[-1]['known_checkpoints']) | known)
    result = {**config, 'recipients': plan['new_recipients'], 'key_reference': plan['new_key_reference'],
              'profile_epoch': plan['new_epoch']}
    history.append({'epoch_id': plan['new_epoch'], **crypto_profile(result), 'activated_at': activated_at,
                    'known_checkpoints': [], 'custody_reference': result['key_reference'],
                    'provenance': 'future rotation; verification/restored evidence is per new object, not inherited'})
    result['key_epochs'] = history
    fmt.config(result)
    epochs(result)
    if len(canonical(result)) + 1 > MAX_MANIFEST:
        raise TransferError('Future configuration exceeds metadata budget; remote state unchanged')
    return result


def _binding(plan, plan_hash, new_config, stamp):
    return {'plan_id': plan['plan_id'], 'plan_sha256': plan_hash, 'source_id': plan['source_id'],
            'from_epoch': plan['current_epoch'], 'to_epoch': plan['new_epoch'],
            'old_key_binding': plan['current_key_binding'], 'new_key_binding': key_binding(new_config),
            'old_config_sha256': plan['current_config_sha256'], 'new_config_sha256': config_hash(new_config),
            'from_checkpoint': plan['base_complete'], 'from_partial': plan['base_partial'],
            'applied_at': stamp, 'commit_epoch': plan['expected_set_epoch'] + 1, 'status': 'applied'}


def apply_rotation(backup, config, path):
    rotation_config(config)
    if config['repo_id'] != backup.github.repo_id:
        raise TransferError('Configured rotation repository identity differs')
    with locked(backup.root):
        plan, plan_hash = _plan(backup, config, path)
        config_path = configuration_path(backup.root, config['set_id'], config['source_id'])
        current = rotation_config(json_read(config_path))
        item, source = _snapshot(backup, config)
        existing = item.get('key_rotations', {}).get(plan['plan_id'])
        current_hash = config_hash(current)
        if existing:
            fmt.timestamp(existing.get('applied_at'))
            expected_fields = {'plan_id': plan['plan_id'], 'plan_sha256': plan_hash, 'source_id': plan['source_id'],
                'from_epoch': plan['current_epoch'], 'to_epoch': plan['new_epoch'],
                'old_key_binding': plan['current_key_binding'], 'old_config_sha256': plan['current_config_sha256'],
                'from_checkpoint': plan['base_complete'], 'from_partial': plan['base_partial'],
                'commit_epoch': plan['expected_set_epoch'] + 1, 'status': 'applied'}
            if any(existing.get(k) != v for k, v in expected_fields.items()):
                raise BackupStale('Remote rotation result differs from its reserved intention')
            # Lost response/journal recovery uses the stable remote result and
            # the public plan, never a regenerated activation date or new epoch.
            if (existing.get('plan_sha256') != plan_hash or existing.get('source_id') != config['source_id'] or
                    existing.get('from_epoch') != plan['current_epoch'] or existing.get('to_epoch') != plan['new_epoch'] or
                    source.get('key_profile_binding') != existing.get('new_key_binding') or
                    source.get('profile_epoch') != plan['new_epoch']):
                raise BackupStale('Rotation result superseded or binding differs; no old-plan rollback')
            if current_hash == existing['new_config_sha256']:
                if (current.get('profile_epoch') != plan['new_epoch'] or current['recipients'] != plan['new_recipients'] or
                        current['key_reference'] != plan['new_key_reference'] or key_binding(current) != existing['new_key_binding']):
                    raise BackupStale('Installed future configuration differs from the reviewed rotation')
                new_config = current
            elif current_hash == plan['current_config_sha256']:
                new_config = _new_config(current, plan, existing['applied_at'])
                if _binding(plan, plan_hash, new_config, existing['applied_at']) != existing:
                    raise BackupStale('Remote rotation result differs from its reserved configuration')
            else:
                raise BackupStale('Local configuration changed after remote rotation; no overwrite')
        else:
            if current_hash != plan['current_config_sha256'] or fmt.fingerprint(current) != plan['producer_fingerprint']:
                raise BackupStale('Local configuration/producer rules changed; regenerate the plan')
            if item['epoch'] != plan['expected_set_epoch']:
                raise BackupStale('Set generation changed; regenerate the plan')
            stamp = now()
            new_config = _new_config(current, plan, stamp)
            _probe(backup, new_config['recipients'])
            existing = _binding(plan, plan_hash, new_config, stamp)
            journal = backup.root / 'key-rotations' / (plan['plan_id'] + '.json')
            save(journal, {**existing, 'state': 'prepared'})
            def mutate(state, clock):
                target = state['sets'][config['set_id']]
                origin = target['sources'][config['source_id']]
                if target['epoch'] != plan['expected_set_epoch']:
                    raise BackupStale('Set generation changed during rotation; no write')
                if target['owner'] and target['expires'] > clock:
                    raise BackupBusy('Another writer owns the set lease; no key rotation applied')
                if (origin.get('latest_complete') != plan['base_complete'] or
                        origin.get('latest_checkpoint', origin.get('latest_complete')) != plan['base_source_checkpoint'] or
                        origin.get('latest_partial') != plan['base_partial'] or
                        origin.get('key_profile_binding') != plan['expected_remote_key_binding']):
                    raise BackupStale('Source checkpoint/key binding changed; regenerate the plan')
                origin.update(key_profile_binding=existing['new_key_binding'], profile_epoch=plan['new_epoch'],
                    rotation_boundary_checkpoint=plan['base_source_checkpoint'])
                target.update(epoch=target['epoch'] + 1, owner='', expires=clock)
                target.setdefault('key_rotations', {})[plan['plan_id']] = existing
            backup.control.change(mutate)
        # Revalidate the exact stable result after possible response loss before
        # changing the local future writer configuration.
        _, state = backup.control.read()
        remote = state['sets'][config['set_id']]
        origin = remote['sources'][config['source_id']]
        if (remote.get('key_rotations', {}).get(plan['plan_id']) != existing or
                origin.get('key_profile_binding') != key_binding(new_config) or origin.get('profile_epoch') != plan['new_epoch']):
            raise BackupStale('Remote rotation result changed; local configuration not replaced')
        if config_hash(json_read(config_path)) not in (plan['current_config_sha256'], existing['new_config_sha256']):
            raise BackupStale('Local configuration changed during rotation; no overwrite')
        if config_hash(json_read(config_path)) != existing['new_config_sha256']:
            save(config_path, new_config)
        save(backup.root / 'key-rotations' / (plan['plan_id'] + '.json'), {**existing, 'state': 'applied'})
        return {'status': 'applied', 'plan_id': plan['plan_id'], 'source_id': config['source_id'],
                'profile_epoch': plan['new_epoch'], 'future_only': True, 'historical_assets_modified': 0,
                'epochs': epochs(new_config), 'custody_warning': plan['recovery_dependency'],
                'evidence': 'configuration rotation only; no new integrity/restored/native evidence'}


def list_epochs(backup, config):
    return {'repo_id': config['repo_id'], 'set_id': config['set_id'], 'source_id': config['source_id'],
            'active_epoch': epoch_id(config), 'epochs': epochs(config),
            'scope': 'private local public-recipient dependency map; not proof of private-key custody or recovery'}
