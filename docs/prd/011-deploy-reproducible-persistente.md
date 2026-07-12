# PRD-011: Deploy reproducible y persistente (preflight + build + health)

Estado: Pendiente  
Prioridad: P0  
Área: Deploy, Backend (health/store), Operación  
Dependencias: PRD-010 (la superficie read-only debe estar en el bundle antes de validar la imagen)  
Fuente: `docs/plan-accion-final-12jul.md:121-143` (Bloque 0b),
`docs/plan-accion-final-12jul.md:222-262` (deploy del Bloque 2 y Bloque 2b),
`docs/plan-accion-final-12jul.md:384-399` (precondiciones del Bloque 7) y
`docs/plan-accion-final-12jul.md:558-588` (rollback y decisión de dependencias); riesgos R0, R3,
R4, R5, R8, R12 y R15.

> **Alcance explícito e innegociable:** el deploy real al server queda **FUERA de alcance esta
> noche por decisión del usuario**. Este PRD solo autoriza cambios de archivos, preparación del
> runbook/preflight y validación **local**. Esta noche no se ejecutan `ssh`, `rsync`, build remoto,
> `docker compose up` remoto ni cambios de firewall, Easy Panel o Swarm. La ejecución remota del
> preflight 0b y todo el Bloque 7 ocurren después, como actividades separadas, usando los
> entregables locales de este PRD como precondición.

## Problema

El stack actual no ofrece una ruta de despliegue reproducible ni una prueba suficiente de
persistencia:

- **Persistencia efímera (R3):** el servicio backend no declara `ARB_DB_URL` ni volumen
  (`deploy/standalone/docker-compose.yml:9-25`). La imagen copia la aplicación a `/app` y el usuario
  escribe allí (`deploy/Dockerfile:9-16`); la URL por defecto es
  `sqlite+aiosqlite:///./arbitraje.db` (`backend/app/config.py:235-236`). Recrear el contenedor
  elimina configuración y datos de esa capa escribible.
- **Build no reproducible (R4):** `deploy/Dockerfile:10-11` copia todo el backend antes de ejecutar
  `pip install .`; no usa el lock. Aunque `backend/uv.lock` existe y es coherente con
  `backend/pyproject.toml`, la imagen puede resolver versiones diferentes en builds posteriores.
  Además, Python, Node y nginx usan tags flotantes (`deploy/Dockerfile:3`,
  `deploy/standalone/Dockerfile.frontend:3`, `deploy/standalone/docker-compose.yml:43-44`).
- **Health con falso positivo (R8):** `_task_status()` distingue `running`, `cancelled`, `failed` y
  `finished` (`backend/app/api/health.py:19-28`), pero el estado global solo degrada ante `failed`
  (`backend/app/api/health.py:86-94`). Una task terminada o cancelada mientras el endpoint sigue
  sirviendo puede dejar `status: "ok"`. El compose tampoco define healthcheck
  (`deploy/standalone/docker-compose.yml:9-58`) y `/health` conserva HTTP 200 al degradarse.
- **Permisos no demostrados (R12):** la imagen crea el UID 10001 y cambia a `USER appuser`
  (`deploy/Dockerfile:13-16`), pero no existe `/data`. El volumen debe inicializarse con ownership
  10001:10001 y la escritura debe probarse con el UID efectivo, no inferirse del Dockerfile.
- **PRAGMAs no demostrados en runtime (R15):** el hook configura WAL, `synchronous=NORMAL`, timeout
  y vacuum incremental (`backend/app/store/db.py:120-150`), pero falta verificarlos dentro del
  contenedor y sobre el archivo del volumen.
- **Bundle read-only no cableado:** el Dockerfile de frontend solo fija `NEXT_PUBLIC_API_BASE` antes
  del build (`deploy/standalone/Dockerfile.frontend:10-14`) y el compose no pasa build args al
  frontend (`deploy/standalone/docker-compose.yml:27-41`). La implementación de PRD-010 no basta si
  `NEXT_PUBLIC_READ_ONLY=1` no existe durante `npm run build`.
- **Infraestructura desconocida (R0):** el plan registra el endpoint público anterior como retirado.
  Hace falta un preflight remoto, pero esta noche solo se prepara su checklist y plantilla de
  evidencia; no se toca el server.
- **Dependencias vulnerables (R5):** el lock conserva `aiohttp 3.13.5`
  (`backend/uv.lock:38-39`), `cryptography 48.0.0` (`backend/uv.lock:659-660`),
  `pydantic-settings 2.14.1` (`backend/uv.lock:1823-1824`) y `starlette 1.2.0`
  (`backend/uv.lock:2351-2352`). La decisión y los mínimos corregidos están definidos en §13 del
  plan.

## Objetivo

Dejar un artefacto local y un runbook verificables para que, en una ventana posterior, el Bloque 7
sea una ejecución mecánica y reversible:

1. Compose y Dockerfiles válidos, reproducibles y sin secretos embebidos.
2. SQLite persistente y escribible por UID/GID 10001, con backup/restore local probado.
3. `/health` veraz y healthcheck usado como gate de avance, no como señal decorativa.
4. Decisión de dependencias resuelta o excepción documentada dentro del timebox.
5. Preflight 0b y rollback remoto preparados, sin ejecutar ninguna acción contra el server.

## No objetivos

- Ejecutar el preflight contra el host, abrir SSH o validar el server esta noche.
- Ejecutar el deploy real: no `rsync`, build remoto, `up`, recreación ni smoke público.
- Migrar Next 14→16 (excepción documentada, ver RF-010).
- Migrar a Postgres, introducir migraciones de esquema o cambiar el motor de persistencia.
- Construir `/livez` + `/readyz` separados con HTTP 503 (post-entrega).
- Tocar Easy Panel, Swarm, firewall, DNS o secretos reales del server.
- Probar restauración sobre datos reales: backup/restore se valida con un volumen local desechable.

## Usuario

- Operador que ejecutará después los Bloques 0b y 7 con gates y rollback preparados.
- Jurado, indirectamente: el stack posterior debe sobrevivir una recreación sin perder la sesión
  canónica.
- Revisor técnico o de seguridad que audita lock, imagen, health y excepciones.

## Estado actual

Existe:

- Stack standalone con red propia; solo nginx publica 8090
  (`deploy/standalone/docker-compose.yml:1-7`, `deploy/standalone/docker-compose.yml:43-58`).
- **Dos composes coexisten.** `deploy/standalone/docker-compose.yml` es el stack completo
  (backend+frontend+nginx, red interna, 8090) que corre en el server: **es el compose canónico de
  este PRD y del Bloque 7**. `deploy/docker-compose.yml:3-23` es una variante backend-solo con bind
  a loopback `127.0.0.1:8000`, pensada para nginx del host (`deploy/nginx.conf` apunta a
  `127.0.0.1:8000`/`:3000`); no es ruta de deploy del server.
- Backend en Python 3.12, un worker y usuario no privilegiado
  (`deploy/Dockerfile:3-7`, `deploy/Dockerfile:13-24`).
- Frontend interno en 3100 y ejecutado como usuario `node`
  (`deploy/standalone/docker-compose.yml:27-41`,
  `deploy/standalone/Dockerfile.frontend:16-21`).
- PRAGMAs por conexión y creación idempotente de tablas
  (`backend/app/store/db.py:120-161`).
- Dependencias declaradas en `backend/pyproject.toml:6-20` y lock válido versionado.

Brecha verificable:

- Sin volumen, `ARB_DB_URL`, healthcheck ni gate `service_healthy`.
- Build backend con pip, no con `uv sync --frozen`.
- `/health` no degrada ante `finished`/`cancelled`.
- `/data` y su ownership no existen en la imagen.
- El flag read-only no llega al build de frontend.
- Parches Python, validación Docker local y prueba de rollback pendientes.
- Estado Docker local medido (2026-07-11): Docker CLI 29.5.2 y buildx v0.35.0 presentes, pero el
  plugin Compose v2 ausente (`docker compose` → `unknown command`), el binario legado
  `docker-compose` inexistente y el daemon (colima) apagado — el socket configurado
  (`~/.colima/sr-mssql/docker.sock`) no existe. Habilitar daemon + Compose v2 es precondición
  explícita del gate local; el binario legado no se acepta como sustituto silencioso.

## Requisitos funcionales

### RF-001 Volumen persistente `arb-data:/data`

En `deploy/standalone/docker-compose.yml`, declarar la URL absoluta, montar el volumen y definirlo
en el nivel raíz. Convertir el bloque `environment` actual de lista a mapa; YAML no permite mezclar
ambas formas dentro del mismo bloque:

```yaml
services:
  backend:
    environment:
      ARB_ENV: prod
      ARB_CONTROL_TOKEN: ${ARB_CONTROL_TOKEN:?define ARB_CONTROL_TOKEN (p.ej. openssl rand -hex 24)}
      ARB_DB_URL: sqlite+aiosqlite:////data/arbitraje.db
    volumes:
      - arb-data:/data

volumes:
  arb-data:
```

Las cuatro barras de `sqlite+aiosqlite:////data/...` son obligatorias. El archivo principal y sus
sidecars `-wal`/`-shm` deben estar bajo `/data`; ningún `*.db` nuevo puede aparecer en `/app`. No
usar `docker compose down -v` en el runbook normal o de rollback.

Ámbito entre composes: este RF y los gates aplican sobre el canónico
(`deploy/standalone/docker-compose.yml`). El compose backend-solo (`deploy/docker-compose.yml`)
comparte `deploy/Dockerfile` y hoy tampoco declara volumen: en el mismo commit recibe el mismo par
`ARB_DB_URL` + `arb-data:/data` (y la misma conversión de `environment` lista→mapa) para no
divergir del Dockerfile con `/data`, pero queda fuera de RF-005/RF-011 y del gate local; su único
uso es levantar el backend suelto en desarrollo.

### RF-002 Dockerfile backend con `uv sync --frozen` en dos fases

Reemplazar el flujo de `deploy/Dockerfile:10-11` por:

1. Instalar una versión explícita de `uv` en la imagen o copiar el binario desde una imagen con
   tag/digest fijado; no usar `latest`.
2. Copiar solo `backend/pyproject.toml` y `backend/uv.lock` a `/app`.
3. Ejecutar `uv sync --frozen --no-dev --no-install-project` para la capa cacheable.
4. Copiar el resto de `backend/`.
5. Ejecutar `uv sync --frozen --no-dev` para instalar el proyecto.
6. Añadir `/app/.venv/bin` al `PATH` y conservar el comando de un solo worker de
   `deploy/Dockerfile:20-24`.

El build debe fallar si proyecto y lock divergen. La prueba de reproducibilidad construye dos veces
desde el mismo commit, la segunda con `--no-cache`, y registra que ambas imágenes contienen las
mismas versiones Python (`uv pip freeze` normalizado); no se exige que los image IDs coincidan.

### RF-003 `/data` propiedad de UID/GID 10001

Crear `/data` en la imagen, asignar `10001:10001` y mantener `USER appuser`. En un volumen nuevo,
Docker debe inicializar el mountpoint con ese ownership. La validación comprueba dentro del
contenedor:

- `id -u` = `10001` e `id -g` = `10001`;
- `/data` es escribible sin elevar privilegios;
- `arbitraje.db` pertenece a 10001:10001;
- DB, WAL y SHM son observables mientras el engine mantiene una conexión activa.

### RF-004 `/health` degrada con toda task terminal

Cambiar la condición de `backend/app/api/health.py:88-94`: mientras `/health` todavía responde,
cualquier estado `failed`, `finished` o `cancelled` en `ctx.tasks`, o writer no vivo, produce
`status: "degraded"`. Durante el shutdown normal no existe una excepción especial que pueda dejar
`ok`: cuando las tasks empiezan a cancelarse, cualquier respuesta aún servida debe degradar; después
el proceso deja de responder.

Conservar el detalle por nombre en `tasks`. No cambiar a HTTP 503 en este PRD porque el plan difiere
`/livez`/`/readyz`; RF-005 debe interpretar el body.

El cambio es implementable sin falsos positivos con el árbol actual, verificado task por task:
las siete tasks posibles son bucles sin salida normal en operación — `while True` en el motor
(`backend/app/engine/__init__.py:58`) y en la retención (`backend/app/main.py:109-112`);
`while not self._stop.is_set()` en watchdog, breakers, rebalancer y demo — y **ningún código de
producción llama a sus `stop()`** (solo tests). `feeds` únicamente retorna si TODOS los runners
mueren (`run_ingestors` agrupa con `gather(..., return_exceptions=True)`,
`backend/app/ingest/__init__.py:40-43`): exactamente el caso que hoy queda oculto como `finished`
con `status: "ok"`. No existe hoy ninguna task opcional que termine legítimamente; si en el futuro
se añade una, deberá retirarse de `ctx.tasks` al completar, no dejarse `finished`. Con
`ingest_autostart=False` (tests) no se crean las tasks de ingesta/motor, pero la retención sigue
en `ctx.tasks` con su default de 24 h (`backend/app/main.py:114-116`) y permanece `running`; el estado
sigue `ok`: sin regresión en la suite. La cancelación solo ocurre en el `finally` del lifespan
(`backend/app/main.py:324-327`),
cuando uvicorn ya dejó de aceptar conexiones nuevas: una respuesta en vuelo que observe `cancelled`
degrada correctamente y no existe ventana estable de falso `degraded`. En concreto, el cambio es la
agregación de `backend/app/api/health.py:91` (`any(st != "running" ...)` sobre `tasks`, que ya
incluye la entrada `writer` mapeada a `failed` si el hilo murió).

### RF-005 Healthcheck de compose y gate de arranque

El backend tendrá un healthcheck sin `curl` ni `jq`, usando la stdlib disponible en la imagen:

```yaml
healthcheck:
  test:
    - CMD
    - python
    - -c
    - >-
      import json,sys,urllib.request;
      data=json.load(urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=5));
      sys.exit(0 if data.get('status')=='ok' else 1)
  interval: 10s
  timeout: 6s
  retries: 6
  start_period: 30s
```

Nginx debe usar la sintaxis larga de `depends_on`: backend con
`condition: service_healthy` y frontend con `condition: service_started`. Esto convierte health en
gate inicial local. Además:

- el avance requiere estado Docker `healthy` y body `status=ok` con todas las tasks esperadas en
  `running`, en un máximo de 120 s;
- antes de levantar, el runbook fija el conjunto esperado. Con el compose canónico (autostart
  activo y defaults) son SIETE tasks más el writer: `feeds`, `engine`, `watchdog`, `breakers` y
  `rebalancer` siempre (`backend/app/main.py:282-310`; el rebalancer no es condicional en la
  práctica porque el portfolio se construye incondicionalmente, `backend/app/main.py:83`);
  `db_retention` porque el default es `db_retention_hours=24` (`backend/app/config.py:241`,
  `backend/app/main.py:114-116`); y `demo` porque el default es `demo_fallback_enabled=True`
  (`backend/app/config.py:193`, `backend/app/main.py:275-280`, `backend/app/main.py:312-313`).
  `writer` siempre debe estar `running`. Si el `.env` del stack cambia esos defaults
  (`ARB_DB_RETENTION_HOURS=0`, fallback de demo off), el conjunto esperado se recalcula y se anota
  en la evidencia;
- `starting`, `degraded`, JSON inválido, timeout o conexión rechazada fallan el gate;
- un contenedor `unhealthy` no se reinicia automáticamente solo por el healthcheck: se detiene el
  flujo, se guardan `docker compose ps` y logs, y se corrige o revierte;
- `restart: unless-stopped` se conserva para caídas de proceso, pero no sustituye este gate.

### RF-006 DB nueva con `auto_vacuum=INCREMENTAL`

El hook ejecuta `auto_vacuum=INCREMENTAL` en `backend/app/store/db.py:120-135` antes de crear las
tablas (`backend/app/store/db.py:158-161`), por lo que aplica a un volumen nuevo. Una DB heredada con
tablas requiere `VACUUM` para cambiar el modo: este PRD no autoriza copiarla ni transformarla. Si en
la ventana posterior hubiera datos heredados, se detiene el despliegue y se abre un procedimiento
de migración/backup separado.

### RF-007 PRAGMAs verificados dentro del contenedor

Con el backend vivo y consultando exactamente `/data/arbitraje.db`, registrar:

- `PRAGMA journal_mode` → `wal`;
- `PRAGMA auto_vacuum` → `2`;
- `PRAGMA synchronous` → `1` (`NORMAL`);
- `PRAGMA integrity_check` → `ok`.

La comprobación local es gate de este PRD. El runbook exige repetirla en el server dentro del
Bloque 7, pero esa repetición no se ejecuta esta noche.

### RF-008 Preparación del preflight 0b — sin contacto con el server

Preparar en `deploy/README.md` una checklist copiable y una plantilla para registrar comando,
timestamp, salida y decisión. Su ejecución posterior comprobará:

- [ ] SSH y usuario de despliegue funcionales.
- [ ] Disco y memoria suficientes, con umbrales documentados: al menos 5 GiB libres y 2 GiB de
  memoria disponible antes del build; si el operador cambia el umbral, debe justificarlo.
- [ ] Docker activo y Compose v2 compatible con `condition: service_healthy` y `--wait`.
- [ ] Puerto 8090 permitido y sin colisión.
- [ ] Directorio objetivo con permisos del usuario de despliegue.
- [ ] `.env` antiguo ausente o respaldado; creación del secreto preparada.
- [ ] Salida registrada y parada explícita antes de cualquier rsync/build/up.

El runbook conserva los gotchas de `docs/plan-accion-final-12jul.md:131-143`: exclusiones de rsync
incluido `.env`; secreto creado en server; frontend interno 3100; restart de nginx; recreación
explícita del backend; no tocar Easy Panel/Swarm; y confirmar venues en `/health`. La exigencia del
token en producción está en `backend/app/config.py:245-255`. Documentar estos pasos no autoriza su
ejecución esta noche.

### RF-009 Parches Python de dependencias en commit aislado

Dentro de 45 minutos, intentar actualizar el lock a:

- `aiohttp >= 3.14.1`;
- `cryptography >= 48.0.1`;
- `pydantic-settings >= 2.14.2`;
- `starlette >= 1.3.1`.

Estado del lock verificado (2026-07-11): `aiohttp 3.13.5`, `cryptography 48.0.0`,
`pydantic-settings 2.14.1`, `starlette 1.2.0`. Los cuatro saltos son patch o minor
(3.13→3.14, 48.0.0→48.0.1, 2.14.1→2.14.2, 1.2→1.3): compatibles en principio, sin cambio de major.
Solo `pydantic-settings` es dependencia directa, con `>=2.3` (`backend/pyproject.toml:11`) — ya
admite 2.14.2 sin tocar `pyproject.toml`; las otras tres son transitivas. Preferir
`uv lock --upgrade-package <pkg>` por paquete en lugar de regenerar todo el árbol. Riesgos de
resolución concretos, verificados en el lock: `aiohttp` y `cryptography` llegan vía `ccxt 4.5.56`
(`backend/uv.lock:308-321`), que históricamente fija techos de `aiohttp` — si no resuelve, la
alternativa es subir `ccxt` en el mismo commit o excepción; `starlette` llega vía `fastapi 0.136.3`
y `sse-starlette 3.4.4` — si el rango de `fastapi` excluye 1.3.1, el fix exige bump coordinado de
`fastapi` dentro del mismo commit o excepción. Actualizar `backend/pyproject.toml` solo cuando haga
falta expresar un mínimo directo o una restricción explícita, y regenerar `backend/uv.lock` con
`uv`, nunca a mano. Se integra el commit
solo si `uv lock --check`, tests/cobertura, auditoría y build local frozen pasan. Si alguna versión no
resuelve o rompe compatibilidad, revertir íntegramente el commit aislado y registrar paquete, versión,
hallazgo, impacto, mitigación, responsable y fecha objetivo. No dejar un lock parcialmente actualizado.

### RF-010 Excepción documentada: Next 14→16 no entra

No ejecutar `npm audit fix --force` ni migrar Next 14→16 el día final. Regenerar la salida de
`npm audit`, registrar los hallazgos vigentes con impacto, mitigación, responsable y fecha de
migración. Read-only, firewall y apagado posterior reducen exposición, pero no vuelven las
vulnerabilidades “inexplotables” ni eliminan riesgo de DoS/runtime.

### RF-011 Flag read-only presente durante el build

En `deploy/standalone/Dockerfile.frontend`, declarar `ARG NEXT_PUBLIC_READ_ONLY=1` y promoverlo a
`ENV` **antes** de `npm run build` (`deploy/standalone/Dockerfile.frontend:12-14`). En
`deploy/standalone/docker-compose.yml`, pasarlo mediante `frontend.build.args` antes de construir la
imagen (`deploy/standalone/docker-compose.yml:27-31`). Criterios:

- el bundle contiene `READ-ONLY DEMO` y las superficies definidas por PRD-010 no mutan;
- `NEXT_PUBLIC_READ_ONLY` puede estar en el bundle por diseño, pero `ARB_CONTROL_TOKEN` no aparece
  en capas, historial, variables ni archivos de la imagen frontend;
- el Dockerfile expone 3100 y arranca por defecto con `next start -H 0.0.0.0 -p 3100`; eliminar la
  duplicación del `command` en compose para que no existan dos autoridades de puerto
  (`deploy/standalone/Dockerfile.frontend:16-21`,
  `deploy/standalone/docker-compose.yml:32-38`);
- cambiar solo `environment:` en runtime no se acepta como implementación.

### RF-012 Backup, restore y rollback local probados

Preparar comandos que creen una copia consistente mediante la API de backup de SQLite, la extraigan
fuera del volumen y verifiquen `PRAGMA integrity_check=ok`. Probarlos únicamente con un volumen local
desechable:

1. insertar un marcador y registrar valores/filas de `app_config`, `opportunities`, `executions` y
   `snapshots`;
2. crear backup consistente y copiarlo a un directorio local de evidencia;
3. restaurarlo en un segundo volumen vacío, nunca encima del volumen fuente;
4. arrancar la misma imagen contra el volumen restaurado;
5. comprobar integrity check y coincidencia exacta de marcador y conteos registrados.

El runbook separa rollback de código (commit + digest/tag de la última imagen verde) y rollback de
datos (backup verificado). Como este PRD no introduce migraciones de esquema, revertir código no debe
alterar ni borrar el volumen. Prohibidos `down -v`, borrado de DB y copia en caliente de solo el
archivo `.db` sin backup consistente.

### RF-013 Imágenes base fijadas por digest

Resolver para la arquitectura objetivo y fijar como `tag@sha256:digest` las bases actuales de
Python, Node y nginx citadas en el problema. Registrar nombre, digest, arquitectura y fecha. Una
actualización posterior de base debe ser un cambio deliberado con rebuild y gates; reutilizar un tag
flotante no cuenta como reproducción del candidato. El digest de `uv` también se fija si se copia
desde otra imagen.

## Cambios técnicos

Archivos:

- `deploy/Dockerfile` — build frozen con uv, base fijada, `/data` y ownership (RF-002, RF-003,
  RF-013).
- `deploy/standalone/docker-compose.yml` — compose canónico: volumen, `ARB_DB_URL`, healthcheck,
  gate y build arg read-only (RF-001, RF-005, RF-011).
- `deploy/docker-compose.yml` — solo el mismo par volumen/`ARB_DB_URL` para no divergir del
  Dockerfile compartido (RF-001); sin healthcheck ni gates.
- `deploy/standalone/Dockerfile.frontend` — flag read-only, puerto único y base fijada (RF-011,
  RF-013).
- `backend/app/api/health.py` — degradación por estados terminales (RF-004).
- Tests de health — regresiones de `finished`, `cancelled`, writer muerto y caso feliz.
- `backend/pyproject.toml` y `backend/uv.lock` — solo si el intento controlado de RF-009 prospera.
- `deploy/README.md` — preflight, validación, backup/restore, gates y rollback (RF-008, RF-012).

## Plan de implementación

1. Habilitar Docker local: arrancar el daemon (colima) e instalar el plugin Compose v2; registrar
   la salida de `docker compose version`. Mientras no estén disponibles, solo son ejecutables los
   gates sin Docker: tests de health (RF-004), `uv lock --check` y RF-009, runbook/preflight
   (RF-008), excepción de Next (RF-010) y la edición de Dockerfiles/composes. Un pre-chequeo
   sintáctico (`python3 -c "import yaml,sys; yaml.safe_load(open(sys.argv[1]))" <compose>`) sirve
   como linting temprano pero NO sustituye a `docker compose config --quiet` (no valida el schema
   de compose). Si Docker no queda habilitado esta noche, TODA la sección «Local/Docker» de
   Pruebas se traslada como primer paso bloqueante de la ventana del server, antes de cualquier
   acción del Bloque 7, y este PRD permanece Pendiente.
2. Implementar volumen/URL, `/data` con UID/GID 10001 y build backend frozen.
3. Corregir health y añadir tests unitarios de todos los estados terminales.
4. Añadir healthcheck, `condition: service_healthy` y gate local de 120 s.
5. Cablear el flag read-only en Dockerfile y `build.args`, unificar el puerto 3100 y fijar los
   digests de las imágenes base; comprobar ausencia del token.
6. Ejecutar validación local con volumen desechable: PRAGMAs, persistencia tras recreación y fallo
   controlado del healthcheck.
7. Probar backup/restore en un segundo volumen local y conservar evidencia.
8. Intentar parches Python en commit aislado; integrar todo o revertir todo dentro del timebox.
9. Documentar excepción de Next, preflight 0b y rollback posterior.
10. Cerrar el gate local y detenerse. No abrir SSH ni iniciar el Bloque 7.

## Pruebas

Backend:

- task `finished` mientras el endpoint sirve → body `status=degraded`;
- task `cancelled` mientras el endpoint sirve → body `status=degraded`;
- task `failed` → body `status=degraded`;
- writer muerto con tasks sanas → body `status=degraded`;
- todas las tasks y writer vivos → body `status=ok`;
- detalle `tasks` conserva los nombres y estados esperados;
- suite completa y cobertura ≥ 85 % tras el árbol definitivo de RF-009.

Local/Docker, sin server:

- `docker compose config --quiet` pasa con `.env` temporal y secreto ficticio no registrado.
- Backend y frontend construyen desde un commit autocontenido; backend usa el lock frozen.
- Python, Node, nginx y la fuente de `uv` están fijados por digest y corresponden a la arquitectura
  registrada.
- Dos builds backend del mismo commit, uno `--no-cache`, tienen el mismo freeze normalizado.
- Backend alcanza `healthy` antes de 120 s; nginx no se considera listo antes de ese estado.
- Un body controlado `degraded` hace retornar 1 al comando exacto del healthcheck.
- UID/GID efectivo = 10001; no aparece DB bajo `/app`; DB/WAL/SHM están bajo `/data`.
- PRAGMAs e integrity check cumplen RF-007.
- Tras insertar un marcador y recrear backend, marcador y conteos permanecen idénticos.
- Backup restaurado en segundo volumen conserva marcador/conteos y pasa integrity check.
- Imagen frontend muestra `READ-ONLY DEMO` y no contiene `ARB_CONTROL_TOKEN`.
- Al finalizar: contenedores de prueba retirados; volúmenes locales se eliminan solo después de
  preservar la evidencia requerida.

## Criterios de aceptación (gate local; preparación de 0b/7)

- Daemon activo y Compose v2 disponibles, versión registrada; `docker compose config --quiet` =
  exit 0 sobre el compose canónico.
- Builds backend/frontend = exit 0 desde el commit completo; lock check = exit 0, bases por digest
  y freezes normalizados coinciden.
- UID/GID 10001 escribe en `/data`; cero `*.db` bajo `/app`.
- `journal_mode=wal`, `auto_vacuum=2`, `synchronous=1` e `integrity_check=ok` registrados.
- Marcador y conteos antes/después de `--force-recreate` coinciden exactamente.
- Restore en segundo volumen pasa integrity check y reproduce marcador/conteos.
- Tests de health cubren `failed`, `finished`, `cancelled`, writer muerto y estado sano.
- Backend llega a `healthy` ≤ 120 s; body degradado hace fallar el comando de healthcheck.
- Bundle read-only validado y búsqueda de `ARB_CONTROL_TOKEN` en imagen sin coincidencias.
- Decisión de dependencias cerrada: cuatro fixes integrados con gates verdes o excepción completa;
  salida de `pip-audit`/`npm audit` guardada.
- Runbook contiene preflight, umbrales, backup/restore, digest/commit de rollback y puntos de parada.
- Bitácora demuestra que esta noche no hubo SSH, rsync, build/up remoto ni cambios al server.

Si falla cualquier criterio, el estado permanece **Pendiente** y el Bloque 7 queda bloqueado. Un
HTTP 200 aislado, un contenedor `running` o una build con caché no sustituyen los gates.

## Redundancia y contingencia

- **Persistencia:** volumen nombrado + marker test + recreación + backup consistente + restore en
  volumen alterno. La redundancia no depende de conservar el contenedor anterior.
- **Health como gate:** unit tests prueban la semántica del body; el healthcheck prueba su consumo;
  `service_healthy` impide adelantar nginx; operador y timeout impiden aceptar un unhealthy estable.
- **Fallo de build/lock:** conservar el último commit e imagen local verdes; revertir el commit
  aislado completo, limpiar solo caché de build si es necesario y reconstruir desde lock.
- **Fallo de persistencia/restore:** no desplegar, no borrar el volumen fuente y conservar logs,
  backup y segundo volumen para diagnóstico.
- **Rollback posterior preparado:** registrar commit y digest, crear backup consistente antes de
  recrear, verificarlo en destino alterno y solo entonces avanzar. Revertir imagen nunca implica
  revertir o eliminar datos automáticamente.
- **Plan B de demo:** stack local, jury mode determinista preactivado, export canónico, video y
  capturas. Si el deploy posterior falla, se presenta local y no se depura producción durante la
  presentación (`docs/plan-accion-final-12jul.md:558-565`).

## Riesgos

- Volumen no escribible por UID 10001. Mitigación: ownership en imagen y prueba efectiva, no solo
  inspección estática.
- WAL/SHM desaparecen al cerrar la última conexión y generan un falso negativo. Mitigación:
  inspeccionarlos con el engine vivo y complementar con PRAGMAs.
- Health HTTP 200 produce falso healthy. Mitigación: parsear JSON, validar tasks y usar timeout.
- `service_healthy` no equivale a autorrecuperación. Mitigación: parada, evidencia y rollback ante
  unhealthy; no crear loops de restart.
- Copia inconsistente de SQLite pierde transacciones/WAL. Mitigación: API de backup, integrity check
  y restore en volumen alterno.
- Rollback de imagen daña datos. Mitigación: cero migraciones, backup previo y separación explícita
  entre rollback de código y datos.
- Parches de seguridad rompen resolución o runtime. Mitigación: commit atómico, 45 minutos y
  excepción completa si no cierra.
- Se filtra el token al bundle o al historial de imagen. Mitigación: solo secreto ficticio local,
  nunca build arg público para el token y búsqueda negativa en la imagen.
- Tentación de desplegar esta noche. Mitigación: punto de parada verificable; todo comando remoto
  permanece fuera de este PRD.
