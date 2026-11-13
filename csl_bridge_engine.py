"""Session-scoped coordination around existing Codex threads; no session cloning."""
import fcntl
import queue
import socketserver
import sqlite3
import threading
import time
import uuid

from csl_bridge_rpc import Runtime, RuntimeRejected, RuntimeUnavailable
from csl_bridge_store import BridgeError, MAX_WIRE, NOTICE, Store, contains_findings, decode, encode, identifier, name, validate
from csl_bridge_transport import exchange


def event_id(value):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, value))


class Connector:
    def __init__(self, home, runtime_factory=Runtime):
        self.store = Store(home)
        self.identity = self.store.setting('identity')
        self.runtime_path = self.store.setting('runtime_socket')
        self.agents, self.peers = self.store.agents(), self.store.peers()
        self.factory = runtime_factory
        self.runtime = None
        self.stop = threading.Event()
        self.changed = threading.Condition()
        self.locks = {agent: threading.RLock() for agent in self.agents}
        self.waiters = {agent: 0 for agent in self.agents}
        self.turns, self.answers = {}, {}
        self.threads = []
        self.server = None
        import os
        descriptor = os.open(self.store.home / 'connector.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        self.owner_lock = os.fdopen(descriptor, 'a')
        try:
            fcntl.flock(self.owner_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.owner_lock.close()
            self.store.close()
            raise BridgeError('A connector already owns this bridge home') from None
        # A crash while invoking is an uncertain operation, never an invitation to replay.
        with self.store.transaction() as db:
            db.execute("UPDATE operations SET state='uncertain' WHERE state='invoking'")

    def spawn(self, function, *args):
        thread = threading.Thread(target=function, args=args, daemon=True)
        self.threads.append(thread)
        thread.start()

    def start(self):
        self.spawn(self.runtime_loop)
        for peer in self.peers:
            self.spawn(self.peer_loop, peer)
        connector = self
        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.connection.settimeout(25)
                try:
                    raw = self.rfile.readline(MAX_WIRE + 1)
                    if not raw.endswith(b'\n'):
                        raise BridgeError('Incomplete bridge request')
                    request = decode(raw)
                    data = connector.local(request)
                    output = {'ok': True, 'data': data}
                except (BridgeError, RuntimeUnavailable, RuntimeRejected, sqlite3.Error, OSError, ValueError, KeyError, TypeError):
                    output = {'ok': False, 'data': {'error': 'Bridge rejected request; inspect receipt/state'}}
                try:
                    self.wfile.write((encode(output) + '\n').encode())
                except OSError:
                    pass
        class Server(socketserver.ThreadingUnixStreamServer):
            daemon_threads = True
        path = self.store.home / 'connector.sock'
        if path.exists() or path.is_symlink():
            # Only an owned socket left by our prior process may be replaced.
            import os, stat
            info = path.lstat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
                raise BridgeError('Refusing non-socket connector endpoint')
            path.unlink()
        self.server = Server(str(path), Handler)
        import os
        os.chmod(path, 0o600)
        self.spawn(self.server.serve_forever)

    def ready(self):
        if self.runtime is None or not self.runtime.connected:
            raise RuntimeUnavailable('Existing runtime unavailable')
        return self.runtime

    def current(self, agent):
        runtime = self.ready()
        thread = self.agents[agent]
        state = runtime.call('thread/read', {'threadId': thread})['thread']['status']
        turn = None
        if state['type'] == 'active':
            turn = self.turns.get(thread)
            if turn is None:
                turns = runtime.call('thread/turns/list', {'threadId': thread, 'limit': 1, 'itemsView': 'notLoaded',
                                                        'sortDirection': 'desc'})['data']
                turn = next((t['id'] for t in turns if t['status'] == 'inProgress'), None)
            if turn is None:
                raise RuntimeUnavailable('Active turn identity not yet observable')
        last = self.store.rows('SELECT id,status,turn FROM tasks WHERE target=? ORDER BY rowid DESC LIMIT 1', (agent,))
        return {'agent': agent, 'thread_id': thread, 'status': state['type'],
                'active_flags': state.get('activeFlags', []), 'turn_id': turn,
                'last_task': last[0] if last else None}

    def runtime_loop(self):
        while not self.stop.is_set():
            runtime = None
            try:
                runtime = self.factory(self.runtime_path)
                # Rejoin selected existing threads only; no start/fork/override/auth surface.
                loaded, cursor = set(), None
                while True:
                    page = runtime.call('thread/loaded/list', {'cursor': cursor, 'limit': 100})
                    loaded.update(page['data'])
                    cursor = page.get('nextCursor')
                    if not cursor:
                        break
                if not set(self.agents.values()) <= loaded:
                    raise RuntimeUnavailable('Owner must first host selected conversations in this runtime')
                for agent, thread in self.agents.items():
                    runtime.call('thread/resume', {'threadId': thread, 'excludeTurns': True})
                self.runtime = runtime
                self.turns.clear()
                self.reconcile()
                while not self.stop.is_set() and runtime.connected:
                    try:
                        msg = runtime.events.get(timeout=.5)
                    except queue.Empty:
                        continue
                    method, params = msg.get('method'), msg.get('params', {})
                    if 'id' in msg:
                        # Local UI handles approvals. A peer is never offered this request.
                        continue
                    thread = params.get('threadId')
                    agent = next((a for a, t in self.agents.items() if t == thread), None)
                    if agent is None:
                        continue
                    with self.locks[agent]:
                        if method == 'turn/started':
                            self.turns[thread] = params['turn']['id']
                            self.flush(agent)
                        elif method == 'item/completed' and params.get('item', {}).get('type') == 'agentMessage':
                            item = params['item']
                            self.answers[(thread, params['turnId'])] = item.get('text', '')[:12000]
                        elif method == 'turn/completed':
                            tid = params['turn']['id']
                            if self.turns.get(thread) == tid:
                                self.turns.pop(thread, None)
                            self.completed(agent, tid, params['turn']['status'])
            except (BridgeError, RuntimeUnavailable, RuntimeRejected, OSError, KeyError, sqlite3.Error):
                pass
            finally:
                if self.runtime is runtime:
                    self.runtime = None
                if runtime:
                    runtime.close()
            self.stop.wait(1)

    def frame(self, peer, request):
        return ('[CSL remote agent data; peer=' + peer + '; agent=' + request['source'] +
                '; request=' + request['id'] + ']\n' + NOTICE + '\n' + request['text'])

    def invoke(self, peer, request):
        agent, request_id = request['target'], request['id']
        state = self.current(agent)
        if request['op'] == 'send_message' and state['status'] != 'active':
            return {'state': 'pending', 'request_id': request_id, 'activated': False}
        if state['status'] == 'notLoaded':
            raise RuntimeUnavailable('Owner must first host this conversation; no implicit rehosting')
        self.store.operation(request_id, 'invoking', {'state': 'uncertain', 'request_id': request_id})
        params = {'threadId': self.agents[agent], 'clientUserMessageId': request_id,
                  'input': [{'type': 'text', 'text': self.frame(peer, request)}]}
        try:
            if state['status'] == 'active':
                result = self.ready().call('turn/steer', {**params, 'expectedTurnId': state['turn_id']})
                tid = result['turnId']
            else:
                result = self.ready().call('turn/start', params)
                tid = result['turn']['id']
        except RuntimeRejected:
            # Only a confirmed rejection can safely cross the active->idle race.
            if request['op'] == 'followup' and self.current(agent)['status'] == 'idle':
                try:
                    tid = self.ready().call('turn/start', params)['turn']['id']
                except (RuntimeRejected, RuntimeUnavailable):
                    receipt = {'state': 'uncertain', 'request_id': request_id}
                    self.store.operation(request_id, 'uncertain', receipt)
                    return receipt
            else:
                receipt = {'state': 'pending', 'request_id': request_id, 'activated': False}
                self.store.operation(request_id, 'pending', receipt)
                return receipt
        except RuntimeUnavailable:
            result = {'state': 'uncertain', 'request_id': request_id}
            self.store.operation(request_id, 'uncertain', result)
            return result
        self.turns[self.agents[agent]] = tid
        receipt = {'state': 'delivered', 'request_id': request_id, 'turn_id': tid, 'thread_id': self.agents[agent]}
        self.store.operation(request_id, 'delivered', receipt)
        if request['op'] == 'followup':
            with self.store.transaction() as db:
                db.execute("UPDATE tasks SET turn=?,status='running' WHERE id=?", (tid, request_id))
        return receipt

    def incoming(self, peer, request):
        peer = name(peer)
        validate(request)
        if peer not in self.peers or request['op'] not in self.peers[peer]['allow_ops']:
            raise BridgeError('Peer operation not permitted')
        op = request['op']
        target = request.get('target')
        if target is not None and (target not in self.agents or target not in self.peers[peer]['allow_agents']):
            raise BridgeError('Peer agent not permitted')
        if op == 'watch':
            deadline = time.monotonic() + 15
            with self.changed:
                while True:
                    rows = self.store.rows('SELECT seq,body FROM outbound WHERE peer=? AND seq>? ORDER BY seq LIMIT 1',
                                           (peer, request['after']))
                    if rows or self.stop.is_set() or time.monotonic() >= deadline:
                        return {'events': [{'seq': r['seq'], 'event': decode(r['body'])} for r in rows]}
                    self.changed.wait(max(.01, deadline - time.monotonic()))
        if op == 'receipt':
            rows = self.store.rows('SELECT state,result FROM operations WHERE id=? AND peer=?',
                                   (request['request_id'], peer))
            if rows and rows[0]['state'] in ('uncertain', 'invoking'):
                try:
                    self.reconcile(flush_pending=False)
                except (RuntimeUnavailable, RuntimeRejected):
                    pass
                rows = self.store.rows('SELECT state,result FROM operations WHERE id=? AND peer=?',
                                       (request['request_id'], peer))
            return {'state': rows[0]['state'], 'result': decode(rows[0]['result']) if rows[0]['result'] else None} if rows else {'state': 'not_found'}
        if op == 'agents':
            agents = []
            for agent in self.peers[peer]['allow_agents']:
                try:
                    agents.append(self.current(agent))
                except RuntimeUnavailable:
                    agents.append({'agent': agent, 'status': 'disconnected', 'turn_id': None})
            return {'agents': agents}
        with self.locks[target]:
            if op == 'status':
                try:
                    return self.current(target)
                except RuntimeUnavailable:
                    return {'agent': target, 'status': 'disconnected', 'turn_id': None}
            previous = self.store.reserve(peer, request)
            if previous:
                return previous['result'] or {'state': previous['state'], 'request_id': request['id']}
            if op in ('followup', 'send_message'):
                if op == 'followup':
                    with self.store.transaction() as db:
                        db.execute('INSERT INTO tasks VALUES(?,?,?,?,NULL,?)',
                                   (request['id'], peer, request['source'], target, 'pending'))
                try:
                    return self.invoke(peer, request)
                except RuntimeUnavailable:
                    result = {'state': 'pending', 'request_id': request['id'], 'runtime': 'disconnected'}
                    self.store.operation(request['id'], 'pending', result)
                    return result
            if op == 'interrupt':
                state = self.current(target)
                tasks = self.store.rows('SELECT id FROM tasks WHERE peer=? AND target=? AND turn=?',
                                        (peer, target, request['turn_id']))
                if state['turn_id'] != request['turn_id'] or not tasks:
                    result = {'state': 'rejected', 'request_id': request['id'], 'reason': 'No matching active delegated turn'}
                    self.store.operation(request['id'], 'rejected', result)
                    return result
                self.store.operation(request['id'], 'invoking', {'state': 'uncertain', 'request_id': request['id']})
                try:
                    self.ready().call('turn/interrupt', {'threadId': self.agents[target], 'turnId': request['turn_id']})
                    result = {'state': 'interrupt_requested', 'request_id': request['id'], 'turn_id': request['turn_id']}
                    self.store.operation(request['id'], 'delivered', result)
                    return result
                except (RuntimeRejected, RuntimeUnavailable):
                    result = {'state': 'uncertain', 'request_id': request['id']}
                    self.store.operation(request['id'], 'uncertain', result)
                    return result

    def flush(self, agent):
        if self.waiters[agent]:
            return
        rows = self.store.rows("SELECT peer,request FROM operations WHERE state='pending'")
        for row in rows:
            request = decode(row['request'])
            if request.get('target') == agent and request['op'] in ('followup', 'send_message') and not row['peer'].startswith('outbound:'):
                self.invoke(row['peer'], request)
        rows = self.store.rows("SELECT * FROM inbound WHERE delivery='pending' ORDER BY seq")
        for row in rows:
            event = decode(row['body'])
            if event['target'] == agent:
                self.deliver_event(row)

    def completed(self, agent, tid, status):
        answer = self.answers.pop((self.agents[agent], tid), '')
        if not answer:
            turns = self.ready().call('thread/turns/list', {'threadId': self.agents[agent], 'limit': 5,
                                                          'itemsView': 'full', 'sortDirection': 'desc'})['data']
            for turn in turns:
                if turn['id'] == tid:
                    answer = '\n'.join(item.get('text', '') for item in turn.get('items', [])
                                       if item.get('type') == 'agentMessage')[-12000:]
        if contains_findings(answer):
            answer = 'Result text withheld by partial secret detection. Review selected evidence locally; completion alone is not validation.'
        tasks = self.store.rows('SELECT * FROM tasks WHERE target=? AND turn=?', (agent, tid))
        for task in tasks:
            event = {'task_id': task['id'], 'source': agent, 'target': task['source'],
                     'kind': 'final', 'text': answer, 'turn_id': tid, 'status': status}
            self.store.publish(task['peer'], event, event_id(task['id'] + '/' + tid + '/final'))
            with self.store.transaction() as db:
                db.execute('UPDATE tasks SET status=? WHERE id=?', (status, task['id']))
        with self.changed:
            self.changed.notify_all()

    def reconcile(self, flush_pending=True):
        # Join first, then recover effects using native client message IDs. Missing
        # evidence remains uncertain; never auto-repeat an invocation.
        for agent, thread in self.agents.items():
            turns, cursor = [], None
            for _ in range(10):
                page = self.ready().call('thread/turns/list', {'threadId': thread, 'limit': 20,
                    'itemsView': 'full', 'sortDirection': 'desc', 'cursor': cursor})
                turns.extend(page['data'])
                cursor = page.get('nextCursor')
                if not cursor:
                    break
            by_client = {item.get('clientId'): turn['id'] for turn in turns for item in turn.get('items', [])
                         if item.get('type') == 'userMessage' and item.get('clientId')}
            with self.store.transaction() as db:
                for row in self.store.rows("SELECT id,body FROM inbound WHERE delivery='uncertain'"):
                    if decode(row['body'])['target'] == agent and row['id'] in by_client:
                        db.execute("UPDATE inbound SET delivery='delivered' WHERE id=?", (row['id'],))
            for row in self.store.rows("SELECT id,request FROM operations WHERE state='uncertain'"):
                request = decode(row['request'])
                if request.get('target') != agent or row['id'] not in by_client:
                    continue
                tid = by_client[row['id']]
                result = {'state': 'delivered', 'request_id': row['id'], 'turn_id': tid, 'thread_id': thread}
                self.store.operation(row['id'], 'delivered', result)
                with self.store.transaction() as db:
                    db.execute("UPDATE tasks SET turn=?,status='running' WHERE id=?", (tid, row['id']))
            for turn in turns:
                if turn['status'] in ('completed', 'interrupted', 'failed'):
                    self.answers[(thread, turn['id'])] = '\n'.join(i.get('text', '') for i in turn.get('items', [])
                        if i.get('type') == 'agentMessage')[-12000:]
                    self.completed(agent, turn['id'], turn['status'])
            if flush_pending:
                with self.locks[agent]:
                    self.flush(agent)

    def peer_loop(self, peer):
        retry = 1
        while not self.stop.is_set():
            try:
                cursor = self.store.rows('SELECT value FROM cursors WHERE peer=?', (peer,))
                after = cursor[0]['value'] if cursor else 0
                result = exchange(self.peers[peer], self.identity,
                    {'version': 1, 'op': 'watch', 'id': str(uuid.uuid4()), 'after': after})
                for row in result['events']:
                    self.accept_event(peer, row)
                retry = 1
            except (BridgeError, OSError, KeyError, ValueError, TypeError, sqlite3.Error):
                self.stop.wait(retry)
                retry = min(retry * 2, 15)

    def accept_event(self, peer, row):
        if not isinstance(row, dict) or set(row) != {'seq', 'event'} or type(row['seq']) is not int or not 0 < row['seq'] <= 2**63 - 1:
            raise BridgeError('Invalid event cursor')
        event = row['event']
        if not isinstance(event, dict) or set(event) != {'id', 'task_id', 'source', 'target', 'kind', 'text', 'turn_id', 'status'}:
            raise BridgeError('Invalid event fields')
        for key in ('id', 'task_id', 'turn_id'):
            identifier(event[key])
        name(event['source']); name(event['target'])
        if event['kind'] not in ('progress', 'final') or event['status'] not in ('progress', 'completed', 'interrupted', 'failed'):
            raise BridgeError('Invalid event state')
        if (event['kind'] == 'progress') != (event['status'] == 'progress'):
            raise BridgeError('Invalid event kind/status correlation')
        if not isinstance(event['text'], str) or len(event['text']) > 12000:
            raise BridgeError('Invalid event text')
        matches = self.store.rows('SELECT request,result FROM operations WHERE id=? AND peer=?',
                                  (event['task_id'], 'outbound:' + peer))
        if not matches:
            raise BridgeError('Event has no matching delegated task')
        request = decode(matches[0]['request'])
        if event['source'] != request.get('target') or event['target'] != request.get('source'):
            raise BridgeError('Event actor does not match delegated task')
        receipt = decode(matches[0]['result']) if matches[0]['result'] else {}
        if receipt.get('turn_id') and receipt['turn_id'] != event['turn_id']:
            raise BridgeError('Event turn does not match delegated task')
        with self.store.transaction() as db:
            existing = db.execute('SELECT body FROM inbound WHERE id=?', (event['id'],)).fetchone()
            if existing and existing['body'] != encode(event):
                raise BridgeError('Event ID collision')
            db.execute('INSERT OR IGNORE INTO inbound(id,peer,body) VALUES(?,?,?)', (event['id'], peer, encode(event)))
            db.execute('INSERT INTO cursors VALUES(?,?) ON CONFLICT(peer) DO UPDATE SET value=max(value,excluded.value)',
                       (peer, row['seq']))
        with self.changed:
            self.changed.notify_all()
        with self.locks[event['target']]:
            rows = self.store.rows('SELECT * FROM inbound WHERE id=?', (event['id'],))
            self.deliver_event(rows[0])

    def deliver_event(self, row):
        event = decode(row['body'])
        agent = event['target']
        if row['delivery'] != 'pending' or self.waiters[agent]:
            return
        try:
            state = self.current(agent)
            if state['status'] != 'active':
                return
            # Commit uncertainty BEFORE invoking; a crash cannot cause silent replay.
            with self.store.transaction() as db:
                db.execute("UPDATE inbound SET delivery='uncertain' WHERE id=?", (event['id'],))
            self.ready().call('turn/steer', {'threadId': self.agents[agent], 'expectedTurnId': state['turn_id'],
                'clientUserMessageId': event['id'], 'input': [{'type': 'text', 'text':
                    '[CSL remote ' + event['kind'] + '; peer=' + row['peer'] + '; task=' + event['task_id'] + ']\n' +
                    NOTICE + '\n' + event['text']}]})
            with self.store.transaction() as db:
                db.execute("UPDATE inbound SET delivery='delivered' WHERE id=?", (event['id'],))
        except RuntimeRejected:
            with self.store.transaction() as db:
                db.execute("UPDATE inbound SET delivery='pending' WHERE id=?", (event['id'],))
        except RuntimeUnavailable:
            pass

    def local(self, request):
        if not isinstance(request, dict) or not isinstance(request.get('local_op'), str):
            raise BridgeError('Invalid local operation')
        op = request['local_op']
        if op == '_incoming' and set(request) == {'local_op', 'trusted_peer', 'request'}:
            return self.incoming(request['trusted_peer'], request['request'])
        if op == 'call' and set(request) == {'local_op', 'peer', 'request'}:
            peer = name(request['peer'])
            body = validate(request['request'])
            if 'text' in body and contains_findings(body['text']):
                raise BridgeError('Possible secrets detected; select or scrub text locally before sending')
            if peer not in self.peers or body.get('source', next(iter(self.agents), None)) not in self.agents:
                raise BridgeError('Unknown configured peer or source agent')
            if body['op'] in ('followup', 'send_message', 'interrupt'):
                previous = self.store.reserve('outbound:' + peer, body)
                if previous:
                    return previous['result'] or {'state': previous['state'], 'request_id': body['id']}
            try:
                result = exchange(self.peers[peer], self.identity, body)
            except BridgeError:
                result = {'state': 'uncertain', 'request_id': body['id']}
            if body['op'] in ('followup', 'send_message', 'interrupt'):
                self.store.operation(body['id'], result.get('state', 'delivered'), result)
            if body['op'] == 'receipt' and result.get('state') != 'not_found' and result.get('result'):
                own = self.store.rows('SELECT id FROM operations WHERE id=? AND peer=?', (body['request_id'], 'outbound:' + peer))
                if own:
                    self.store.operation(body['request_id'], result['state'], result['result'])
            return result
        if op == 'agents' and set(request) == {'local_op'}:
            result = []
            for agent in self.agents:
                try:
                    result.append(self.current(agent))
                except RuntimeUnavailable:
                    result.append({'agent': agent, 'status': 'disconnected', 'turn_id': None})
            return {'agents': result}
        if op == 'progress' and set(request) == {'local_op', 'source', 'task_id', 'id', 'text'}:
            identifier(request['id']); identifier(request['task_id']); name(request['source'])
            rows = self.store.rows('SELECT * FROM tasks WHERE id=? AND target=?', (request['task_id'], request['source']))
            if not rows or rows[0]['status'] not in ('running',):
                raise BridgeError('Progress requires an active delegated task')
            task = rows[0]
            validate({'version': 1, 'op': 'send_message', 'id': request['id'], 'source': request['source'],
                      'target': task['source'], 'text': request['text']})
            if contains_findings(request['text']):
                raise BridgeError('Possible secrets detected; select or scrub progress text locally')
            body = {'task_id': task['id'], 'source': task['target'], 'target': task['source'],
                    'kind': 'progress', 'text': request['text'], 'turn_id': task['turn'], 'status': 'progress'}
            existing = self.store.rows('SELECT body FROM outbound WHERE id=?', (request['id'],))
            if existing and decode(existing[0]['body']) != {**body, 'id': request['id']}:
                raise BridgeError('Progress ID collision')
            self.store.publish(task['peer'], body, request['id'])
            with self.changed:
                self.changed.notify_all()
            return {'state': 'published', 'event_id': request['id']}
        if op == 'wait' and set(request) == {'local_op', 'agent', 'after', 'timeout'}:
            agent = name(request['agent'])
            if agent not in self.agents or type(request['after']) is not int or not 0 <= request['after'] <= 2**63 - 1:
                raise BridgeError('Invalid wait agent/cursor')
            if type(request['timeout']) not in (int, float) or not 0 <= request['timeout'] <= 20:
                raise BridgeError('Invalid wait timeout')
            deadline = time.monotonic() + request['timeout']
            with self.changed:
                self.waiters[agent] += 1
                try:
                    while True:
                        rows = [r for r in self.store.rows('SELECT * FROM inbound WHERE seq>? ORDER BY seq', (request['after'],))
                                if decode(r['body'])['target'] == agent][:1]
                        if rows or self.stop.is_set() or time.monotonic() >= deadline:
                            # Tool return delivers these events to the waiting conversation.
                            with self.store.transaction() as db:
                                for row in rows:
                                    db.execute("UPDATE inbound SET delivery='delivered' WHERE id=?", (row['id'],))
                            return {'notice': NOTICE, 'events': [{'cursor': r['seq'], 'event': decode(r['body'])} for r in rows]}
                        self.changed.wait(max(.01, deadline - time.monotonic()))
                finally:
                    self.waiters[agent] -= 1
        raise BridgeError('Unknown local operation')

    def close(self):
        if getattr(self, '_closed', False):
            return
        self._closed = True
        self.stop.set()
        with self.changed:
            self.changed.notify_all()
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.runtime:
            self.runtime.close()
        for thread in self.threads:
            thread.join(timeout=2)
        if self.server:
            (self.store.home / 'connector.sock').unlink(missing_ok=True)
        fcntl.flock(self.owner_lock, fcntl.LOCK_UN)
        self.owner_lock.close()
        # Peer calls can remain blocked until their bounded transport timeout;
        # retain DB connection until daemon threads end rather than close under them.
        if all(not thread.is_alive() for thread in self.threads):
            self.store.close()
