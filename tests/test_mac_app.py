"""Local backend scope, existing-session and configuration preservation tests."""
import importlib.util
import json
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('csl_app_service',ROOT/'macos/CSLBridge/app_service.py')
app=importlib.util.module_from_spec(spec);sys.modules[spec.name]=app;spec.loader.exec_module(app)
class AppTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  self.service=app.Service(self.root/'state',self.root/'bridge',self.root/'codex')
 def tearDown(self):self.temp.cleanup()
 def test_default_home_does_not_adopt_private_lab_configuration(self):
  with patch.object(app.Path,'home',return_value=self.root):
   legacy=self.root/'.cslb-mac';legacy.mkdir();(legacy/'bridge.sqlite').touch()
   service=app.Service(state_root=self.root/'new-state')
  self.assertEqual(service.home,self.root/'.csl-bridge-app')
  self.assertEqual(shlex.split(service.connection_info()['receiver_command'])[2],'CSL_BRIDGE_PEER=coordinator')
 def test_profile_uses_current_bundled_interpreter_and_only_communication_grant(self):
  import tomllib
  p=tomllib.loads(self.service.mcp_profile())['mcp_servers']['csl_bridge']
  self.assertEqual(p['command'],sys.executable)
  self.assertEqual(p['tools'],{'send_progress':{'approval_mode':'approve'}})
  self.assertEqual(p['default_tools_approval_mode'],'writes')
  self.assertNotIn('followup_task',p['enabled_tools'])
 def test_only_owned_mcp_sections_replaced_other_text_preserved(self):
  old='model="owner-model"\n\n[mcp_servers.other]\ncommand="owner"\n\n[mcp_servers.csl_bridge]\ncommand="old"\n[mcp_servers.csl_bridge.tools.send_progress]\napproval_mode="prompt"\n'
  new,previous=app.Service.replace_owned(old,self.service.mcp_profile())
  self.assertTrue(new.startswith('model="owner-model"\n\n[mcp_servers.other]\ncommand="owner"\n\n'))
  self.assertIn('command="old"',previous)
  self.assertNotIn('owner-model',previous)
 def test_inline_personal_configuration_is_not_rewritten(self):
  with self.assertRaises(app.AppError):app.Service.replace_owned('mcp_servers={csl_bridge={command="owned"}}\n',self.service.mcp_profile())
 def test_live_connector_adopted_no_new_process_or_config_change(self):
  with patch.object(self.service,'status',return_value={'connected':True,'adopted':True}),patch('csl_app_service.subprocess.Popen') as spawn:
   result=self.service.start()
  spawn.assert_not_called();self.assertTrue(result['adopted'])
 def test_disconnected_existing_connector_does_not_start_second_writer(self):
  with patch.object(self.service,'status',return_value={'connected':False,'connector_running':True}),patch('csl_app_service.subprocess.Popen') as spawn:
   with self.assertRaises(app.AppError):self.service.start()
  spawn.assert_not_called()
 def test_unloaded_thread_never_registered(self):
  with patch.object(self.service,'discover',return_value={'sessions':[]}):
   with self.assertRaises(app.AppError):self.service.configure(str(uuid.uuid4()))
  self.assertFalse((self.service.home/'bridge.sqlite').exists())
 def test_stop_refuses_process_not_owned_by_app(self):
  with patch.object(self.service,'owned',return_value=None),patch('csl_app_service.os.kill') as kill:
   with self.assertRaises(app.AppError):self.service.stop()
  kill.assert_not_called()
 def test_live_local_runtime_is_not_remote_readiness(self):
  with patch.object(app,'local_call',return_value={'agents':[{'status':'idle'}]}),patch.object(self.service,'owned',return_value=None):
   result=self.service.status()
  self.assertTrue(result['runtime_ready']);self.assertTrue(result['connector_running'])
  self.assertFalse(result['connected']);self.assertFalse(result['peer']['ready'])
 def test_authenticated_peer_response_required_and_expires(self):
  import time
  app.json_file(self.service.state/'peer-proof.json',{'ready':True,'observed_at':time.time()-60})
  with patch.object(app,'local_call',return_value={'agents':[{'status':'idle'}]}),patch.object(self.service,'owned',return_value=None):
   self.assertFalse(self.service.status()['connected'])
  app.json_file(self.service.state/'peer-proof.json',{'ready':True,'observed_at':time.time(),'phase':'authenticated_application_response'})
  with patch.object(app,'local_call',return_value={'agents':[{'status':'idle'}]}),patch.object(self.service,'owned',return_value=None):
   self.assertTrue(self.service.status()['connected'])
 def test_peer_check_rejects_pid_or_tunnel_only_response(self):
  from csl_bridge_store import Store,encode
  store=Store(self.service.home,create=True)
  with store.transaction() as db:
   db.executemany('INSERT INTO config VALUES(?,?)',[('identity',encode('mac')),('runtime_socket',encode('/unused'))])
   db.execute('INSERT INTO agents VALUES(?,?)',('worker',str(uuid.uuid4())))
   db.execute('INSERT INTO peers VALUES(?,?)',('owner',encode({'transport':'operator','helper':'/unused'})))
  store.close()
  with patch.object(app,'exchange',return_value={'pid':42,'status':'running'}):
   with self.assertRaises(app.AppError):self.service.peer_check()
  self.assertFalse((self.service.state/'peer-proof.json').exists())

 def test_connection_descriptor_shell_quotes_paths(self):
  with patch.object(self.service,'registered',return_value={'worker':str(uuid.uuid4())}):
   result=self.service.connection_info()
  argv=shlex.split(result['receiver_command']);self.assertEqual(argv[0],'env');self.assertIn(sys.executable,argv)
if __name__=='__main__':unittest.main()
