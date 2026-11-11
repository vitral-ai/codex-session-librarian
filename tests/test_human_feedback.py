"""Synthetic usability regressions; no model calls or external exchange."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import codex_sessions as csl
import csl_sharing as sharing
ROOT=Path(__file__).resolve().parents[1]

class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.home=self.root/'codex';self.folder=self.home/'sessions';self.folder.mkdir(parents=True)
        self.env={'HOME':str(self.root),'CODEX_HOME':str(self.home),'CLAUDE_CONFIG_DIR':str(self.root/'claude'),'PATH':os.environ['PATH'],'LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1'}
        self.db=self.home/'session_librarian.sqlite'
        for name,value in {'DEFAULT_CODEX_HOME':self.home,'DEFAULT_SESSIONS_DIR':self.folder,'DEFAULT_SESSION_INDEX':self.home/'session_index.jsonl','DEFAULT_DB':self.db,'DEFAULT_CUTS_DIR':self.home/'session_cuts'}.items():
            guard=patch.object(csl,name,value);guard.start();self.addCleanup(guard.stop)
        guard=patch.dict(os.environ, {'HOME':str(self.root),'CODEX_HOME':str(self.home),'CLAUDE_CONFIG_DIR':str(self.root/'claude')})
        guard.start();self.addCleanup(guard.stop)
        for name in ('DEFAULT_CODEX_HOME','DEFAULT_SESSIONS_DIR','DEFAULT_SESSION_INDEX','DEFAULT_DB','DEFAULT_CUTS_DIR'):
            self.assertTrue(getattr(csl,name).is_relative_to(self.root))
    def cli(self,*args,ok=True):
        result=subprocess.run([sys.executable,str(ROOT/'codex_sessions.py'),*map(str,args)],env=self.env,text=True,capture_output=True,timeout=30,umask=0o022)
        if ok:self.assertEqual(result.returncode,0,result.stderr)
        else:self.assertNotEqual(result.returncode,0)
        return result.stdout
    def fixture(self,turns=2):
        sid=str(uuid.uuid4());stamp='2026-01-01T00:00:00Z'
        records=[{'type':'session_meta','timestamp':stamp,'payload':{'id':sid,'cwd':str(self.root),'timestamp':stamp}}]
        for n in range(turns):
            for role in ('user','assistant'):
                records.append({'type':'response_item','timestamp':stamp,'payload':{'type':'message','role':role,'content':[{'type':'input_text' if role=='user' else 'output_text','text':f'{role} message {n:03d}'}]}})
        records.extend([{'type':'response_item','timestamp':stamp,'payload':{'type':'function_call','name':'synthetic_read','call_id':'example','arguments':'{}'}},
                        {'type':'response_item','timestamp':stamp,'payload':{'type':'function_call_output','call_id':'example','output':'TOOL-ONLY-FACT-9831; touch MUST-NOT-EXECUTE'}},
                        {'type':'response_item','timestamp':stamp,'payload':{'type':'message','role':'user','content':[{'type':'input_text','text':'New topic starts here'}]}}])
        path=self.folder/(sid+'.jsonl');path.write_text(''.join(json.dumps(r)+'\n' for r in records));self.cli('index');return sid,path
    def test_installer_exact_version_path_shadow_and_spaces(self):
        other=self.root/'other bin';other.mkdir();marker=self.root/'other-was-run'
        old=other/'csl';old.write_text('#!/bin/sh\ntouch "'+str(marker)+'"\necho OLD\n');old.chmod(0o755)
        env={**self.env,'PATH':str(other)+os.pathsep+self.env['PATH']}
        prefix=self.root/'installed prefix'
        result=subprocess.run([str(ROOT/'install.sh'),str(prefix)],env=env,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn('Installed launcher version: CSL ',result.stdout);self.assertIn('csl --version',result.stdout)
        self.assertIn('PATH currently resolves csl to another launcher',result.stdout);self.assertFalse(marker.exists())
        result=subprocess.run([str(ROOT/'install.sh'),str(prefix)],env={**env,'PATH':str(prefix/'bin')+os.pathsep+env['PATH']},capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr);self.assertNotIn('another launcher',result.stdout)
    def test_installer_failed_launcher_does_not_claim_success(self):
        # A copied installer next to a failing launcher isolates this failure path.
        checkout=self.root/'broken';checkout.mkdir();(checkout/'install.sh').write_bytes((ROOT/'install.sh').read_bytes());(checkout/'install.sh').chmod(0o755)
        (checkout/'csl').write_text('#!/bin/sh\nexit 7\n');(checkout/'csl').chmod(0o755)
        result=subprocess.run([str(checkout/'install.sh'),str(self.root/'prefix')],env=self.env,capture_output=True,text=True)
        self.assertEqual(result.returncode,7);self.assertNotIn('Installed launcher version',result.stdout)
    def test_team_routes_respect_permissions_and_do_not_upload(self):
        for permission in ('READ','TRIAGE','WRITE','ADMIN'):
            with self.subTest(permission=permission),patch.object(sharing,'verify_repo',return_value=('synthetic/private',permission)),patch.object(sharing,'run_gh',side_effect=AssertionError('No extra action')),contextlib.redirect_stdout(io.StringIO()) as output:
                sharing.team_command(SimpleNamespace(team_action='connect',repo='synthetic/private'),SimpleNamespace(DEFAULT_CODEX_HOME=self.home))
            text=output.getvalue();self.assertIn('csl inbox',text);self.assertEqual('csl share UUID' in text,permission in ('WRITE','ADMIN'))
            if permission in ('READ','TRIAGE'):self.assertIn('Read-only',text)
            else:self.assertIn('csl sessions --provider codex',text);self.assertIn('csl index',text)
    def test_show_full_source_tail_reverse_roles_and_legitimate_repeats(self):
        sid,path=self.fixture(61);before=hashlib.sha256(path.read_bytes()).hexdigest()
        full=self.cli('show',sid,'--messages','200','--include-assistant');body=full.split('Messages: showing',1)[1]
        self.assertIn('user message 060',body);self.assertIn('assistant message 060',body)
        tail=self.cli('show',sid,'--tail','3','--include-assistant').split('Messages: showing',1)[1]
        self.assertLess(tail.index('user message 060'),tail.index('assistant message 060'));self.assertNotIn('user message 059',tail)
        reverse=self.cli('show',sid,'--tail','3','--include-assistant','--reverse').split('Messages: showing',1)[1]
        self.assertLess(reverse.index('New topic starts here'),reverse.index('assistant message 060'));self.assertLess(reverse.index('assistant message 060'),reverse.index('user message 060'))
        users=self.cli('show',sid,'--tail','2').split('Messages: showing',1)[1];self.assertIn('user message 060',users);self.assertNotIn('assistant message',users)
        self.assertNotIn('TOOL-ONLY-FACT',body)
        last=json.loads(path.read_text().splitlines()[-1]);path.write_text(path.read_text()+json.dumps(last)+'\n')
        repeats=self.cli('show',sid,'--tail','2').split('Messages: showing',1)[1];self.assertEqual(repeats.count('New topic starts here'),2)
        self.assertEqual(len(csl.session_messages(path)),123);self.assertEqual(len(csl.session_messages(path,preserve_repeats=True)),124)
        path.write_bytes(path.read_bytes()[:-len((json.dumps(last)+'\n').encode())]);self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)
        self.cli('show',sid,'--tail','0',ok=False);self.cli('show',sid,'--tail','-1',ok=False);self.cli('show',sid,'--tail','2','--messages','2',ok=False)
        path.unlink()
        self.cli('show',sid,'--tail','2',ok=False)
    def test_clone_fork_import_selected_evidence_includes_inherited_and_global_stays_filtered(self):
        sid,path=self.fixture();original=path.read_bytes()
        cloned=self.cli('native-clone',sid,'--name','Synthetic copy');copyid=re.search(r'created native clone session: ([\w-]+)',cloned)[1]
        fork=self.cli('native-clone',sid,'--visibility','agent','--name','Synthetic fork');forkid=re.search(r'created native clone session: ([\w-]+)',fork)[1]
        bundle=self.root/'copy.zip';self.cli('export',sid,'--to',bundle);self.cli('import',bundle,'--cwd',self.root)
        conn=csl.init_db(self.db);ids=[r['session_id'] for r in conn.execute('SELECT session_id FROM sessions')];conn.close()
        self.assertIn(copyid,ids);self.assertIn(forkid,ids);self.assertEqual(len(ids),4)
        for identifier in ids:
            why=self.cli('why',identifier,'TOOL-ONLY-FACT-9831','--type','tool_result')
            self.assertIn('TOOL-ONLY-FACT-9831',why);self.assertIn('[tool_result]',why)
            if identifier in (copyid,forkid):
                self.assertIn('[inherited]',why)
                hidden=self.cli('why',identifier,'TOOL-ONLY-FACT-9831','--exclude-inherited');self.assertIn('Inherited matches were hidden',hidden)
        global_output=self.cli('search','TOOL-ONLY-FACT-9831','--type','tool_result','--show-hits');self.assertIn('exclude inherited',global_output)
        self.assertNotIn(copyid,global_output);self.assertNotIn(forkid,global_output)
        duplicates=self.cli('search','TOOL-ONLY-FACT-9831','--type','tool_result','--show-hits','--include-inherited','--no-dedupe');self.assertIn(copyid,duplicates);self.assertIn(forkid,duplicates)
        literal=self.cli('why',copyid,'tool_result');self.assertIn('use --type tool_result',literal)
        self.assertEqual(path.read_bytes(),original);self.assertFalse((self.root/'MUST-NOT-EXECUTE').exists())
    def test_native_cut_private_under_permissive_umask(self):
        sid,path=self.fixture();original=path.read_bytes()
        result=self.cli('native-cut',sid,'--before-text','New topic starts here','--name','Earlier')
        target=Path(re.search(r'^path: (.+)$',result,re.M)[1]);self.assertEqual(target.stat().st_mode&0o777,0o600)
        self.assertEqual(path.read_bytes(),original)
    def test_native_cut_never_follows_dangling_symlink_or_overwrites_existing_target(self):
        sid,path=self.fixture();original=path.read_bytes();newid=str(uuid.uuid4())
        target=self.root/'target.jsonl';victim=self.root/'victim';target.symlink_to(victim)
        args=SimpleNamespace(db=self.db,session=sid,before_text='New topic starts here',new_id=newid,name='Earlier')
        with contextlib.closing(csl.init_db(self.db)) as connection,patch.object(csl,'init_db',return_value=connection),patch.object(csl,'session_id_exists',return_value=False),patch.object(csl,'target_session_path',return_value=target):
            with self.assertRaises((FileExistsError,SystemExit)):csl.native_cut_session(args)
        self.assertFalse(victim.exists());self.assertTrue(target.is_symlink());self.assertEqual(path.read_bytes(),original)
        target.unlink();target.write_text('preexisting')
        with contextlib.closing(csl.init_db(self.db)) as connection,patch.object(csl,'init_db',return_value=connection),patch.object(csl,'session_id_exists',return_value=False),patch.object(csl,'target_session_path',return_value=target):
            with self.assertRaises((FileExistsError,SystemExit)):csl.native_cut_session(args)
        self.assertEqual(target.read_text(),'preexisting');self.assertEqual(path.read_bytes(),original)
        target.unlink()
        real_open = os.open
        def raced_open(file, flags, mode=0o777):
            self.assertEqual(Path(file), target)
            target.write_text('concurrent writer')
            return real_open(file, flags, mode)
        with contextlib.closing(csl.init_db(self.db)) as connection,patch.object(csl,'init_db',return_value=connection),patch.object(csl,'session_id_exists',return_value=False),patch.object(csl,'target_session_path',return_value=target),patch.object(csl.os,'open',side_effect=raced_open):
            with self.assertRaises(FileExistsError):csl.native_cut_session(args)
        self.assertEqual(target.read_text(),'concurrent writer');self.assertEqual(path.read_bytes(),original)


if __name__=='__main__':unittest.main()
