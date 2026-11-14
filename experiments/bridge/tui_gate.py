"""Optional actual terminal UI check against synthetic native engine, never inference."""
from pathlib import Path
import fcntl
import json
import os
import re
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from connector_gate import Native, eventually
from runtime_gate import Plan, text_input

root = Path(tempfile.mkdtemp(prefix='csl-bridge-tui-gate-'))
native = Native(root, 'native')
master, slave = os.openpty()
fcntl.ioctl(slave, 0x5414, struct.pack('HHHH', 40, 140, 0, 0))
env = {**native.env, 'TERM': 'xterm-256color', 'COLORTERM': 'truecolor'}
process = subprocess.Popen(['codex', '--remote', 'unix://' + str(native.sock), '--no-alt-screen',
    'resume', '--all', native.sid], env=env, cwd=native.root / 'project',
    stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
os.close(slave)
capture = bytearray()
def reader():
    try:
        while True:
            chunk = os.read(master, 65536)
            if not chunk:
                return
            if len(capture) < 2000000:
                capture.extend(chunk)
            if b'\x1b[6n' in chunk:
                os.write(master, b'\x1b[1;1R')
    except OSError:
        pass
thread = threading.Thread(target=reader, daemon=True)
thread.start()
report = {'root': str(root), 'real_inference': False, 'real_terminal_UI': True}
print('LAB_ROOT', root, flush=True)
try:
    eventually(lambda: b'IDENTITY-SEED' in capture or process.poll() is not None, timeout=12)
    assert process.poll() is None, capture.decode(errors='replace')[-2000:]
    native.backend.add(Plan(text='TUI-REMOTE-FINAL-719'))
    start = len(native.ui.messages)
    native.ui.call('turn/start', {'threadId': native.sid, 'input': text_input('TUI-MESSAGE-929')})
    native.ui.event('turn/completed', after=start)
    eventually(lambda: b'TUI-REMOTE-FINAL-719' in capture, timeout=12)
    report['receives_remote_turn_and_final_in_same_conversation'] = True
    native.backend.add(Plan(kind='approval'), Plan(text='AFTER-TUI-APPROVAL-DECLINE'))
    start = len(native.ui.messages)
    native.ui.call('turn/start', {'threadId': native.sid, 'input': text_input('TUI-APPROVAL-449')})
    approval = native.ui.event('item/commandExecution/requestApproval', after=start)
    eventually(lambda: b'SYNTHETIC_APPROVAL' in capture and b'Would you like' in capture and b'Yes, proceed' in capture, timeout=12)
    native.ui.send({'id': approval['id'], 'result': {'decision': 'decline'}})
    native.ui.event('turn/completed', after=start)
    report['approval_visible_in_actual_TUI_declined_by_local_protocol_client'] = True
    report['status'] = 'PASS_SYNTHETIC_BACKEND_ACTUAL_TUI'
except Exception as exc:
    report['status'], report['error'] = 'FAIL', repr(exc)
finally:
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=4)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)
    os.close(master)
    thread.join(timeout=2)
    (root / 'terminal.log').write_bytes(capture)
    native.close()
    (root / 'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2), flush=True)
raise SystemExit(0 if report['status'].startswith('PASS') else 1)
