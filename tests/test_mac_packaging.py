"""Synthetic canaries only: never package/read an untracked private path."""
import importlib.util
import json
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('csl_package',ROOT/'macos/package_source.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class PackagingTests(unittest.TestCase):
 def test_frozen_git_snapshot_ignores_untracked_and_tracked_private_canaries(self):
  with tempfile.TemporaryDirectory() as tmp:
   source=Path(tmp)/'repo';source.mkdir()
   def git(*args):return subprocess.check_output(['git','-C',str(source),*args],stderr=subprocess.DEVNULL)
   git('init');git('config','user.name','Synthetic');git('config','user.email','synthetic@invalid');git('config','commit.gpgsign','false');git('config','core.hooksPath','/dev/null')
   required=['csl','csl_bridge_engine.py','csl_bridge_rpc.py','macos/CSLBridge/CSLBridge.swift','macos/CSLBridge/app_service.py']
   for name in required:
    p=source/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('FROZEN PUBLIC SOURCE\n')
   tracked=source/'.agents/private.json';tracked.parent.mkdir();tracked.write_text('SYNTHETIC_TRACKED_PRIVATE_CANARY')
   git('add','.');git('commit','-qm','synthetic fixture');sha=git('rev-parse','HEAD').decode().strip()
   untracked=source/'.local/private/auth.json';untracked.parent.mkdir(parents=True);untracked.write_text('SYNTHETIC_UNTRACKED_PRIVATE_CANARY')
   (source/'csl').write_text('DIRTY WORKTREE NOT FROZEN\n')
   output=Path(tmp)/'export';manifest=module.snapshot(source,output,sha)
   self.assertEqual((output/'csl').read_text(),'FROZEN PUBLIC SOURCE\n')
   self.assertFalse((output/'.agents').exists());self.assertFalse((output/'.local').exists())
   self.assertFalse(any('CANARY' in p.read_text() for p in output.rglob('*') if p.is_file()))
   manifest_sha=hashlib.sha256((output/'SOURCE-MANIFEST.json').read_bytes()).hexdigest()
   second=Path(tmp)/'second';module.snapshot(output,second,sha,manifest_sha)
   self.assertEqual((second/'csl').read_text(),'FROZEN PUBLIC SOURCE\n')
   (output/'csl').write_text('TAMPERED')
   with self.assertRaises(ValueError):module.snapshot(output,Path(tmp)/'reject',sha,manifest_sha)
 def test_sha_argument_alone_does_not_certify_export(self):
  with tempfile.TemporaryDirectory() as tmp:
   source=Path(tmp)/'source';source.mkdir()
   with self.assertRaises(ValueError):module.snapshot(source,Path(tmp)/'out','0'*40)
if __name__=='__main__':unittest.main()
