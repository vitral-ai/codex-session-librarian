#!/usr/bin/env python3
"""Build a private native .app on macOS; no installation, network, login or services."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
from package_source import snapshot


def run(argv, **kwargs):
    result=subprocess.run([str(x) for x in argv],capture_output=True,text=True,**kwargs)
    if result.returncode:
        raise RuntimeError('Build command failed: '+str(argv[0])+'\n'+result.stderr[-4000:])
    return result.stdout.strip()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--runtime-root',type=Path,required=True,help='Existing private Python3.12 standalone distribution; copied, not linked')
    parser.add_argument('--output',type=Path,required=True,help='New private output directory; existing app is never replaced')
    parser.add_argument('--source-sha',required=True)
    parser.add_argument('--source-manifest-sha256',help='Required for exports without .git; pin supplied by the source exporter')
    args=parser.parse_args()
    if platform.system()!='Darwin':raise SystemExit('Native macOS/CLT required. No .app has been built on this host.')
    original_source=args.source.resolve();runtime=args.runtime_root.resolve();output=args.output.expanduser().absolute()
    if not (runtime/'bin/python3.12').is_file():raise SystemExit('A complete private Python3.12 runtime is required for bundling.')
    output.mkdir(parents=True,mode=0o700,exist_ok=True)
    app=output/'CSL Bridge.app'
    if app.exists():raise SystemExit('Preserving existing app: choose a new output directory.')
    source=output/'verified-source'
    source_manifest=snapshot(original_source,source,args.source_sha,args.source_manifest_sha256)
    contents=app/'Contents';resources=contents/'Resources';macos=contents/'MacOS'
    resources.mkdir(parents=True);macos.mkdir()
    shutil.copytree(runtime,resources/'python-runtime',symlinks=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','site-packages','.local','.agents','.ssh','.codex','.claude','.aws','.azure','.kube','.gnupg','.config','.cache','auth.json','credentials.json','.env','.netrc','.pypirc','id_rsa','id_ed25519'))
    # Rewrite only links back into the original runtime; other absolute links abort.
    for path in (resources/'python-runtime').rglob('*'):
        if path.is_symlink():
            target=os.readlink(path)
            if os.path.isabs(target):
                original=Path(target)
                if not original.is_relative_to(runtime):raise RuntimeError('Runtime contains external absolute symlink: '+str(path.relative_to(resources)))
                relative=original.relative_to(runtime);path.unlink();path.symlink_to(os.path.relpath(resources/'python-runtime'/relative,path.parent))
    shutil.copytree(source,resources/'bridge',symlinks=False)
    shutil.copy2(source/'macos/CSLBridge/app_service.py',resources/'app_service.py')
    shutil.copy2(source/'macos/CSLBridge/ssh_session.py',resources/'ssh_session.py')
    plist={'CFBundleName':'CSL Bridge','CFBundleDisplayName':'CSL Bridge','CFBundleIdentifier':'ai.vitral.cslbridge.private',
           'CFBundleExecutable':'CSLBridge','CFBundlePackageType':'APPL','CFBundleShortVersionString':'0.1.0','CFBundleVersion':'1',
           'LSMinimumSystemVersion':'13.0','NSHighResolutionCapable':True,'NSPrincipalClass':'NSApplication',
           'CSLSourceRevision':args.source_sha,'CSLPrivateDevelopmentBuild':True}
    with (contents/'Info.plist').open('wb') as file:plistlib.dump(plist,file)
    swift=run(['/usr/bin/xcrun','--find','swiftc'])
    run([swift,'-O','-swift-version','5','-target',platform.machine()+'-apple-macos13.0','-framework','AppKit','-framework','Foundation',source/'macos/CSLBridge/CSLBridge.swift','-o',macos/'CSLBridge'],timeout=180)
    executable=resources/'python-runtime/bin/python3.12'
    # An empty home and minimal environment prevent fallback to uv/user packages.
    isolated=output/'selftest-home';isolated.mkdir(mode=0o700)
    env={'HOME':str(isolated),'PATH':'/usr/bin:/bin','LANG':'en_US.UTF-8','PYTHONDONTWRITEBYTECODE':'1','CODEX_HOME':str(isolated/'no-native-runtime')}
    backend=run([executable,'-I','-S','-B',resources/'app_service.py','selftest','--state-root',isolated/'state','--bridge-home',isolated/'bridge','--codex-home',isolated/'no-native-runtime'],env=env,timeout=15)
    data=json.loads(backend);assert data['ok'] and Path(data['data']['prefix']).is_relative_to(resources/'python-runtime')
    linked=run(['/usr/bin/otool','-L',executable])
    if str(runtime) in linked:raise RuntimeError('Bundled Python still links to the original runtime.')
    # Sign nested Mach-O objects, then the app; no Developer ID, hardened policy or notarization.
    signed=[]
    for path in sorted(resources.rglob('*')):
        if path.is_file() and not path.is_symlink():
            with path.open('rb') as file:magic=file.read(4)
            if magic in (b'\xcf\xfa\xed\xfe',b'\xce\xfa\xed\xfe',b'\xca\xfe\xba\xbe',b'\xfe\xed\xfa\xcf'):
                run(['/usr/bin/codesign','--force','--sign','-',path],timeout=20);signed.append(str(path.relative_to(app)))
    run(['/usr/bin/codesign','--force','--sign','-',app],timeout=30)
    run(['/usr/bin/codesign','--verify','--deep','--strict',app],timeout=30)
    manifest={'source_sha':args.source_sha,'verified_source_manifest':source_manifest,'tracked_only':True,'input_manifest_sha256':args.source_manifest_sha256,'architecture':platform.machine(),'build_macos':platform.mac_ver()[0],
              'app':str(app),'swift':run([swift,'--version']),'python_bundle_selftest':data,'python_linkage':linked,
              'runtime_source':'existing private standalone Python, copied fully; original no longer required',
              'signed_objects':len(signed),'codesign':'ad-hoc; verification PASS; no notarization/public release',
              'does_not':'Start/stop existing bridge, Codex, models, login, SSH, tunnels or services',
              'earlier_macos_versions':'NOT_TESTED; deployment target is not a compatibility result'}
    (output/'BUILD-MANIFEST.json').write_text(json.dumps(manifest,indent=2))
    archive=output/('CSL-Bridge-private-'+platform.machine()+'.zip')
    run(['/usr/bin/ditto','-c','-k','--keepParent',app,archive],timeout=120)
    manifest['artifact_sha256']=hashlib.sha256(archive.read_bytes()).hexdigest();manifest['artifact_bytes']=archive.stat().st_size
    (output/'BUILD-MANIFEST.json').write_text(json.dumps(manifest,indent=2))
    (output/'SHA256SUMS').write_text(manifest['artifact_sha256']+'  '+archive.name+'\n')
    print(json.dumps(manifest,indent=2))


if __name__=='__main__':main()
