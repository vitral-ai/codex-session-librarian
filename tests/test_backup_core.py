"""Backup primitives use synthetic files, never personal native homes."""

import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import warnings
from unittest.mock import patch
import zipfile

import csl_backup_core as core
from csl_transfer import TransferError
from experiments.backup_f0.profiles import fixture


class BackupCoreTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.sid = "11111111-1111-4111-8111-111111111111"

    def test_capture_exact_utf8_spacing_and_incomplete_tail(self):
        source, target = self.root / "source", self.root / "cut"
        content = fixture("pending", self.sid)
        source.write_bytes(content + b'{"incomplete":')
        result = core.capture(source, target)
        self.assertEqual(target.read_bytes(), content)
        self.assertEqual(result["sha256"], core.hash_bytes(content))
        self.assertGreater(result["deferred_bytes"], 0)
        self.assertEqual(source.read_bytes(), content + b'{"incomplete":')

    def test_complete_final_json_without_newline_is_preserved(self):
        source, target = self.root/'source', self.root/'cut'
        content = fixture('text',self.sid).rstrip(b'\n ')
        source.write_bytes(content)
        result = core.capture(source,target)
        self.assertEqual(target.read_bytes(),content)
        self.assertEqual(result['deferred_bytes'],0)

    def test_capture_source_and_preexisting_alias_destinations_untouched(self):
        source = self.root / "source"
        original = fixture("text", self.sid)
        source.write_bytes(original)
        hard, link, sentinel = [self.root / name for name in ("hard", "symlink", "sentinel")]
        os.link(source, hard)
        link.symlink_to(source)
        sentinel.write_bytes(b"sentinel")
        for target in (source, hard, link, sentinel):
            with self.subTest(target=target.name), self.assertRaises(TransferError):
                core.capture(source, target)
            self.assertEqual(source.read_bytes(), original)
        self.assertEqual(sentinel.read_bytes(), b"sentinel")
        self.assertTrue(link.is_symlink())

    def test_codex_structured_subagent_source_not_reclassified_as_cli(self):
        value = {'subagent':{'thread_spawn':{'parent_thread_id':self.sid,'depth':1,
                                          'agent_nickname':'Synthetic','agent_role':'worker'}}}
        self.assertEqual(core.source_kind(value), 'agent')
        self.assertEqual(core.source_kind({'subagent':'review'}), 'agent')
        self.assertEqual(core.source_kind({'internal':'guardian'}), 'agent')
        self.assertEqual(core.source_kind('mcp'), 'noninteractive')
        self.assertEqual(core.source_kind({'custom':'fixture'}), 'noninteractive')
        for unknown in ({'subagent':{'future':{}}}, {'subagent':{'thread_spawn':{'parent_thread_id':self.sid,'depth':True}}}, 'future'):
            with self.assertRaises(TransferError):
                core.source_kind(unknown)

    def test_capture_publish_race_preserves_final_sentinel(self):
        source, target = self.root / "source", self.root / "final"
        original = fixture("text", self.sid)
        source.write_bytes(original)
        def race(staging, final):
            Path(final).write_bytes(b"racing sentinel")
            raise FileExistsError
        with patch.object(core.os, "link", side_effect=race), self.assertRaises(TransferError):
            core.capture(source, target)
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(target.read_bytes(), b"racing sentinel")
        self.assertFalse(list(self.root.glob('.csl-output-*')))

    def test_symlink_malformed_and_unidentified_sources_rejected(self):
        source, target = self.root / "source", self.root / "cut"
        source.write_bytes(b'{}\n')
        link = self.root / "link"
        link.symlink_to(source)
        with self.assertRaises(OSError):
            core.capture(link, target)
        for content in (b'{}\n', b'{not-json}\n', b'{"type":"session_meta","payload":{}}\n'):
            source.write_bytes(content)
            with self.assertRaises(TransferError):
                core.capture(source, target)

    def test_identifiable_metadata_only_native_prefix_is_preserved(self):
        source,target=self.root/'source',self.root/'cut'
        content=fixture('text',self.sid).splitlines(keepends=True)[0]
        source.write_bytes(content)
        result=core.capture(source,target)
        self.assertEqual(target.read_bytes(),content)
        self.assertEqual(result['message_records'],0)

    def test_private_durable_state_and_exclusive_intent(self):
        target = self.root / "state" / "intent.json"
        core.save(target, {"reserved_uuid": self.sid}, exclusive=True)
        self.assertEqual(core.json_read(target)["reserved_uuid"], self.sid)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(target.parent.stat().st_mode & 0o777, 0o700)
        with self.assertRaises(FileExistsError):
            core.save(target, {"reserved_uuid": "different"}, exclusive=True)
        self.assertEqual(core.json_read(target)["reserved_uuid"], self.sid)

    def test_local_lock_does_not_wait_forever(self):
        with core.locked(self.root):
            with self.assertRaisesRegex(TransferError, "busy"):
                with core.locked(self.root):
                    self.fail("must be exclusive")

    def test_preflight_checks_bomb_before_any_member_read(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as writer:
            writer.writestr("manifest.json", b"A" * 100000)
        with zipfile.ZipFile(io.BytesIO(data.getvalue())) as archive:
            with patch.object(archive, "read", side_effect=AssertionError("no read before preflight")):
                with self.assertRaisesRegex(TransferError, "ratio"):
                    core.zip_preflight(archive)

    def test_preflight_rejects_paths_duplicates_sizes_and_symlink(self):
        for mode in ("path", "duplicate", "size", "symlink"):
            data = io.BytesIO()
            with zipfile.ZipFile(data, "w") as writer:
                writer.writestr("manifest.json", b"{}")
                info = zipfile.ZipInfo("../escape" if mode == "path" else "members/" + self.sid + ".jsonl")
                if mode == "symlink":
                    info.external_attr = (0o120777 << 16)
                writer.writestr(info, b"fixture")
                if mode == "duplicate":
                    with warnings.catch_warnings():
                        warnings.simplefilter('ignore')
                        writer.writestr(info, b"fixture")
            with zipfile.ZipFile(io.BytesIO(data.getvalue())) as archive:
                if mode == "size":
                    archive.infolist()[1].file_size = core.MAX_OBJECT + 1
                with patch.object(archive, "read", side_effect=AssertionError("preflight must not read")):
                    with self.assertRaises(TransferError):
                        core.zip_preflight(archive)

    def test_json_duplicate_fields_and_oversize_rejected(self):
        path = self.root / "bad.json"
        path.write_bytes(b'{"version":1,"version":2}')
        with self.assertRaises(TransferError):
            core.json_read(path)
        with path.open("wb") as stream:
            stream.truncate(core.MAX_MANIFEST + 1)
        with self.assertRaises(TransferError):
            core.json_read(path)


if __name__ == "__main__":
    unittest.main()
