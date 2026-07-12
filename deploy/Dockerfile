# Backend long-running (NFR-008). Un proceso, 1 worker, estado en memoria.
# Contexto de build = raíz del repo (ver docker-compose.yml).
#
# Base fijada por digest (RF-013, PRD-011). Índice multi-arch resuelto el 2026-07-11:
#   python:3.12-slim  → sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf
# Actualizar la base es un cambio deliberado: nuevo digest + rebuild + gates.
FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# uv fijado por versión + digest (RF-013): binario copiado desde la imagen oficial.
#   ghcr.io/astral-sh/uv:0.10.10 → sha256:cbe0a44ba994e327b8fe7ed72beef1aaa7d2c4c795fd406d1dbf328bacb2f1c5
COPY --from=ghcr.io/astral-sh/uv:0.10.10@sha256:cbe0a44ba994e327b8fe7ed72beef1aaa7d2c4c795fd406d1dbf328bacb2f1c5 \
     /uv /uvx /usr/local/bin/

WORKDIR /app

# Build reproducible en dos fases (RF-002): primero SOLO manifest+lock → capa de
# dependencias cacheable; `--frozen` falla si pyproject y uv.lock divergen.
COPY backend/pyproject.toml backend/uv.lock /app/
RUN uv sync --frozen --no-dev --no-install-project

# Después el código; segunda pasada instala el proyecto (rápida: deps ya resueltas).
COPY backend/ /app/
RUN uv sync --frozen --no-dev

# El venv manda: uvicorn y la app se resuelven desde /app/.venv sin activar nada.
ENV PATH="/app/.venv/bin:$PATH"

# Usuario no privilegiado: un contenedor comprometido no obtiene root. /app es suyo
# (fallback db_url ./arbitraje.db) y /data es el mountpoint del volumen persistente
# (RF-003): debe existir en la imagen con ownership 10001:10001 para que Docker
# inicialice un volumen nuevo con esos permisos.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app \
    && mkdir -p /data && chown 10001:10001 /data
USER appuser

EXPOSE 8000

# --timeout-keep-alive 300: el default de 5 s corta los SSE inactivos.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--loop", "uvloop", "--http", "httptools", \
     "--timeout-keep-alive", "300"]
