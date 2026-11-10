#!/usr/bin/env python3
"""Test-only GET transport over a private Unix socket; no stored credential."""

import json
import os
import socket
import struct
import sys


def main():
    # The selected executable is explicit in the tested CSL command. This shim
    # does not inspect gh config, load a token, mutate a repo or initiate login.
    arguments = sys.argv[1:]
    if not arguments or arguments[0] != 'api':
        raise SystemExit(2)
    request = json.dumps({'arguments':arguments}).encode()
    with socket.socket(socket.AF_UNIX) as stream:
        stream.connect(os.environ['CSL_BACKUP_TEST_SOCKET'])
        stream.sendall(struct.pack('!I',len(request))+request)
        def read(size):
            data = bytearray()
            while len(data)<size:
                chunk = stream.recv(min(1024**2,size-len(data)))
                if not chunk:
                    raise RuntimeError('test transport closed')
                data.extend(chunk)
            return bytes(data)
        metadata = json.loads(read(struct.unpack('!I',read(4))[0]))
        body = read(metadata['bytes'])
    if metadata['status']>=400:
        if '--include' in arguments:
            sys.stdout.buffer.write(('HTTP/2.0 '+str(metadata['status'])+' Error\n\n').encode()+b'{}')
        raise SystemExit(1)
    if '--include' in arguments:
        header = 'HTTP/2.0 200 OK\nDate: '+metadata['date']+'\n\n'
        sys.stdout.buffer.write(header.encode())
    sys.stdout.buffer.write(body)


if __name__=='__main__':
    main()
