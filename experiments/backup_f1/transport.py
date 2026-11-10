"""Authorized memory-only GET broker for isolated cold B, never a product service."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import struct
import threading
import urllib.error
import urllib.parse
import urllib.request

from csl_backup_store import API_VERSION


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None


@contextmanager
def reader_broker(path, token, repo):
    path = Path(path)
    opener = urllib.request.build_opener(NoRedirect())
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(path))
    path.chmod(0o600)
    listener.listen(4)
    listener.settimeout(.2)
    stopped = threading.Event()
    counters = {'calls':0,'bytes':0,'write_attempts':0,'failures':0}
    def serve():
        while not stopped.is_set():
            try:
                connection,_=listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with connection:
                def read(size):
                    data=bytearray()
                    while len(data)<size:
                        chunk=connection.recv(size-len(data))
                        if not chunk:
                            raise RuntimeError('test request truncated')
                        data.extend(chunk)
                    return bytes(data)
                status,body,date=500,b'', 'Thu, 01 Jan 1970 00:00:00 GMT'
                try:
                    size=struct.unpack('!I',read(4))[0]
                    if size>65536:
                        raise ValueError('oversize test request')
                    args=json.loads(read(size))['arguments']
                    if '--method' not in args or args[args.index('--method')+1]!='GET':
                        counters['write_attempts']+=1
                        raise ValueError('cold reader is GET-only')
                    endpoint=next((v for v in args if v.startswith('repos/')),None)
                    prefix='repos/'+repo
                    if endpoint!=prefix and not (isinstance(endpoint,str) and endpoint.startswith(prefix+'/')):
                        raise ValueError('outside authorized synthetic repo')
                    binary='Accept: application/octet-stream' in args
                    request=urllib.request.Request('https://api.github.com/'+endpoint,headers={
                        'Authorization':'Bearer '+token,'X-GitHub-Api-Version':API_VERSION,
                        'Accept':'application/octet-stream' if binary else 'application/vnd.github+json',
                        'User-Agent':'csl-synthetic-cold-b'})
                    counters['calls']+=1
                    try:
                        response=opener.open(request,timeout=30)
                    except urllib.error.HTTPError as error:
                        if binary and error.code==302:
                            url=error.headers.get('Location','')
                            parsed=urllib.parse.urlparse(url)
                            if parsed.scheme!='https' or parsed.hostname not in ('release-assets.githubusercontent.com','objects.githubusercontent.com'):
                                raise ValueError('unexpected redirect') from None
                            response=opener.open(urllib.request.Request(url),timeout=30)
                        else:
                            status=error.code
                            response=None
                    if response:
                        with response:
                            status=response.status
                            date=response.headers.get('Date',date)
                            body=response.read(50*1024**2+1)
                        if len(body)>50*1024**2:
                            raise ValueError('test response exceeded laboratory budget')
                    counters['bytes']+=len(body)
                except Exception:
                    counters['failures']+=1
                    status,body=500,b''
                metadata=json.dumps({'status':status,'bytes':len(body),'date':date}).encode()
                connection.sendall(struct.pack('!I',len(metadata))+metadata+body)
    thread=threading.Thread(target=serve,daemon=True)
    thread.start()
    try:
        yield counters
    finally:
        stopped.set()
        listener.close()
        thread.join(timeout=35)
        path.unlink(missing_ok=True)
