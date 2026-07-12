'use client';

import { Badge, Box, Card, Group, Text } from '@mantine/core';
import { IconChartArea } from '@tabler/icons-react';
import type { EdgeCapacity } from '../hooks/useStream';
import { FetchFallback, SectionHeader } from './primitives';

/**
 * Projection Suite v2 — Capa 2: Capacity Curve. Edge neto TOTAL ($) vs capital desplegado Q (BTC):
 * curva cóncava que sube, satura y cae (gross sube ≤ lineal; el coste de impacto/slippage crece
 * más rápido). `Q*` = óptimo donde el edge marginal cruza 0 (capacidad por oportunidad); hard
 * capacity = donde el edge total cruza 0. Responde "¿cuánto capital absorbe la estrategia?".
 * SVG dependency-free. Datos de /api/v1/capacity.
 */

const W = 520;
const H = 200;
const PAD = { l: 44, r: 16, t: 14, b: 28 };

const POS = '#2fd98c';
const NEG = '#f6678a';
const BRAND = '#16D67F';

export function CapacityCurve({
  capacity,
  error = false,
  onRetry,
}: {
  capacity: EdgeCapacity | null;
  error?: boolean;
  onRetry?: () => void;
}) {
  const header = (
    <SectionHeader
      title="Capacity Curve"
      subtitle="edge total $ vs capital desplegado · ¿cuánto absorbe?"
      help="Cuánto capital puede absorber la oportunidad antes de que tu propio volumen mate el edge: comprar/vender en cantidad mueve el precio. La curva se aplana y luego cae; el punto óptimo (Q*) es donde la ganancia total es máxima."
      icon={<IconChartArea size={18} />}
      right={
        capacity ? (
          <Badge variant="light" color={capacity.mode === 'live' ? 'brand' : 'gray'} tt="none">
            {capacity.mode === 'live' && capacity.route
              ? `live ${capacity.route.buy}→${capacity.route.sell}`
              : 'demo'}
          </Badge>
        ) : null
      }
    />
  );

  if (!capacity || capacity.points.length < 2) {
    return (
      <Card h="100%">
        {header}
        {!capacity ? (
          <FetchFallback error={error} onRetry={onRetry} loading="Proyectando capacidad…" />
        ) : (
          <Text size="sm" c="dimmed">Sin puntos suficientes para trazar la curva.</Text>
        )}
      </Card>
    );
  }

  const pts = capacity.points;
  const qs = pts.map((p) => p.q_btc);
  const edges = pts.map((p) => p.edge_total_usd);
  const qMin = Math.min(...qs);
  const qMax = Math.max(...qs);
  const eMin = Math.min(0, ...edges);
  const eMax = Math.max(0, ...edges);
  const span = eMax - eMin || 1;

  const x = (q: number) => PAD.l + ((q - qMin) / (qMax - qMin || 1)) * (W - PAD.l - PAD.r);
  const y = (e: number) => PAD.t + (1 - (e - eMin) / span) * (H - PAD.t - PAD.b);

  const linePath = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(p.q_btc).toFixed(1)},${y(p.edge_total_usd).toFixed(1)}`).join(' ');
  const areaPath =
    `${linePath} L${x(qMax).toFixed(1)},${y(0).toFixed(1)} L${x(qMin).toFixed(1)},${y(0).toFixed(1)} Z`;
  const zeroY = y(0);
  const qStarX = capacity.q_star_btc != null ? x(capacity.q_star_btc) : null;
  const hardX = capacity.hard_capacity_btc != null ? x(capacity.hard_capacity_btc) : null;

  return (
    <Card h="100%">
      {header}
      <Box style={{ overflowX: 'auto' }}>
        <svg
          viewBox={`0 0 ${W} ${H}`}
          width="100%"
          style={{ minWidth: 360 }}
          role="img"
          aria-label={`Curva de capacidad: edge total en dólares frente a capital desplegado de ${qMin.toFixed(2)} a ${qMax.toFixed(2)} BTC a ${capacity.fee_bps.toFixed(1)} bps.${capacity.q_star_btc != null ? ` Óptimo Q* en ${capacity.q_star_btc.toFixed(2)} BTC con ${(capacity.q_star_edge_usd ?? 0).toFixed(1)} dólares por oportunidad.` : ''}${capacity.hard_capacity_btc != null ? ` Capacidad dura: ${capacity.hard_capacity_btc.toFixed(2)} BTC.` : ''}`}
        >
          {/* eje cero */}
          <line x1={PAD.l} y1={zeroY} x2={W - PAD.r} y2={zeroY} stroke="rgba(255,255,255,0.18)" strokeDasharray="3 3" />
          {/* área + línea de edge total */}
          <path d={areaPath} fill="rgba(47,217,140,0.10)" />
          <path d={linePath} fill="none" stroke={POS} strokeWidth={2} />
          {/* hard capacity (edge total cruza 0) */}
          {hardX != null && (
            <line x1={hardX} y1={PAD.t} x2={hardX} y2={H - PAD.b} stroke={NEG} strokeWidth={1} strokeDasharray="4 3" />
          )}
          {/* Q* óptimo */}
          {qStarX != null && (
            <>
              <line x1={qStarX} y1={PAD.t} x2={qStarX} y2={H - PAD.b} stroke={BRAND} strokeWidth={1.5} />
              <circle cx={qStarX} cy={y(capacity.q_star_edge_usd ?? 0)} r={3.5} fill={BRAND} />
            </>
          )}
          {/* etiquetas de ejes */}
          <text x={PAD.l} y={H - 8} fontSize="9" fill="rgba(255,255,255,0.62)">{qMin.toFixed(2)} BTC</text>
          <text x={W - PAD.r} y={H - 8} fontSize="9" fill="rgba(255,255,255,0.62)" textAnchor="end">{qMax.toFixed(2)} BTC</text>
          <text x={6} y={PAD.t + 8} fontSize="9" fill="rgba(255,255,255,0.62)">${eMax.toFixed(0)}</text>
        </svg>
      </Box>

      <Group gap="lg" mt="xs" wrap="wrap">
        {capacity.q_star_btc != null && (
          <Text fz={11} c="dimmed">
            Q* óptimo:{' '}
            <Text span c="brand.4" fw={700} ff="monospace">
              {capacity.q_star_btc.toFixed(2)} BTC → +${(capacity.q_star_edge_usd ?? 0).toFixed(1)}/opp
            </Text>
          </Text>
        )}
        {capacity.hard_capacity_btc != null && (
          <Text fz={11} c="dimmed">
            hard capacity:{' '}
            <Text span style={{ color: NEG }} fw={700} ff="monospace">
              {capacity.hard_capacity_btc.toFixed(2)} BTC
            </Text>
          </Text>
        )}
        <Badge variant="light" color="gray" tt="none">fee {capacity.fee_bps.toFixed(1)} bps</Badge>
      </Group>

      <Text size="xs" c="dimmed" mt={8} lh={1.4}>
        Curva cóncava: cada BTC adicional rinde menos (slippage del libro). El edge marginal cae a
        cero en Q* — más allá, desplegar más capital destruye edge. Overlay teórico square-root law
        (Donier-Bonart, δ≈0.5 en BTC).
      </Text>
    </Card>
  );
}
