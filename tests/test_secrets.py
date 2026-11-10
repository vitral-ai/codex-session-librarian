import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import csl_canonical as canonical
import csl_claude
import csl_secrets as secrets
import csl_sharing as sharing
import csl_transfer as transfer
from test_canonical import sample

TOKEN = 'ghp_' + 's' * 36
OTHER = 'sk-proj-' + 'z' * 32
REPO = Path(__file__).resolve().parents[1]


class Terminal(io.StringIO):
    def isatty(self):
        return True


class SecretExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.csl = SimpleNamespace(utc_now=lambda: '2026-11-02T00:00:00Z',
                                   DEFAULT_CODEX_HOME=self.root/'codex')
        self.env = {**os.environ, 'HOME': str(self.root), 'CODEX_HOME': str(self.root/'codex'),
                    'CLAUDE_CONFIG_DIR': str(self.root/'claude')}

    def fixture(self, provider, *, title='Synthetic fixture', token=TOKEN, references=False):
        data = sample()
        data['events'][0]['blocks'][0]['text'] = 'Historical credential ' + token
        data['events'][1]['blocks'][0]['arguments'] = {'api_key': token}
        data['events'][2]['blocks'][0]['content'][0]['text'] = 'Repeated ' + token
        if references:
            data['events'][0]['blocks'][0]['references'] = [{'kind': 'citation', 'data': {'url': 'https://example.invalid/' + token}}]
        source = self.root / (provider + '-' + uuid.uuid4().hex + '.jsonl')
        writer = canonical.restore_codex if provider == 'codex' else canonical.restore_claude
        info = writer(data, source, self.root)
        header = {'id': info['id'], 'title': title, 'cwd': '/project/' + token}
        if provider == 'claude':
            header['provider'] = provider
        return source, header

    def export(self, source, header, *, allow=False, scrub=False, terminal=None, destination=None, raw=False, quiet=False):
        args = SimpleNamespace(sessions=[str(source)], provider=None, db=self.root/'index.sqlite',
            to=destination or self.root/(uuid.uuid4().hex+'.zip'), raw=raw,
            allow_secrets=allow, scrub_secrets=scrub)
        self.out, self.err = io.StringIO(), io.StringIO()
        with patch.object(transfer, 'resolve_sources', return_value=[(source, header)]), \
             patch('sys.stdin', terminal or io.StringIO()), patch('sys.stdout', self.out), patch('sys.stderr', self.err):
            return transfer.export_bundle(args, self.csl, quiet=quiet)

    def contents(self, bundle):
        with zipfile.ZipFile(bundle) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            entry = manifest['sessions'][0]
            native = archive.read(entry['file'])
            self.assertEqual(hashlib.sha256(native).hexdigest(), entry['sha256'])
            self.assertEqual(len(native), entry['bytes'])
            return manifest, native

    def assert_masked(self):
        for token in (TOKEN, OTHER):
            self.assertNotIn(token, self.out.getvalue() + self.err.getvalue())

    def test_scrub_zip_and_native_import_both_providers(self):
        for provider in ('codex', 'claude'):
            with self.subTest(provider=provider):
                source, header = self.fixture(provider, title='Title ' + TOKEN)
                original = source.read_bytes()
                bundle = self.export(source, header, scrub=True, destination=self.root/provider)
                manifest, native = self.contents(bundle)
                self.assertNotIn(TOKEN.encode(), native)
                self.assertNotIn(TOKEN, json.dumps(manifest) + bundle.name)
                self.assertEqual(manifest['sessions'][0]['id'], header['id'])
                self.assertEqual(source.read_bytes(), original)
                self.assert_masked()
                restored = self.root/(provider+'-scrubbed.jsonl')
                restored.write_bytes(native)
                normalized = canonical.normalize(provider, restored)
                self.assertEqual(normalized['events'][1]['blocks'][0]['call_id'], 'call-1')
                result = subprocess.run([sys.executable, str(REPO/'codex_sessions.py'), 'import', str(bundle), '--cwd', str(self.root)],
                    env=self.env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn(TOKEN, result.stdout + result.stderr)

    def test_business_fields_named_like_native_metadata_are_scanned(self):
        for provider in ('codex', 'claude'):
            with self.subTest(provider=provider):
                source, header = self.fixture(provider, token='plain')
                rows = canonical.read_jsonl(source)
                arguments = {key: TOKEN for key in ('id', 'type', 'sha256', 'encrypted_content')}
                for row in rows:
                    if row.get('payload', {}).get('type') == 'function_call':
                        row['payload']['arguments'] = json.dumps(arguments)
                    for block in row.get('message', {}).get('content', []):
                        if isinstance(block, dict) and block.get('type') == 'tool_use':
                            block['input'] = arguments
                source.write_text(''.join(json.dumps(row)+'\n' for row in rows))
                before = source.read_bytes()
                bundle = self.export(source, header, scrub=True)
                manifest, native = self.contents(bundle)
                self.assertNotIn(TOKEN.encode(), native)
                self.assertEqual(manifest['sessions'][0]['id'], header['id'])
                output = self.root/(provider+'-business-fields.jsonl')
                output.write_bytes(native)
                calls = [block for event in canonical.normalize(provider, output)['events']
                         for block in event['blocks'] if block['type']=='tool_call']
                self.assertEqual(calls[0]['call_id'], 'call-1')
                self.assertEqual(calls[0]['arguments'], {key: secrets.REPLACEMENT for key in arguments})
                self.assertEqual(source.read_bytes(), before)
                self.assert_masked()
                with self.assertRaisesRegex(ValueError, '--allow-secrets'):
                    self.export(source, header)
                self.assert_masked()

    def test_readable_business_data_in_native_result_arrays_is_scanned(self):
        for provider in ('codex', 'claude'):
            with self.subTest(provider=provider):
                source, header = self.fixture(provider, token='plain')
                rows = canonical.read_jsonl(source)
                content = [{'type':'json', 'data':{key:TOKEN for key in ('id','type','encrypted_content')}},
                           {'id':TOKEN}]
                for row in rows:
                    if row.get('payload',{}).get('type') == 'function_call_output':
                        row['payload']['output'] = content
                    for block in row.get('message',{}).get('content',[]):
                        if isinstance(block,dict) and block.get('type') == 'tool_result':
                            block['content'] = content
                source.write_text(''.join(json.dumps(row)+'\n' for row in rows))
                before = source.read_bytes()
                bundle = self.export(source,header,scrub=True)
                _,native = self.contents(bundle)
                self.assertNotIn(TOKEN.encode(),native)
                self.assertIn(b'call-1',native)
                self.assertEqual(source.read_bytes(),before)
                self.assert_masked()
                # This is native preservation of an extension, not canonical
                # support for a previously unknown structured result block.

    def test_scrub_embedded_json_arguments_preserves_escaping_and_structure(self):
        values = ('long-password"suffix', 'long-password\\"suffix',
                  'long-password\nnext-line', 'long-password-\u2603"suffix')
        for provider in ('codex', 'claude'):
            for number, password in enumerate(values):
                with self.subTest(provider=provider, value=number):
                    source, header = self.fixture(provider, token='plain')
                    rows = canonical.read_jsonl(source)
                    arguments = {'password': password, 'id': 'business-id', 'count': 17}
                    for row in rows:
                        if row.get('payload', {}).get('type') == 'function_call':
                            row['payload']['arguments'] = json.dumps(arguments, ensure_ascii=True)
                        for block in row.get('message', {}).get('content', []):
                            if isinstance(block, dict) and block.get('type') == 'tool_use':
                                block['input'] = arguments
                    source.write_text(''.join(json.dumps(row)+'\n' for row in rows))
                    before = source.read_bytes()
                    bundle = self.export(source, header, scrub=True)
                    _, native = self.contents(bundle)
                    output = self.root/(provider+'-escaped-'+str(number)+'.jsonl')
                    output.write_bytes(native)
                    calls = [block for event in canonical.normalize(provider, output)['events']
                             for block in event['blocks'] if block['type']=='tool_call']
                    self.assertEqual(calls[0]['arguments'], {**arguments, 'password': secrets.REPLACEMENT})
                    self.assertEqual(source.read_bytes(), before)
                    self.assertNotIn(password, self.out.getvalue()+self.err.getvalue())

    def test_scrub_invalid_embedded_json_refuses_publication(self):
        source, header = self.fixture('codex', token='plain')
        rows = canonical.read_jsonl(source)
        for row in rows:
            if row.get('payload', {}).get('type') == 'function_call':
                row['payload']['arguments'] = '{"password":"synthetic-password"'
        source.write_text(''.join(json.dumps(row)+'\n' for row in rows))
        before = source.read_bytes()
        with self.assertRaisesRegex(ValueError, 'invalid JSON tool arguments'):
            self.export(source, header, scrub=True)
        self.assertFalse(list(self.root.rglob('*.zip')))
        self.assertEqual(source.read_bytes(), before)
        self.assertNotIn('synthetic-password', self.out.getvalue()+self.err.getvalue())

    def test_allow_retains_values_without_printing_them(self):
        for provider in ('codex', 'claude'):
            source, header = self.fixture(provider, title=TOKEN)
            original = source.read_bytes()
            bundle = self.export(source, header, allow=True)
            manifest, native = self.contents(bundle)
            self.assertIn(TOKEN.encode(), native)
            self.assertEqual(manifest['sessions'][0]['title'], TOKEN)
            self.assertEqual(source.read_bytes(), original)
            self.assert_masked()

    def test_non_tty_fails_without_zip_or_input(self):
        source, header = self.fixture('codex')
        stream = io.StringIO()
        with patch.object(stream, 'readline', side_effect=AssertionError('must not wait')):
            with self.assertRaisesRegex(ValueError, '--allow-secrets.*--scrub-secrets'):
                self.export(source, header, terminal=stream)
        self.assertFalse(list(self.root.rglob('*.zip')))
        self.assert_masked()

    def test_cancel_leaves_no_zip_and_unchanged_source(self):
        source, header = self.fixture('claude')
        before = source.read_bytes()
        with self.assertRaisesRegex(ValueError, 'cancelled'):
            self.export(source, header, terminal=Terminal('cancel\n'))
        self.assertFalse(list(self.root.rglob('*.zip')))
        self.assertEqual(source.read_bytes(), before)
        self.assert_masked()

    def test_each_distinct_value_decided_once_and_repeated_bare_value_scrubbed(self):
        source, header = self.fixture('codex', token='bare-password-value')
        rows = canonical.read_jsonl(source)
        for row in rows:
            if row.get('payload', {}).get('type') == 'message' and row['payload'].get('role') == 'assistant':
                row['payload']['content'][0]['text'] = OTHER
        source.write_text(''.join(json.dumps(row)+'\n' for row in rows))
        bundle = self.export(source, header, terminal=Terminal('scrub\nkeep\n'))
        _, native = self.contents(bundle)
        self.assertNotIn(b'bare-password-value', native)
        self.assertIn(OTHER.encode(), native)
        self.assertEqual(self.err.getvalue().count('Choose keep / scrub / cancel:'), 2)
        self.assert_masked()

    def test_no_findings_adds_no_prompt(self):
        source, header = self.fixture('codex', token='ordinary text')
        rows = canonical.read_jsonl(source)
        for row in rows:
            if row.get('payload', {}).get('type') == 'function_call':
                row['payload']['arguments'] = '{}'
            if row.get('csl_display_projection', {}).get('kind') == 'historical_tool':
                row['payload']['invocation']['arguments'] = {}
        source.write_text(''.join(json.dumps(row)+'\n' for row in rows))
        for quiet in (False, True):
            with self.subTest(quiet=quiet):
                bundle = self.export(source, header, terminal=Terminal(''), quiet=quiet)
                self.assertTrue(bundle.is_file())
                self.assertNotIn('Choose ', self.err.getvalue())
                self.assertIn('partial', self.err.getvalue())

    def test_scrub_reference_projection_remains_canonical_roundtrippable(self):
        for provider in ('codex', 'claude'):
            source, header = self.fixture(provider, references=True)
            bundle = self.export(source, header, scrub=True)
            _, native = self.contents(bundle)
            output = self.root/(provider+'-references.jsonl')
            output.write_bytes(native)
            data = canonical.normalize(provider, output)
            self.assertNotIn(TOKEN, json.dumps(data['events']))
            self.assertIn('references', data['events'][0]['blocks'][0])

    def test_cli_flags_mutually_exclusive_and_noninteractive_errors_masked(self):
        source, _ = self.fixture('codex')
        for flags in ([], ['--allow-secrets', '--scrub-secrets']):
            result = subprocess.run([sys.executable, str(REPO/'codex_sessions.py'), 'export', str(source), '--to', str(self.root/'fail.zip'), *flags],
                env=self.env, capture_output=True, text=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(TOKEN, result.stdout + result.stderr)
        self.assertFalse((self.root/'fail.zip').exists())

    def test_cli_explicit_flags_and_error_paths_do_not_echo_secrets(self):
        source, _ = self.fixture('codex')
        for flag in ('--scrub-secrets', '--allow-secrets'):
            bundle = self.root / (flag[2:] + '.zip')
            result = subprocess.run([sys.executable, str(REPO/'codex_sessions.py'), 'export', str(source), '--to', str(bundle), flag],
                env=self.env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn(TOKEN, result.stdout + result.stderr)
            _, native = self.contents(bundle)
            self.assertEqual(TOKEN.encode() in native, flag == '--allow-secrets')
        malformed = self.root / (TOKEN + '.jsonl')
        malformed.write_text('{"type":"unsupported"}\n')
        result = subprocess.run([sys.executable, str(REPO/'codex_sessions.py'), 'export', str(malformed), '--to', str(self.root/'bad.zip')],
            env=self.env, capture_output=True, text=True, timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(TOKEN, result.stdout + result.stderr)

    def test_cancel_and_non_tty_never_construct_even_a_staged_zip(self):
        source, header = self.fixture('codex')
        for stream in (io.StringIO(), Terminal('cancel\n')):
            with patch.object(transfer.zipfile, 'ZipFile') as archive:
                with self.assertRaises(ValueError):
                    self.export(source, header, terminal=stream)
                archive.assert_not_called()

    def test_secret_only_in_share_title_blocks_before_zip_or_upload(self):
        source, header = self.fixture('codex', token='ordinary text')
        rows = canonical.read_jsonl(source)
        for row in rows:
            if row.get('payload', {}).get('type') == 'function_call':
                row['payload']['arguments'] = '{}'
        source.write_text(''.join(json.dumps(row)+'\n' for row in rows))
        args = SimpleNamespace(sessions=[str(source)], db=self.root/'index.sqlite', raw=False,
                               title=TOKEN, provider=None)
        with patch.object(sharing, 'configured_repo', return_value='team/private-exchange'), \
             patch.object(sharing, 'run_gh') as gh, patch.object(transfer.zipfile, 'ZipFile') as archive, \
             patch.object(transfer, 'resolve_sources', return_value=[(source, header)]), \
             patch('sys.stdin', io.StringIO()), patch('sys.stdout', io.StringIO()), patch('sys.stderr', io.StringIO()) as err:
            with self.assertRaisesRegex(ValueError, '--allow-secrets'):
                sharing.share(args, self.csl)
            gh.assert_not_called()
            archive.assert_not_called()
            self.assertNotIn(TOKEN, err.getvalue())

    def test_readable_raw_thinking_scanned_but_opaque_bytes_not_modified(self):
        args = SimpleNamespace(scrub_secrets=True)
        review = secrets.SecretReview(args)
        value = {'message': {'content': [{'type': 'thinking', 'thinking': TOKEN},
            {'type': 'image', 'source': {'type': 'base64', 'data': TOKEN}},
            {'type': 'input_image', 'image_url': 'https://user:password123@invalid.test/image'}]}}
        review.scan(value, 'record[1]')
        with patch('sys.stderr', io.StringIO()):
            review.resolve()
        actual = review.cleaned(value)['message']['content']
        self.assertEqual(actual[0]['thinking'], secrets.REPLACEMENT)
        self.assertEqual(actual[1]['source']['data'], TOKEN)
        self.assertNotIn('password123', actual[2]['image_url'])

    def test_private_key_and_assignment_and_no_generic_random_filter(self):
        review = secrets.SecretReview(SimpleNamespace(scrub_secrets=True))
        pem = '-----BEGIN PRIVATE KEY-----\nsynthetic-fixture\n-----END PRIVATE KEY-----'
        text = pem + '\npassword="synthetic-password"\n' + 'q' * 64
        review.scan(text, 'record[1]')
        with patch('sys.stderr', io.StringIO()):
            review.resolve()
        result = review.cleaned(text)
        self.assertNotIn(pem, result)
        self.assertNotIn('synthetic-password', result)
        self.assertIn('q'*64, result)

    def test_share_cannot_upload_before_decisions_and_scrubs_release_metadata(self):
        for action in ('blocked', 'scrub', 'allow', 'cancel'):
            source, header = self.fixture('codex', title=TOKEN)
            args = SimpleNamespace(sessions=[str(source)], db=self.root/'index.sqlite', raw=False,
                title='Handoff '+TOKEN, provider=None, scrub_secrets=action=='scrub', allow_secrets=action=='allow')
            uploaded = []
            def upload(command):
                self.assertEqual(command[:2], ['release', 'create'])
                notes = Path(command[command.index('--notes-file')+1]).read_text()
                with zipfile.ZipFile(command[3]) as archive:
                    contents = b''.join(archive.read(name) for name in archive.namelist())
                uploaded.append((command, notes, contents))
                return ''
            out, err = io.StringIO(), io.StringIO()
            before = source.read_bytes()
            with patch.object(sharing, 'configured_repo', return_value='team/private-exchange'), \
                 patch.object(sharing, 'run_gh', side_effect=upload), \
                 patch.object(transfer, 'resolve_sources', return_value=[(source, header)]), \
                 patch('sys.stdin', Terminal('cancel\n') if action=='cancel' else io.StringIO()), \
                 patch('sys.stdout', out), patch('sys.stderr', err):
                if action in ('blocked', 'cancel'):
                    with self.assertRaises(ValueError):
                        sharing.share(args, self.csl)
                    self.assertEqual(uploaded, [])
                else:
                    sharing.share(args, self.csl)
                    self.assertEqual(len(uploaded), 1)
                    command, notes, contents = uploaded[0]
                    outgoing = json.dumps(command) + notes + contents.decode()
                    self.assertEqual(TOKEN in outgoing, action=='allow')
            self.assertNotIn(TOKEN, out.getvalue()+err.getvalue())
            self.assertEqual(source.read_bytes(), before)


class SecretURLScaleTests(unittest.TestCase):
    def test_long_non_url_scheme_token_is_linear_without_changing_password_selection(self):
        import time
        pattern=next(pattern for name,pattern,_ in secrets.PATTERNS if name=='URL password')
        start=time.monotonic()
        self.assertEqual(list(pattern.finditer('x'*131072)),[])
        self.assertLess(time.monotonic()-start,1.0)
        for prefix in ('','some text ','123','123+.-','[','\u2603'):
            matches=list(pattern.finditer(prefix+'https://user:synthetic-password@invalid.test'))
            self.assertEqual([m.group(1) for m in matches],['synthetic-password'])
