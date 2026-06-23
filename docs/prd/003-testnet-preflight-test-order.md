# PRD-003: Testnet preflight + test order

Estado: Implementado inicial  
Prioridad: P1  
Área: Ejecución, Riesgo, API, Seguridad operacional  
Dependencias: PRD-006 es complementario para métricas/operación
Arquitectura: [docs/architecture/003-testnet-preflight-test-order.md](../architecture/003-testnet-preflight-test-order.md)

## Problema

El sistema simula ejecución con mucho detalle, pero no demuestra que pueda pasar controles reales de exchange: balances, precisión, min notional, lot size, firma y test order. Competidores fuertes muestran testnet o `TEST_ORDER`.

## Objetivo

Agregar un modo seguro de preflight/testnet que valide órdenes sin operar dinero real.

## No objetivos

- No ejecutar órdenes reales en producción.
- No guardar secretos en repo.
- No soportar todos los exchanges al inicio.
- No hacer smart order routing.

## Alcance P1

Exchange inicial:

- Binance Spot Testnet o Binance Spot `order/test`.
- Implementación inicial: adapter local determinista con reglas tipo Binance `BTCUSDT`,
  sin red real. Deja el contrato listo para conectar `POST /api/v3/order/test`.

Operaciones:

- Validar credenciales.
- Leer exchange info.
- Validar symbol filters.
- Validar balances testnet si aplica.
- Crear payload de orden saneado.
- Enviar test order o dry-run firmado.
- Registrar resultado.

## Requisitos funcionales

### RF-001 Feature flag duro

Nada de preflight debe activarse sin:

```bash
ARB_EXECUTION_MODE=testnet
ARB_ENABLE_TEST_ORDERS=true
```

Valores permitidos:

- `disabled`
- `dry_run`
- `testnet`

Default: `disabled`.

### RF-002 Endpoint de preflight

Agregar:

```http
POST /api/v1/execution/preflight
```

Body:

```json
{
  "opportunity_id": "opp-id",
  "venue": "binance",
  "side": "buy",
  "quantity_btc": 0.001,
  "order_type": "market"
}
```

Respuesta:

```json
{
  "mode": "testnet",
  "accepted": true,
  "venue": "binance",
  "symbol": "BTCUSDT",
  "checks": [
    {"name": "credentials", "passed": true},
    {"name": "min_notional", "passed": true},
    {"name": "lot_size", "passed": true},
    {"name": "balance", "passed": true}
  ],
  "sanitized_order": {
    "side": "BUY",
    "type": "MARKET",
    "quantity": "0.001"
  }
}
```

### RF-003 Endpoint test order

Agregar:

```http
POST /api/v1/execution/test-order
```

Condiciones:

- Solo con `ARB_ENABLE_TEST_ORDERS=true`.
- Solo en venues soportados.
- Sin fallback silencioso a live.
- Log saneado, sin API key ni firma.

### RF-004 Estado de ejecución

Agregar estados conceptuales, aunque al inicio no todos se usen:

- `detected`
- `preflighted`
- `reserved`
- `submitted_test`
- `accepted_test`
- `rejected_test`
- `failed`

## Cambios técnicos

Crear:

- `backend/app/execution/__init__.py`
- `backend/app/execution/preflight.py`
- `backend/app/execution/binance.py`
- `backend/app/execution/registry.py`
- `backend/app/models/preflight.py`

Modificar:

- `backend/app/config.py`
- `backend/app/api/v1/router.py`
- `backend/tests/test_config.py`

## Seguridad

- No imprimir secretos.
- Leer secretos solo desde env.
- No aceptar endpoint si `execution_mode=disabled`.
- Requerir token de control para endpoints POST.
- Rate limit opcional por proceso.

## Plan de implementación

1. Añadir settings de ejecución.
2. Crear modelos `PreflightRequest`, `PreflightResult`, `PreflightCheck`.
3. Implementar validador local de symbol filters.
4. Implementar cliente Binance aislado.
5. Agregar endpoint `/execution/preflight`.
6. Agregar endpoint `/execution/test-order`.
7. Agregar tests con cliente fake.
8. Documentar variables y flujo.

## Implementación inicial

Backend:

- `GET /api/v1/execution/status`
- `POST /api/v1/execution/preflight`
- `POST /api/v1/execution/test-order`
- Guards duros:
  - `execution_mode=disabled` bloquea todo preflight/test-order.
  - `test-order` requiere `execution_mode=testnet` y `enable_test_orders=true`.
  - Ambos POST reutilizan `X-Control-Token` cuando `ARB_CONTROL_TOKEN` está configurado.
- Adapter inicial `BinanceTestnetAdapter`:
  - soporta sólo `binance` + `BTCUSDT`;
  - sanea cantidad/precio por step/tick;
  - valida `min_qty`, `lot_size`, `min_notional`, balance local y credenciales testnet;
  - no toca red y no serializa secretos.

Frontend:

- Drawer de oportunidad incluye `Testnet preflight`.
- El botón se habilita sólo si la ruta incluye Binance.
- `Test order` se habilita sólo cuando el preflight fue aceptado.

## Pruebas

- `test_preflight_disabled_by_default`
- `test_preflight_requires_control_token`
- `test_preflight_rejects_unknown_venue`
- `test_preflight_checks_min_notional`
- `test_preflight_checks_lot_size`
- `test_test_order_never_runs_without_flag`
- `test_secrets_not_in_response`

## Criterios de aceptación

- Se puede validar una oportunidad contra reglas de exchange sin operar.
- `test-order` queda bloqueado por defecto.
- No hay secretos en logs ni respuestas.
- Tests usan fakes, no red real.
- README documenta modo testnet.

## Riesgos

- API de exchange cambia. Mitigación: encapsular en adapter y test con contratos mínimos.
- Confusión entre testnet y live. Mitigación: settings explícitos y nombres agresivamente claros.
- Superficie de seguridad. Mitigación: token de control, disabled por defecto, sin secretos en output.
