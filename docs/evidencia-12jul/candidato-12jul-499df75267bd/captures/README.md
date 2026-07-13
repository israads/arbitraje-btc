# Capturas — candidato-12jul

- **Fecha**: 2026-07-12T18:10-06:00 (America/Mexico_City)
- **Tag**: `candidato-12jul` · **SHA**: `499df75267bd49ec5fd8f54e01e43ee3f03f30c3`
- **Modo**: **JURY · LOCAL** — stack compose de producción en http://localhost:8090, demo `jury` activo
- **Método**: Chrome headless (`/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`)
  controlado por CDP con espera de 15 s tras `Page.navigate` para que el SSE conecte y el
  dashboard pinte datos en vivo. `--screenshot` plano dispara en el evento `load`, antes de que
  conecte el stream (badge CONECTANDO), y `--virtual-time-budget` se cuelga con el SSE abierto —
  por eso la espera explícita vía CDP.

| Archivo | Viewport | Contenido |
|---|---|---|
| `resumen-desktop.png` | 1600×2400 | Pestaña Resumen (por defecto): header con badges READ-ONLY DEMO / DEMO DATA / EN VIVO, KPIs P&L, Tesis de negocio, Naive vs Edge, spread cross-venue, P&L total, Evidencia de ganancias (2 capturas rentables) |
| `resumen-desktop-1600x1000.png` | 1600×1000 | Misma pestaña por defecto, viewport desktop estándar |

`resumen-desktop.png` se copió como `assets/dashboard.png` (regeneración pedida por el plan;
entra en el commit de evidencia, el tag no se mueve).
