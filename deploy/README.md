# Despliegue - arbitraje-btc

Proceso long-running: WebSockets persistentes + estado en memoria. Un worker
uvicorn detras de nginx con HTTPS. No esta pensado para serverless.

## Opcion A - systemd + nginx (VM Linux)

```bash
# 1. Backend en /opt/arbitraje-btc/backend con su venv.
uv sync --python 3.12                      # crea .venv
cp .env.example .env                       # ajusta parametros

# 2. Servicio
sudo cp deploy/arbitraje-btc.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now arbitraje-btc

# 3. nginx + HTTPS.
sudo cp deploy/nginx.conf /etc/nginx/sites-available/arbitraje-btc
sudo ln -s /etc/nginx/sites-available/arbitraje-btc /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d tu-dominio.com     # anade el bloque 443 + redireccion

# 4. Frontend.
cd frontend && npm ci && npm run build && npm run start   # :3000 (nginx lo proxya en /)
```

## Opcion B - Docker

```bash
# ARB_CONTROL_TOKEN es OBLIGATORIO: la compose corre con ARB_ENV=prod y el backend se niega
# a arrancar sin token (los endpoints de control no pueden quedar sin auth en público).
export ARB_CONTROL_TOKEN="$(openssl rand -hex 24)"
docker compose -f deploy/docker-compose.yml up -d --build   # backend en 127.0.0.1:8000
```

## Verificación

```bash
curl -s https://tu-dominio.com/health          # {"status":"ok",...}
curl -N  https://tu-dominio.com/api/v1/stream   # event-stream (ping cada 15 s)
```

## Preflight 0b — checklist remota (PREPARADA, ejecutar SOLO en la ventana del server)

Ningún comando de esta sección se ejecuta en local. Registrar cada ítem con la plantilla y
**parar** antes de cualquier `rsync`/build/`up`.

Plantilla de evidencia (una entrada por comando):

```
[0b-NN] <timestamp ISO> | comando: <literal> | salida: <resumen o adjunto> | decisión: GO/NO-GO
```

Checklist (todo GO o se detiene el bloque):

- [ ] SSH y usuario de despliegue funcionales (`ssh <user>@159.89.187.165 true`).
- [ ] Disco ≥ 5 GiB libres y memoria disponible ≥ 2 GiB antes del build
      (`df -h /` y `free -m`); umbral distinto exige justificación escrita.
- [ ] Docker activo y Compose v2 con soporte de `condition: service_healthy` y `--wait`
      (`docker info`, `docker compose version`).
- [ ] Puerto 8090 permitido en firewall y sin colisión (`ss -ltn | grep 8090` vacío).
- [ ] Directorio objetivo existente y escribible por el usuario de despliegue.
- [ ] `.env` antiguo ausente o respaldado; secreto nuevo preparado en el server
      (`openssl rand -hex 24`), NUNCA copiado desde local ni versionado.
- [ ] Salida registrada y parada explícita: el avance a rsync/build/up es una decisión
      separada, no consecuencia automática del checklist.

Gotchas del server (confirmados en despliegues previos — no re-descubrirlos):

- rsync con exclusiones: `.env`, `node_modules`, `.next`, `.venv`, `__pycache__`, `*.db*`
  (el `.env` del server JAMÁS se pisa desde local).
- El secreto `ARB_CONTROL_TOKEN` se crea EN el server; el backend se niega a arrancar en
  `ARB_ENV=prod` sin token (backend/app/config.py).
- Frontend interno en **3100**, no 3000: Easy Panel tiene una regla iptables DOCKER-USER
  que DROPea el tráfico al :3000 entre contenedores.
- Cambios de nginx.conf requieren restart del contenedor nginx (la conf se monta :ro).
- Cambios de imagen backend requieren recreación explícita (`up -d --force-recreate backend`);
  `restart` NO recarga imagen nueva.
- NO tocar Easy Panel ni el Swarm existente: este stack vive en su propia red y solo
  publica 8090.
- Tras levantar: confirmar en `/health` los venues esperados y `status: "ok"` con las
  tasks en `running` (el healthcheck del compose ya parsea el body, no solo HTTP 200).

## Backup / restore del volumen `arb-data` (SQLite)

La DB vive en el volumen nombrado `arb-data` (`/data/arbitraje.db`). Copiar el archivo
"en caliente" pierde transacciones del WAL: usar SIEMPRE la API de backup de SQLite.

```bash
# 1. Backup consistente (funciona con el backend vivo; VACUUM INTO crea copia íntegra).
docker compose -f deploy/standalone/docker-compose.yml exec backend \
  python -c "import sqlite3; sqlite3.connect('/data/arbitraje.db').execute(\"VACUUM INTO '/data/backup-arbitraje.db'\")"

# 2. Extraer el backup fuera del volumen (directorio local de evidencia).
mkdir -p evidencia
docker compose -f deploy/standalone/docker-compose.yml cp backend:/data/backup-arbitraje.db ./evidencia/
docker compose -f deploy/standalone/docker-compose.yml exec backend rm /data/backup-arbitraje.db

# 3. Verificar integridad del backup extraído.
python3 -c "import sqlite3; print(sqlite3.connect('./evidencia/backup-arbitraje.db').execute('PRAGMA integrity_check').fetchone())"
# → ('ok',)

# 4. Restore: SIEMPRE a un volumen alterno vacío, NUNCA encima del volumen fuente.
docker volume create arb-data-restore
docker run --rm -v arb-data-restore:/data -v "$PWD/evidencia":/src \
  arbitraje-btc-backend sh -c "cp /src/backup-arbitraje.db /data/arbitraje.db"

# 5. Arrancar la MISMA imagen contra el volumen restaurado y comparar marcador/conteos
#    (app_config, opportunities, executions, snapshots) con los registrados en el backup.
```

Prohibido en cualquier runbook: `docker compose down -v` (borra `arb-data`), borrar la DB,
y copiar solo el archivo `.db` sin backup consistente (deja fuera `-wal`/`-shm`).

## Rollback

Dos rollbacks independientes — revertir código NUNCA implica tocar datos:

- **Código/imagen:** registrar antes de cada deploy el commit y el image ID/digest de la
  última imagen verde (`git rev-parse HEAD`, `docker images --digests arbitraje-btc-backend`).
  Rollback = checkout de ese commit + rebuild (o retag de la imagen guardada) +
  `up -d --force-recreate backend`. Este PRD no introduce migraciones de esquema: la imagen
  anterior lee el mismo `/data` sin transformación.
- **Datos:** solo desde un backup consistente verificado (sección anterior), restaurado
  primero en volumen alterno y comprobado (integrity check + marcador) antes de promoverlo.
  Ante un backend `unhealthy` estable: parar el flujo, guardar `docker compose ps` + logs,
  y decidir corrección o rollback — el healthcheck no reinicia nada por sí mismo.

## Gotchas confirmados

- `uvicorn --timeout-keep-alive 300`: el default de **5 s mata los SSE** inactivos.
- nginx SSE: `proxy_buffering off` + `X-Accel-Buffering: no` + `proxy_read_timeout 3600s`.
- nginx WS: `proxy_http_version 1.1` + headers `Upgrade`/`Connection` (bloque `map`).
- Arrancar el backend **con antelación** a la demo; tener replay de respaldo cargado.
