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

## Gotchas confirmados

- `uvicorn --timeout-keep-alive 300`: el default de **5 s mata los SSE** inactivos.
- nginx SSE: `proxy_buffering off` + `X-Accel-Buffering: no` + `proxy_read_timeout 3600s`.
- nginx WS: `proxy_http_version 1.1` + headers `Upgrade`/`Connection` (bloque `map`).
- Arrancar el backend **con antelación** a la demo; tener replay de respaldo cargado.
