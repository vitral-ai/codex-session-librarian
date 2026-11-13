"""Two real native runtimes, synthetic backends, production connector; no inference."""
from pathlib import Path
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from csl_bridge_engine import Connector
from csl_bridge_store import Store, encode
from csl_bridge_transport import local_call
from runtime_gate import Backend, Client, Plan, text_input


def eventually(function, timeout=12):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        value = function()
        if value:
            return value
        time.sleep(.05)
    raise AssertionError('Condition timed out')


class Native:
    def __init__(self, root, label):
        self.root = root / label
        self.root.mkdir(mode=0o700)
        (self.root / 'home').mkdir()
        (self.root / 'codex').mkdir()
        (self.root / 'project').mkdir()
        self.backend = Backend()
        self.sock = self.root / 'native.sock'
        self.env = {'PATH': os.environ['PATH'], 'HOME': str(self.root / 'home'),
            'CODEX_HOME': str(self.root / 'codex'), 'CODEX_SQLITE_HOME': str(self.root / 'sqlite'),
            'LANG': 'C.UTF-8', 'SHELL': '/bin/sh', 'NO_PROXY': '127.0.0.1,localhost',
            'DISABLE_TELEMETRY': '1', 'DISABLE_ERROR_REPORTING': '1'}
        command = [shutil.which('codex'), 'app-server', '--listen', 'unix://' + str(self.sock),
            '-c', 'model_provider="bridge_gate"', '-c', 'model="csl-synthetic"',
            '-c', 'model_providers.bridge_gate.name="CSL synthetic loopback"',
            '-c', 'model_providers.bridge_gate.base_url="http://127.0.0.1:' + str(self.backend.server.server_port) + '/v1"',
            '-c', 'model_providers.bridge_gate.wire_api="responses"',
            '-c', 'model_providers.bridge_gate.requires_openai_auth=false',
            '-c', 'web_search="disabled"', '-c', 'analytics.enabled=false',
            '-c', 'model_providers.bridge_gate.supports_websockets=false']
        self.errors = (self.root / 'server.log').open('w')
        self.server = subprocess.Popen(command, env=self.env, cwd=self.root / 'project', stdin=subprocess.DEVNULL,
            stdout=self.errors, stderr=self.errors, start_new_session=True)
        eventually(lambda: self.sock.exists())
        self.ui = Client(shutil.which('codex'), self.sock, self.env, self.root, 'protocol_ui')
        self.sid = self.ui.call('thread/start', {'cwd': str(self.root / 'project'),
            'approvalPolicy': 'on-request', 'sandbox': 'read-only'})['thread']['id']
        self.backend.add(Plan(text=label + '-IDENTITY-SEED'))
        self.ui.call('turn/start', {'threadId': self.sid, 'input': text_input(label + '-CONTEXT-991')})
        self.ui.event('turn/completed')

    def close(self):
        self.ui.close()
        os.killpg(self.server.pid, signal.SIGTERM)
        self.server.wait(timeout=5)
        self.errors.close()
        self.backend.close()
        (self.root / 'backend.json').write_text(json.dumps(self.backend.requests, indent=2))


def setup(home, identity, runtime, agent, peer, peerhome):
    store = Store(home, create=True)
    with store.transaction() as db:
        db.executemany('INSERT INTO config VALUES(?,?)', [('identity', encode(identity)),
            ('runtime_socket', encode(str(runtime.sock)))])
        db.execute('INSERT INTO agents VALUES(?,?)', (agent, runtime.sid))
        db.execute('INSERT INTO peers VALUES(?,?)', (peer, encode({'transport': 'lab', 'home': str(peerhome),
            'allow_agents': [agent], 'allow_ops': ['followup', 'send_message', 'status', 'interrupt', 'receipt', 'watch']})))
    store.close()


def request(home, op, identifier=None, **params):
    return local_call(home, {'local_op': 'call', 'peer': 'bob', 'request': {
        'version': 1, 'op': op, 'id': identifier or str(uuid.uuid4()), **params}})


def main():
    root = Path(tempfile.mkdtemp(prefix='csl-bridge-e2e-'))
    print('LAB_ROOT', root, flush=True)
    a = b = ca = cb = None
    evidence = {'root': str(root), 'native_model_inference': False, 'SSH_Mac_auth': 'NOT_TESTED', 'checks': {}}
    try:
        a, b = Native(root, 'alice'), Native(root, 'bob')
        ha, hb = root / 'bridge-a', root / 'bridge-b'
        setup(ha, 'alice', a, 'coordinator', 'bob', hb)
        setup(hb, 'bob', b, 'worker', 'alice', ha)
        ca, cb = Connector(ha), Connector(hb)
        ca.start(); cb.start()
        eventually(lambda: ca.runtime is not None and cb.runtime is not None)

        hold = Plan(text='WORKER-FIRST', hold=True)
        b.backend.add(hold, Plan(text='WORKER-RESULT-771'))
        task_id = str(uuid.uuid4())
        receipt = request(ha, 'followup', task_id, source='coordinator', target='worker', text='Review fictitious note. TASK-499')
        assert receipt['state'] == 'delivered', receipt
        assert hold.requested.wait(10)
        assert receipt['thread_id'] == b.sid
        history = b.ui.call('thread/turns/list', {'threadId': b.sid, 'itemsView': 'full'})['data']
        assert any(item.get('clientId') == task_id for turn in history for item in turn.get('items', []))
        evidence['checks']['native_client_message_id_is_reconcilable'] = True
        evidence['checks']['delegate_idle_starts_existing_thread'] = True
        clarify = request(ha, 'send_message', source='coordinator', target='worker', text='CLARIFY-882: focus on section two')
        assert clarify['turn_id'] == receipt['turn_id']

        waiting = []
        waiter = threading.Thread(target=lambda: waiting.append(local_call(ha,
            {'local_op': 'wait', 'agent': 'coordinator', 'after': 0, 'timeout': 20})))
        waiter.start()
        eventually(lambda: ca.waiters['coordinator'] == 1)
        n = len(a.backend.requests)
        local_call(hb, {'local_op': 'progress', 'source': 'worker', 'task_id': task_id,
            'id': str(uuid.uuid4()), 'text': 'PROGRESS-775: reviewed synthetic first section'})
        waiter.join(timeout=10)
        assert waiting and waiting[0]['events'][0]['event']['kind'] == 'progress'
        assert len(a.backend.requests) == n
        evidence['checks']['progress_automatically_wakes_wait_without_inference_polling'] = True

        ahold = Plan(text='COORDINATOR-FIRST', hold=True)
        a.backend.add(ahold, Plan(text='COORDINATOR-AFTER-RESULT'))
        a.ui.call('turn/start', {'threadId': a.sid, 'input': text_input('COORDINATOR-ACTIVE-771')})
        assert ahold.requested.wait(10)
        hold.release.set()
        eventually(lambda: ca.store.rows("SELECT * FROM inbound WHERE delivery='delivered'") and
            any('WORKER-RESULT-771' in r['body'] and r['delivery'] == 'delivered'
                for r in ca.store.rows('SELECT * FROM inbound')))
        ahold.release.set()
        eventually(lambda: any('WORKER-RESULT-771' in json.dumps(r.get('input')) for r in a.backend.requests))
        assert any('CLARIFY-882' in json.dumps(r.get('input')) for r in b.backend.requests)
        evidence['checks']['clarification_in_active_turn_and_final_auto_enters_coordinator_turn'] = True
        eventually(lambda: ca.current('coordinator')['status'] == 'idle')
        eventually(lambda: cb.current('worker')['status'] == 'idle')

        old_count = len(b.backend.requests)
        idle = request(ha, 'send_message', source='coordinator', target='worker', text='IDLE-MESSAGE-663')
        assert idle['state'] == 'pending' and len(b.backend.requests) == old_count
        hold = Plan(text='FOLLOWUP-FIRST', hold=True)
        b.backend.add(hold, Plan(text='FOLLOWUP-RESULT'))
        followup_id = str(uuid.uuid4())
        followup = request(ha, 'followup', followup_id, source='coordinator', target='worker', text='FOLLOWUP-992 same identity')
        assert hold.requested.wait(10)
        eventually(lambda: cb.store.rows("SELECT state FROM operations WHERE id=?", (idle['request_id'],))[0]['state'] == 'delivered')
        hold.release.set()
        eventually(lambda: cb.current('worker')['status'] == 'idle')
        assert any('IDLE-MESSAGE-663' in json.dumps(r.get('input')) for r in b.backend.requests)
        assert 'bob-CONTEXT-991' in json.dumps(b.backend.requests[-1]['input'])
        evidence['checks']['idle_message_no_wakeup_then_auto_delivery_on_followup_same_context'] = True

        hold = Plan(hold=True)
        b.backend.add(hold)
        interrupted_id = str(uuid.uuid4())
        receipt = request(ha, 'followup', interrupted_id, source='coordinator', target='worker', text='INTERRUPT-RETOMA-882')
        assert hold.requested.wait(10)
        stop = request(ha, 'interrupt', target='worker', turn_id=receipt['turn_id'])
        assert stop['state'] == 'interrupt_requested'
        eventually(lambda: cb.store.rows('SELECT status FROM tasks WHERE id=?', (interrupted_id,))[0]['status'] == 'interrupted')
        hold.release.set()
        evidence['checks']['interrupt_is_request_then_final_confirmation'] = True

        hold = Plan(text='RECOVERED-RESULT-883', hold=True)
        b.backend.add(hold)
        final_id = str(uuid.uuid4())
        body = dict(source='coordinator', target='worker', text='RESUME-AND-RECONNECT-773')
        receipt = request(ha, 'followup', final_id, **body)
        assert hold.requested.wait(10)
        ca.stop.set(); ca.close(); ca = None
        hold.release.set()
        eventually(lambda: cb.current('worker')['status'] == 'idle')
        ca = Connector(ha); ca.start()
        eventually(lambda: ca.runtime is not None)
        eventually(lambda: any('RECOVERED-RESULT-883' in r['body'] for r in ca.store.rows('SELECT * FROM inbound')))
        count = len(b.backend.requests)
        duplicate = request(ha, 'followup', final_id, **body)
        assert duplicate == receipt and len(b.backend.requests) == count
        evidence['checks']['reconnect_recovers_final_and_identical_id_does_not_reexecute'] = True
        evidence['status'] = 'PASS_NATIVE_ENGINE_SYNTHETIC_BACKENDS'
        print('ALL CONNECTOR CHECKS PASS', flush=True)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        evidence['status'], evidence['error'] = 'FAIL', repr(exc)
    finally:
        for con in (ca, cb):
            if con:
                con.stop.set()
        for con in (ca, cb):
            if con:
                con.close()
        for native in (a, b):
            if native:
                native.close()
        (root / 'report.json').write_text(json.dumps(evidence, indent=2))
        print(json.dumps(evidence, indent=2), flush=True)
    return 0 if evidence.get('status') == 'PASS_NATIVE_ENGINE_SYNTHETIC_BACKENDS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
