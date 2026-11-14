"""Local app backend. No model starts, native servers, login or network setup."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import shlex
import socket
import stat
import subprocess
import sys
import tempfile
import time
import uuid

RESOURCE = Path(__file__).resolve().parent
SOURCE = RESOURCE / 'bridge'
if not SOURCE.exists():
    SOURCE = RESOURCE.parents[1]
sys.path.insert(0, str(SOURCE))
from csl_bridge_store import Store, BridgeError, encode, decode, name, identifier
from csl_bridge_transport import local_call, exchange
from csl_bridge_rpc import Runtime, RuntimeUnavailable, RuntimeRejected


class AppError(ValueError):
    pass


def json_file(path, value):
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.csl-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


class Service:
    def __init__(self, state_root=None, bridge_home=None, codex_home=None):
        self.state = Path(state_root or Path.home() / 'Library/Application Support/CSLBridge')
        self.settings_path = self.state / 'connection.json'
        self.settings = json.loads(self.settings_path.read_text()) if self.settings_path.exists() else {}
        default = Path.home() / '.csl-bridge-app'
        self.home = Path(bridge_home or self.settings.get('bridge_home') or default)
        self.codex_home = Path(codex_home or self.settings.get('codex_home') or os.environ.get('CODEX_HOME', str(Path.home()/'.codex'))).expanduser()

    def endpoint(self):
        path = self.codex_home / 'app-server-control/app-server-control.sock'
        try:
            resolved = path.resolve(strict=True)
            info = resolved.stat()
        except OSError:
            raise AppError('No encontramos un runtime local. Abre tu conversación existente en Codex y vuelve a detectar.') from None
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise AppError('El endpoint no pertenece a este usuario o no es privado.')
        if sys.platform == 'darwin' and len(os.fsencode(str(resolved))) >= 104:
            raise AppError('La ruta del socket es demasiado larga para macOS. El dueño del runtime debe resolverla.')
        return resolved

    def registered(self):
        if not (self.home/'bridge.sqlite').exists():
            return {}
        store = Store(self.home)
        try:
            return store.agents()
        finally:
            store.close()

    def discover(self):
        path = self.endpoint()
        runtime = Runtime(path)
        try:
            loaded, cursor = [], None
            for _ in range(10):
                page = runtime.call('thread/loaded/list', {'limit':100, 'cursor':cursor})
                loaded.extend(page['data']); cursor = page.get('nextCursor')
                if not cursor: break
        finally:
            runtime.close()
        registered = self.registered()
        sessions = [{'id': value, 'label': ('Agente Mac conectado' if value in registered.values() else 'Sesión cargada')+' · '+value[-12:]} for value in loaded]
        selected = self.settings.get('thread_id') or next(iter(registered.values()), None)
        return {'sessions':sessions, 'selected':selected, 'socket':str(path), 'complete':not bool(cursor),
                'note':'Sólo conversaciones ya cargadas. No se lee historia ni se crea otra sesión.'}

    def owned(self):
        path = self.state/'owned-process.json'
        if not path.exists(): return None
        row = json.loads(path.read_text())
        if row.get('bridge_home') != str(self.home): return None
        try:
            result = subprocess.run(['ps','-p',str(row['pid']),'-o','args='],capture_output=True,text=True,timeout=3)
        except (OSError,subprocess.TimeoutExpired): return None
        return row if result.returncode==0 and str(self.home) in result.stdout and 'bridge' in result.stdout and 'run' in result.stdout else None

    def status(self, verify_peer=False):
        if verify_peer and self.registered():
            try:self.peer_check()
            except (AppError,BridgeError,OSError,ValueError):
                json_file(self.state/'peer-proof.json',{'ready':False,'phase':'peer_unreachable','observed_at':time.time(),
                    'note':'No hay respuesta autenticada del peer. Se conserva la tarea/ID; no se reenvía trabajo.'})
        peer={'ready':False,'phase':'not_verified','note':'Sin respuesta autenticada reciente del peer.'}
        proof=self.state/'peer-proof.json'
        if proof.exists():
            saved=json.loads(proof.read_text());age=time.time()-saved.get('observed_at',0)
            if 0<=age<=45:
                peer={**saved,'age_seconds':round(age,1)}
        try:
            data = local_call(self.home, {'local_op':'agents'}, timeout=3)
            agents = data['agents']; active = any(x.get('status')=='active' for x in agents)
            connected=bool(agents) and all(x.get('status')!='disconnected' for x in agents)
            ready=connected and peer['ready']
            return {'connected':ready,'runtime_ready':connected,'connector_running':True,'peer':peer,
                    'headline':('Listo · trabajando' if active else 'Listo · intercambio verificado') if ready else (('Sesión lista · enlace remoto no responde' if peer.get('phase')=='peer_unreachable' else 'Sesión disponible · peer sin verificar') if connected else 'Conector esperando al runtime'),
                    'agents':agents,'owned':bool(self.owned()),'adopted':not bool(self.owned()),
                    'note':peer.get('note','La conversación original sigue en su runtime.') if not ready else 'Respuesta autenticada reciente; la conversación original sigue en su runtime.'}
        except (BridgeError,OSError):
            return {'connected':False,'runtime_ready':False,'connector_running':False,'peer':peer,'headline':'Sin conexión local','agents':[], 'owned':False,
                    'note':'Selecciona una sesión existente para iniciar el conector.'}

    def configure(self, thread, coordinator='coordinator'):
        identifier(thread); name(coordinator)
        discovery = self.discover()
        if thread not in [x['id'] for x in discovery['sessions']]:
            raise AppError('La sesión ya no está cargada. Vuelve a detectar; no iniciaremos otra.')
        registered = self.registered()
        if registered and registered != {'worker':thread}:
            raise AppError('Este conector pertenece a otra sesión. Conservamos su estado; deténlo con su dueño antes de cambiarla.')
        if not registered:
            store=Store(self.home,create=True)
            try:
                with store.transaction() as db:
                    db.executemany('INSERT INTO config VALUES(?,?)',[('identity',encode('mac')),('runtime_socket',encode(discovery['socket']))])
                    db.execute('INSERT INTO agents VALUES(?,?)',('worker',thread))
                    db.execute('INSERT INTO peers VALUES(?,?)',(coordinator,encode({'transport':'receive-only','allow_agents':['worker'],'allow_ops':['followup','send_message','status','interrupt','receipt','watch','agents']})))
            finally:store.close()
        self.settings.update(thread_id=thread,bridge_home=str(self.home),codex_home=str(self.codex_home),coordinator=coordinator)
        json_file(self.settings_path,self.settings)
        return {'configured':True,'thread_id':thread,'note':'No se inició generación ni se cambió login.'}

    def start(self, thread=None, coordinator='coordinator'):
        if thread:self.configure(thread,coordinator)
        current=self.status()
        if current.get('runtime_ready',current['connected']):
            return {**current,'note':'Conector existente adoptado. No se inició otro proceso ni se cambió su código.'}
        if current.get('connector_running'):
            raise AppError('Ya hay un conector esperando al runtime. No iniciaremos otro: revisa la sesión local o deténlo desde su dueño.')
        if not self.registered():
            selected=self.settings.get('thread_id') or os.environ.get('CODEX_THREAD_ID')
            if not selected:
                choices=self.discover()['sessions']
                if len(choices)==1:selected=choices[0]['id']
            if not selected:raise AppError('Hay varias sesiones. Abre la app y elige la conversación existente.')
            self.configure(selected,coordinator)
        self.state.mkdir(parents=True,mode=0o700,exist_ok=True)
        log=(self.state/'connector.log').open('a');os.chmod(self.state/'connector.log',0o600)
        process=subprocess.Popen([sys.executable,'-I','-S','-B',str(SOURCE/'csl'),'bridge','--home',str(self.home),'run'],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
        json_file(self.state/'owned-process.json',{'pid':process.pid,'bridge_home':str(self.home)})
        end=time.monotonic()+8
        while time.monotonic()<end:
            current=self.status()
            if current.get('runtime_ready',current['connected']):return current
            if process.poll() is not None:break
            time.sleep(.1)
        raise AppError('El conector no pudo unirse. El runtime y tu conversación no se reiniciaron.')

    def stop(self):
        row=self.owned()
        if not row:raise AppError('El conector existente fue iniciado fuera de esta app; no lo detendremos automáticamente.')
        os.kill(row['pid'],signal.SIGTERM)
        return {'stopping':True,'note':'Se detiene sólo el conector de esta app, no Codex ni su conversación.'}

    def events(self, after=0):
        if type(after) is not int or after<0:raise AppError('Cursor inválido.')
        store=Store(self.home)
        try:
            rows=store.rows('SELECT seq,peer,body FROM outbound WHERE seq>? ORDER BY seq LIMIT 30',(after,))
            return {'events':[{'cursor':r['seq'],'peer':r['peer'],**decode(r['body'])} for r in rows]}
        finally:store.close()

    def peer_check(self, remote_agent='coordinator'):
        name(remote_agent)
        if not self.registered():raise AppError('Configura una sesión existente primero.')
        store=Store(self.home)
        try:
            peers=store.peers();identity=store.setting('identity')
        finally:store.close()
        selected=self.settings.get('coordinator') or next(iter(peers),None)
        config=peers.get(selected,{})
        if config.get('transport') in (None,'receive-only'):
            pending={'ready':False,'phase':'receive_only_not_verified','observed_at':time.time(),'note':'Este perfil recibe al coordinador. Su proceso vivo no acredita la ruta de vuelta; falta verificarla desde el otro equipo.'}
            json_file(self.state/'peer-proof.json',pending)
            return pending
        result=exchange(config,identity,{'version':1,'op':'status','id':str(uuid.uuid4()),'target':remote_agent})
        valid=result.get('agent')==remote_agent and result.get('status') in ('idle','active','tool-client') and isinstance(result.get('thread_id'),str)
        if not valid:raise AppError('La respuesta del peer no confirma el agente seleccionado; no se marca Listo.')
        proof={'ready':True,'phase':'authenticated_application_response','observed_at':time.time(),'peer':selected,
               'agent':remote_agent,'remote_status':result['status'],'note':'Respuesta de aplicación por el transporte configurado, no sólo PID o banner SSH.'}
        json_file(self.state/'peer-proof.json',proof)
        return proof

    def mcp_profile(self):
        return '[mcp_servers.csl_bridge]\ncommand = '+json.dumps(sys.executable)+'\nargs = '+json.dumps(['-I','-S','-B',str(SOURCE/'csl-bridge-mcp'),'--home',str(self.home),'--agent','worker'])+'\nrequired = true\nstartup_timeout_sec = 10\ntool_timeout_sec = 25\nenabled_tools = ["send_progress", "wait_agent", "list_agents", "agent_status", "operation_receipt"]\ndefault_tools_approval_mode = "writes"\n[mcp_servers.csl_bridge.tools.send_progress]\napproval_mode = "approve"\n'

    @staticmethod
    def replace_owned(text, replacement):
        import tomllib
        data=tomllib.loads(text);exists='csl_bridge' in data.get('mcp_servers',{})
        lines=text.splitlines(keepends=True);kept=[];owned=[];inside=False;found=False
        for line in lines:
            if line.lstrip().startswith('['):
                header=line.strip().split('#',1)[0].strip()
                inside=bool(re.fullmatch(r'\[mcp_servers\.csl_bridge(?:\.[A-Za-z0-9_-]+)*\]',header))
                if inside:found=True
            (owned if inside else kept).append(line)
        if exists and not found:raise AppError('La configuración existente usa un formato que requiere revisión local. No se cambió.')
        result=''.join(kept)+'\n'+replacement
        tomllib.loads(result)
        return result,''.join(owned)

    def mcp_plan(self):
        return {'profile':self.mcp_profile(),'tools':['Enviar avances de la tarea activa','Consultar estado y resultados'],
                'note':'Consentimiento local sólo para send_progress. No cambia aprobación global, modelo, login o permisos shell.'}

    def mcp_install(self):
        import tomllib
        thread=self.registered().get('worker')
        if not thread:raise AppError('Selecciona una sesión primero.')
        if thread not in [x['id'] for x in self.discover()['sessions']]:
            raise AppError('La sesión debe seguir cargada para activar herramientas. No se reabrirá implícitamente.')
        path=self.codex_home/'config.toml'
        if path.is_symlink():raise AppError('La configuración está redirigida; requiere revisión de su dueño.')
        old=path.read_text() if path.exists() else ''
        new,previous=self.replace_owned(old,self.mcp_profile())
        rollback={'path':str(path),'previous_owned_section':previous,'applied_profile':self.mcp_profile()}
        json_file(self.state/'mcp-rollback.json',rollback)
        fd,temp=tempfile.mkstemp(prefix='.csl-mcp-',dir=path.parent)
        try:
            os.fchmod(fd,path.stat().st_mode&0o777 if path.exists() else 0o600)
            with os.fdopen(fd,'w') as stream:stream.write(new)
            if (path.read_text() if path.exists() else '')!=old:raise AppError('Configuración cambió durante la operación; no se reemplazó.')
            os.replace(temp,path)
        finally:
            if os.path.exists(temp):os.unlink(temp)
        runtime=Runtime(self.endpoint())
        try:
            runtime.call('config/mcpServer/reload',{})
            runtime.call('thread/resume',{'threadId':thread,'excludeTurns':True})
        finally:runtime.close()
        return {'installed':True,'note':'Sólo sección csl_bridge actualizada. Rollback local de esa sección disponible.'}

    def mcp_rollback(self):
        path=self.state/'mcp-rollback.json'
        if not path.exists():raise AppError('No hay un cambio de herramientas de esta app para revertir.')
        backup=json.loads(path.read_text());config=Path(backup['path']);current=config.read_text()
        _,owned=self.replace_owned(current,'')
        if owned.strip()!=backup['applied_profile'].strip():
            raise AppError('La sección cambió después; no se sobrescribirá una configuración posterior.')
        restored,_=self.replace_owned(current,backup['previous_owned_section'])
        fd,temp=tempfile.mkstemp(prefix='.csl-rollback-',dir=config.parent)
        try:
            os.fchmod(fd,config.stat().st_mode&0o777)
            with os.fdopen(fd,'w') as stream:stream.write(restored)
            os.replace(temp,config)
        finally:
            if os.path.exists(temp):os.unlink(temp)
        runtime=Runtime(self.endpoint())
        try:runtime.call('config/mcpServer/reload',{})
        finally:runtime.close()
        return {'restored_owned_section_only':True}

    def connection_info(self):
        return {'thread_id':next(iter(self.registered().values()),None),'bridge_home':str(self.home),
                'receiver_command':shlex.join(['env','CSL_BRIDGE_HOME='+str(self.home),'CSL_BRIDGE_PEER='+self.settings.get('coordinator','coordinator'),sys.executable,'-I','-S','-B',str(SOURCE/'csl-bridge-receiver')]),
                'note':'Requiere transporte ya autorizado. No habilita SSH ni puertos ni un servicio de pairing.'}


def main():
    parser=argparse.ArgumentParser(description='CSL Bridge app: existing sessions only, no model/server/login creation.')
    parser.add_argument('action',choices=['discover','status','configure','connect','start','stop','events','peer-check','mcp-plan','mcp-install','mcp-rollback','connection-info','transport-run','transport-status','selftest'])
    parser.add_argument('--thread');parser.add_argument('--coordinator',default='coordinator');parser.add_argument('--after',type=int,default=0)
    parser.add_argument('--approve-communication',action='store_true',help='Explicit local consent to install only csl_bridge communication tools after connect.')
    parser.add_argument('--transport-profile',type=Path)
    parser.add_argument('--remote-agent',default='coordinator')
    parser.add_argument('--verify-peer',action='store_true',help='Explicitly refresh application-level peer response; never starts a model/task.')
    parser.add_argument('--state-root');parser.add_argument('--bridge-home');parser.add_argument('--codex-home')
    args=parser.parse_args();service=Service(args.state_root,args.bridge_home,args.codex_home)
    try:
        if args.action=='transport-run':
            if not args.transport_profile:raise AppError('Selecciona un perfil SSH ya autorizado; no se configura red automáticamente.')
            sys.path.insert(0,str(RESOURCE))
            from ssh_session import run_profile
            run_profile(args.transport_profile,service.state/'transport-status.json')
            result={'stopped':True}
        elif args.action=='transport-status':
            path=service.state/'transport-status.json'
            result=json.loads(path.read_text()) if path.exists() else {'phase':'not_configured','end_to_end_verified':False}
        elif args.action=='selftest':
            import fcntl,curses,sqlite3,platform
            result={'python':platform.python_version(),'architecture':platform.machine(),'prefix':sys.prefix,'stdlib_imports':True,'source':str(SOURCE),'model_calls':0}
        elif args.action=='configure':result=service.configure(args.thread,args.coordinator)
        elif args.action in ('connect','start'):
            result=service.start(args.thread,args.coordinator)
            if args.action=='connect':
                result['peer_verification']=service.peer_check(args.remote_agent)
                result.update(service.status())
            if args.approve_communication:result['communication_tools']=service.mcp_install()
        elif args.action=='peer-check':result=service.peer_check(args.remote_agent)
        elif args.action=='events':result=service.events(args.after)
        elif args.action=='status':result=service.status(args.verify_peer)
        else:result=getattr(service,args.action.replace('-','_'))()
        print(json.dumps({'ok':True,'data':result},ensure_ascii=False))
    except (AppError,BridgeError,RuntimeUnavailable,RuntimeRejected,OSError,ValueError,KeyError) as exc:
        message=str(exc) if isinstance(exc,(AppError,BridgeError)) else 'Operación local no disponible. No se inició ni reinició una sesión.'
        if isinstance(exc,(RuntimeUnavailable,RuntimeRejected)):
            message='El runtime no aceptó la consulta. Conservamos tu sesión: comprueba que sigue abierta y que permite el acceso local.'
        print(json.dumps({'ok':False,'error':message},ensure_ascii=False));return 1
    return 0
if __name__=='__main__':raise SystemExit(main())
