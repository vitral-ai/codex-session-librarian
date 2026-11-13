"""Native per-tool MCP consent gate; synthetic backend/tools and isolated homes.
Never connects to authenticated Ubuntu, credentials, or production bridge state.
"""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json,os,queue,shutil,signal,subprocess,sys,tempfile,threading,time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from csl_bridge_rpc import Runtime

MCP='''import sys,json,pathlib
marker=pathlib.Path(sys.argv[1])
for line in sys.stdin:
 m=json.loads(line)
 if "id" not in m:continue
 method=m["method"]
 if method=="initialize":result={"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"synthetic-consent-control","version":"1"}}
 elif method=="tools/list":result={"tools":[{"name":n,"description":"Synthetic consent control only; no bridge effect","inputSchema":{"type":"object","properties":{},"additionalProperties":False},"annotations":{"readOnlyHint":n=="wait_agent","destructiveHint":False}} for n in ("send_progress","followup_task","wait_agent")]}
 elif method=="tools/call":
  with marker.open("a") as f:f.write(m["params"]["name"]+"\\n")
  result={"content":[{"type":"text","text":"SYNTHETIC-TOOL-COMPLETED"}],"isError":False}
 else:result={}
 print(json.dumps({"jsonrpc":"2.0","id":m["id"],"result":result}),flush=True)
'''
class Backend:
 def __init__(self,tool):
  self.tool=tool;self.requests=[];outer=self
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*_):pass
   def do_POST(self):
    body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));outer.requests.append(body)
    if body.get('tools') and not any(i.get('type')=='function_call_output' for i in body.get('input',[])):
     namespace=next(t['name'] for t in body['tools'] if t.get('name')=='mcp__consent_control')
     item={'id':'synthetic-call','type':'function_call','name':outer.tool,'namespace':namespace,'call_id':'synthetic-consent-call','arguments':'{}'}
    else:item={'id':'synthetic-final','type':'message','role':'assistant','status':'completed','content':[{'type':'output_text','text':'SYNTHETIC-FINAL','annotations':[]}]}
    events=[{'type':'response.output_item.added','output_index':0,'item':item},{'type':'response.output_item.done','output_index':0,'item':item},{'type':'response.completed','response':{'id':'synthetic-response','status':'completed','output':[item],'usage':{'input_tokens':1,'output_tokens':1,'total_tokens':2}}}]
    raw=''.join('event: '+e['type']+'\ndata: '+json.dumps(e)+'\n\n' for e in events).encode()
    self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
  self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.daemon_threads=True
  self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
 def close(self):self.server.shutdown();self.server.server_close();self.thread.join(timeout=2)

def case(root,label,tool,override=None):
 directory=root/label;directory.mkdir(mode=0o700)
 for name in ('home','codex','project'):(directory/name).mkdir(mode=0o700)
 mcp=directory/'synthetic_mcp.py';mcp.write_text(MCP);marker=directory/'tool-called.txt'
 backend=Backend(tool);sock=directory/'native.sock';log=(directory/'native.log').open('w')
 env={'PATH':os.environ['PATH'],'HOME':str(directory/'home'),'CODEX_HOME':str(directory/'codex'),'CODEX_SQLITE_HOME':str(directory/'codex'/'sqlite'),'LANG':'C.UTF-8','NO_PROXY':'127.0.0.1,localhost','DISABLE_TELEMETRY':'1','DISABLE_ERROR_REPORTING':'1'}
 command=['codex','app-server','--listen','unix://'+str(sock),'-c','cli_auth_credentials_store="ephemeral"','-c','analytics.enabled=false','-c','web_search="disabled"','-c','model="csl-synthetic"','-c','model_provider="consent_gate"','-c','model_providers.consent_gate.name="Synthetic consent gate"','-c','model_providers.consent_gate.base_url="http://127.0.0.1:'+str(backend.server.server_port)+'/v1"','-c','model_providers.consent_gate.wire_api="responses"','-c','model_providers.consent_gate.requires_openai_auth=false','-c','model_providers.consent_gate.supports_websockets=false']
 process=subprocess.Popen(command,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True);runtime=None;tid=None
 (directory/'native.pid').write_text(str(process.pid))
 try:
  end=time.monotonic()+10
  while not sock.exists():
   if time.monotonic()>end or process.poll() is not None:raise RuntimeError('Synthetic native startup failed')
   time.sleep(.05)
  runtime=Runtime(sock)
  config={'command':sys.executable,'args':[str(mcp),str(marker)],'required':True,'default_tools_approval_mode':'writes'}
  if override:config['tools']={'send_progress':{'approval_mode':override}}
  tid=runtime.call('thread/start',{'cwd':str(directory/'project'),'sandbox':'workspace-write','approvalPolicy':'on-request','config':{'mcp_servers':{'consent_control':config}}})['thread']['id']
  runtime.call('turn/start',{'threadId':tid,'input':[{'type':'text','text':'Run synthetic consent control, no real task.'}]})
  result={'label':label,'selected_tool':tool,'override_send_progress':override,'sandbox':'workspace-write','approval_policy':'on-request','approval_requested':False,'native_completed':False}
  end=time.monotonic()+10
  while time.monotonic()<end:
   try:event=runtime.events.get(timeout=.1)
   except queue.Empty:continue
   if 'id' in event and event.get('method')=='mcpServer/elicitation/request':
    meta=event['params'].get('_meta',{});result.update(approval_requested=True,approval_tool=meta.get('tool_name'),native_request=event['method']);break
   if event.get('method')=='turn/completed':result['native_completed']=True;break
  result['tool_calls']=marker.read_text().splitlines() if marker.exists() else []
  result['auth_file_present']=(directory/'codex'/'auth.json').exists()
  (directory/'result.json').write_text(json.dumps(result,indent=2));return result
 finally:
  if runtime:
   if tid:
    try:runtime.call('turn/interrupt',{'threadId':tid,'turnId':runtime.call('thread/turns/list',{'threadId':tid,'limit':1,'itemsView':'notLoaded','sortDirection':'desc'})['data'][0]['id']},timeout=2)
    except Exception:pass
   runtime.close()
  if process.poll() is None:
   os.killpg(process.pid,signal.SIGTERM)
   try:process.wait(timeout=3)
   except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=3)
  log.close();backend.close()

def main():
 root=Path(tempfile.mkdtemp(prefix='csl-mcp-consent-gate-'));print('LAB_ROOT',root,flush=True)
 results=[]
 for label,tool,override in [('baseline-writes','send_progress',None),('per-tool-auto','send_progress','auto'),('per-tool-approve','send_progress','approve'),('per-tool-prompt','send_progress','prompt'),('scope-unapproved-followup','followup_task','approve'),('readonly-wait','wait_agent','approve')]:
  result=case(root,label,tool,override);results.append(result);print(json.dumps(result),flush=True)
 report={'native_version':subprocess.check_output(['codex','--version']).decode().strip(),'real_model_inference':False,'authenticated_runtime_accessed':False,'root':str(root),'results':results}
 (root/'report.json').write_text(json.dumps(report,indent=2))
 print('REPORT', root/'report.json', flush=True)
if __name__=='__main__':main()
