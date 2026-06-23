# PRD-004: Integridad específica por exchange

Estado: Implementado inicial  
Prioridad: P1  
Área: Ingesta, Integridad, Métricas  
Dependencias: ninguna
Arquitectura: [docs/architecture/004-exchange-specific-integrity.md](../architecture/004-exchange-specific-integrity.md)

## Problema

La integridad estructural actual descarta libros vacíos, mal ordenados, cruzados o con regresión de `seq`. Eso es necesario, pero no suficiente. Cada exchange tiene reglas propias de secuencia, snapshots, deltas y checksums. Un book desincronizado puede producir oportunidades matemáticamente correctas pero falsas.

## Objetivo

Agregar validadores específicos por exchange y exponer su estado como métrica y dato de salud.

## No objetivos

- No reemplazar `ccxt.pro`.
- No implementar clientes websocket propios para todos los venues.
- No bloquear venues sin checksum si no ofrecen soporte.

## Alcance inicial

| Exchange | Validación objetivo | Prioridad |
|---|---|---:|
| Binance | `lastUpdateId`, `U/u`, gaps de depth stream | P1 |
| Kraken | checksum CRC32 cuando disponible | P1 |
| Coinbase | sequence/gap handling y stale detection | P1 |
| OKX | checksum/order book sequence si se usa live | P2 |
| Bitfinex | checksum flag si se usa live | P2 |

Implementación inicial:

- `integrity_mode=warn` por defecto: reporta gaps/checksum sin bloquear libros específicos.
- `integrity_mode=enforce`: bloquea también gaps/checksum específicos.
- La validación estructural genérica sigue bloqueando siempre libros vacíos, corruptos,
  cruzados, mal ordenados o con regresión de secuencia.

## Requisitos funcionales

### RF-001 Resultado de integridad enriquecido

Cada venue debe reportar:

- `accepted`
- `rejected`
- `last_reason`
- `last_seq`
- `last_checksum`
- `checksum_failures`
- `sequence_gaps`
- `last_valid_at`
- `validator`

### RF-002 Estrategia por venue

Crear interfaz:

```python
class VenueIntegrityValidator(Protocol):
    def check(self, raw: RawOrderBook) -> IntegrityDecision: ...
```

Implementaciones:

- `GenericIntegrityValidator`
- `BinanceIntegrityValidator`
- `KrakenIntegrityValidator`
- `CoinbaseIntegrityValidator`

### RF-003 Health/API

Extender `/health` y/o agregar:

```http
GET /api/v1/integrity
```

Respuesta:

```json
{
  "binance": {
    "validator": "binance",
    "accepted": 1200,
    "rejected": 2,
    "sequence_gaps": 1,
    "checksum_failures": 0,
    "last_reason": null
  }
}
```

### RF-004 Métricas

Agregar a métricas:

- books rejected por venue.
- gaps por venue.
- checksum failures por venue.
- stale age por venue.

## Cambios técnicos

Archivos:

- `backend/app/integrity/checker.py`
- nuevo `backend/app/integrity/validators.py`
- nuevo `backend/app/integrity/models.py`
- `backend/app/api/health.py`
- `backend/app/api/v1/router.py`
- `backend/app/metrics/collector.py`

Posible cambio de modelo:

- `RawOrderBook` puede necesitar `meta: dict[str, Any] = {}` para campos específicos del exchange.

Implementado:

- `RawOrderBook.meta`.
- `backend/app/integrity/models.py`.
- `backend/app/integrity/validators.py`.
- Registry de validadores Binance/Kraken/Coinbase con fallback generic.
- `GET /api/v1/integrity`.
- `/health` mantiene resumen de integridad enriquecido.
- `/api/v1/metrics` incluye `integrity`.

## Plan de implementación

1. Extraer la validación genérica actual a `GenericIntegrityValidator`.
2. Crear `IntegrityDecision` y `IntegrityReport` extendido.
3. Agregar registry por exchange.
4. Capturar metadata disponible desde ccxt.pro en `_to_raw`.
5. Implementar Binance sequence validator con tests de gaps.
6. Implementar Kraken checksum con fixture pequeño.
7. Exponer `/api/v1/integrity`.
8. Conectar métricas.

## Pruebas

- `test_generic_rejects_crossed_book`
- `test_binance_detects_sequence_gap`
- `test_binance_accepts_monotonic_updates`
- `test_kraken_checksum_failure_rejects_book`
- `test_integrity_endpoint_contract`
- `test_integrity_metrics_increment`

Pruebas implementadas adicionales:

- `test_binance_detects_sequence_gap_in_warn_mode_without_blocking`
- `test_binance_enforce_blocks_sequence_gap`
- `test_binance_accepts_monotonic_updates`
- `test_kraken_checksum_failure_is_visible_in_warn_mode`
- `test_kraken_checksum_passes_when_crc_matches`
- `test_coinbase_sequence_gap_is_visible`

## Criterios de aceptación

- Los validadores genéricos actuales siguen pasando.
- Un gap de secuencia conocido se rechaza y queda visible.
- Un fallo de checksum queda visible por venue.
- Ningún book rechazado actualiza `latest_norm`.
- La UI o health permite saber qué venue está fallando.

## Riesgos

- `ccxt.pro` puede abstraer parte de la metadata. Mitigación: usar `raw`/`nonce` disponible y degradar a generic con `validator="generic"`.
- Checksums varían por formato. Mitigación: fixtures por exchange y documentación exacta.
- Falsos rechazos. Mitigación: rollout por venue con modo `warn` antes de `enforce`.
