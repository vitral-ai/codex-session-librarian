"""Session-owned supervision of an ALREADY approved SSH profile; no services/auth setup."""
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import tempfile
import threading
import time


def write_state(path, state):
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='.transport-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as out:json.dump(state,out,indent=2)
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)


def ssh_arguments(profile):
    alias=profile.get('ssh_alias','')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,63}',alias):raise ValueError('Choose an existing concrete SSH alias')
    config=Path(profile['ssh_config']).expanduser().absolute()
    info=config.lstat()
    if not config.is_file() or config.is_symlink() or info.st_uid!=os.getuid() or info.st_mode&0o077:
        raise ValueError('Use a private owned SSH profile file')
    return ['/usr/bin/ssh','-F',str(config),'-N','-T','-oBatchMode=yes','-oIdentitiesOnly=yes',
            '-oStrictHostKeyChecking=yes','-oPermitLocalCommand=no','-oForwardAgent=no',
            '-oExitOnForwardFailure=yes','-oServerAliveInterval=15','-oServerAliveCountMax=3',
            '-oConnectTimeout=10','--',alias]


def local_banner():
    try:
        with socket.create_connection(('127.0.0.1',22),timeout=2) as connection:
            data=connection.recv(255)
        return 'ssh_banner_verified' if data.startswith(b'SSH-') else 'no_ssh_banner'
    except PermissionError:return 'local_probe_denied'
    except OSError:return 'local_sshd_unreachable'


class SSHSession:
    def __init__(self, profile, state_path, spawn=subprocess.Popen, clock=time.monotonic):
        self.argv=ssh_arguments(profile)
        self.state_path=Path(state_path)
        self.spawn=spawn;self.clock=clock;self.stop=threading.Event();self.child=None
        self.state={'supervisor_pid':os.getpid(),'ssh_pid':None,'phase':'not_started',
                    'end_to_end_verified':False,'credential_handling':'existing SSH config/agent or OS vault helper; no key bytes stored here'}

    def publish(self,phase,**values):
        self.state.update(values,phase=phase)
        write_state(self.state_path,self.state)

    def terminate_child(self):
        if self.child and self.child.poll() is None:
            self.child.terminate()
            try:self.child.wait(timeout=3)
            except subprocess.TimeoutExpired:self.child.kill();self.child.wait(timeout=3)

    def run(self):
        retry=1
        try:
            while not self.stop.is_set():
                self.publish('connecting',retry_seconds=retry,local_backend=local_banner())
                self.child=self.spawn(self.argv,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                started=self.clock();self.publish('ssh_running_e2e_unverified',ssh_pid=self.child.pid,
                    note='SSH process/forward success does not prove the forwarded Mac SSH banner or model conversation.')
                last_health=0
                while self.child.poll() is None and not self.stop.wait(1):
                    if self.clock()-last_health>=15:
                        self.publish('ssh_running_e2e_unverified',local_backend=local_banner())
                        last_health=self.clock()
                if self.stop.is_set():break
                code=self.child.returncode
                if self.clock()-started>=30:retry=1
                self.publish('retrying',ssh_pid=None,exit_code=code,retry_seconds=retry,
                    note='Check the approved profile/host/agent. No task or model request is replayed.')
                if self.stop.wait(retry):break
                retry=min(retry*2,30)
        finally:
            self.terminate_child();self.publish('stopped',ssh_pid=None)


def run_profile(profile_path,state_path):
    profile=json.loads(Path(profile_path).read_text())
    session=SSHSession(profile,state_path)
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:session.stop.set())
    session.run()
