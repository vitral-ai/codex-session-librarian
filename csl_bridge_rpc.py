"""Private Unix WebSocket client for an EXISTING Codex app-server, not a launcher."""
import base64
import hashlib
import json
import os
from pathlib import Path
import queue
import socket
import selectors
import subprocess
import struct
import threading
import time


class RuntimeUnavailable(RuntimeError):
    pass


class RuntimeRejected(RuntimeError):
    pass


class ProxyStream:
    """WebSocket bytes over the official proxy's pipes, not JSON-line framing."""
    def __init__(self, path, executable):
        self.process = subprocess.Popen([str(executable), 'app-server', 'proxy', '--sock', str(path)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        self.timeout = None

    def settimeout(self, value):
        self.timeout = value

    def connect(self, _):
        pass  # official proxy connects only to the explicitly selected existing socket

    def sendall(self, data):
        view = memoryview(data)
        while view:
            count = os.write(self.process.stdin.fileno(), view)
            if not count:
                raise OSError('Existing proxy transport closed')
            view = view[count:]

    def recv(self, size):
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            if not selector.select(self.timeout):
                raise TimeoutError('Existing proxy transport timed out')
        return os.read(self.process.stdout.fileno(), size)

    def shutdown(self, _):
        if self.process.stdin and not self.process.stdin.closed:
            self.process.stdin.close()
        if self.process.poll() is None:
            self.process.terminate()  # only this transport child, never the native server

    def close(self):
        self.shutdown(None)
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=2)
        if self.process.stdout:
            self.process.stdout.close()


class Runtime:
    def __init__(self, path, proxy_executable=None):
        self.path = Path(path).expanduser().resolve()
        self.events = queue.Queue()
        self.condition = threading.Condition()
        self.writes = threading.Lock()
        self.responses = {}
        self.number = 0
        self.connected = False
        self.socket = None
        try:
            self.socket = ProxyStream(self.path, proxy_executable) if proxy_executable else socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.socket.settimeout(5)
            self.socket.connect(str(self.path))
            key = base64.b64encode(os.urandom(16)).decode()
            self.socket.sendall(('GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n'
                'Connection: Upgrade\r\nSec-WebSocket-Key: ' + key +
                '\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
            header = b''
            while not header.endswith(b'\r\n\r\n'):
                if len(header) > 8192:
                    raise RuntimeUnavailable('Invalid runtime handshake')
                header += self.read_exact(1)
            expected = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest())
            if b'101 Switching Protocols' not in header or expected.lower() not in header.lower():
                raise RuntimeUnavailable('Runtime is not a compatible Unix WebSocket endpoint')
            self.socket.settimeout(None)
            self.connected = True
            self.reader = threading.Thread(target=self.read, daemon=True)
            self.reader.start()
            self.call('initialize', {'clientInfo': {'name': 'csl_bridge_experimental', 'version': '1'}})
            self.send({'method': 'initialized', 'params': {}})
        except (OSError, EOFError, RuntimeUnavailable, RuntimeRejected):
            self.close()
            raise RuntimeUnavailable('Existing runtime unavailable; bridge never starts a substitute') from None

    def read_exact(self, size):
        out = b''
        while len(out) < size:
            data = self.socket.recv(size - len(out))
            if not data:
                raise EOFError
            out += data
        return out

    def frame(self, data, opcode=1):
        length = len(data)
        head = bytes([128 | opcode, 128 | length]) if length < 126 else (
            bytes([128 | opcode, 254]) + struct.pack('!H', length) if length < 65536 else
            bytes([128 | opcode, 255]) + struct.pack('!Q', length))
        mask = os.urandom(4)
        with self.writes:
            self.socket.sendall(head + mask + bytes(c ^ mask[i % 4] for i, c in enumerate(data)))

    def send(self, data):
        self.frame(json.dumps(data, ensure_ascii=False, allow_nan=False).encode())

    def read(self):
        fragments, message_opcode = bytearray(), None
        try:
            while self.connected:
                first, second = self.read_exact(2)
                length = second & 127
                if length == 126:
                    length = struct.unpack('!H', self.read_exact(2))[0]
                elif length == 127:
                    length = struct.unpack('!Q', self.read_exact(8))[0]
                if second & 128 or length > 16000000:
                    raise RuntimeUnavailable('Invalid runtime frame')
                raw, opcode = self.read_exact(length), first & 15
                if opcode == 8:
                    break
                if opcode == 9:
                    self.frame(raw, 10)
                    continue
                if opcode == 10:
                    continue
                if opcode in (1, 2):
                    message_opcode = opcode
                    fragments = bytearray(raw)
                elif opcode == 0:
                    fragments.extend(raw)
                else:
                    raise RuntimeUnavailable('Invalid runtime frame')
                if len(fragments) > 16000000:
                    raise RuntimeUnavailable('Runtime message too large')
                if not first & 128:
                    continue
                if message_opcode != 1:
                    raise RuntimeUnavailable('Invalid runtime message')
                value = json.loads(fragments)
                if not isinstance(value, dict):
                    raise RuntimeUnavailable('Invalid runtime message')
                if 'id' in value and 'method' not in value:
                    with self.condition:
                        self.responses[value['id']] = value
                        self.condition.notify_all()
                elif 'method' in value:
                    # Server requests, especially approvals, are NEVER answered here.
                    self.events.put(value)
        except (OSError, EOFError, ValueError, RuntimeUnavailable):
            pass
        finally:
            with self.condition:
                self.connected = False
                self.condition.notify_all()
            self.events.put({'method': 'bridge/runtimeDisconnected', 'params': {}})

    def call(self, method, params, timeout=12):
        with self.condition:
            if not self.connected:
                raise RuntimeUnavailable('Runtime disconnected; delivery may be uncertain')
            self.number += 1
            identifier = 'csl-bridge-' + str(self.number)
            try:
                self.send({'id': identifier, 'method': method, 'params': params})
            except OSError:
                raise RuntimeUnavailable('Runtime disconnected; delivery may be uncertain') from None
            deadline = time.monotonic() + timeout
            while identifier not in self.responses:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self.connected:
                    raise RuntimeUnavailable('Runtime response lost; reconcile before retry')
                self.condition.wait(remaining)
            response = self.responses.pop(identifier)
        if 'error' in response:
            raise RuntimeRejected('Runtime rejected operation; policies were not changed')
        return response['result']

    def close(self):
        self.connected = False
        if self.socket is None:
            return
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.socket.close()
        if hasattr(self, 'reader') and threading.current_thread() != self.reader:
            self.reader.join(timeout=2)
