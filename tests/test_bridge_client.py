"""Explicit current-caller mode: no runtime attach or implicit async delivery."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from csl_bridge_engine import Connector
from csl_bridge_store import BridgeError, Store, encode
from csl_bridge_transport import ssh_argv

class ClientTests(unittest.TestCase):
 def test_current_caller_wait_delivers_correlated_event_without_runtime(self):
  with tempfile.TemporaryDirectory() as tmp:
   home=Path(tmp)/'origin'; thread=str(uuid.uuid4()); task=str(uuid.uuid4()); turn=str(uuid.uuid4())
   store=Store(home,create=True)
   with store.transaction() as db:
    db.executemany('INSERT INTO config VALUES(?,?)',[('identity',encode('manunruks')),('runtime_socket',encode(None))])
    db.execute('INSERT INTO agents VALUES(?,?)',('coordinator',thread))
    db.execute('INSERT INTO peers VALUES(?,?)',('ubuntu',encode({'transport':'receive-only','allow_agents':['coordinator'],'allow_ops':['followup','status']})))
   request={'version':1,'op':'followup','id':task,'source':'coordinator','target':'worker','text':'Review synthetic fixture'}
   store.reserve('outbound:ubuntu',request);store.operation(task,'delivered',{'turn_id':turn});store.close()
   factory=Mock(side_effect=AssertionError('No runtime may be contacted'))
   connector=Connector(home,runtime_factory=factory)
   try:
    connector.start()
    self.assertEqual(connector.current('coordinator')['thread_id'],thread)
    self.assertEqual(connector.current('coordinator')['status'],'tool-client')
    event={'id':str(uuid.uuid4()),'task_id':task,'source':'worker','target':'coordinator','kind':'final','text':'Observed synthetic result','turn_id':turn,'status':'completed'}
    connector.accept_event('ubuntu',{'seq':1,'event':event})
    row=connector.store.rows('SELECT delivery FROM inbound')[0]
    self.assertEqual(row['delivery'],'pending') # not falsely claimed as injected
    output=connector.local({'local_op':'wait','agent':'coordinator','after':0,'timeout':0})
    self.assertEqual(output['events'][0]['event'],event)
    self.assertEqual(connector.store.rows('SELECT delivery FROM inbound')[0]['delivery'],'delivered')
    with self.assertRaises(BridgeError):
     connector.incoming('ubuntu',{**request,'id':str(uuid.uuid4()),'source':'worker','target':'coordinator'})
    factory.assert_not_called()
   finally:connector.close()
 def test_explicit_private_ssh_config_is_one_literal_argument(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'config with spaces';path.write_text('Host ubuntu-bridge\n HostName 127.0.0.1\n');path.chmod(0o600)
   argv=ssh_argv('ubuntu-bridge',path)
   self.assertEqual(argv[1:3],['-F',str(path)])
   self.assertEqual(argv[-2:],['ubuntu-bridge','csl-bridge-receiver'])
   path.chmod(0o644)
   with self.assertRaises(BridgeError):ssh_argv('ubuntu-bridge',path)
   path.chmod(0o600);link=Path(tmp)/'link';link.symlink_to(path)
   with self.assertRaises(BridgeError):ssh_argv('ubuntu-bridge',link)
if __name__=='__main__':unittest.main()
