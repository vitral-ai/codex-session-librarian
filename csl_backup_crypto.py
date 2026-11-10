"""Optional pinned age CLI; private identities travel only in memory/file descriptors."""

import os
from pathlib import Path
import re
import shutil
import subprocess

from csl_transfer import TransferError
from csl_backup_core import exclusive_output

AGE_VERSION = "v1.3.2"


class BackupPolicyError(TransferError):
    pass


class Age:
    def __init__(self, executable="age"):
        self.executable = shutil.which(executable)
        if not self.executable:
            raise BackupPolicyError("Optional age CLI missing; install the documented pinned version explicitly")
        try:
            result = subprocess.run([self.executable, "--version"], capture_output=True, text=True, timeout=15)
        except subprocess.TimeoutExpired:
            raise BackupPolicyError("age version probe timed out; no fallback") from None
        if result.returncode or result.stdout.strip() != AGE_VERSION:
            raise BackupPolicyError("Backup requires pinned age " + AGE_VERSION + "; no automatic installation")

    @staticmethod
    def recipients(values):
        if (not isinstance(values, list) or len(values) != 2 or
                not all(isinstance(v, str) and re.fullmatch(r"age1[023456789acdefghjklmnpqrstuvwxyz]{58}", v) for v in values) or
                len(set(values)) != 2):
            raise BackupPolicyError("Exactly two distinct X25519 public recipients are required: operational and external recovery")
        return sorted(values)

    def encrypt(self, source, target, recipients):
        command = [self.executable]
        for recipient in self.recipients(recipients):
            command.extend(["-r", recipient])
        self._output(source, target, command)

    @staticmethod
    def _output(source, target, command, *, pass_fds=()):
        source, target = Path(source), Path(target)
        try:
            with exclusive_output(target, source=source) as output:
                try:
                    result = subprocess.run([*command, "-o", str(output), str(source)],
                        pass_fds=pass_fds, capture_output=True, timeout=300)
                except subprocess.TimeoutExpired:
                    raise BackupPolicyError("age deadline exceeded; destination unchanged") from None
                if result.returncode:
                    raise BackupPolicyError("age operation failed; no plaintext fallback, details suppressed")
        except TransferError as error:
            if isinstance(error, BackupPolicyError):
                raise
            raise BackupPolicyError(str(error)) from None

    def decrypt(self, source, target, identity):
        if not isinstance(identity, bytes) or not identity or len(identity) > 16384:
            raise BackupPolicyError("Missing or invalid private identity; nothing installed")
        fd = os.memfd_create("csl-backup-identity", os.MFD_CLOEXEC)
        try:
            os.write(fd, identity)
            os.lseek(fd, 0, os.SEEK_SET)
            self._output(source, target, [self.executable, "-d", "-i", "/proc/self/fd/" + str(fd)], pass_fds=(fd,))
        finally:
            os.close(fd)


def operational_identity(reference, *, manual=None):
    """No file/env fallback. A missing headless keyring blocks the operation."""
    if reference == "stdin":
        if manual is None:
            raise BackupPolicyError("Manual identity requires explicit --identity-stdin; scheduler cannot use it")
        return manual
    if not isinstance(reference, str) or not re.fullmatch(r"keyring:[0-9a-f-]{36}", reference):
        raise BackupPolicyError("Unsupported key reference; use explicit stdin or keyring reference")
    executable = shutil.which("secret-tool")
    if not executable:
        raise BackupPolicyError("System keyring unavailable; no plaintext fallback")
    try:
        result = subprocess.run([executable, "lookup", "service", "csl-backup", "key_id", reference[8:]],
                                capture_output=True, timeout=15)
    except subprocess.TimeoutExpired:
        raise BackupPolicyError("Keyring lookup timed out; no plaintext fallback or login") from None
    if result.returncode or not result.stdout.strip():
        raise BackupPolicyError("Keyring identity unavailable; no login, generation or plaintext fallback")
    return result.stdout.strip() + b"\n"
