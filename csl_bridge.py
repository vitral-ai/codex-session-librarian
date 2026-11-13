"""Optional experimental CLI for automatic coordination of existing Codex agents."""
import argparse
import fcntl
import os
from pathlib import Path
import signal
import sqlite3
import sys
import uuid

from csl_bridge_store import BridgeError, MAX_WIRE, Store, decode, encode, identifier, name
from csl_bridge_transport import local_call, ssh_argv


def reviewed_text(path, scrub=False):
    from csl_secrets import SecretReview
    try:
        if str(path) == '-':
            raw = sys.stdin.buffer.read(MAX_WIRE + 1)
        else:
            with Path(path).open('rb') as stream:
                raw = stream.read(MAX_WIRE + 1)
        if len(raw) > 48000:
            raise BridgeError('Bridge text exceeds size limit')
        text = raw.decode('utf-8')
    except (OSError, UnicodeError):
        raise BridgeError('Cannot read selected UTF-8 text') from None
    review = SecretReview(argparse.Namespace(allow_secrets=False, scrub_secrets=scrub))
    review.scan({'text': text}, 'bridge-selected-text')
    if review.findings:
        if not scrub:
            raise BridgeError('Possible secrets detected; redact selected text or use --scrub-secrets for this message')
        review.decisions = {secret: 'scrub' for secret in review.findings}
        text = review.cleaned({'text': text})['text']
    return text


def configure(args):
    if args.action == 'init':
        identity = name(args.identity)
        path = args.runtime_socket.expanduser().absolute() if args.runtime_socket else None
        store = Store(args.home, create=True)
    else:
        store = Store(args.home)
    try:
        # Configuration is offline only. Running connector owns its immutable snapshot.
        lock = os.fdopen(os.open(store.home / 'connector.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), 'a')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            raise BridgeError('Stop connector before changing explicit configuration') from None
        with lock, store.transaction() as db:
            if args.action == 'init':
                old = db.execute("SELECT value FROM config WHERE key='identity'").fetchone()
                if old and decode(old['value']) != identity:
                    raise BridgeError('Bridge identity already initialized')
                if old:
                    raise BridgeError('Bridge already initialized; preserve its configuration')
                db.executemany('INSERT INTO config VALUES(?,?)',
                               [('identity', encode(identity)), ('runtime_socket', encode(str(path) if path else None))])
            elif args.action == 'agent':
                agent, thread = name(args.agent), identifier(args.thread)
                db.execute('INSERT INTO agents VALUES(?,?)', (agent, thread))
            elif args.action == 'peer':
                peer = name(args.peer)
                if peer == store.setting('identity'):
                    raise BridgeError('Peer must have a distinct bridge identity')
                agents = [name(a) for a in args.allow_agent]
                if not set(agents) <= set(store.agents()):
                    raise BridgeError('Allow only explicitly registered local agents')
                if args.ssh_config and not args.ssh_alias:
                    raise BridgeError('Explicit SSH config requires SSH transport')
                if args.receive_only:
                    config = {'transport': 'receive-only'}
                elif args.lab_home:
                    config = {'transport': 'lab', 'home': str(args.lab_home.expanduser().absolute())}
                else:
                    ssh_argv(args.ssh_alias, args.ssh_config)
                    config = {'transport': 'ssh', 'alias': args.ssh_alias}
                    if args.ssh_config:
                        config['ssh_config'] = str(args.ssh_config.expanduser().absolute())
                config.update(allow_agents=agents, allow_ops=sorted(set(args.allow_op)))
                db.execute('INSERT INTO peers VALUES(?,?)', (peer, encode(config)))
        return {'state': 'configured', 'action': args.action, 'inference': False}
    finally:
        store.close()


def run(args):
    try:
        if args.action in ('init', 'agent', 'peer'):
            result = configure(args)
        elif args.action == 'run':
            from csl_bridge_engine import Connector
            connector = Connector(args.home)
            previous = {}
            def stopping(*_):
                connector.stop.set()
            for sig in (signal.SIGINT, signal.SIGTERM):
                previous[sig] = signal.signal(sig, stopping)
            try:
                connector.start()
                print(encode({'state': 'running', 'foreground': True, 'runtime': 'tool-client' if connector.client_only else 'existing-only',
                              'notice': 'Existing compatible runtime only. Previously authorized pending followups may resume.'}), flush=True)
                while not connector.stop.wait(.5):
                    pass
            finally:
                connector.close()
                for sig, old in previous.items():
                    signal.signal(sig, old)
            return
        elif args.action == 'mcp-config':
            from csl_bridge_mcp import configuration
            print(configuration(args.home, args.agent, args.approve_tool))
            return
        elif args.action == 'agents' and not args.peer:
            result = local_call(args.home, {'local_op': 'agents'})
        elif args.action == 'wait':
            result = local_call(args.home, {'local_op': 'wait', 'agent': args.agent,
                                          'after': args.after, 'timeout': args.timeout})
        elif args.action == 'progress':
            result = local_call(args.home, {'local_op': 'progress', 'source': args.source,
                'task_id': args.task_id, 'id': args.request_id or str(uuid.uuid4()),
                'text': reviewed_text(args.text_file, args.scrub_secrets)})
        else:
            request = {'version': 1, 'op': args.action, 'id': args.request_id or str(uuid.uuid4())}
            if args.action in ('followup', 'send_message'):
                request.update(source=args.source, target=args.target,
                               text=reviewed_text(args.text_file, args.scrub_secrets))
            elif args.action in ('status', 'interrupt'):
                request['target'] = args.target
                if args.action == 'interrupt':
                    request['turn_id'] = args.turn_id
            elif args.action == 'receipt':
                request['request_id'] = args.operation_id
            result = local_call(args.home, {'local_op': 'call', 'peer': args.peer, 'request': request})
        print(encode(result))
    except BridgeError as exc:
        print('Bridge: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
    except (OSError, ValueError, sqlite3.Error):
        # Do not expose DB/OS/remote errors that may contain text, account or paths.
        print('Bridge operation failed. Check explicit configuration and receipt/state; do not blindly resend uncertain work.', file=sys.stderr)
        raise SystemExit(1)


def add_commands(subparsers, csl):
    parser = subparsers.add_parser('bridge', help='Experimental automatic agent coordination (optional, existing runtime only).',
        description='Coordinate existing Codex agents through a foreground session connector. '
                    'Followup activates idle; messages/events enter active work automatically. '
                    'No native attach to standalone TUI, no cloning, no automatic approvals. '
                    'Requires initial endpoint/agent/peer setup. Mac/SSH/accounts integration unverified.')
    parser.add_argument('--home', type=Path, required=True, help='Explicit private bridge home, separate from Codex histories/auth.')
    sub = parser.add_subparsers(dest='action', required=True)
    init = sub.add_parser('init', help='Initialize explicit private state; does not start anything.')
    init.add_argument('--id', dest='identity', required=True)
    hosting = init.add_mutually_exclusive_group(required=True)
    hosting.add_argument('--runtime-socket', type=Path, help='Existing app-server Unix WebSocket socket; never a new runtime.')
    hosting.add_argument('--client-only', action='store_true', help='Existing caller receives events through wait tool results; no runtime attach, activation or async injection into the caller.')
    agent = sub.add_parser('agent', help='Register an existing conversation as an agent, offline.')
    agent.add_argument('agent')
    agent.add_argument('--thread', required=True)
    peer = sub.add_parser('peer', help='Configure a peer and its explicit incoming permissions, offline.')
    peer.add_argument('peer')
    transport = peer.add_mutually_exclusive_group(required=True)
    transport.add_argument('--ssh-alias', help='Trusted SSH config alias; fixed receiver, no arbitrary SSH options.')
    transport.add_argument('--lab-home', type=Path, help='Synthetic same-UID local transport; NOT SSH authentication.')
    transport.add_argument('--receive-only', action='store_true', help='Peer initiates requests/watch; no reverse transport or network connection is attempted.')
    peer.add_argument('--ssh-config', type=Path, help='Explicit private trusted SSH config file, separate from personal SSH setup.')
    peer.add_argument('--allow-agent', action='append', required=True)
    peer.add_argument('--allow-op', action='append', required=True,
                      choices=['followup', 'send_message', 'status', 'interrupt', 'receipt', 'watch', 'agents'])
    sub.add_parser('run', help='Run connector in foreground for this session; Ctrl-C stops it, not Codex work.')
    mcp_config = sub.add_parser('mcp-config', help='Print a reviewable local MCP profile; never applies consent/configuration.')
    mcp_config.add_argument('--agent', required=True, help='Explicit registered local identity bound to the tools.')
    mcp_config.add_argument('--approve-tool', action='append', default=[], choices=['send_progress', 'send_message'],
        help='Explicit initial local consent for this message tool only; other side-effecting tools remain unavailable.')
    agents = sub.add_parser('agents', help='List registered local agents, or the agents a peer permits you to inspect.')
    agents.add_argument('--peer')
    agents.add_argument('--request-id')
    for action in ('followup', 'send_message', 'status', 'interrupt', 'receipt'):
        command = sub.add_parser(action, help={'followup': 'Delegate/continue in the SAME agent; starts idle, steers active.',
            'send_message': 'Deliver while running; hold idle without generation.', 'status': 'Observe remote agent state.',
            'interrupt': 'Request interruption of an exact turn; await confirmation event.',
            'receipt': 'Reconcile an uncertain operation; never blindly resend.'}[action])
        command.add_argument('--peer', required=True)
        command.add_argument('--request-id', help='Stable UUID for this operation; same ID/content returns its receipt.')
        if action == 'receipt':
            command.add_argument('--operation-id', required=True)
        else:
            command.add_argument('--to', dest='target', required=True)
        if action in ('followup', 'send_message'):
            command.add_argument('--from', dest='source', required=True)
            command.add_argument('--text-file', type=Path, required=True, help='Selected UTF-8 text, or - for stdin. No secrets in argv.')
            command.add_argument('--scrub-secrets', action='store_true', help='Partial scan/scrub for this text only; no secret-free guarantee.')
        if action == 'interrupt':
            command.add_argument('--turn-id', required=True)
    progress = sub.add_parser('progress', help='Publish progress for an active delegated task; delivered automatically to its coordinator.')
    progress.add_argument('--from', dest='source', required=True)
    progress.add_argument('--task-id', required=True)
    progress.add_argument('--request-id')
    progress.add_argument('--text-file', type=Path, required=True)
    progress.add_argument('--scrub-secrets', action='store_true')
    wait = sub.add_parser('wait', help='Wait for correlated advances/final without inference or aggressive polling.')
    wait.add_argument('--agent', required=True)
    wait.add_argument('--after', type=int, default=0)
    wait.add_argument('--timeout', type=int, default=20, help='Seconds, 0..20; timeout is not cancellation.')
    parser.set_defaults(func=run)
