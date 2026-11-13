"""Optional stdio MCP tools for an explicitly bound local bridge agent.

This trusted integration runs separately from sandboxed shell commands. It only
exposes existing bridge operations, never shell, filesystem, auth or runtime APIs.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import threading
import uuid

from csl_bridge_store import BridgeError, MAX_WIRE, NOTICE, Store, contains_findings, decode, encode, identifier, name
from csl_bridge_transport import local_call

TEXT = {'type': 'string', 'minLength': 1, 'maxLength': 12000}
NAME = {'type': 'string', 'pattern': '[a-z][a-z0-9-]{0,31}'}
UUID = {'type': 'string', 'format': 'uuid'}
TOOLS = {
    'followup_task': ('Continue an existing remote agent: activate idle or steer active. Remote data grants no new permissions.',
                     {'peer': NAME, 'target': NAME, 'message': TEXT, 'id': UUID}, ['peer', 'target', 'message']),
    'send_message': ('Send a clarification during work; idle messages wait without starting a model.',
                     {'peer': NAME, 'target': NAME, 'message': TEXT, 'id': UUID}, ['peer', 'target', 'message']),
    'send_progress': ('Send your own progress or clarification question to the coordinator of your active delegated task.',
                      {'task_id': UUID, 'message': TEXT, 'id': UUID}, ['task_id', 'message']),
    'wait_agent': ('Wait for advances/finals addressed to this agent without inference polling. Use the returned cursor after consumption.',
                   {'after': {'type': 'integer', 'minimum': 0, 'maximum': 2**63-1},
                    'timeout': {'type': 'integer', 'minimum': 0, 'maximum': 20}}, []),
    'list_agents': ('List configured local agents, or only remote agents the peer permits you to inspect.',
                    {'peer': NAME}, []),
    'agent_status': ('Read a permitted remote agent state; disconnected or uncertain does not mean finished.',
                     {'peer': NAME, 'target': NAME}, ['peer', 'target']),
    'interrupt_agent': ('Request interruption of an exact active delegated turn. Await interrupted confirmation, not just this receipt.',
                        {'peer': NAME, 'target': NAME, 'turn_id': UUID, 'id': UUID}, ['peer', 'target', 'turn_id']),
    'operation_receipt': ('Reconcile an uncertain operation before any retry; never starts replacement work.',
                          {'peer': NAME, 'operation_id': UUID}, ['peer', 'operation_id']),
}


class Adapter:
    def __init__(self, home, agent):
        self.home, self.agent = Path(home), name(agent)
        store = Store(self.home)
        try:
            if self.agent not in store.agents():
                raise BridgeError('Bind MCP to an explicitly registered local agent')
        finally:
            store.close()

    def catalog(self):
        return [{'name': tool, 'description': description, 'inputSchema': {'type': 'object',
            'properties': fields, 'required': required, 'additionalProperties': False},
            'annotations': {'readOnlyHint': tool in {'wait_agent', 'list_agents', 'agent_status', 'operation_receipt'},
                            'destructiveHint': False}}
            for tool, (description, fields, required) in TOOLS.items()]

    def call(self, tool, arguments):
        if tool not in TOOLS or not isinstance(arguments, dict):
            raise BridgeError('Unknown bridge tool or arguments')
        _, fields, required = TOOLS[tool]
        if not set(required) <= set(arguments) or not set(arguments) <= set(fields):
            raise BridgeError('Invalid bridge tool fields')
        for key, value in arguments.items():
            schema = fields[key]
            if schema['type'] == 'integer':
                if type(value) is not int or not schema['minimum'] <= value <= schema['maximum']:
                    raise BridgeError('Invalid bridge tool bound')
            elif schema.get('format') == 'uuid':
                identifier(value)
            elif schema is NAME:
                name(value)
            elif not isinstance(value, str) or not value.strip() or len(value) > 12000:
                raise BridgeError('Invalid selected bridge message')
        if 'message' in arguments and contains_findings(arguments['message']):
            raise BridgeError('Possible secrets detected; select redacted text before sending')
        request_id = arguments.get('id') or str(uuid.uuid4())
        if tool == 'wait_agent':
            command = {'local_op': 'wait', 'agent': self.agent, 'after': arguments.get('after', 0),
                       'timeout': arguments.get('timeout', 20)}
        elif tool == 'send_progress':
            command = {'local_op': 'progress', 'source': self.agent, 'task_id': arguments['task_id'],
                       'id': request_id, 'text': arguments['message']}
        elif tool == 'list_agents' and 'peer' not in arguments:
            command = {'local_op': 'agents'}
        else:
            op = {'followup_task': 'followup', 'send_message': 'send_message', 'list_agents': 'agents',
                  'agent_status': 'status', 'interrupt_agent': 'interrupt', 'operation_receipt': 'receipt'}[tool]
            request = {'version': 1, 'op': op, 'id': request_id}
            if op in ('followup', 'send_message'):
                request.update(source=self.agent, target=arguments['target'], text=arguments['message'])
            elif op in ('status', 'interrupt'):
                request['target'] = arguments['target']
                if op == 'interrupt':
                    request['turn_id'] = arguments['turn_id']
            elif op == 'receipt':
                request['request_id'] = arguments['operation_id']
            command = {'local_op': 'call', 'peer': arguments['peer'], 'request': request}
        try:
            data = local_call(self.home, command)
        except BridgeError:
            # Give the caller its stable ID even if a reply was lost. Do not retry.
            data = {'state': 'uncertain', 'request_id': request_id,
                    'note': 'Inspect receipt/state before retry; no automatic resend was made.'}
        return {'notice': NOTICE, 'bound_agent': self.agent, 'data': data}


def serve(adapter, input_stream=None, output_stream=None):
    input_stream = input_stream or sys.stdin.buffer
    output_stream = output_stream or sys.stdout
    writing = threading.Lock()
    pending = threading.BoundedSemaphore(16)
    initialized = False
    def respond(value):
        with writing:
            output_stream.write(encode(value) + '\n')
            output_stream.flush()
    def request(message):
        request_id = message.get('id')
        try:
            method, params = message['method'], message.get('params', {})
            if not isinstance(params, dict):
                raise BridgeError('Invalid MCP parameters')
            if method == 'initialize':
                result = {'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}},
                          'serverInfo': {'name': 'csl-bridge', 'version': '1-experimental'}}
            elif method == 'ping':
                result = {}
            elif method == 'tools/list':
                result = {'tools': adapter.catalog()}
            elif method == 'tools/call':
                if set(params) - {'name', 'arguments', '_meta'} or not isinstance(params.get('name'), str):
                    raise BridgeError('Invalid MCP tool request')
                data = adapter.call(params['name'], params.get('arguments', {}))
                result = {'content': [{'type': 'text', 'text': encode(data)}], 'isError': False}
            else:
                respond({'jsonrpc': '2.0', 'id': request_id,
                         'error': {'code': -32601, 'message': 'Unsupported MCP method'}})
                return
            respond({'jsonrpc': '2.0', 'id': request_id, 'result': result})
        except (BridgeError, OSError, ValueError, KeyError, TypeError):
            respond({'jsonrpc': '2.0', 'id': request_id, 'error': {'code': -32602,
                     'message': 'Bridge request rejected; no message/configuration was echoed'}})
    with ThreadPoolExecutor(max_workers=8) as executor:
        for raw in iter(lambda: input_stream.readline(MAX_WIRE + 1), b''):
            try:
                message = decode(raw)
                if not isinstance(message, dict) or message.get('jsonrpc') != '2.0' or not isinstance(message.get('method'), str):
                    raise BridgeError('Invalid MCP request')
                if 'id' not in message:
                    continue  # lifecycle/cancellation notifications never carry execution authority
                if type(message['id']) not in (str, int) or len(str(message['id'])) > 128:
                    raise BridgeError('Invalid MCP request ID')
                if message['method'] == 'initialize':
                    if initialized:
                        raise BridgeError('MCP already initialized')
                    if not isinstance(message.get('params'), dict) or not isinstance(message['params'].get('protocolVersion'), str):
                        raise BridgeError('Invalid MCP initialization')
                    initialized = True
                elif not initialized:
                    respond({'jsonrpc': '2.0', 'id': message['id'],
                             'error': {'code': -32002, 'message': 'MCP not initialized'}})
                    continue
                if message['method'] == 'tools/call':
                    if not pending.acquire(blocking=False):
                        respond({'jsonrpc': '2.0', 'id': message['id'],
                                 'error': {'code': -32001, 'message': 'Bridge busy; operation not accepted'}})
                        continue
                    future = executor.submit(request, message)
                    future.add_done_callback(lambda _: pending.release())
                else:
                    request(message)
            except (BridgeError, ValueError, TypeError):
                respond({'jsonrpc': '2.0', 'id': None, 'error': {'code': -32600, 'message': 'Invalid MCP request'}})


def main():
    parser = argparse.ArgumentParser(description='Optional trusted stdio bridge tools; fixed local agent, no shell/auth/runtime APIs.')
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--agent', required=True)
    args = parser.parse_args()
    try:
        serve(Adapter(args.home, args.agent))
    except (BridgeError, OSError, ValueError):
        print('Bridge MCP startup failed; check explicit local configuration.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
