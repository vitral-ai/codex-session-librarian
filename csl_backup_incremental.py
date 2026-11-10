"""Incremental conversation heads and durable, fenced snapshot intentions.

Only encrypted plans are uploaded. A plan/draft is never a restorable checkpoint.
No automatic downloads for thirty-day verification debt, timers, repacks or GC.
"""
import copy
import datetime as dt
from pathlib import Path
import tempfile
import time
import uuid

import csl_backup_format as fmt
from csl_backup_core import (BackupBusy, MAX_MANIFEST, canonical, hash_file, json_read,
                             locked, now, save, uid)
from csl_backup_crypto import BackupPolicyError
from csl_backup_store import RemoteError
from csl_transfer import TransferError


def due(container, at):
    stamp = container.get('integrity_verified_at')
    return stamp is None or (fmt.timestamp(at) - fmt.timestamp(stamp)).total_seconds() >= 30 * 86400


def _head(container, member, stamp):
    return {'container_id': container['container_id'], 'member_id': member['member_id'],
            'version_key': member['version_key'], 'sha256': member['sha256'],
            'captured_at': member.get('captured_at', stamp), 'last_observed_at': stamp, 'state': 'current'}


def _check_light(backup, container, stamp):
    try:
        backup._asset(container['container_id'], 'o', container)
    except (TransferError, OSError, KeyError):
        backup._event(container['manifest'], container, 'available', result='failed')
        raise
    backup._event(container['manifest'], container, 'available')
    result = copy.deepcopy(container)
    result.update(last_available_at=stamp, referenced_at=stamp,
                  evidence_level='available', verification_due=due(container, stamp))
    return result


def _previous(backup, config, identity, directory):
    _, state = backup.control.read()
    source = state['sets'].get(config['set_id'], {}).get('sources', {}).get(config['source_id'], {})
    base = source.get('latest_complete')
    identifier = source.get('latest_checkpoint') or base
    if not identifier:
        return base, None, None
    previous_dir = directory / 'previous'
    previous_dir.mkdir()
    previous, _ = backup._read_checkpoint(identifier, identity, previous_dir,
        set_id=config['set_id'], source_id=config['source_id'], metadata_only=True, allow_partial=True)
    # Changed rules/profile/recipients create a new lineage; older checkpoints
    # remain independently addressable and are never relabelled with new rules.
    if previous['fingerprint'] != fmt.fingerprint(config):
        previous = None
    return base, previous, identifier


def _plan(backup, config, identity, directory, run_id, checkpoint_id):
    stamp = now()
    base, previous, source_base = _previous(backup, config, identity, directory)
    entries, exclusions, failures = backup._entries(config, directory)
    old = {}
    if previous:
        by_id = {c['container_id']: c for c in previous['containers']}
        for head in fmt.heads(previous):
            container = by_id[head['container_id']]
            member = next(m for m in container['manifest']['members'] if m['member_id'] == head['member_id'])
            old[member['origin']['source_uuid']] = (container, member, copy.deepcopy(head))
    containers, heads, fresh, checked = {}, [], [], {}
    def available(c):
        cid = c['container_id']
        if cid not in checked:
            try:
                checked[cid] = _check_light(backup, c, stamp)
            except (TransferError, OSError, KeyError):
                checked[cid] = None
        return checked[cid]
    fallbacks = []
    current_ids = set()
    reused = 0
    for path, entry in entries:
        sid = entry['origin']['source_uuid']
        current_ids.add(sid)
        prior = old.get(sid)
        if prior and prior[1]['version_key'] == entry['version_key'] and available(prior[0]):
            container, member, head = prior
            containers[container['container_id']] = checked[container['container_id']]
            head.update(last_observed_at=entry['last_observed_at'], state='current')
            heads.append(head)
            reused += 1
        else:
            fresh.append((path, entry))
            if prior and available(prior[0]):
                container, member, head = prior
                head['state'] = 'stale'
                fallbacks.append({'source_uuid': sid, 'container': checked[container['container_id']], 'head': head})
    failed_ids = {f['source_uuid'] for f in failures}
    excluded_ids = {e['origin']['source_uuid'] for e in exclusions}
    for sid, (container, member, head) in old.items():
        if sid in current_ids or sid in excluded_ids:
            continue
        checked_container = available(container)
        if checked_container:
            containers[container['container_id']] = checked_container
            head['state'] = 'stale' if sid in failed_ids else 'missing_local'
            heads.append(head)  # Preserve observation/capture dates for old bytes.
        elif sid not in failed_ids:
            failures.append({'source_uuid': sid, 'reason_code': 'UnavailableMissingLocal'})
    packed = []
    # Pack failures affect only their eligible conversations. A large single
    # member cannot discard unrelated good captures or become a fake complete.
    try:
        packed = backup._pack(config, run_id, fresh, directory)
    except TransferError:
        for entry in fresh:
            try:
                packed.extend(backup._pack(config, run_id, [entry], directory / _mkdir(directory, entry[1]['version_key'])))
            except (TransferError, OSError):
                failures.append({'source_uuid': entry[1]['origin']['source_uuid'], 'reason_code': 'PackingFailed'})
    if sum(c['bytes'] for c in containers.values()) + sum(p.stat().st_size for p, _ in packed) > 2 * 1024**3:
        raise TransferError('Final ciphertext/run budget exceeded before remote mutation')
    return {'format': 'csl-backup-plan', 'schema_version': 1, 'repo_id': config['repo_id'],
            'set_id': config['set_id'], 'source_id': config['source_id'], 'fingerprint': fmt.fingerprint(config),
            'run_id': run_id, 'checkpoint_id': checkpoint_id, 'base_checkpoint': base,
            'base_source_checkpoint': source_base, 'cut_at': stamp,
            'selection': {'provider': 'codex', 'archives': True, 'agent_forks': config['agent_forks']},
            'exclusions': exclusions, 'failures': failures, 'eligible': len(entries) + len(failures),
            'captured_source_bytes': backup._last_capture_bytes,
            'reused': reused, 'containers': list(containers.values()), 'heads': heads, 'fallbacks': fallbacks,
            'pending': [{'manifest': manifest, 'ciphertext_sha256': hash_file(path), 'bytes': path.stat().st_size}
                        for path, manifest in packed]}, packed


def _mkdir(directory, name):
    (directory / name).mkdir(exist_ok=True)
    return name


def _bind(plan, config, run_id):
    if (plan.get('format') != 'csl-backup-plan' or type(plan.get('schema_version')) is not int or
            plan['schema_version'] != 1 or plan.get('run_id') != run_id or
            plan.get('fingerprint') != fmt.fingerprint(config)):
        raise TransferError('Resume plan/profile/rules binding differs')
    fmt.binding(plan, config)
    uid(plan.get('checkpoint_id'))
    fmt.timestamp(plan.get('cut_at'))
    for pending in plan.get('pending', []):
        fmt.manifest(pending['manifest'], plan)
        if pending['manifest']['run_id'] != run_id:
            raise TransferError('Resume container/run binding differs')



def _bind_intent(plan, binding, config, run_id):
    """Valid encryption is not enough: reserved IDs must remain unchanged."""
    _bind(plan, config, run_id)
    fields = ('repo_id', 'set_id', 'source_id', 'run_id', 'checkpoint_id',
              'base_checkpoint', 'base_source_checkpoint', 'artifact_epoch')
    if not isinstance(binding, dict) or any(k not in plan or k not in binding or plan[k] != binding[k] for k in fields):
        raise TransferError('Resume plan differs from reserved intention binding')
    fmt.integer(binding.get('lease_epoch'), 1)
    fmt.integer(binding.get('artifact_epoch'), 1)
    for key in ('base_checkpoint', 'base_source_checkpoint'):
        if plan[key] is not None:
            uid(plan[key])

def _download_plan(backup, config, identity, run_id, directory):
    _, state = backup.control.read()
    item = state['sets'].get(config['set_id'], {})
    binding = item.get('runs', {}).get(run_id)
    if not binding or binding.get('source_id') != config['source_id']:
        raise TransferError('No remote intention for this exact run/source; no source adoption')
    checkpoint = uid(binding['checkpoint_id'])
    release = backup.github.resolve_release(checkpoint, 'c', binding.get('release_id'))
    assets = [a for a in release['assets'] if a['name'] == 'plan.age']
    if len(assets) != 1:
        raise TransferError('Remote plan not uploaded; pending cut cannot be reconstructed')
    envelope = backup.github.read_envelope(release, checkpoint, 'plan-descriptor.json')
    encrypted, plain = directory / 'recovered-plan.age', directory / 'recovered-plan.json'
    backup.github.download(assets[0], encrypted)
    if hash_file(encrypted) != envelope['sha256'] or encrypted.stat().st_size != envelope['bytes']:
        raise TransferError('Remote plan envelope differs')
    backup.age.decrypt(encrypted, plain, identity)
    plan = json_read(plain)
    _bind_intent(plan, binding, config, run_id)
    return plan, binding


def run(backup, config, identity, *, dry_run=False, resume=None):
    fmt.config(config)
    if config['repo_id'] != backup.github.repo_id:
        raise TransferError('Configured backup repository identity differs')
    if dry_run and resume:
        raise TransferError('Resume and dry-run cannot be combined')
    if not backup.github.metadata.get('permissions', {}).get('push'):
        raise TransferError('Backup requires existing write permission')
    started = time.monotonic()
    metrics_before = copy.deepcopy(getattr(backup.github, "metrics", {}))
    backup.root.mkdir(parents=True, mode=0o700, exist_ok=True)
    run_id = uid(resume) if resume else str(uuid.uuid4())
    directory = backup.root / 'runs' / run_id
    with locked(backup.root):
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        journal = directory / 'journal.json'
        with tempfile.TemporaryDirectory(prefix='working-', dir=directory) as scratch:
            temporary = Path(scratch)
            if resume:
                if journal.exists() and (directory / 'plan.json').exists():
                    binding = json_read(journal)
                    plan = json_read(directory / 'plan.json')
                else:
                    plan, binding = _download_plan(backup, config, identity, run_id, temporary)
                _bind_intent(plan, binding, config, run_id)
                _, state = backup.control.read()
                item = state['sets'][config['set_id']]
                source = item['sources'][config['source_id']]
                if source.get('latest_complete') == plan['checkpoint_id'] or source.get('latest_partial') == plan['checkpoint_id']:
                    return {'status': 'already_committed', 'run_id': run_id, 'checkpoint_id': plan['checkpoint_id'],
                            'cut_at': plan['cut_at'], 'fresh_capture': False}
                remote_binding = item.get('runs', {}).get(run_id)
                if remote_binding is not None:
                    _bind_intent(plan, remote_binding, config, run_id)
                    binding = remote_binding
                epoch = binding['lease_epoch']
                # Every explicit resume takes a NEW generation, even while
                # the previous execution of this run is paused and still alive.
                # Its old token can never renew or commit after this acquire.
                artifact_epoch = binding.get('artifact_epoch', epoch)
                epoch = backup._lease(config, run_id, acquire=True, expected_epoch=item['epoch'],
                                      base_checkpoint=plan['base_checkpoint'], source_base=plan['base_source_checkpoint'])
                binding = {**binding, 'lease_epoch': epoch, 'artifact_epoch': artifact_epoch}
            else:
                checkpoint_id = str(uuid.uuid4())
                plan, packed = _plan(backup, config, identity, temporary, run_id, checkpoint_id)
                if dry_run:
                    return {'status': 'planned', 'sessions': len(plan['heads']) + sum(len(m['manifest']['members']) for m in plan['pending']),
                            'containers': len(plan['containers']) + len(packed), 'remote_writes': 0,
                            'ciphertext_bytes': sum(p.stat().st_size for p, _ in packed), 'failures': plan['failures']}
                if not plan['heads'] and not plan['pending']:
                    raise TransferError('No protected conversations; run failed without publishing a checkpoint')
                epoch = backup._lease(config, run_id, acquire=True, base_checkpoint=plan['base_checkpoint'], source_base=plan['base_source_checkpoint'])
                plan['artifact_epoch'] = epoch
                binding = {k: plan[k] for k in ('repo_id', 'set_id', 'source_id', 'run_id', 'checkpoint_id',
                           'base_checkpoint', 'base_source_checkpoint', 'artifact_epoch')}
                binding['lease_epoch'] = epoch
                save(journal, binding, exclusive=True)
                for path, manifest in packed:
                    destination = directory / (manifest['container_id'] + '.age')
                    path.replace(destination)
                save(directory / 'plan.json', plan, exclusive=True)
            # Local intent/ciphertexts are durable before any release POST. The
            # opaque control binding permits recovery when the journal is lost.
            backup._lease(config, run_id, expected_epoch=epoch, base_checkpoint=plan['base_checkpoint'], source_base=plan['base_source_checkpoint'],
                          run_binding={k: binding[k] for k in ('repo_id','set_id','source_id','run_id','checkpoint_id','base_checkpoint','base_source_checkpoint','lease_epoch','artifact_epoch')})
            release = backup.github.reserve(plan['checkpoint_id'])
            encrypted = directory / 'plan.age'
            if not encrypted.exists():
                if not (directory / 'plan.json').exists():
                    save(directory / 'plan.json', plan, exclusive=True)
                backup.age.encrypt(directory / 'plan.json', encrypted, config['recipients'])
            published = backup.github.publish(plan['checkpoint_id'], encrypted, 'p', release_id=release['id'])
            checked, plain = temporary / 'plan.checked.age', temporary / 'plan.checked.json'
            backup.github.download(published['asset'], checked)
            backup.age.decrypt(checked, plain, identity)
            if json_read(plain) != plan:
                raise TransferError('Uploaded plan differs from intended cut')
            _bind_intent(plan, binding, config, run_id)
            save(journal, {**binding, 'state': 'uploading'})
            containers, heads = copy.deepcopy(plan['containers']), copy.deepcopy(plan['heads'])
            failures = copy.deepcopy(plan['failures'])
            reused = plan['reused']
            if resume:
                current_containers = []
                for container in containers:
                    try:
                        current_containers.append(_check_light(backup, container, now()))
                    except (TransferError, OSError, KeyError):
                        removed = [h for h in heads if h['container_id'] == container['container_id']]
                        by_member = {m['member_id']: m for m in container['manifest']['members']}
                        reused -= sum(h['state'] == 'current' for h in removed)
                        failed_ids = {f['source_uuid'] for f in failures}
                        for head in removed:
                            sid = by_member[head['member_id']]['origin']['source_uuid']
                            if sid not in failed_ids:
                                failures.append({'source_uuid': sid, 'reason_code': 'ResumeReferenceUnavailable'})
                                failed_ids.add(sid)
                        heads = [h for h in heads if h['container_id'] != container['container_id']]
                containers = current_containers
            captured = 0
            uploaded_bytes = downloaded_bytes = 0
            for pending in plan['pending']:
                manifest = pending['manifest']
                cid = manifest['container_id']
                backup._lease(config, run_id, expected_epoch=epoch, base_checkpoint=plan['base_checkpoint'], source_base=plan['base_source_checkpoint'])
                if time.monotonic() - started > 3600:
                    failures.extend({'source_uuid': m['origin']['source_uuid'], 'reason_code': 'RunBudgetExceeded'} for m in manifest['members'])
                    continue
                encrypted = directory / (cid + '.age')
                try:
                    release = backup.github.resolve_release(cid, 'o')
                    if release and any(a['name'] == 'container.age' for a in release['assets']):
                        asset = next(a for a in release['assets'] if a['name'] == 'container.age')
                        published = {'asset': asset, 'release_id': release['id']}
                    else:
                        if not encrypted.exists():
                            raise TransferError('Pending bytes unavailable; old cut cannot be invented from current source')
                        if hash_file(encrypted) != pending['ciphertext_sha256'] or encrypted.stat().st_size != pending['bytes']:
                            raise TransferError('Durable ciphertext changed')
                        published = backup.github.publish(cid, encrypted, 'o')
                        uploaded_bytes += encrypted.stat().st_size
                    checked, plain = temporary / (cid + '.checked.age'), temporary / (cid + '.checked.zip')
                    backup.github.download(published['asset'], checked)
                    downloaded_bytes += checked.stat().st_size
                    backup.age.decrypt(checked, plain, identity)
                    backup._verify_container(plain, manifest)
                    # Existing randomized ciphertext is adopted only after all
                    # intended origin/version/profile/member bindings match.
                    release = backup.github.resolve_release(cid, 'o', published['release_id'])
                    backup.github._descriptor(release, cid, checked)
                    envelope = backup.github.read_envelope(backup.github.resolve_release(cid, 'o', published['release_id']), cid)
                    if envelope['sha256'] != hash_file(checked) or envelope['bytes'] != checked.stat().st_size:
                        raise TransferError('Container envelope conflicts with verified bytes')
                    backup._lease(config, run_id, expected_epoch=epoch, base_checkpoint=plan['base_checkpoint'], source_base=plan['base_source_checkpoint'])
                    backup.github.finalize(cid, 'o', published['release_id'])
                    container = {'container_id': cid, 'release_id': published['release_id'],
                        'asset_id': published['asset']['id'], 'bytes': checked.stat().st_size, 'sha256': hash_file(checked),
                        'manifest': manifest, 'integrity_verified_at': now(), 'last_available_at': now(),
                        'referenced_at': now(), 'evidence_level': 'integrity_verified', 'verification_due': False}
                    backup._event(manifest, container, "verify")
                    containers.append(container)
                    heads.extend(_head(container, m, m.get('last_observed_at', plan['cut_at'])) for m in manifest['members'])
                    captured += len(manifest['members'])
                except (BackupBusy, BackupPolicyError):
                    raise
                except (TransferError, OSError, KeyError) as error:
                    failures.extend({'source_uuid': m['origin']['source_uuid'], 'reason_code': type(error).__name__} for m in manifest['members'])
            failed_ids = {f['source_uuid'] for f in failures}
            for fallback in plan.get('fallbacks', []):
                if fallback['source_uuid'] in failed_ids:
                    try:
                        available_fallback = _check_light(backup, fallback['container'], now())
                    except (TransferError, OSError, KeyError):
                        continue
                    heads.append(copy.deepcopy(fallback['head']))
                    if not any(c['container_id'] == fallback['container']['container_id'] for c in containers):
                        containers.append(available_fallback)
            if not heads or (captured + reused == 0 and failures):
                save(journal, {**binding, 'state': 'failed', 'failures': failures,
                               'reason_code': 'NoCurrentSuccess', 'protected_heads': len(heads)})
                raise TransferError('No protected conversations/current successes; draft is not a restorable checkpoint; durable failures retained')
            counts = {'eligible': reused + captured + len(failures), 'captured': captured,
                      'reused': reused, 'failed': len(failures),
                      'stale': sum(h['state'] == 'stale' for h in heads),
                      'missing_local': sum(h['state'] == 'missing_local' for h in heads),
                      'protected': len(heads), 'excluded': len(plan['exclusions'])}
            catalog = {k: plan[k] for k in ('repo_id', 'set_id', 'source_id', 'run_id', 'checkpoint_id',
                       'fingerprint', 'cut_at', 'selection', 'exclusions')}
            catalog.update(format='csl-backup-catalog', schema_version=2, lease_epoch=binding['artifact_epoch'],
                status='partial' if failures else 'complete', failures=failures, heads=heads, counts=counts,
                containers=containers, evidence_policy='light-each-run-full-30d-v1',
                base_checkpoint=plan['base_checkpoint'], base_source_checkpoint=plan['base_source_checkpoint'], published_at=now())
            fmt.catalog(catalog, {**config, 'fingerprint': fmt.fingerprint(config)})
            plain, encrypted = temporary / 'catalog.json', temporary / 'catalog.age'
            save(plain, catalog, exclusive=True)
            if plain.stat().st_size > MAX_MANIFEST:
                raise TransferError('Checkpoint metadata exceeds budget')
            backup.age.encrypt(plain, encrypted, config['recipients'])
            backup._lease(config, run_id, expected_epoch=epoch, base_checkpoint=plan['base_checkpoint'], source_base=plan['base_source_checkpoint'])
            published = backup.github.publish(plan['checkpoint_id'], encrypted, 'c')
            checked, decrypted = temporary / 'catalog.checked.age', temporary / 'catalog.checked.json'
            backup.github.download(published['asset'], checked)
            backup.age.decrypt(checked, decrypted, identity)
            accepted = fmt.catalog(json_read(decrypted), {**config, 'fingerprint': fmt.fingerprint(config)})
            # A resumed catalog can have earlier evidence dates, but must bind
            # the same cut and logical selection. Never adopt a different result.
            for field in ('run_id', 'checkpoint_id', 'lease_epoch', 'cut_at', 'heads', 'counts', 'failures'):
                if accepted[field] != catalog[field]:
                    raise TransferError('Existing catalog result differs; never overwrite')
            release = backup.github.resolve_release(plan['checkpoint_id'], 'c', published['release_id'])
            envelope = backup.github.read_envelope(release, plan['checkpoint_id'])
            if envelope['sha256'] != hash_file(checked) or envelope['bytes'] != checked.stat().st_size:
                raise TransferError('Catalog envelope differs')
            backup._lease(config, run_id, expected_epoch=epoch, base_checkpoint=plan['base_checkpoint'], source_base=plan['base_source_checkpoint'])
            backup.github.finalize(plan['checkpoint_id'], 'c', published['release_id'])
            pointer = {'release_id': published['release_id'], 'asset_id': published['asset']['id'],
                       'bytes': checked.stat().st_size, 'sha256': hash_file(checked), 'lease_epoch': binding['artifact_epoch'], 'commit_epoch': epoch}
            backup._lease(config, run_id, checkpoint=plan['checkpoint_id'], catalog_binding=pointer,
                partial=bool(failures), expected_epoch=epoch, base_checkpoint=plan['base_checkpoint'], source_base=plan['base_source_checkpoint'])
            result = {'status': catalog['status'], 'checkpoint_id': plan['checkpoint_id'], 'run_id': run_id,
                    'cut_at': plan['cut_at'], 'fresh_capture': not bool(resume), 'sessions': len(heads),
                    'containers': len(containers), 'repo_id': config['repo_id'], 'counts': counts,
                    'verification_due': sum(c['verification_due'] for c in containers),
                    'costs': {'captured_source_bytes': 0 if resume else plan.get('captured_source_bytes', 0),
                              'cut_captured_source_bytes': plan.get('captured_source_bytes', 0),
                              'uploaded_container_bytes': uploaded_bytes, 'downloaded_container_bytes': downloaded_bytes,
                              'transport': {k: v - metrics_before.get(k, 0) for k, v in getattr(backup.github, 'metrics', {}).items()}}}
            save(journal, {**binding, 'state': catalog['status'], 'completed_at': now(), 'summary': result})
            return result
