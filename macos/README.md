# CSL Bridge — app privada para Mac

Candidato revisable, no release pública ni pairing nuevo. Dos vistas: **Sesión y
conexión** y **Actividad**. Conserva la sesión/login originales y adopta un conector
existente sin reemplazarlo. Detecta sólo conversaciones ya cargadas; no lee historia
para descubrirlas ni crea otro agente. Iniciar/parar afecta sólo al conector propio.

La `.app` incluye Python3.12 privado y la biblioteca CSL: no necesita Python de Apple,
uv, PATH de usuario, Homebrew ni una instalación global. La primera compilación DEV
necesita macOS/CLT y una distribución Python standalone existente; el builder la COPIA.
La prueba en home vacío y el análisis de linkage deben confirmar que no depende de
la instalación original. ARM64 y versión de macOS se acreditan por build, no por UI.

Abrir la app y seleccionar una sesión existente. Para CLI, un comando:

```sh
'/ruta/CSL Bridge.app/Contents/MacOS/CSLBridge' connect
```

Usa la sesión guardada, CODEX_THREAD_ID actual o la única cargada; si hay ambigüedad
pide selección. `status`, `stop`, `events`, `connection-info` también están disponibles.
`connect --approve-communication` concede explícitamente sólo herramientas de avances
y consultas; la interfaz ofrece el mismo consentimiento con un botón. `mcp-rollback`
restaura sólo la sección propia respaldada localmente, sin copiar config completa.
No modifica el modelo, aprobación global, permisos shell o credenciales de Codex.

Reutiliza el transporte entre equipos ya autorizado. No habilita SSH, abre puertos,
crea relay ni implementa pairing propio automático. Esa parte del onboarding aún no
está resuelta. Al cerrar la GUI para el conector que ella inició; no para uno adoptado.
La CLI `connect` mantiene un proceso de sesión hasta `stop`; no instala autostart.

Build nativo privado, en un directorio NUEVO:

```sh
python3.12 macos/build_app.py --source /fuente/verificada --source-sha SHA \
  --runtime-root /python-standalone-3.12 --output /directorio/nuevo
```

Produce `.app`, ZIP, manifiesto y SHA256. Firma ad-hoc local; sin Developer ID ni
notarización. No desactivar Gatekeeper para distribuirlo. Las capturas offscreen
usan controles AppKit reales; no sustituyen pruebas de interacción/WindowServer.

El builder no copia el worktree: crea snapshot `git archive` del commit exacto,
tracked-only y allowlist de runtime. Un export sin Git requiere `SOURCE-MANIFEST.json`
con hashes verificados y `--source-manifest-sha256` fijado por el exportador; una etiqueta SHA no basta. No incluye tests, .local/.agents,
skills, planes, evidencia ni credenciales. La distribución Python excluye site-packages,
caches y directorios privados; no se copia el home. El archivo manifiesto acredita los
bytes incluidos y se verifica en el build; canaries sintéticos prueban exclusiones.

Estados separados: runtime local, conector y peer. PID vivo o banner SSH no marcan
Listo: se exige una respuesta de aplicación del agente remoto por el transporte
preautorizado. Un perfil sólo receptor no puede acreditar por sí solo la ruta de vuelta
ni una conversación WAN; se muestra pendiente. La prueba de modelo completa se registra
aparte. Tras Conectar, la GUI renueva verificaciones sin inferencia; perder respuesta
quita Readiness y conserva tareas/IDs.

Supervisión opcional de un perfil SSH YA autorizado: `transport-run --transport-profile
/perfil/privado.json` y `transport-status`. Perfil mínimo: `ssh_alias` y `ssh_config` de
archivo propio0600. Ese SSH config contiene hostpin, forwards y selección de identidad
pública/agent ya autorizados; no se pegan claves privadas/tokens. `transport-run` permanece
en primer plano hasta SIGINT/SIGTERM, supervisa keepalive/backoff1..30s, nunca reenvía
encargos y mata sólo su hijo SSH al salir. No instala un servicio global ni puede impedir
suspensión física del Mac. Un proceso SSH en ejecución sigue como E2E NO verificado
hasta comprobar el otro extremo; no configurar ni lanzar este modo durante el build.
