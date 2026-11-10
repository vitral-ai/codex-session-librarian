# CSL Backup: entrega F0 para revision

Fecha local: 2026-11-09; evidencia remota tambien fechada 2026-11-10 UTC.
Estado: experimentos locales/remotos ejecutados; **gate pendiente de revision**.
No se inicio F1 ni se entrega aun un comando de backup utilizable.

## Encargo y aislamiento

AUTH-019, orden `IMPLEMENTACION-Y-CONTROL.md` y aclaraciones 0.2.1 recibidas de
Manunruks. Alcance completo F0-F5 y preparacion F6 autorizado; este corte entrega
F0 antes de continuar. Las portadas historicas de la especificacion no revocan
esa autorizacion posterior. No se pide de nuevo permiso de inicio.

- Base oficial v0.1.1: `318332bfe73c5b585651b39b9bd258927e65df22`.
- Checkout: `/home/lmrc/Documents/projects/csl-backup-implementation`.
- Rama: `feat/backup-f0-viability`.
- Implementacion experimental: `experiments/backup_f0/`; pruebas `tests/test_backup_f0.py`.
- Evidencia separada y privada: `.local/backup-evidence/f0/` (excluida de Git).
- Sin incorporar la rama secret-review, modificar otros worktrees, instalar
  dependencias globales, tocar historiales reales, iniciar modelos o activar timers.
- Git local configurado por el coordinador como Manu Ruks/dev3@bizglo.com, sin
  helper heredado. No se hizo push del codigo, cambio de login o release de CSL.

## Evidencia y resultados

| Requisito | Evidencia | Resultado y alcance |
| --- | --- | --- |
| F0-T01 contratos | `local-06/schemas`, `vectors.json`; pruebas F0 | Diez esquemas candidatos, serializacion y UUID namespace fijos, vector dorado, tipos/versiones/cobertura/limites rechazados. |
| F0-T02 descubrimiento frio | `remote-01`, `cold-01/cold-result.json` | Listado real paginado; B con HOME/CODEX_HOME nuevos y A oculto descarga catalogo y objeto, verifica hash, sin journal ni archivos de A. Rename y repo sustituido solo probados localmente. |
| F0-T03 control | pruebas Git locales y `remote-01/remote-requests.json` | CAS/bootstrap, renewal/expiry y A pausado/B nuevo epoch/A reanuda locales; GitHub rechaza avance FF obsoleto y conserva puntero de B. Tiempo/renovacion del lease en API real no demostrado. |
| F0-T04 reintentos/fallos | pruebas F0 y `remote-01` | POST aceptado/respuesta ignorada se recupera por tag estable real; conflicto/asset incompleto/crash antes de catalogo en backend local. Binding interior cifrado pendiente de F1. |
| F0-T05 API/politicas | `remote-01/remote-requests.json` e inventario | REST 2026-03-10, `make_latest: "false"` preserva sentinel. No se modificaron politicas de inmutabilidad. |
| F0-T06 escala | `local-06/scale*.json`, `catalog-measurements.json`, `container-alternative.json` | 729 escenarios; formulas/estimaciones separadas de tiempos locales. Contenedores cuantificados y prototipados por resolucion tecnica posterior. |
| F0-T07 perfiles | `local-06/profiles.json` | 9 capturas exactas; 27 cargas thread/read aceptadas; limites visibles de herramientas y visibilidad detallados abajo. |
| F0-T08 cifrado | `local-06/age.json`; `encrypted-01` | age1.3.2, clave erronea/tamper rechazados; pack+catalogo cifrados y dos miembros verificados en B con solo clave externa. **No E1 de producto**. |
| F0-T09 errores | pruebas F0, contrato/adaptador experimental | 403/404 ambiguos y 429 clasificados, sin login/retry infinito. No se revocaron permisos ni provoco rate limiting remoto. |

Los estados mock/local/remoto no se equiparan. El gate no queda cerrado por esta
tabla; requiere revisar evidencia y resolver el formato/backend/perfiles.

## Preservacion, carga y visibilidad: resultados distintos

Los nueve casos sinteticos cubren texto no ASCII y JSON no canonico, herramientas,
errores, llamada pendiente, archivada, agente, contenido opaco, compaction y
dependencia externa. Hashes/originales permanecen intactos.

- Captura nativa del prefijo completo: 9/9 byte-exactas; cola parcial diferida.
- Export raw actual: 9/9 distintos del origen por parseo/reserializacion, aunque
  conserva los registros soportados. No se propone como captura native-age-v1.
- Portable elimina contenido opaco en los casos opaque/compaction; perdidas
  registradas. No prueba recuperar estado cifrado real entre cuentas.
- Codex0.167.0 acepta 27/27 archivos en `thread/read` aislado, sin red ni modelos.
  El mensaje final es visible. Marcadores de resultados tools/error faltan en seis
  proyecciones visibles, aun cuando estan en los bytes. No declarar fidelidad
  visible total ni perdida del respaldo por este resultado.
- Este reader no necesita sidecars para aceptar esos fixtures. Esto **no** demuestra
  ausencia universal de dependencias: visibilidad archivada/agente e instalacion
  con UUID nuevo se validaran en F1, con metadatos allowlisted por version.
- El corte de bytes sintetico no sustituye las pruebas F1 de append/rewrite/truncate
  e identidad de archivo durante escritura concurrente.

`local-01` se conserva como fallo del harness: rutas relativas de bwrap en filesystem
read-only. Se corrigieron a absolutas, sin relajar sandbox; `local-02` y posteriores
repiten el experimento. `local-05` agrega aserciones de marcadores visibles y es la
referencia vigente de perfiles.

`local-06` repite esos probes con los diez esquemas ajustados. `local-07` actualiza
solo evidencia de esquemas/escala/packing con1MiB de margen estimado de empaquetado;
sus probes nativos no se ejecutan. Para carga/visibilidad usar `local-06`.

## Destino remoto y autorizacion efectiva

Destino autorizado: `manunruks/csl-backup-validation-20261109`, repo_id1452103289,
privado. Escrituras exclusivamente mediante `gh-manunruks`. El reader B usa
credencial propia validada por el helper privado del coordinador, solo en memoria/
stdin; no se copio auth y no se registro material secreto. No hubo DELETE.

Inventario inicial: **3 releases, 2 assets, 310 bytes**, frente al maximo autorizado
de5/10/10MiB. IDs exactos en `remote-01/remote-result.json`:

| Release | ID | Asset |
| --- | --- | --- |
| Sentinel de prueba | 439870134 | Ninguno |
| Objeto sintetico | 439870156 | 729784696, 53 bytes |
| Catalogo sintetico | 439870185 | 729784825, 257 bytes |

El sentinel establece deliberadamente latest en el repo de laboratorio; los otros
dos no lo desplazan. Son releases sinteticas, no publicaciones de CSL. Tambien
quedaron commits/branch de control del experimento. No se limpiaron recursos.

Prototipo posterior autorizado por Manunruks: pack+catalogo cifrados de dos miembros.
Inventario FINAL: **5 releases, 6 assets, 6787 bytes**. Releases adicionales439877985
(container.age4313B, descriptor207B) y439878034(catalog.age1750B, descriptor207B).
IDs/hash completos en `encrypted-01/encrypted-result.json`. Presupuesto de releases
agotado: no volver a crear recursos ni borrar los existentes por esta entrega.

`encrypted-01/cold-B/cold-result.json`: B descarga el contenedor una sola vez,
descifra catalogo+pack con clave externa y verifica dos miembros/bindings interiores.
No recibe privada operacional ni estado de A. Amplificacion observada4313/1053=
4.096x respecto al miembro menor, incluidos ZIP/manifiesto/age. No mide capacidad
real de64MiB ni carga de sesiones instaladas. E1 operacional sigue pendiente.

Las claves de estos ensayos eran sinteticas y descartables: no se conservaron
privadas para volver a descifrar posteriormente esos assets. La evidencia registra
la ejecucion realizada, no promete que otro ejecutor pueda recuperar esas claves.
E1 debe resolver custodia externa persistente antes de respaldos utilizables.

Cuota primaria observada:5000/h; version API seleccionada2026-03-10. El wrapper
verifica identidad por invocacion, por lo que agrega un GET al coste de subprocess.
Las cuotas secundarias generales y limitaciones de API estan referenciadas en el
[README del laboratorio](../experiments/backup_f0/README.md). No equivalen a SLA
de durabilidad o rendimiento ni se midieron mediante carga agresiva.

Consultas iniciales al codigo oficial se hicieron con gh por defecto antes de la
precision posterior de identidad. Fueron publicas/solo lectura. Desde esa precision,
todo acceso GitHub de F0 usa identidad Manunruks; no hubo writes como warevista.

## Escala y alternativa que requiere decision

El modelo original reenvia la conversacion completa, no deltas. En un bootstrap de
1000 sesiones de1MiB:1001 releases/2002 assets y al menos3015 escrituras estimadas,
antes de intents individuales y renovaciones. No encaja con una corrida de1h bajo
la referencia general de500 content writes/h. Un promedio anual bajo no lo resuelve.

Para1000 sesiones,90dias,10% cambios,6h,1% crecimiento diario:36900 versiones,
37260 releases, unos62.46GB de subida modelada y373 paginas de listado sin control.
Un puntero de control valido evitaria ese scan en el caso normal: estimacion de
seis llamadas, todavia no benchmark. No declarar latencia real a partir del modelo.

La medicion local de esquemas arrojo para1000 entradas921512 bytes y3.82MB pico
Python; para10000 entradas9.21MB y36.74MB pico. Son vectores minimos: el modelo de
2048B/entrada es una sensibilidad mas conservadora, no un limite empirico universal.

Alternativa offline, **sin cambio de contrato implementado**: empaquetar miembros
logicos en contenedores cifrados de hasta64MiB. No basta agrupar releases manteniendo
un asset por conversacion: aqui disminuyen tambien assets y transferencias.

| Escenario1000x1MiB | Diseño por version | Contenedores64MiB |
| --- | --- | --- |
| Bootstrap | 1000 objetos +1catalogo | 16contenedores +1catalogo |
| Assets | 2002 | 34 |
| Escrituras minimas con intencion por unidad fisica | 7015 | 127 |
| Corrida100 cambios | 101 releases/202assets/715writes | 3releases/6assets/29writes |

Se conserva version_key/UUID/recibo por conversacion; el catalogo necesitaria
member hash/path/length y binding de contenedor. Un restore individual podria leer
hasta64 veces mas bytes. Retener un miembro retiene el contenedor; repack seria un
objeto nuevo, no overwrite. Cambios futuros van a contenedores nuevos, sin reenviar
miembros sin cambios. Sesiones individuales mayores al contenedor requieren una
regla explicita, no exclusion o particion silenciosa.

Resolucion posterior: Manunruks acepta tecnicamente esta direccion para F0,
registrada en [ADR002/contrato0.2.2](BACKUP_ADR_002_CONTAINERS.md). No atribuirla
a una decision especifica de Luis ni declarar GitHub universalmente viable.
No se limita arbitrariamente el producto a10-100 conversaciones. El prototipo
no es aun el motor F1 ni un cambio de backend; el gate permanece bajo revision.

## Contratos ajustados por revision

- Config age rechaza cipher sintetico, recipients vacios y referencia a privada
  plana. Requiere cipher coherente, dos recipients publicos ordenados y keyref;
  la validacion criptografica real corresponde a age/E1, no a una regex.
- Partial exige al menos un exito y un fallo elegible. Complete no acepta fallos.
- Eventos posteriores son locales por observer/asset/hash, no escrituras de catalogo
  inmutable ni un nuevo stream remoto; no heredan salud entre maquinas.
- Restore-intent reserva destino/UUID/hash antes de publicar. Su implementacion
  durable y reconciliacion exacta quedan en el motor F1, no se simulan como producto.
- Puntero unico de este experimento solo demuestra F0/un origen. F2 necesita
  latest por source, no un latest global que mezcle origenes.

## Comandos y evidencia de regresion

Reproduccion local en `experiments/backup_f0/README.md`. Los artefactos JSON y
logs, con hashes, versiones y duraciones, permanecen en el directorio separado.
Las pruebas usan solo fixtures generados; no se llama a modelos comerciales.

- Suite nueva focal F0:19 pruebas pasando.
- Regresion estandar inicial:281 pruebas,33 opt-in omitidas, antes de las cuatro
  pruebas F0 agregadas por revision. No atribuir ese numero al candidato final.
- Suite opt-in intermedia:285 pruebas completas, sin skips,145.921s;
  `regressions-01/result.json` y `tests.log`. Incluye17 pruebas F0, no las dos finales.
- Suite opt-in final:287 pruebas completas, sin skips,150.060s, en
  `regressions-02/result.json` y `tests.log`. Sin inferencia comercial. Un ajuste
  posterior solo del modelo de packing agrega1MiB de margen estimado; las19
  pruebas focales se repitieron sobre ese ajuste con exito.

## Gate y siguiente accion

Entregar a Manunruks para revision. Contenedores aceptados como direccion tecnica;
pendiente cierre del gate/sobre backend y perfiles; F1 no iniciada.
Evidencia aun no demostrada en vivo: rename/permisos
revocados, expiracion/renovacion de lease con Date del proveedor y bindings interiores
cifrados tras POST incierto. No cambiar settings para forzar esas pruebas.

E1 sigue pendiente: cifrar objeto+catalogo, custodia operacional y clave externa,
restore nativo completo en B sin A, identidad/visibilidad y casos negativos.
F0 no habilita datos reales, timers personales, limpieza remota o release.
