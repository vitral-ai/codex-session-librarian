# CSL Backup F1 / E1 manual: entrega tecnica

Fecha: 2026-11-10. Rama `feat/backup-f1-manual`.
Base F0: `32322850b7b341048448fd6d03cfacd82b3babd2`, sobre oficial v0.1.1.
Estado: E1 manual revisada favorablemente por Manunruks; condiciones de fuente y
regresion final cumplidas. Codigo probado: `3547d7b3cf3c0176896957197c10e2caf44f456a`.
El commit de cierre posterior solo agrega informe/utility de hashes. No es release,
activacion real o certificacion headless. F2 autorizada, sin pedir otro inicio.

## Alcance implementado

CLI `backup init/run/status/list/discover/restore/verify`, solo Linux/Codex.
Snapshots manuales completos nativos/portables cifrados, archivo/agent opt-in,
captura coherente, contenedores ADR002, control con lease/fencing, intenciones
durables, verificacion integral antes de instalar y recibos por version logica.
No incremental/resume distribuido/multisource, timer, rotacion avanzada ni GC aun.

`csl-backup` usa config propia, no team connect. Historial no implica autorizacion;
restore no abre modelos, ejecuta tools historicas ni adopta config/timer del origen.
No se leyeron historiales reales, cambio auth/permisos o instalaron paquetes globales.

## Custodia real probada

**Manual stdin / memoria / FD**, no secret-tool positivo ni headless. age v1.3.2
aislado del coordinador; dos recipients sinteticos. B recibe solo privada externa
y transporte GitHub propio GET-only en memoria. No recibe privada operacional,
auth files, journal, config, recibos ni catalogos locales de A.

El helper privado valida identidad Manunruks. El transporte de B es un Unix socket
temporal privado de laboratorio, no servicio del producto ni archivo con token.
No se imprimen privadas ni se guardan en evidencia. Los pares sinteticos son
descartables: no se promete descifrar esos assets despues de finalizar el ensayo.

El producto soporta referencia keyring y bloquea si falta o falla; solo negativas
de ese provider estan probadas. Su disponibilidad operacional desatendida queda F4.

## Evidencia por requisito

Directorio separado: `.local/backup-evidence/f1/` (no se publica en Git).

| Requisito | Evidencia | Resultado/limite |
| --- | --- | --- |
| F1-T01 perfiles/visibilidad | `live-03/{run,cold,native}.json`; `portable/` | Native y portable de seis fixtures cada uno; archivo sigue archivado, SubAgent estructurado no aparece en default picker; reader acepta seis en cada perfil. |
| F1-T02 corte/origen | `source-hashes.json`; `test_backup_core` | UTF-8/whitespace exactos, cola incompleta diferida, ultima fila JSON completa sin newline preservada; sin identidad/malformado falla. Pruebas de escala/early budget adicionales pasan a F2. |
| F1-T03 pendientes/compaction | fixtures live y pruebas engine/core | Se preservan llamadas sin fabricar resultado y opaco nativo; portable declara omisiones. No implica continuidad del modelo. |
| F1-T04 politicas | `live-03/portable/policy.json` y tests | stop bloquea antes de writes; scrub quita marcador ficticio y deja origen intacto. Native+scrub y retain sin aceptacion explicita rechazados. |
| F1-T05 B externo | `live-03/cold.json` | Native: HOME/CODEX_HOME vacios, A oculto, source seleccionado desde discover remoto, clave externa y GET propio; sin estado A. |
| F1-T06 negativos crypto | `test_backup_crypto`, live wrong-key | Fallos/timeouts/destino existente/alias/race preservan centinelas. Clave incorrecta exit3 no altera copias; tamper/wrong-key age real se probaron tambien en F0. |
| F1-T07 privacidad | cifrado objeto+catalogo, envelopes opacos, custodia memoria | Sin privada/configauth en assets/control. Repo privado e ID se revalidan antes de mutaciones; no promesa de carrera ACL imposible de eliminar. |
| F1-T08 ZIP | `test_backup_core` | file_size/ratio/total/tipos/path/symlink/duplicados revisados ANTES de leer; lecturas acotadas. |
| F1-T09 crashes | `test_backup_engine` | Intencion antes del archivo, reconciliacion tras publicar y antes del recibo; segundos miembros fallidos no generan falso evento de contenedor entero restaurado. |
| F1-T10 idempotencia/conflicto | live repeat y tests | UUIDs repetidos iguales; copia modificada/cwd distinto conflicto; --new es duplicacion explicita. Init igual reutiliza IDs, cambio material conflicto. |
| F1-T11 fuente/lease/destino | negativos CLI/engine/store | --source diferente bloquea; segundo source F1 rechazado; writer obsoleto no reacquire/commit. Private->public/ID sustituido/write revocado producen cero POST en mocks. |
| F1-T12 hashes/native | `live-03/source-hashes.json`, ambos `native.json` | Origen intacto antes/despues de cada ensayo; read/picker real Codex0.167.0, sin red/generacion en probe. No recall comercial. |

### Distincion de los entornos B

`live-03` nativo usa un B inicialmente vacio. Portable se restaura DESPUES en ese
MISMO B, que ya contiene seis copias nativas; termina con doce instalaciones.
Sigue sin config/journal de A, pero **no es un segundo HOME frio independiente**.
No se describe como dos recuperaciones frias. Las visibilidades de las seis
copias portables se verificaron aparte y no se infieren del perfil nativo.

La evolucion posterior del harness agrega metadata-only y un conjunto portable
representable separado: ese nuevo escenario NO se atribuye a live-03. Vacio/
metadata-only nativo esta cubierto en tests locales con preservacion exacta y
cuarentena explicita, no mensajes inventados. Portable declara no representable
si el exportador no lo soporta, sin sustituir perfil silenciosamente.

## Fallos encontrados y corregidos

- Age, capture y download podian sobrescribir/eliminar destinos preexistentes en
  ciertas rutas. Ahora todos escriben staging propio y publican mediante link
  exclusivo; no se limpia target ajeno. Regresiones source==target, hardlink,
  symlink, fallo, timeout y carrera. Reproducciones solo sinteticas.
- `live-02` subio un checkpoint y restore termino, pero --json quedo contaminado
  por progreso del indice nativo. No se conto como E1. Progreso ahora va a stderr;
  test local y CLI real `live-03` comprueban un unico JSON.
- Fencing multipack rojo->verde: A pausado tras primer pack, B adquiere nuevo
  epoch y termina; A no puede reacquire en una renovacion ni sobrescribir puntero.
  Acquire inicial es explicito, renovacion/commit exigen owner+epoch+vigencia;
  catalogo/puntero ligan lease_epoch. No se observo perdida real en live monowriter.
- Lector rechazando unknown profiles/version booleana/cobertura incoherente y
  native source_sha distinto de member_sha, incluso con version_key recalculada.
- Fallos preparatorios (stdin/age/keyring/transporte/config) se registran ANTES
  de resolver dependencias. Cached no oculta el fallo tras passed antiguo. Si
  no puede persistirse, se bloquea/advierte explicitamente el estado obsoleto.
- Eventos restored ligan miembro/version/UUID/hash instalado/target binding;
  verificar un miembro no declara restaurado todo su contenedor.

No se atribuyen estos defectos de modulos nuevos al CSL publicado anterior.
No se borraron evidencias de fallo ni recursos del proveedor para ocultarlos.

## Fuente, versiones y regresiones

La evidencia live se ejecuto sobre worktree en desarrollo, anterior al freeze:
no se presenta como ejecucion de un commit final que aun no existia. Se conservan
base, versiones, datos y resultados; los guards posteriores se prueban con sus
regresiones y el candidato congelado. Exporter version2 distingue el candidato de
los primeros ensayos; el lector admite el perfil compatible antiguo, no lo reutiliza
como si hubiese sido producido con las reglas nuevas.

- `live-01`: motor/CLI cold basico, seis sesiones, sin chequeo de picker completo.
- `live-02`: fallo de stdout descrito arriba; nunca se declara aprobado.
- `live-03`: native+portable, picker/reader, repeat, wrong key, cached failure y scrub.
- `regressions-01`:323 tests opt-in, sin skips/fallos,214.792s, estado intermedio.
- Candidato final:59 tests backup focales, incluyendo19 del laboratorio F0.
- `regressions-final/result.json` + `tests.log`:327 pruebas, sin omisiones ni fallos,
  193.511s, sobre el SHA fijo3547d7b. Todos los opt-ins media/native/migration
  habilitados, sandbox media requerido; sin inferencia comercial.
- Sealed manifest enlaza codigo final, spec y artefactos. No tags ni release nueva.

Fingerprint incluye version real CSL, exporter version y reglas secretas. Cambios
de semantica requieren bump aun sin release; no usa Git en runtime. Cold reader
no exige que la version productora sea identica a la actual si el perfil/esquema
siguen siendo compatibles. Documentado en `BACKUP.md`.

## Destinos y presupuesto observado

F0: `manunruks/csl-backup-validation-20261109`, id1452103289, no modificado por F1.
F1: `manunruks/csl-backup-e2e-20261109`, id1452127356, privado/main; control estandar
`csl-backup-control-v1`. No se reparo/sobrescribio el control experimental de F0.

Inventario acumulado observado al cerrar live-03: **13 releases,22 assets,114018
bytes** en ambos repositorios. Techo conjunto F0-F5 autorizado:40/80/50MiB, no por
repositorio. IDs/tamanos exactos en `live-03/ledger.json`; no DELETE/settings/scopes.
Validaciones futuras reobservan antes de crear; no se reintenta POST ciegamente.

Revalidar privacidad/ID/write agrega GET antes de mutaciones, y el wrapper de
identidad agrega su propio GET por invocacion. Contabilizar ambos en F2. Aun
existe una carrera inevitable entre GET y POST si un administrador cambia ACL;
el cifrado protege contenido, no garantiza disponibilidad o WORM.

## Gate y siguientes controles

Manunruks reviso favorablemente **E1 manual** y autoriza F2 tras fuente final,
regresion y seal. No autoriza uso de datos reales, headless/timer personal,
eliminacion remota, publicacion ni piloto humano intermedio.

F2 debe agregar reutilizacion por version/cipher/profile, evidence levels con
fechas honestas/full-30d, resume, multiples sources y parciales. Mantener repro
fencing. Agregar early budget ANTES de clonar mas bytes y mediciones locales de
memoria/I/O grandes; restore ya valida streaming y conserva rutas/flags, no todos
los registros en RAM. Clasificar agentes excluidos antes de copiar es optimizacion
pendiente que no debe perder coherencia de metadata repetida/cambiante.

Formato F1 usa todos los miembros de cada contenedor como conjunto restaurable.
F2 necesita referencias explicitas a versiones logicas vigentes: un contenedor
viejo puede conservar un miembro vigente y otro reemplazado. No restaurar ambos
como heads por accidente; versionar ese cambio y mantener lectura F1 compatible.

Guia del operador: [BACKUP.md](BACKUP.md). Contrato de contenedores:
[ADR002](BACKUP_ADR_002_CONTAINERS.md). No continuidad universal, recuperación sin
claves, secreto universalmente detectado, metadata-native equivalente a recall,
ni piloto humano completado.
