# Backend long-running (NFR-008). Un proceso, 1 worker, estado en memoria.
# Contexto de build = raíz del repo (ver docker-compose.yml).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY backend/ /app/
RUN pip install --upgrade pip && pip install .

# Usuario no privilegiado: un contenedor comprometido no obtiene root. /app debe ser
# suyo porque la app escribe ahí la DB SQLite (db_url por defecto: ./arbitraje.db).
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# --timeout-keep-alive 300: el default de 5 s corta los SSE inactivos.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--loop", "uvloop", "--http", "httptools", \
     "--timeout-keep-alive", "300"]
