"""No SSH/network/model invocation: verify supervised-session command and truthfulness."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('csl_ssh_session',ROOT/'macos/CSLBridge/ssh_session.py')
module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
class TransportTests(unittest.TestCase):
 def test_command_uses_existing_profile_keepalive_host_checks_no_shell_or_credentials(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'ssh profile';path.write_text('Host approved\n HostName localhost\n');path.chmod(0o600)
   argv=module.ssh_arguments({'ssh_alias':'approved','ssh_config':str(path)})
   self.assertIn('-oExitOnForwardFailure=yes',argv);self.assertIn('-oServerAliveInterval=15',argv)
   self.assertIn('-oStrictHostKeyChecking=yes',argv);self.assertEqual(argv[-2:],['--','approved'])
   self.assertNotIn('StrictHostKeyChecking=no',' '.join(argv));self.assertFalse(any('TOKEN=' in x for x in argv))
   with self.assertRaises(ValueError):module.ssh_arguments({'ssh_alias':'host;execute','ssh_config':str(path)})
 def test_running_process_is_never_labeled_end_to_end_success(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'config';path.write_text('Host approved\n');path.chmod(0o600)
   session=module.SSHSession({'ssh_alias':'approved','ssh_config':str(path)},Path(tmp)/'state.json')
   session.publish('ssh_running_e2e_unverified',ssh_pid=123)
   data=json.loads((Path(tmp)/'state.json').read_text())
   self.assertFalse(data['end_to_end_verified']);self.assertEqual(data['phase'],'ssh_running_e2e_unverified')
 def test_failed_transport_retries_with_bounded_backoff_without_replaying_tasks(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'config';path.write_text('Host approved\n');path.chmod(0o600)
   child=Mock();child.pid=123;child.poll.return_value=255;child.returncode=255
   spawn=Mock(return_value=child);ticks=iter(range(100))
   session=module.SSHSession({'ssh_alias':'approved','ssh_config':str(path)},Path(tmp)/'state.json',spawn=spawn,clock=lambda:next(ticks))
   class Stop:
    def __init__(self):self.delays=[];self.done=False
    def is_set(self):return self.done
    def wait(self,seconds):
     self.delays.append(seconds);self.done=len(self.delays)>=3;return self.done
   stop=Stop();session.stop=stop
   with patch.object(module,'local_banner',return_value='ssh_banner_verified'):session.run()
   self.assertEqual(stop.delays,[1,2,4]);self.assertEqual(spawn.call_count,3)
   self.assertFalse(session.state['end_to_end_verified']);self.assertEqual(session.state['phase'],'stopped')

 def test_shutdown_only_terminates_its_own_child(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'config';path.write_text('Host approved\n');path.chmod(0o600)
   session=module.SSHSession({'ssh_alias':'approved','ssh_config':str(path)},Path(tmp)/'state.json')
   child=Mock();child.poll.return_value=None;session.child=child
   session.terminate_child();child.terminate.assert_called_once();child.wait.assert_called_once()
if __name__=='__main__':unittest.main()
