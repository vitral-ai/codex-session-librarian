"""Synthetic coordination/security tests. No native daemon, SSH, auth or inference."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr
import io
import json
import os
from pathlib import Path
import queue
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from csl_bridge import reviewed_text
from csl_bridge_engine import Connector, event_id
from csl_bridge_rpc import RuntimeRejected, RuntimeUnavailable
from csl_bridge_store import BridgeError, Store, decode, encode, validate
from csl_bridge_transport import exchange, local_call, ssh_argv


def uid():
    return str(uuid.uuid4())


class FakeRuntime:
    def __init__(self, thread):
        self.thread = thread
        self.connected = True
        self.events = queue.Queue()
        self.turn = None
        self.history = []
        self.calls = []
        self.lose_ack = False

    def call(self, method, params, **_):
        self.calls.append((method, params))
        if not self.connected:
            raise RuntimeUnavailable('Disconnected synthetic runtime')
        if method == 'thread/resume':
            return {'thread': {'id': self.thread}}
        if method == 'thread/loaded/list':
            return {'data': [self.thread], 'nextCursor': None}
        if method == 'thread/read':
            return {'thread': {'id': self.thread, 'status': {'type': 'active' if self.turn else 'idle'}}}
        if method == 'thread/turns/list':
            return {'data': list(reversed(self.history)), 'nextCursor': None}
        if method in ('turn/start', 'turn/steer'):
            if method == 'turn/steer' and params['expectedTurnId'] != self.turn:
                raise RuntimeRejected('Obsolete synthetic steer')
            if self.turn is None:
                self.turn = uid()
                self.history.append({'id': self.turn, 'status': 'inProgress', 'items': []})
            self.history[-1]['items'].append({'id': uid(), 'type': 'userMessage',
                'clientId': params.get('clientUserMessageId'), 'content': params['input']})
            if self.lose_ack:
                self.lose_ack = False
                raise RuntimeUnavailable('Synthetic ack loss after input accepted')
            return {'turn': {'id': self.turn}} if method == 'turn/start' else {'turnId': self.turn}
        if method == 'turn/interrupt':
            assert params['turnId'] == self.turn
            self.history[-1]['status'] = 'interrupted'
            self.turn = None
            return {}
        raise AssertionError(method)

    def close(self):
        self.connected = False


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / 'bridge'
        self.thread = uid()
        store = Store(self.home, create=True)
        with store.transaction() as db:
            db.executemany('INSERT INTO config VALUES(?,?)', [('identity', encode('bob')),
                ('runtime_socket', encode(str(self.root / 'never-personal.sock')))])
            db.execute('INSERT INTO agents VALUES(?,?)', ('worker', self.thread))
            db.execute('INSERT INTO peers VALUES(?,?)', ('alice', encode({'transport': 'lab', 'home': str(self.root / 'alice'),
                'allow_agents': ['worker'], 'allow_ops': ['followup', 'send_message', 'status', 'interrupt', 'watch', 'receipt']})))
        store.close()
        self.connector = Connector(self.home)
        self.runtime = FakeRuntime(self.thread)
        self.connector.runtime = self.runtime

    def tearDown(self):
        self.connector.close()
        self.temp.cleanup()

    def request(self, op='followup', **kwargs):
        result = {'version': 1, 'op': op, 'id': uid()}
        if op in ('followup', 'send_message'):
            result.update(source='coordinator', target='worker', text='Synthetic fictional review')
        result.update(kwargs)
        return result

    def test_new_or_settled_bridge_never_scans_history_on_rejoin(self):
        self.connector.reconcile()
        self.assertFalse(self.runtime.calls)
        self.connector.completed('worker', uid(), 'completed')
        self.assertFalse(self.runtime.calls)
        self.assertFalse(self.connector.store.rows('SELECT * FROM outbound'))

    def test_completed_correlated_task_is_not_scanned_or_published_again(self):
        result=self.connector.incoming('alice',self.request())
        self.connector.answers[(self.thread,result['turn_id'])]='Synthetic final'
        self.connector.completed('worker',result['turn_id'],'completed')
        self.runtime.calls.clear()
        self.connector.completed('worker',result['turn_id'],'completed')
        self.connector.reconcile()
        self.assertFalse(self.runtime.calls)
        self.assertEqual(len(self.connector.store.rows('SELECT * FROM outbound')),1)

    def test_cli_wait_invalid_timeout_reports_limit_before_ipc(self):
        result=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'csl'),'bridge','--home',str(self.home),'wait','--agent','worker','--timeout','60'],capture_output=True,text=True)
        self.assertEqual(result.returncode,2)
        self.assertIn('0..20 seconds',result.stderr)
        self.assertIn('returned cursor',result.stderr)

    def test_followup_idle_then_active_uses_same_runtime_turn(self):
        first = self.connector.incoming('alice', self.request())
        second = self.connector.incoming('alice', self.request())
        self.assertEqual(first['turn_id'], second['turn_id'])
        self.assertEqual(first['thread_id'], self.thread)
        methods = [m for m, _ in self.runtime.calls]
        self.assertEqual(methods.count('turn/start'), 1)
        self.assertEqual(methods.count('turn/steer'), 1)
        self.assertFalse(any(m.startswith('account/') or m == 'thread/start' for m in methods))

    def test_idle_message_waits_and_flushes_automatically_in_active_turn(self):
        message = self.request('send_message', text='Remote data with no idle activation')
        self.assertEqual(self.connector.incoming('alice', message)['state'], 'pending')
        self.assertIsNone(self.runtime.turn)
        task = self.connector.incoming('alice', self.request())
        self.connector.flush('worker')
        rows = self.connector.store.rows('SELECT state FROM operations WHERE id=?', (message['id'],))
        self.assertEqual(rows[0]['state'], 'delivered')
        self.assertEqual(self.runtime.turn, task['turn_id'])

    def test_idempotency_collision_and_concurrent_consumers(self):
        request = self.request()
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _: self.connector.incoming('alice', request), range(16)))
        self.assertTrue(all(r == results[0] for r in results))
        self.assertEqual(sum(m == 'turn/start' for m, _ in self.runtime.calls), 1)
        with self.assertRaises(BridgeError):
            self.connector.incoming('alice', {**request, 'text': 'Different content'})

    def test_peer_binding_allowlist_and_approval_denial(self):
        for peer, request in [('mallory', self.request()), ('alice', self.request(target='unregistered')),
                              ('alice', self.request('account/login/start')),
                              ('alice', self.request('item/commandExecution/requestApproval')),
                              ('alice', {**self.request(), 'sender': 'alice'})]:
            with self.subTest(peer=peer, op=request['op']), self.assertRaises(BridgeError):
                self.connector.incoming(peer, request)
        self.assertEqual(self.connector.store.rows('SELECT * FROM operations'), [])

    def test_uncertain_native_ack_reconciles_without_reexecution(self):
        request = self.request()
        self.runtime.lose_ack = True
        result = self.connector.incoming('alice', request)
        self.assertEqual(result['state'], 'uncertain')
        count = len(self.runtime.calls)
        self.assertEqual(self.connector.incoming('alice', request), result)
        self.assertEqual(len(self.runtime.calls), count)
        receipt = self.connector.incoming('alice', self.request('receipt', request_id=request['id']))
        self.assertEqual(receipt['state'], 'delivered')
        self.assertEqual(sum(m == 'turn/start' for m, _ in self.runtime.calls), 1)

    def test_remote_list_exposes_only_agents_explicitly_permitted(self):
        self.connector.peers['alice']['allow_ops'].append('agents')
        self.connector.agents['private-agent'] = uid()
        result = self.connector.incoming('alice', self.request('agents'))
        self.assertEqual([a['agent'] for a in result['agents']], ['worker'])

    def test_uncertain_transport_no_automatic_resend_then_receipt_reconciles(self):
        request = self.request(source='worker', target='coordinator')
        operation = {'local_op': 'call', 'peer': 'alice', 'request': request}
        with patch('csl_bridge_engine.exchange', side_effect=BridgeError('Synthetic lost receipt')) as send:
            first = self.connector.local(operation)
            again = self.connector.local(operation)
        self.assertEqual(first, again)
        self.assertEqual(first['state'], 'uncertain')
        self.assertEqual(send.call_count, 1)
        receipt = self.request('receipt', request_id=request['id'])
        with patch('csl_bridge_engine.exchange', return_value={'state': 'delivered', 'result': {
                'state': 'delivered', 'request_id': request['id'], 'turn_id': uid()}}):
            self.connector.local({'local_op': 'call', 'peer': 'alice', 'request': receipt})
        self.assertEqual(self.connector.store.rows('SELECT state FROM operations')[0]['state'], 'delivered')

    def test_progress_after_completed_task_is_rejected(self):
        task_id = self.request()['id']
        task = self.connector.incoming('alice', self.request(id=task_id))
        self.connector.completed('worker', task['turn_id'], 'completed')
        with self.assertRaises(BridgeError):
            self.connector.local({'local_op': 'progress', 'source': 'worker', 'task_id': task_id,
                                  'id': uid(), 'text': 'Late progress cannot reopen task'})

    def test_missing_reconciliation_evidence_remains_uncertain(self):
        request = self.request()
        self.connector.store.reserve('alice', request)
        self.connector.store.operation(request['id'], 'uncertain', {'state': 'uncertain'})
        self.connector.reconcile()
        self.assertEqual(self.connector.store.rows('SELECT state FROM operations')[0]['state'], 'uncertain')
        self.assertFalse(any(m == 'turn/start' for m, _ in self.runtime.calls))

    def test_interruption_exact_delegated_turn_then_same_agent_continues(self):
        task = self.connector.incoming('alice', self.request())
        wrong = self.connector.incoming('alice', self.request('interrupt', target='worker', turn_id=uid()))
        self.assertEqual(wrong['state'], 'rejected')
        result = self.connector.incoming('alice', self.request('interrupt', target='worker', turn_id=task['turn_id']))
        self.assertEqual(result['state'], 'interrupt_requested')
        self.connector.completed('worker', task['turn_id'], 'interrupted')
        again = self.connector.incoming('alice', self.request())
        self.assertEqual(again['thread_id'], task['thread_id'])
        self.assertNotEqual(again['turn_id'], task['turn_id'])

    def test_partial_secret_detection_withholds_automatic_result_text(self):
        task = self.connector.incoming('alice', self.request())
        self.connector.answers[(self.thread, task['turn_id'])] = 'password="synthetic-password-value"'
        self.connector.completed('worker', task['turn_id'], 'completed')
        events = self.connector.store.rows('SELECT body FROM outbound')
        self.assertNotIn('synthetic-password-value', events[0]['body'])
        self.assertIn('withheld', events[0]['body'])

    def test_publish_collision_atomic_and_rollback(self):
        store = self.connector.store
        eid = uid()
        store.publish('alice', {'text': 'first'}, eid)
        with self.assertRaises(BridgeError):
            store.publish('alice', {'text': 'second'}, eid)
        with self.assertRaises(RuntimeError):
            with store.transaction() as db:
                db.execute("INSERT INTO config VALUES('rollback','true')")
                raise RuntimeError('Synthetic interrupted write')
        self.assertEqual(store.rows("SELECT * FROM config WHERE key='rollback'"), [])
        self.assertEqual(len(store.rows('SELECT * FROM outbound')), 1)

    def outgoing_event(self):
        request = self.request(source='worker', target='coordinator')
        self.connector.store.reserve('outbound:alice', request)
        turn = uid()
        self.connector.store.operation(request['id'], 'delivered', {'turn_id': turn})
        return {'seq': 1, 'event': {'id': uid(), 'task_id': request['id'], 'source': 'coordinator',
            'target': 'worker', 'kind': 'final', 'text': 'Synthetic final evidence',
            'turn_id': turn, 'status': 'completed'}}

    def test_correlated_events_automatic_delivery_and_duplicate_cursor(self):
        self.connector.incoming('alice', self.request())
        event = self.outgoing_event()
        self.connector.accept_event('alice', event)
        self.connector.accept_event('alice', event)
        self.assertEqual(len(self.connector.store.rows('SELECT * FROM inbound')), 1)
        self.assertEqual(sum(m == 'turn/steer' for m, _ in self.runtime.calls), 1)
        self.assertEqual(self.connector.store.rows('SELECT delivery FROM inbound')[0]['delivery'], 'delivered')

    def test_event_correlation_collision_and_wrong_peer_have_no_partial_effect(self):
        original = self.outgoing_event()
        for peer, event in [('mallory', original),
                            ('alice', {**original, 'event': {**original['event'], 'turn_id': uid()}}),
                            ('alice', {**original, 'event': {**original['event'], 'target': 'unregistered'}}),
                            ('alice', {**original, 'event': {**original['event'], 'kind': 'approve'}})]:
            with self.assertRaises(BridgeError):
                self.connector.accept_event(peer, event)
        self.assertFalse(self.connector.store.rows('SELECT * FROM inbound'))
        self.assertFalse(self.connector.store.rows('SELECT * FROM cursors'))
        self.connector.accept_event('alice', original)
        with self.assertRaises(BridgeError):
            self.connector.accept_event('alice', {**original, 'event': {**original['event'], 'text': 'Changed'}})
        self.assertEqual(len(self.connector.store.rows('SELECT * FROM inbound')), 1)

    def test_event_delivery_ack_loss_reconciles_no_duplicate_input(self):
        self.connector.incoming('alice', self.request())
        event = self.outgoing_event()
        self.runtime.lose_ack = True
        self.connector.accept_event('alice', event)
        self.assertEqual(self.connector.store.rows('SELECT delivery FROM inbound')[0]['delivery'], 'uncertain')
        self.connector.reconcile()
        self.assertEqual(self.connector.store.rows('SELECT delivery FROM inbound')[0]['delivery'], 'delivered')
        self.assertEqual(sum(m == 'turn/steer' for m, _ in self.runtime.calls), 1)

    def test_wait_is_event_driven_and_idle_event_does_not_activate(self):
        event = self.outgoing_event()
        result = []
        waiter = threading.Thread(target=lambda: result.append(self.connector.local(
            {'local_op': 'wait', 'agent': 'worker', 'after': 0, 'timeout': 2})))
        waiter.start()
        until = time.monotonic() + 1
        while not self.connector.waiters['worker'] and time.monotonic() < until:
            time.sleep(.01)
        self.connector.accept_event('alice', event)
        waiter.join(timeout=2)
        self.assertEqual(result[0]['events'][0]['event']['id'], event['event']['id'])
        self.assertIsNone(self.runtime.turn)
        self.assertFalse(any(m == 'turn/start' for m, _ in self.runtime.calls))
        again = self.connector.local({'local_op': 'wait', 'agent': 'worker', 'after': 0, 'timeout': 0})
        self.assertEqual(again['events'], result[0]['events'])

    def test_protocol_limits_malformed_and_hostile_paths_have_no_effect(self):
        invalid = [self.request(id='../../auth.json'), self.request(version=2), self.request(version=True),
                   self.request(text='x' * 12001), self.request(target='../../other'),
                   self.request(text='control\x1b'), self.request('watch', after=-1)]
        for request in invalid:
            with self.subTest(request=request['op']), self.assertRaises(BridgeError):
                self.connector.incoming('alice', request)
        for raw in ['{"x":1,"x":2}', '{"x":NaN}', 'a' * 65537, b'\xff']:
            with self.assertRaises(BridgeError):
                decode(raw)
        self.assertFalse(self.connector.store.rows('SELECT * FROM operations'))

    def test_state_disconnected_is_not_completed(self):
        self.runtime.connected = False
        result = self.connector.incoming('alice', self.request('status', target='worker'))
        self.assertEqual(result['status'], 'disconnected')

    def test_private_permissions_and_exclusive_connector(self):
        self.assertEqual(self.home.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.home / 'bridge.sqlite').stat().st_mode & 0o777, 0o600)
        with self.assertRaises(BridgeError):
            Connector(self.home)
        link = self.root / 'link'
        link.symlink_to(self.home, target_is_directory=True)
        with self.assertRaises(BridgeError):
            Store(link)

    def test_selected_text_scan_stops_or_scrubs_only_this_message(self):
        path = self.root / 'selected.txt'
        path.write_text('password="synthetic-password-value"')
        with self.assertRaises(BridgeError):
            reviewed_text(path)
        cleaned = reviewed_text(path, scrub=True)
        self.assertNotIn('synthetic-password-value', cleaned)
        self.assertIn('CSL REDACTED', cleaned)
        self.assertIn('synthetic-password-value', path.read_text())

    def test_raw_local_ipc_cannot_bypass_outgoing_partial_secret_check(self):
        body = self.request(source='worker', target='coordinator', text='password="synthetic-password-value"')
        with patch('csl_bridge_engine.exchange') as send:
            with self.assertRaises(BridgeError):
                self.connector.local({'local_op': 'call', 'peer': 'alice', 'request': body})
        send.assert_not_called()
        self.assertFalse(self.connector.store.rows('SELECT * FROM operations'))

    def test_ssh_fixed_argv_stdin_and_uncertainty_no_secrets_in_error(self):
        request = self.request(text='synthetic selected content $(uname) `id`')
        response = SimpleNamespace(returncode=0, stdout=b'{"ok":true,"data":{"state":"delivered"}}')
        with patch('csl_bridge_transport.subprocess.run', return_value=response) as run:
            result = exchange({'transport': 'ssh', 'alias': 'trusted-mac'}, 'bob', request)
        self.assertEqual(result['state'], 'delivered')
        args, kwargs = run.call_args
        self.assertEqual(args[0][-1], 'csl-bridge-receiver')
        self.assertNotIn(request['text'], ' '.join(args[0]))
        self.assertIn(request['text'], kwargs['input'].decode())
        self.assertEqual(kwargs['stderr'], subprocess.DEVNULL)
        for alias in ['-oProxyCommand=bad', 'host;id', 'a b', '$(id)', 'user@host']:
            with self.assertRaises(BridgeError):
                ssh_argv(alias)
        with patch('csl_bridge_transport.subprocess.run', side_effect=subprocess.TimeoutExpired(['secret-argv'], 25)):
            with self.assertRaises(BridgeError) as error:
                exchange({'transport': 'ssh', 'alias': 'trusted-mac'}, 'bob', request)
        self.assertNotIn('secret-argv', str(error.exception))
        self.assertIn('uncertain', str(error.exception))

    def test_ssh_receiver_identity_comes_from_trusted_environment(self):
        # Stub transport identity is tested here; this is NOT a real SSH/login test.
        request = self.request('status', target='worker')
        with patch('csl_bridge_transport.local_call', return_value={'status': 'idle'}) as call, \
             patch.dict(os.environ, {'CSL_BRIDGE_HOME': str(self.home), 'CSL_BRIDGE_PEER': 'alice',
                                      'SSH_ORIGINAL_COMMAND': 'csl-bridge-receiver'}), \
             patch('csl_bridge_transport.sys.stdin', SimpleNamespace(buffer=io.BytesIO((encode(request) + '\n').encode()))), \
             patch('csl_bridge_transport.sys.stdout', new_callable=io.StringIO):
            from csl_bridge_transport import receiver_main
            self.assertEqual(receiver_main(), 0)
            self.assertEqual(call.call_args.args[1]['trusted_peer'], 'alice')

    def test_cli_help_no_runtime_or_personal_history_access(self):
        import codex_sessions
        parser = codex_sessions.build_parser()
        with patch('csl_bridge_engine.Runtime', side_effect=AssertionError('Must not start runtime')):
            with redirect_stderr(io.StringIO()):
                args = parser.parse_args(['bridge', '--home', str(self.home), 'agents'])
            self.assertEqual(args.action, 'agents')


if __name__ == '__main__':
    unittest.main()
