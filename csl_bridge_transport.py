"""On-demand bridge operations over private local IPC or restricted SSH stdio."""
import os
import re
import socket
import subprocess
import sys
from pathlib import Path
import stat

from csl_bridge_store import BridgeError, MAX_WIRE, decode, encode, name, private_directory, validate

REMOTE_COMMAND = 'csl-bridge-receiver'


def local_call(home, request, timeout=25):
    home = private_directory(home)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        sock.connect(str(home / 'connector.sock'))
        sock.sendall((encode(request) + '\n').encode())
        with sock.makefile('rb') as stream:
            raw = stream.readline(MAX_WIRE + 1)
        if not raw or not raw.endswith(b'\n'):
            raise BridgeError('Bridge connection ended; outcome uncertain')
        response = decode(raw)
        if not isinstance(response, dict) or set(response) != {'ok', 'data'} or type(response['ok']) is not bool:
            raise BridgeError('Invalid bridge response; outcome uncertain')
        if not response['ok']:
            # Never repeat remote-provided error text in logs or terminal diagnostics.
            raise BridgeError('Bridge rejected operation; inspect receipt/state')
        return response['data']
    except (OSError, TimeoutError):
        raise BridgeError('Bridge unavailable; outcome uncertain; reconcile receipt before retry') from None
    finally:
        sock.close()


def ssh_argv(alias, config=None):
    if not isinstance(alias, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,63}', alias):
        raise BridgeError('Use a concrete trusted SSH config alias')
    selected = []
    if config is not None:
        path = Path(config).expanduser().absolute()
        try:
            info = path.lstat()
        except OSError:
            raise BridgeError('Explicit SSH configuration must exist privately') from None
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise BridgeError('Explicit SSH configuration must be an owned private regular file')
        selected = ['-F', str(path)]
    return ['ssh', *selected, '-T', '-oBatchMode=yes', '-oStrictHostKeyChecking=yes',
            '-oClearAllForwardings=yes', '-oPermitLocalCommand=no', '-oConnectTimeout=5',
            '--', alias, REMOTE_COMMAND]


def exchange(config, local_peer, request):
    validate(request)
    if config['transport'] == 'lab':
        # Explicit same-UID laboratory only. This is not SSH authentication evidence.
        return local_call(config['home'], {'local_op': '_incoming', 'trusted_peer': local_peer, 'request': request})
    if config['transport'] != 'ssh':
        raise BridgeError('Unknown bridge transport')
    try:
        result = subprocess.run(ssh_argv(config['alias'], config.get('ssh_config')), input=(encode(request) + '\n').encode(),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=25, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise BridgeError('SSH outcome uncertain; reconcile receipt before retry') from None
    if result.returncode or len(result.stdout) > MAX_WIRE:
        raise BridgeError('SSH outcome uncertain; reconcile receipt before retry')
    response = decode(result.stdout)
    if not isinstance(response, dict) or set(response) != {'ok', 'data'} or type(response['ok']) is not bool:
        raise BridgeError('Invalid SSH response; outcome uncertain')
    if not response['ok']:
        raise BridgeError('Remote bridge rejected operation; inspect receipt/state')
    return response['data']


def receiver_main():
    """Only a trusted forced-command environment chooses home and peer identity."""
    try:
        peer = name(os.environ.get('CSL_BRIDGE_PEER'))
        home = private_directory(os.environ.get('CSL_BRIDGE_HOME', ''))
        if not os.environ.get('CSL_BRIDGE_HOME'):
            raise BridgeError('Missing trusted bridge configuration')
        original = os.environ.get('SSH_ORIGINAL_COMMAND', '')
        if original not in ('', REMOTE_COMMAND):
            raise BridgeError('Only the fixed bridge receiver is allowed')
        request = validate(decode(sys.stdin.buffer.readline(MAX_WIRE + 1)))
        data = local_call(home, {'local_op': '_incoming', 'trusted_peer': peer, 'request': request})
        response = {'ok': True, 'data': data}
    except (BridgeError, OSError, ValueError):
        response = {'ok': False, 'data': {'error': 'Bridge receiver rejected request'}}
    print(encode(response))
    return 0 if response['ok'] else 1
