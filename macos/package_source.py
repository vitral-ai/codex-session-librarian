"""Tracked-only verified packaging snapshot. Never walks untracked source directories."""
import argparse
import hashlib
import io
import json
from pathlib import Path,PurePosixPath
import re
import shutil
import subprocess
import tarfile

FORBIDDEN={'.git','.local','.agents','.ssh','.codex','.claude','skills','plans','planes','evidence','evidencias','credentials','secrets','lab','reports','tests','__pycache__'}
SECRET_NAMES={'auth.json','credentials.json','.env','.netrc','.pypirc','id_rsa','id_ed25519','config.private.json'}
ROOT_FILES={'csl','csl-bridge-mcp','csl-bridge-receiver','LICENSE','LICENSE.md','NOTICE','THIRD_PARTY_NOTICES.md'}
APP_FILES={'macos/CSLBridge/CSLBridge.swift','macos/CSLBridge/app_service.py','macos/CSLBridge/ssh_session.py','macos/build_app.py','macos/package_source.py','macos/README.md'}


def allowed(name):
    path=PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or any(p in FORBIDDEN for p in path.parts) or path.name in SECRET_NAMES:return False
    return (len(path.parts)==1 and (path.name.endswith('.py') or path.name in ROOT_FILES)) or name in APP_FILES


def git(source,*args):
    return subprocess.check_output(['git','-C',str(source),*args],stderr=subprocess.DEVNULL)


def snapshot(source,destination,source_sha,expected_manifest_sha256=None):
    source=Path(source).resolve();destination=Path(destination)
    if not re.fullmatch(r'[0-9a-f]{40}',source_sha):raise ValueError('Full frozen source commit is required')
    if destination.exists():raise ValueError('Snapshot destination must be new')
    destination.mkdir(parents=True,mode=0o700)
    if (source/'.git').exists():
        resolved=git(source,'rev-parse','--verify',source_sha+'^{commit}').decode().strip()
        if resolved!=source_sha:raise ValueError('Source commit mismatch')
        names=git(source,'ls-tree','-r','--name-only',source_sha).decode().splitlines()
        selected=[name for name in names if allowed(name)]
        if not selected:raise ValueError('No runtime files in frozen commit')
        # Only eligible tracked paths are read by git archive. Private/untracked paths are not opened.
        raw=git(source,'archive','--format=tar',source_sha,'--',*selected)
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            members=archive.getmembers()
            if any(m.issym() or m.islnk() or (m.isfile() and not allowed(m.name)) for m in members):raise ValueError('Unexpected source member')
            archive.extractall(destination,filter='data')
        files={name:hashlib.sha256((destination/name).read_bytes()).hexdigest() for name in selected}
        method='git archive of eligible tracked paths at exact commit'
    else:
        manifest_path=source/'SOURCE-MANIFEST.json'
        if not manifest_path.is_file():raise ValueError('Export requires a trusted SOURCE-MANIFEST.json, not a source SHA label alone')
        raw_manifest=manifest_path.read_bytes()
        if not expected_manifest_sha256 or hashlib.sha256(raw_manifest).hexdigest()!=expected_manifest_sha256:
            raise ValueError('Export requires its independently pinned manifest SHA256')
        manifest=json.loads(raw_manifest)
        if manifest.get('source_sha')!=source_sha:raise ValueError('Export source revision mismatch')
        files={name:digest for name,digest in manifest['files'].items() if allowed(name)}
        for name,digest in files.items():
            original=source/name
            if original.is_symlink() or not original.resolve().is_relative_to(source):raise ValueError('Source path escapes snapshot')
            if hashlib.sha256(original.read_bytes()).hexdigest()!=digest:raise ValueError('Source file hash mismatch: '+name)
            target=destination/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(original,target)
        method='verified exported manifest, eligible tracked file hashes'
    required={'csl','csl_bridge_engine.py','csl_bridge_rpc.py','macos/CSLBridge/CSLBridge.swift','macos/CSLBridge/app_service.py'}
    if not required<=set(files):raise ValueError('Frozen source is missing required runtime/app files')
    manifest={'source_sha':source_sha,'method':method,'files':files,'policy':'runtime allowlist; no untracked/private/skills/plans/evidence/tests/credentials'}
    (destination/'SOURCE-MANIFEST.json').write_text(json.dumps(manifest,sort_keys=True,indent=2))
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--source-sha',required=True);parser.add_argument('--manifest-sha256')
    args=parser.parse_args();manifest=snapshot(args.source,args.output,args.source_sha,args.manifest_sha256)
    print(json.dumps({'source_sha':manifest['source_sha'],'files':len(manifest['files']),'output':str(args.output)}))
if __name__=='__main__':main()
