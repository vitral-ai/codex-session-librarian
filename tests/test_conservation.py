"""Human conservation summaries from existing diagnostics, with isolated synthetic homes."""
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
import uuid

import test_conversion_cli as fixtures
import csl_canonical as canonical
import csl_diagnostics as diagnostics

ROOT=Path(__file__).resolve().parents[1]

class ConservationTests(unittest.TestCase):
    setUp=fixtures.ConversionCliTests.setUp
    tearDown=fixtures.ConversionCliTests.tearDown
    write_source=fixtures.ConversionCliTests.write_source
    cli=fixtures.ConversionCliTests.cli
    installed=fixtures.ConversionCliTests.installed

    def generated(self, pairs=0):
        target=self.root/('comparison-'+uuid.uuid4().hex)
        result=subprocess.run([sys.executable,str(ROOT/'demo/native_import_fixture.py'),'--out',str(target),'--pairs',str(pairs)],env=self.env,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        return target,json.loads(result.stdout)

    def test_two_way_conversion_counts_errors_and_independent_identity(self):
        root,fixture=self.generated();source=root/'source.jsonl';before=source.read_bytes()
        first=self.cli('convert',source,'--to','codex','--cwd',self.cwd)
        second=self.cli('convert',source,'--to','codex','--cwd',self.cwd)
        a,b=(self.installed(result.stdout,'codex') for result in (first,second))
        self.assertNotEqual(a,b)
        for result in (first,second):
            self.assertIn('5 text/media message records; 1 correlated historical tool pairs; 1 result error flags',result.stdout)
            self.assertIn('independent codex copy',result.stdout)
            self.assertIn('native CLI loading=not-tested; model continuation=not-tested',result.stdout)
            self.assertNotIn('touch HISTORICAL_NEVER_EXECUTE',result.stdout)
            self.assertNotIn('SYNTHETIC-TOOL-7392',result.stdout)
        reverse=self.cli('convert',a,'--to','claude','--cwd',self.cwd)
        self.assertIn('1 correlated historical tool pairs; 1 result error flags',reverse.stdout)
        converted=canonical.normalize('claude',self.installed(reverse.stdout,'claude'))
        self.assertEqual(canonical.semantic_events(converted),canonical.semantic_events(canonical.normalize('claude',source)))
        self.assertEqual(source.read_bytes(),before)
        self.assertEqual(a.stat().st_mode&0o777,0o600)
        self.assertFalse((self.cwd/'HISTORICAL_NEVER_EXECUTE').exists())

    def test_native_and_converted_zip_import_summaries_keep_package_contract(self):
        root,fixture=self.generated();source=root/'source.jsonl';bundle=self.root/'fixture.zip'
        self.cli('export',source,'--to',bundle);before=hashlib.sha256(bundle.read_bytes()).hexdigest()
        self.assertNotIn('Conservation (',self.cli('import',bundle,'--list').stdout)
        native=self.cli('import',bundle,'--cwd',self.cwd)
        converted=self.cli('import',bundle,'--target','codex','--cwd',self.cwd)
        for result in (native,converted):
            self.assertIn('1 correlated historical tool pairs; 1 result error flags',result.stdout)
            self.assertIn('Conservation (selected history;',result.stdout)
        self.assertNotIn('canonical/native representation',native.stdout)
        self.assertIn('canonical/native representation',converted.stdout)
        self.assertEqual(hashlib.sha256(bundle.read_bytes()).hexdigest(),before)
        repeat=self.cli('import',bundle,'--cwd',self.cwd)
        self.assertNotEqual(self.installed(native.stdout,'claude'),self.installed(repeat.stdout,'claude'))

    def test_summary_uses_destination_counts_after_message_grouping(self):
        data=canonical.from_codex(self.source)
        duplicate=copy.deepcopy(data['events'][0]);duplicate['id']='synthetic-adjacent-user'
        data['events'].insert(1,duplicate)
        source=self.root/'grouping.json';canonical.write_json(source,data)
        result=self.cli('convert',source,'--to','claude','--cwd',self.cwd)
        destination=self.installed(result.stdout,'claude')
        observation={};diagnostics.analyze(destination,'claude',observation=observation)
        selected=diagnostics.conversion_observation(data)
        self.assertNotEqual(selected['messages'],observation['messages'])
        self.assertIn(f"{observation['messages']} text/media message records",result.stdout)
        self.assertIn(f"from {selected['messages']} to {observation['messages']}",result.stdout)

    def test_untrusted_manifest_omission_field_not_echoed_or_rejected(self):
        import zipfile
        bundle=self.root/'raw.zip';self.cli('export',self.source,'--to',bundle)
        with zipfile.ZipFile(bundle) as archive:members={n:archive.read(n) for n in archive.namelist()}
        manifest=json.loads(members['manifest.json']);secret='PRIVATE-SYNTHETIC-MANIFEST-8921'
        manifest['sessions'][0]['encrypted_items_removed']=secret
        members['manifest.json']=json.dumps(manifest).encode()
        modified=self.root/'compatible.zip'
        with zipfile.ZipFile(modified,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            for name,content in members.items():archive.writestr(name,content)
        result=self.cli('import',modified,'--cwd',self.cwd)
        self.assertNotIn(secret,result.stdout+result.stderr)
        self.assertIn('unrecognized source-package omission count',result.stdout)

    def test_machine_reports_unchanged_and_observation_adds_no_file_reads(self):
        source=self.source
        count=0
        real=canonical.read_jsonl
        def read(path):
            nonlocal count
            count+=1
            return real(path)
        with patch.object(canonical,'read_jsonl',side_effect=read):
            expected=diagnostics.analyze(source,'codex');self.assertEqual(count,1)
            observation={};actual=diagnostics.analyze(source,'codex',observation=observation);self.assertEqual(count,2)
        self.assertEqual(expected,actual)
        self.assertNotIn('observation',actual)
        self.assertEqual(observation['tool_pairs'],1)
        result=self.cli('doctor',source,'--json')
        document=json.loads(result.stdout);self.assertEqual(set(document),{'schema_version','sessions'})
        self.assertNotIn('Conservation (',result.stdout)
        exported=self.root/'canonical.json';self.cli('convert',source,'--to','canonical','--out',exported)
        data=json.loads(exported.read_text());canonical.validate(data)
        self.assertEqual(set(data),{'format','version','source','source_context','events','report'})

    def test_report_and_tool_secrets_never_reflected_by_new_summary(self):
        data=canonical.from_codex(self.source)
        secret='PRIVATE-SYNTHETIC-PROVENANCE-9381'
        data['report']['warnings']=[secret]
        data['report']['ignored_native_state'][secret]=7
        for event in data['events']:
            for block in event['blocks']:
                if block['type']=='tool_call':block['arguments']=secret
                if block['type']=='tool_result':block['content']=[{'type':'text','text':secret}]
        source=self.root/'sensitive.json';canonical.write_json(source,data)
        result=self.cli('convert',source,'--to','claude','--cwd',self.cwd)
        self.assertNotIn(secret,result.stdout+result.stderr)
        self.assertIn('content/projection warnings recorded',result.stdout)
        self.assertIn('1 source context/policy records',result.stdout)

    def test_selection_omission_provider_text_and_unknown_outcomes_are_explicit(self):
        self.records.extend([
            {'type':'response_item','payload':{'type':'reasoning','encrypted_content':'PRIVATE-OPAQUE-9381'}},
            {'type':'response_item','payload':{'type':'web_search_call','status':'completed','query':'PRIVATE-PROVIDER-9381'}}])
        self.write_source()
        result=self.cli('convert',self.source,'--to','claude','--cwd',self.cwd)
        self.assertIn('1 reasoning records',result.stdout)
        self.assertIn('1 provider actions represented as historical text',result.stdout)
        self.assertNotIn('PRIVATE-OPAQUE-9381',result.stdout)
        self.assertNotIn('PRIVATE-PROVIDER-9381',result.stdout)
        self.records=[row for row in self.records if row.get('payload',{}).get('type')!='custom_tool_call_output'];self.write_source()
        rejected=self.cli('convert',self.source,'--to','claude','--cwd',self.cwd,ok=False)
        self.assertEqual(rejected.returncode,2);self.assertNotIn('Conservation (',rejected.stdout)
        repaired=self.cli('convert',self.source,'--to','claude','--cwd',self.cwd,'--repair-interrupted')
        self.assertIn('0 correlated historical tool pairs',repaired.stdout)
        self.assertIn('synthetic UNKNOWN results',repaired.stdout)

    def test_textual_tool_descriptions_not_promoted_and_rejection_installs_nothing(self):
        root,fixture=self.generated();source=root/'source.jsonl';data=canonical.normalize('claude',source)
        text=[{'role':'assistant','blocks':[{'type':'text','text':'external_agent_tool_call call_id=unknown; external_agent_tool_result error'}]}]
        self.assertEqual(diagnostics.observe_blocks(text)['tool_pairs'],0)
        data['events'][0]['blocks']=[{'type':'audio','data':'unsupported'}]
        # Invalid input is written only as a fixture; the public writer rejects it.
        invalid=self.root/'unsupported.json';invalid.write_text(json.dumps(data));before=list(self.claude.rglob('*.jsonl'))
        result=self.cli('convert',invalid,'--to','claude','--cwd',self.cwd,ok=False)
        self.assertEqual(result.returncode,2);self.assertNotIn('Conservation (',result.stdout)
        self.assertEqual(list(self.claude.rglob('*.jsonl')),before)
        truncated=self.root/'truncated.jsonl';truncated.write_text(source.read_text()[:-4])
        digest=hashlib.sha256(truncated.read_bytes()).hexdigest()
        result=self.cli('convert',truncated,'--to','codex','--cwd',self.cwd,ok=False)
        self.assertEqual(result.returncode,2);self.assertNotIn('Conservation (',result.stdout)
        self.assertEqual(hashlib.sha256(truncated.read_bytes()).hexdigest(),digest)

    def test_fixture_refuses_existing_paths_and_summary_scales_without_new_io(self):
        root,fixture=self.generated(600);source=root/'source.jsonl'
        self.assertEqual(fixture['CLI_or_model_calls'],0)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),fixture['sha256'])
        self.assertEqual(hashlib.sha256((root/fixture['native_source']).read_bytes()).hexdigest(),fixture['sha256'])
        self.assertEqual(root.stat().st_mode&0o777,0o700)
        self.assertEqual(source.stat().st_mode&0o777,0o600)
        result=subprocess.run([sys.executable,str(ROOT/'demo/native_import_fixture.py'),'--out',str(root)],env=self.env,capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        start=time.monotonic();data=canonical.normalize('claude',source);elapsed=time.monotonic()-start
        with patch.object(Path,'open',side_effect=AssertionError('summary may not re-open files')):
            observation=diagnostics.conversion_observation(data)
            with contextlib.redirect_stdout(io.StringIO()) as output:
                diagnostics.print_conservation({'structure':'passed'}, {}, provider='codex',conversion=observation)
        self.assertEqual(observation['messages'],1205)
        self.assertEqual(observation['tool_pairs'],1)
        self.assertIn('1205 text/media message records',output.getvalue())
        self.assertLess(elapsed,10)
        result=self.cli('convert',source,'--to','codex','--cwd',self.cwd)
        self.assertIn('1205 text/media message records',result.stdout)
        restored=canonical.normalize('codex',self.installed(result.stdout,'codex'))
        self.assertEqual(canonical.semantic_events(restored),canonical.semantic_events(data))
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),fixture['sha256'])


if __name__=='__main__':unittest.main()
