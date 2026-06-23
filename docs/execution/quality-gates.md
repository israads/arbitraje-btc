# Quality gates

Estos gates aplican a todos los PRDs. Si una mejora toca ejecución, datos live o decisiones de trading, no se considera terminada sin pasar los gates correspondientes.

## Gate 1: Compatibilidad

- Endpoints existentes mantienen respuesta compatible.
- Campos nuevos son opcionales si viajan en objetos existentes.
- UI tolera ausencia de datos nuevos.
- No se rompe modo autostart-safe de tests.

## Gate 2: Seguridad operacional

- Ejecución real desactivada por defecto.
- Test orders requieren flag explícito y token de control.
- Ninguna respuesta contiene API keys, secrets, signatures o headers privados.
- Logs usan payload saneado.
- Demo y replay siempre se etiquetan como no live.

## Gate 3: Correctitud financiera

- No se duplica la fórmula económica fuera de `ExecutionCostModel`.
- Cambios de VWAP se comparan contra `walk_book`.
- Cambios de `P_survive` empiezan en observe-only.
- USD/USDT/MXN no se mezclan sin factor de conversión visible.

## Gate 4: Integridad de datos

- Book rechazado no actualiza `latest_norm`.
- Validadores nuevos tienen modo `warn` antes de `enforce`.
- Gaps/checksums se exponen en health o endpoint.
- Stale feed no puede producir oportunidad ejecutable.

## Gate 5: Observabilidad

- Cada nuevo módulo expone estado mínimo.
- Cada descarte nuevo tiene razón enumerada.
- Métricas nuevas tienen labels acotados.
- Errores importantes tienen log estructurado.

## Gate 6: Pruebas

Mínimo por tipo de cambio:

- Modelos: serialización y defaults.
- Builders puros: unit tests.
- Endpoints: contrato 200/error.
- UI: estados empty/loading/error si aplica.
- Integración: no regresión de smoke principal.

Comandos objetivo:

```bash
cd backend
uv run pytest

cd frontend
npm run lint
npm run typecheck
```

Si algún comando no existe todavía, se documenta y se crea tarea para agregarlo.

## Gate 7: Documentación

- PRD actualizado si cambia alcance.
- Arquitectura actualizada si cambia diseño.
- README actualizado si hay nuevo endpoint/config.
- Runbook actualizado si afecta operación.

