"""Crypto output ownership regressions; no real secrets or global keyrings."""

from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from csl_backup_crypto import Age, BackupPolicyError


class CryptoOwnershipTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / "source"
        self.source.write_bytes(b"synthetic source")
        self.target = self.root / "target"
        self.age = object.__new__(Age)
        self.age.executable = "/synthetic/age"
        self.recipients = ["age1" + "a" * 58, "age1" + "c" * 58]

    def test_existing_sentinel_never_overwritten_or_deleted(self):
        self.target.write_bytes(b"sentinel")
        with patch('subprocess.run', side_effect=AssertionError('must not launch')):
            for operation in (lambda: self.age.encrypt(self.source, self.target, self.recipients),
                              lambda: self.age.decrypt(self.source, self.target, b"synthetic key")):
                with self.assertRaises(BackupPolicyError):
                    operation()
                self.assertEqual(self.target.read_bytes(), b"sentinel")

    def test_same_path_and_symlink_refused(self):
        with self.assertRaises(BackupPolicyError):
            self.age.encrypt(self.source, self.source, self.recipients)
        self.target.symlink_to(self.root / "missing")
        with self.assertRaises(BackupPolicyError):
            self.age.decrypt(self.source, self.target, b"synthetic key")
        self.assertTrue(self.target.is_symlink())
        self.assertEqual(self.source.read_bytes(), b"synthetic source")

    def test_failure_timeout_and_racing_destination_only_clean_own_staging(self):
        for action in ('failure', 'timeout', 'race', 'success'):
            with self.subTest(action=action):
                target = self.root / action
                def run(command, **kwargs):
                    output = Path(command[command.index('-o') + 1])
                    output.write_bytes(b"synthetic output")
                    if action == 'timeout':
                        raise subprocess.TimeoutExpired(command, 300)
                    if action == 'race':
                        target.write_bytes(b"racing sentinel")
                    return SimpleNamespace(returncode=1 if action == 'failure' else 0)
                with patch('subprocess.run', side_effect=run):
                    if action == 'success':
                        self.age.encrypt(self.source, target, self.recipients)
                        self.assertEqual(target.read_bytes(), b"synthetic output")
                    else:
                        with self.assertRaises(BackupPolicyError):
                            self.age.decrypt(self.source, target, b"synthetic key")
                if action == 'race':
                    self.assertEqual(target.read_bytes(), b"racing sentinel")
                elif action != 'success':
                    self.assertFalse(target.exists())
                self.assertFalse(list(self.root.glob('.csl-output-*')))


if __name__ == '__main__':
    unittest.main()
