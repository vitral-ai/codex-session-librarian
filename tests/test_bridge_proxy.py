"""Raw byte transport preserves WS framing; only own transport child is terminated."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from csl_bridge_rpc import ProxyStream,Runtime,RuntimeUnavailable

class ProxyTests(unittest.TestCase):
 def test_proxy_transport_relays_exact_bytes_and_has_no_shell_or_model_arguments(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);exe=root/'proxy with spaces';trace=root/'argv.json'
   exe.write_text('#!'+sys.executable+'\nimport os,sys,json\nfrom pathlib import Path\nPath('+repr(str(trace))+').write_text(json.dumps(sys.argv[1:]))\nwhile True:\n b=os.read(0,65536)\n if not b:break\n os.write(1,b)\n')
   exe.chmod(0o700);stream=ProxyStream(root/'selected socket.sock',exe)
   try:
    stream.settimeout(2);raw=b'GET / HTTP/1.1\r\n\x81\x82\xff\x00';stream.sendall(raw)
    self.assertEqual(stream.recv(len(raw)),raw)
    import json
    self.assertEqual(json.loads(trace.read_text()),['app-server','proxy','--sock',str(root/'selected socket.sock')])
   finally:stream.close()
   self.assertIsNotNone(stream.process.poll())
 def test_missing_proxy_fails_without_starting_a_replacement_server(self):
  with self.assertRaises(RuntimeUnavailable):
   Runtime('/nonexistent/explicit.sock',proxy_executable='/nonexistent/codex')
if __name__=='__main__':unittest.main()
