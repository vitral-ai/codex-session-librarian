"""Native-engine gate with a protocol UI client (not the interactive TUI). Fake loopback Responses; never real inference/auth."""
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import os
import queue
import signal
import subprocess
import tempfile
import threading
import time
import uuid
import base64
import socket
import struct


class Client:
    def __init__(self, executable, sock, env, root, label):
        self.label = label
        self.messages = []
        self.condition = threading.Condition()
        self.number = 0
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.connect(str(sock))
        self.socket.settimeout(20)
        key = base64.b64encode(os.urandom(16)).decode()
        self.socket.sendall(('GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n'
            'Connection: Upgrade\r\nSec-WebSocket-Key: ' + key + '\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
        headers = b''
        while not headers.endswith(b'\r\n\r\n'):
            headers += self.socket.recv(1)
        assert b'101 Switching Protocols' in headers, headers
        self.socket.settimeout(None)
        self.write_lock = threading.Lock()
        self.closed = False
        def read_exact(size):
            out = b''
            while len(out) < size:
                data = self.socket.recv(size - len(out))
                if not data:
                    raise EOFError
                out += data
            return out
        def read():
            try:
                while True:
                    first, second = read_exact(2)
                    length = second & 127
                    if length == 126:
                        length = struct.unpack('!H', read_exact(2))[0]
                    elif length == 127:
                        length = struct.unpack('!Q', read_exact(8))[0]
                    assert length < 16000000
                    mask = read_exact(4) if second & 128 else None
                    raw = read_exact(length)
                    if mask:
                        raw = bytes(x ^ mask[i % 4] for i, x in enumerate(raw))
                    opcode = first & 15
                    if opcode == 8:
                        break
                    if opcode == 9:
                        self.frame(raw, 10)
                        continue
                    if opcode != 1:
                        continue
                    msg = json.loads(raw)
                    with self.condition:
                        self.messages.append(msg)
                        self.condition.notify_all()
            except (EOFError, OSError):
                pass
            with self.condition:
                self.messages.append({'closed': True})
                self.condition.notify_all()
        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        self.call('initialize', {'clientInfo': {'name': 'csl_bridge_gate_' + label, 'version': '1'},
                                 'capabilities': {'experimentalApi': True}})
        self.send({'method': 'initialized', 'params': {}})

    def send(self, value):
        self.frame(json.dumps(value).encode())

    def frame(self, raw, opcode=1):
        size = len(raw)
        prefix = bytes([128 | opcode, 128 | size]) if size < 126 else (
            bytes([128 | opcode, 128 | 126]) + struct.pack('!H', size) if size < 65536 else
            bytes([128 | opcode, 128 | 127]) + struct.pack('!Q', size))
        mask = os.urandom(4)
        with self.write_lock:
            self.socket.sendall(prefix + mask + bytes(x ^ mask[i % 4] for i, x in enumerate(raw)))

    def wait(self, predicate, timeout=12, after=0):
        until = time.monotonic() + timeout
        with self.condition:
            while True:
                for msg in self.messages[after:]:
                    if predicate(msg):
                        return msg
                remaining = until - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(self.label + ': missing expected message; methods=' +
                        repr([m.get('method', 'response') for m in self.messages[after:]]))
                self.condition.wait(remaining)

    def call_raw(self, method, params):
        self.number += 1
        identifier = self.label + '-' + str(self.number)
        self.send({'id': identifier, 'method': method, 'params': params})
        return self.wait(lambda m: m.get('id') == identifier and 'method' not in m)

    def call(self, method, params):
        response = self.call_raw(method, params)
        if 'error' in response:
            raise RuntimeError(method + ': ' + json.dumps(response['error']))
        return response['result']

    def event(self, method, after=0, timeout=12):
        return self.wait(lambda m: m.get('method') == method, after=after, timeout=timeout)

    def close(self):
        if not self.closed:
            self.closed = True
            try:
                self.frame(b'', 8)
                self.socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.socket.close()
        self.reader.join(timeout=2)


class Plan:
    def __init__(self, kind='text', text='SYNTHETIC-FINAL', hold=False):
        self.kind, self.text = kind, text
        self.release = threading.Event()
        self.requested = threading.Event()
        if not hold:
            self.release.set()


class Backend:
    def __init__(self):
        self.plans = deque()
        self.requests = []
        self.condition = threading.Condition()
        outer = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_POST(self):
                size = int(self.headers['Content-Length'])
                assert size < 4000000
                body = json.loads(self.rfile.read(size))
                with outer.condition:
                    # The actual TUI can concurrently request an auxiliary title.
                    # It is not the interactive agent turn and must not consume
                    # a scripted tool/hold response intended for that turn.
                    auxiliary = (not body.get('tools') and 'text' in body and
                        'Generate a concise, single-line task title' in json.dumps(body.get('input')))
                    plan = Plan(text='Synthetic task title') if auxiliary else (
                        outer.plans.popleft() if outer.plans else Plan(text='SYNTHETIC-DEFAULT'))
                    outer.requests.append(body)
                    outer.condition.notify_all()
                plan.requested.set()
                if not plan.release.wait(20):
                    self.send_error(504)
                    return
                item_id = 'msg_' + uuid.uuid4().hex
                if plan.kind == 'approval':
                    item = {'id': item_id, 'type': 'function_call', 'name': 'exec_command',
                            'call_id': 'call_' + uuid.uuid4().hex,
                            'arguments': json.dumps({'cmd': 'printf SYNTHETIC_APPROVAL',
                                'sandbox_permissions': 'require_escalated',
                                'justification': 'Synthetic approval routing gate; reject this command.'})}
                else:
                    item = {'id': item_id, 'type': 'message', 'role': 'assistant', 'status': 'completed',
                            'content': [{'type': 'output_text', 'text': plan.text, 'annotations': []}]}
                events = [
                    {'type': 'response.output_item.added', 'output_index': 0,
                     'item': {**item, 'status': 'in_progress'}},
                    {'type': 'response.output_item.done', 'output_index': 0, 'item': item},
                    {'type': 'response.completed', 'response': {'id': 'resp_' + uuid.uuid4().hex,
                        'status': 'completed', 'output': [item],
                        'usage': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}}},
                ]
                response = ''.join('event: ' + e['type'] + '\ndata: ' + json.dumps(e) + '\n\n' for e in events).encode()
                try:
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/event-stream')
                    self.send_header('Content-Length', str(len(response)))
                    self.end_headers()
                    self.wfile.write(response)
                except (BrokenPipeError, ConnectionResetError):
                    pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def add(self, *plans):
        with self.condition:
            self.plans.extend(plans)

    def close(self):
        with self.condition:
            for plan in self.plans:
                plan.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


def text_input(text):
    return [{'type': 'text', 'text': text}]


def main():
    # Keep evidence for review; it contains only fabricated data and isolated paths.
    root = Path(tempfile.mkdtemp(prefix='csl-bridge-native-gate-'))
    (root / 'home').mkdir()
    (root / 'codex').mkdir()
    (root / 'project').mkdir()
    import shutil
    executable = shutil.which('codex')
    env = {'PATH': os.environ['PATH'], 'HOME': str(root / 'home'),
           'CODEX_HOME': str(root / 'codex'), 'CODEX_SQLITE_HOME': str(root / 'sqlite'),
           'LANG': 'C.UTF-8', 'SHELL': '/bin/sh', 'NO_PROXY': '127.0.0.1,localhost',
           'DISABLE_TELEMETRY': '1', 'DISABLE_ERROR_REPORTING': '1'}
    backend = Backend()
    sock = root / 'control.sock'
    errors = (root / 'app-server.log').open('w')
    command = [executable, 'app-server', '--listen', 'unix://' + str(sock),
        '-c', 'model_provider="bridge_gate"', '-c', 'model="csl-synthetic"',
        '-c', 'model_providers.bridge_gate.name="CSL synthetic loopback"',
        '-c', 'model_providers.bridge_gate.base_url="http://127.0.0.1:' + str(backend.server.server_port) + '/v1"',
        '-c', 'model_providers.bridge_gate.wire_api="responses"',
        '-c', 'model_providers.bridge_gate.requires_openai_auth=false',
        '-c', 'web_search="disabled"', '-c', 'analytics.enabled=false',
        '-c', 'model_providers.bridge_gate.supports_websockets=false']
    server = subprocess.Popen(command, cwd=root / 'project', env=env,
        stdin=subprocess.DEVNULL, stdout=errors, stderr=errors, start_new_session=True)
    clients, evidence = [], {'root': str(root), 'real_inference': False, 'auth': False, 'checks': {}}
    print('LAB_ROOT', root, flush=True)
    try:
        until = time.monotonic() + 12
        while not sock.exists():
            if server.poll() is not None or time.monotonic() > until:
                raise RuntimeError('isolated app-server did not open socket: ' + (root / 'app-server.log').read_text()[-1500:])
            time.sleep(.05)
        ui = Client(executable, sock, env, root, 'ui')
        clients.append(ui)
        bridge = Client(executable, sock, env, root, 'bridge')
        clients.append(bridge)
        thread = ui.call('thread/start', {'cwd': str(root / 'project'), 'approvalPolicy': 'on-request',
                                         'sandbox': 'read-only'})['thread']
        sid = thread['id']
        evidence['thread_id'] = sid
        backend.add(Plan(text='IDENTITY-CONTINUITY-SEED'))
        ui.call('turn/start', {'threadId': sid, 'input': text_input('IDENTITY-SEED-931')})
        ui.event('turn/completed')
        resumed = bridge.call('thread/resume', {'threadId': sid, 'excludeTurns': True})
        assert resumed['thread']['id'] == sid
        assert bridge.call('thread/loaded/list', {})['data'].count(sid) == 1
        evidence['checks']['rejoin_same_loaded_thread'] = True
        print('PASS rejoin same loaded thread', flush=True)

        hold, final = Plan(text='FIRST-SYNTHETIC', hold=True), Plan(text='AFTER-STEER')
        backend.add(hold, final)
        ui_start, bridge_start = len(ui.messages), len(bridge.messages)
        turn = bridge.call('turn/start', {'threadId': sid, 'input': text_input('HOLD-ONE')})['turn']
        tid = turn['id']
        assert hold.requested.wait(10)
        tools = backend.requests[-1].get('tools', [])
        evidence['tool_names'] = [t.get('name', t.get('type')) for t in tools]
        same = ui.call('thread/resume', {'threadId': sid, 'excludeTurns': True})
        assert same['thread']['status']['type'] == 'active'
        steered = ui.call('turn/steer', {'threadId': sid, 'expectedTurnId': tid,
                                       'input': text_input('STEER-MARKER-771')})
        assert steered['turnId'] == tid
        stale = bridge.call_raw('turn/steer', {'threadId': sid, 'expectedTurnId': str(uuid.uuid4()),
                                              'input': text_input('STALE-MARKER-DO-NOT-DELIVER')})
        assert 'error' in stale
        hold.release.set()
        done_ui = ui.event('turn/completed', after=ui_start)
        done_bridge = bridge.event('turn/completed', after=bridge_start)
        assert done_ui['params']['turn']['id'] == done_bridge['params']['turn']['id'] == tid
        assert done_bridge['params']['turn']['status'] == 'completed'
        assert any('STEER-MARKER-771' in json.dumps(r.get('input')) for r in backend.requests)
        assert not any('STALE-MARKER-DO-NOT-DELIVER' in json.dumps(r.get('input')) for r in backend.requests)
        evidence['checks']['start_steer_same_turn_auto_events_both_clients'] = True
        evidence['checks']['stale_steer_rejected'] = stale['error']
        print('PASS start/steer and automatic completion to both clients', flush=True)

        hold = Plan(text='SHOULD-NOT-FINISH', hold=True)
        backend.add(hold)
        start = len(bridge.messages)
        turn = ui.call('turn/start', {'threadId': sid, 'input': text_input('INTERRUPT-MARKER')})['turn']
        assert hold.requested.wait(10)
        bridge.call('turn/interrupt', {'threadId': sid, 'turnId': turn['id']})
        done = bridge.event('turn/completed', after=start)
        assert done['params']['turn']['status'] == 'interrupted'
        hold.release.set()
        evidence['checks']['interrupt_confirmed'] = True
        print('PASS interrupt confirmed by turn/completed', flush=True)

        # Connector initiates work. Only local UI declines; connector never approves.
        backend.add(Plan(kind='approval'), Plan(text='AFTER-LOCAL-DECLINE'))
        ui_start, bridge_start = len(ui.messages), len(bridge.messages)
        bridge.call('turn/start', {'threadId': sid, 'input': text_input('APPROVAL-ROUTING-MARKER')})
        approval = ui.event('item/commandExecution/requestApproval', after=ui_start)
        bridge_approval = bridge.event('item/commandExecution/requestApproval', after=bridge_start)
        evidence['checks']['approval_visible_local_ui_and_bridge'] = (
            approval['params']['threadId'] == bridge_approval['params']['threadId'] == sid)
        pending_turn = approval['params']['turnId']
        bridge.call('turn/steer', {'threadId': sid, 'expectedTurnId': pending_turn,
                                 'input': text_input('MESSAGE-WHILE-APPROVAL-PENDING-893')})
        assert not any(m.get('method') == 'serverRequest/resolved' and
                       m.get('params', {}).get('requestId') == approval['id'] for m in ui.messages[ui_start:])
        ui.send({'id': approval['id'], 'result': {'decision': 'decline'}})
        done = bridge.event('turn/completed', after=bridge_start)
        assert done['params']['turn']['status'] == 'completed'
        evidence['checks']['local_ui_resolves_bridge_origin_approval'] = True
        assert any('MESSAGE-WHILE-APPROVAL-PENDING-893' in json.dumps(r.get('input')) for r in backend.requests)
        evidence['checks']['message_during_approval_does_not_resolve_it'] = True
        print('PASS local UI resolves bridge-origin approval', flush=True)

        # Pending approval survives UI drop and is offered on rejoin.
        backend.add(Plan(kind='approval'), Plan(text='AFTER-RECONNECT-DECLINE'))
        ui_start, bridge_start = len(ui.messages), len(bridge.messages)
        bridge.call('turn/start', {'threadId': sid, 'input': text_input('APPROVAL-RECONNECT-MARKER')})
        approval = ui.event('item/commandExecution/requestApproval', after=ui_start)
        ui.close()
        ui2 = Client(executable, sock, env, root, 'ui_reconnected')
        clients.append(ui2)
        same = ui2.call('thread/resume', {'threadId': sid, 'excludeTurns': True})
        replayed = ui2.event('item/commandExecution/requestApproval')
        ui2.send({'id': replayed['id'], 'result': {'decision': 'decline'}})
        done = bridge.event('turn/completed', after=bridge_start)
        assert done['params']['turn']['status'] == 'completed'
        evidence['checks']['pending_approval_replayed_after_local_ui_rejoin'] = True
        print('PASS approval replay on UI reconnect', flush=True)

        backend.add(Plan(kind='approval'), Plan(text='AFTER-ORIGINATING-CONNECTOR-DROP'))
        ui_start = len(ui2.messages)
        bridge.call('turn/start', {'threadId': sid, 'input': text_input('DROP-APPROVAL-ORIGIN-663')})
        approval = ui2.event('item/commandExecution/requestApproval', after=ui_start)
        bridge.close()
        ui2.send({'id': approval['id'], 'result': {'decision': 'decline'}})
        done = ui2.event('turn/completed', after=ui_start)
        assert done['params']['turn']['status'] == 'completed'
        bridge = Client(executable, sock, env, root, 'bridge_after_approval_drop')
        clients.append(bridge)
        bridge.call('thread/resume', {'threadId': sid, 'excludeTurns': True})
        evidence['checks']['local_ui_keeps_approval_control_after_origin_connector_drop'] = True
        print('PASS local approval control after originating connector drop', flush=True)

        # Two simultaneous starts must enter the same runtime, not two writers.
        hold, tail = Plan(text='CONCURRENT-FIRST', hold=True), Plan(text='CONCURRENT-FINAL')
        backend.add(hold, tail)
        start_bridge, start_ui = len(bridge.messages), len(ui2.messages)
        barrier = threading.Barrier(3)
        outputs = queue.Queue()
        def concurrent(client, marker):
            barrier.wait()
            try:
                outputs.put(client.call('turn/start', {'threadId': sid, 'input': text_input(marker)}))
            except Exception as exc:
                outputs.put(exc)
        workers = [threading.Thread(target=concurrent, args=(client, marker)) for client, marker in
                   [(bridge, 'CONCURRENT-A-118'), (ui2, 'CONCURRENT-B-629')]]
        for worker in workers:
            worker.start()
        barrier.wait()
        results = [outputs.get(timeout=12), outputs.get(timeout=12)]
        assert all(isinstance(r, dict) for r in results), results
        ids = {r['turn']['id'] for r in results}
        assert len(ids) == 1, results
        assert hold.requested.wait(10)
        hold.release.set()
        bridge.event('turn/completed', after=start_bridge)
        ui2.event('turn/completed', after=start_ui)
        starts = [m for m in bridge.messages[start_bridge:] if m.get('method') == 'turn/started']
        assert len(starts) == 1, starts
        assert all(any(marker in json.dumps(r.get('input')) for r in backend.requests)
                   for marker in ['CONCURRENT-A-118', 'CONCURRENT-B-629'])
        evidence['checks']['concurrent_starts_same_turn_single_start_event'] = True
        print('PASS concurrent turn/start same turn/runtime', flush=True)

        hold = Plan(text='SURVIVES-BRIDGE-DROP', hold=True)
        backend.add(hold)
        ui_start = len(ui2.messages)
        turn = bridge.call('turn/start', {'threadId': sid, 'input': text_input('BRIDGE-DROP-513')})['turn']
        assert hold.requested.wait(10)
        bridge.close()
        state = ui2.call('thread/read', {'threadId': sid})['thread']['status']
        assert state['type'] == 'active', state
        bridge2 = Client(executable, sock, env, root, 'bridge_reconnected')
        clients.append(bridge2)
        state = bridge2.call('thread/resume', {'threadId': sid, 'excludeTurns': True})['thread']
        assert state['id'] == sid and state['status']['type'] == 'active'
        start_bridge = len(bridge2.messages)
        hold.release.set()
        done = bridge2.event('turn/completed', after=start_bridge)
        assert done['params']['turn']['id'] == turn['id']
        ui2.event('turn/completed', after=ui_start)
        turns = bridge2.call('thread/turns/list', {'threadId': sid, 'itemsView': 'full'})['data']
        assert 'SURVIVES-BRIDGE-DROP' in json.dumps(turns)
        assert 'IDENTITY-SEED-931' in json.dumps(backend.requests[-1]['input'])
        evidence['checks']['bridge_drop_no_cancel_rejoin_active_and_recover_result'] = True
        evidence['checks']['identity_context_seed_preserved_after_interrupt_and_reconnect'] = True
        print('PASS connector drop/rejoin and context continuity', flush=True)
        evidence['status'] = 'passed_native_engine_synthetic_backend_gate'
    except Exception as exc:
        evidence['status'] = 'failed'
        evidence['error'] = str(exc)
        print('GATE_FAILURE', repr(exc), flush=True)
    finally:
        for i, client in enumerate(clients):
            (root / ('client-' + str(i) + '.json')).write_text(json.dumps(client.messages, indent=2))
            client.close()
        if server.poll() is None:
            os.killpg(server.pid, signal.SIGTERM)
            try:
                server.wait(timeout=4)
            except subprocess.TimeoutExpired:
                os.killpg(server.pid, signal.SIGKILL)
                server.wait(timeout=3)
        errors.close()
        backend.close()
        (root / 'backend-requests.json').write_text(json.dumps(backend.requests, indent=2))
        (root / 'report.json').write_text(json.dumps(evidence, indent=2))
        print(json.dumps(evidence, indent=2), flush=True)
    return 0 if evidence.get('status') == 'passed_native_engine_synthetic_backend_gate' else 1


if __name__ == '__main__':
    raise SystemExit(main())
