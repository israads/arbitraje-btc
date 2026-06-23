# Runbook: testnet preflight

## Síntoma

- Preflight falla.
- Test order es rechazado.
- Endpoint de ejecución devuelve disabled o unauthorized.

## Revisar

```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/v1/execution/status
```

Variables esperadas cuando PRD-003 esté implementado:

- `ARB_EXECUTION_MODE=testnet`
- `ARB_ENABLE_TEST_ORDERS=true`
- `ARB_BINANCE_TESTNET_API_KEY`
- `ARB_BINANCE_TESTNET_API_SECRET`
- token de control presente

Para validar sólo reglas locales, sin test order:

```bash
ARB_EXECUTION_MODE=dry_run
```

Para probar endpoints:

```bash
curl http://localhost:8000/api/v1/execution/status

curl -X POST http://localhost:8000/api/v1/execution/preflight \
  -H 'Content-Type: application/json' \
  -H "X-Control-Token: $ARB_CONTROL_TOKEN" \
  -d '{
    "venue": "binance",
    "side": "buy",
    "symbol": "BTCUSDT",
    "quantity_btc": 0.001,
    "order_type": "market",
    "reference_price": 70000
  }'
```

## Acción segura

- Confirmar que el modo no es live.
- Revisar min notional, lot size, precision y balance testnet.
- Revisar payload saneado.
- Confirmar que la respuesta no contiene API key, secret ni firma.

Nota: la implementación inicial usa adapter offline determinista. No toca red ni dinero real;
la conexión firmada a Binance Spot Testnet queda como siguiente hardening.

## No hacer

- No cambiar a credenciales live para "probar rápido".
- No imprimir secretos.
- No activar test orders sin token de control.

## Recuperación

El incidente se considera resuelto cuando:

- Preflight pasa todos los checks.
- Test order devuelve accepted en testnet o endpoint oficial de test.
- La respuesta no contiene secretos.
