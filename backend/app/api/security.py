"""Protecciones opcionales de la API pública: API key + rate limiting.

Ambas están desactivadas por defecto (dev/demo local) y se habilitan por settings:
`api_key` no vacío exige header `X-API-Key`; `api_rate_limit_per_min` > 0 limita por IP en una
ventana deslizante en memoria. Se excluyen health, docs y el schema OpenAPI para no romper la
exploración. In-memory a propósito: una sola instancia (single-worker); no hay dependencia externa.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

# Prefijos exentos de auth/rate-limit: exploración, salud, métricas y el SSE de larga duración
# (BaseHTTPMiddleware puede interferir con respuestas en streaming).
_EXEMPT_PREFIXES = (
    "/health", "/docs", "/redoc", "/openapi.json", "/metrics",
    "/api/v1/stream", "/stream",
)
# Tope de IPs rastreadas a la vez: cota dura de memoria del rate limiter.
_MAX_TRACKED_IPS = 4096


def _client_ip(request: Request) -> str:
    """IP de origen real (peer TCP). NO se usa X-Forwarded-For: es controlable por el cliente
    cuando no hay un proxy de confianza delante, lo que permitiría evadir el límite y crear
    claves ilimitadas. Tras un proxy, configúralo allí o termina TLS con el peer correcto."""
    return request.client.host if request.client else "unknown"


class ApiGuardMiddleware(BaseHTTPMiddleware):
    """API key + rate limit por IP. No-op si ambas protecciones están desactivadas."""

    def __init__(self, app: ASGIApp, *, api_key: str, rate_limit_per_min: int) -> None:
        super().__init__(app)
        self._api_key = api_key
        self._rate = rate_limit_per_min
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _evict_stale(self, cutoff: float) -> None:
        """Purga IPs cuyo último hit expiró: evita crecimiento de memoria sin tope."""
        if len(self._hits) <= _MAX_TRACKED_IPS:
            return
        for ip in [k for k, b in self._hits.items() if not b or b[-1] < cutoff]:
            del self._hits[ip]

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path
        if request.method == "OPTIONS" or any(path.startswith(p) for p in _EXEMPT_PREFIXES):
            return await call_next(request)

        if self._api_key and request.headers.get("x-api-key") != self._api_key:
            return JSONResponse({"detail": "invalid or missing API key"}, status_code=401)

        if self._rate > 0:
            now = time.time()
            cutoff = now - 60.0
            self._evict_stale(cutoff)
            bucket = self._hits[_client_ip(request)]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self._rate:
                retry = max(1, int(60 - (now - bucket[0])))
                return JSONResponse(
                    {"detail": "rate limit exceeded"},
                    status_code=429,
                    headers={"Retry-After": str(retry)},
                )
            bucket.append(now)

        return await call_next(request)
