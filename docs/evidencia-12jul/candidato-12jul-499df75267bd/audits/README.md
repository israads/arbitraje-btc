# Audits — candidato-12jul

- Fecha: 2026-07-12T18:06-06:00 · Tag `candidato-12jul` · SHA `499df75267bd49ec5fd8f54e01e43ee3f03f30c3`

## Backend (`backend-pip-audit.log`)

`uv export --frozen --no-dev --no-emit-project --no-hashes` → `backend-runtime-requirements.txt`,
auditado con `uv run pip-audit -r ... --no-deps --disable-pip` (pip-audit ejecutado vía uv).

**Resultado: "No known vulnerabilities found" — exit 0.** Las dependencias con CVEs previos ya
están parcheadas en el lock: `aiohttp==3.14.1`, `cryptography==48.0.1`,
`pydantic-settings==2.14.2`, `starlette==1.3.1`.

## Frontend (`frontend-npm-audit.log`)

`npm audit` — **exit 1: 6 vulnerabilidades (2 moderate, 4 high)**, todas en la cadena de
Next.js 14 (incluye PostCSS transitivo de `next`); el fix propuesto es `next@16` (breaking).

**Excepción documentada (§13 del PRD-015)**: se permanece en Next 14 para esta entrega; los
hallazgos afectan tooling/SSR dev y el deployment es loopback/demo read-only detrás de nginx.
No se ejecuta `npm audit fix --force`. Se conserva el exit code no-cero del audit como manda
RF-008. Migración a Next 15/16 queda como riesgo conocido post-entrega.
