'use client';

import { Badge, Box, Card, Group, SimpleGrid, Text, Tooltip } from '@mantine/core';
import { IconChartLine } from '@tabler/icons-react';
import type { ForwardProjection } from '../hooks/useStream';
import { FetchFallback, SectionHeader } from './primitives';

/**
 * Projection Suite v2 — Capa 3: Forward de P&L (Monte Carlo honesto). Fan chart de equity
 * proyectada (bandas P5/P25/P50/P75/P95) por bootstrap ESTACIONARIO de la distribución empírica
 * de P&L por trade (no i.i.d.: las oportunidades llegan en ráfagas). Panel de honestidad
 * estadística: Sharpe, PSR, Deflated Sharpe y MinTRL (López de Prado). NO es un pronóstico: es
 * la dispersión consistente con la muestra. Si la mediana/P5 cae bajo 0, el edge no es defendible.
 */

const W = 520;
const H = 190;
const PAD = { l: 44, r: 16, t: 12, b: 24 };
const POS = '#2fd98c';
const NEG = '#f6678a';

function pct(n: number | null): string {
  return n == null ? '—' : `${(n * 100).toFixed(0)}%`;
}
function num(n: number | null, d = 2): string {
  return n == null ? '—' : n.toFixed(d);
}

function Stat({ label, value, hint, color }: { label: string; value: string; hint: string; color?: string }) {
  return (
    <Tooltip label={hint} withArrow multiline w={240}>
      <Box>
        <Text fz={9} tt="uppercase" c="dimmed" fw={700} style={{ letterSpacing: 0 }}>
          {label}
        </Text>
        <Text ff="monospace" className="mono-nums" fz="sm" fw={700} c={color}>
          {value}
        </Text>
      </Box>
    </Tooltip>
  );
}

export function ForwardFanChart({
  forward,
  error = false,
  onRetry,
}: {
  forward: ForwardProjection | null;
  error?: boolean;
  onRetry?: () => void;
}) {
  const header = (
    <SectionHeader
      title="Proyección forward de P&L"
      subtitle="Monte Carlo honesto · dispersión, no pronóstico"
      help="Simula miles de futuros posibles remuestreando la serie real de P&L de la sesión. Las bandas (P5–P95) muestran el rango probable; no es una predicción, es la dispersión consistente con los datos. Incluye prob. de ganancia, de ruina y Sharpe/PSR (si el rendimiento es real o suerte)."
      icon={<IconChartLine size={18} />}
      right={
        forward?.available ? (
          <Badge variant="light" color="gray" tt="none">
            {forward.n_paths.toLocaleString('en-US')} paths · {forward.n_trades} trades
          </Badge>
        ) : null
      }
    />
  );

  if (!forward || !forward.available) {
    return (
      <Card h="100%">
        {header}
        {!forward ? (
          <FetchFallback error={error} onRetry={onRetry} loading="Simulando trayectorias…" />
        ) : (
          <Text size="sm" c="dimmed">
            {forward.notes ||
              'Sin trades suficientes en la grabación. Deja correr el motor para poblar la muestra de P&L por trade.'}
          </Text>
        )}
      </Card>
    );
  }

  const { bands } = forward;
  const steps = bands.step;
  const allVals = [...bands.p5, ...bands.p95, 0];
  const yMin = Math.min(...allVals);
  const yMax = Math.max(...allVals);
  const span = yMax - yMin || 1;
  const n = steps.length;

  const x = (i: number) => PAD.l + (i / (n - 1 || 1)) * (W - PAD.l - PAD.r);
  const y = (v: number) => PAD.t + (1 - (v - yMin) / span) * (H - PAD.t - PAD.b);

  const band = (lo: number[], hi: number[]) => {
    const up = hi.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
    const down = lo
      .map((v, i) => `L${x(n - 1 - i).toFixed(1)},${y(lo[n - 1 - i]).toFixed(1)}`)
      .join(' ');
    return `${up} ${down} Z`;
  };
  const line = (vals: number[]) =>
    vals.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');

  const profitColor = (forward.terminal_p50 ?? 0) >= 0 ? POS : NEG;

  return (
    <Card h="100%">
      {header}
      <Box style={{ overflowX: 'auto' }}>
        <svg
          viewBox={`0 0 ${W} ${H}`}
          width="100%"
          style={{ minWidth: 360 }}
          role="img"
          aria-label={`Fan chart de P&L proyectado a ${n} trades sobre ${forward.n_paths.toLocaleString('en-US')} trayectorias: mediana terminal $${num(forward.terminal_p50, 0)}, banda P5 $${num(forward.terminal_p5, 0)} a P95 $${num(forward.terminal_p95, 0)}, probabilidad de ganancia ${pct(forward.prob_profit)}.`}
        >
          <line x1={PAD.l} y1={y(0)} x2={W - PAD.r} y2={y(0)} stroke="rgba(255,255,255,0.18)" strokeDasharray="3 3" />
          <path d={band(bands.p5, bands.p95)} fill="rgba(47,217,140,0.08)" />
          <path d={band(bands.p25, bands.p75)} fill="rgba(47,217,140,0.16)" />
          <path d={line(bands.p50)} fill="none" stroke={profitColor} strokeWidth={2} />
          <text x={6} y={PAD.t + 8} fontSize="9" fill="rgba(255,255,255,0.62)">${yMax.toFixed(0)}</text>
          <text x={6} y={H - PAD.b} fontSize="9" fill="rgba(255,255,255,0.62)">${yMin.toFixed(0)}</text>
          <text x={W - PAD.r} y={H - 6} fontSize="9" fill="rgba(255,255,255,0.62)" textAnchor="end">
            +{n} trades
          </text>
        </svg>
      </Box>

      <SimpleGrid cols={{ base: 2, xs: 3, sm: 4 }} spacing="sm" mt="xs">
        <Stat
          label="P(P&L>0)"
          value={pct(forward.prob_profit)}
          color={(forward.prob_profit ?? 0) >= 0.5 ? POS : NEG}
          hint="Fracción de trayectorias bootstrap con P&L terminal positivo."
        />
        <Stat
          label="P&L medio"
          value={`$${num(forward.terminal_p50, 0)}`}
          color={profitColor}
          hint="Mediana del P&L terminal (P5..P95 en el fan chart)."
        />
        <Stat
          label="Max DD p95"
          value={`$${num(forward.max_dd_p95, 0)}`}
          color={NEG}
          hint="Drawdown máximo en el percentil 95 de las simulaciones (riesgo de cola)."
        />
        <Stat
          label="Sharpe/trade"
          value={num(forward.sharpe_per_trade)}
          color={(forward.sharpe_per_trade ?? 0) >= 0 ? POS : NEG}
          hint="Sharpe por trade (no anualizado). Puntual: ver PSR/DSR para significancia."
        />
        <Stat
          label="PSR"
          value={pct(forward.psr)}
          hint="Probabilistic Sharpe Ratio: prob. de que el Sharpe verdadero sea > 0 (Bailey & López de Prado)."
        />
        <Stat
          label="Deflated SR"
          value={pct(forward.dsr)}
          hint={`Deflated Sharpe: PSR corregido por las ${forward.n_configs} configuraciones probadas (multiple testing) y no-normalidad.`}
        />
        <Stat
          label="MinTRL"
          value={forward.min_trl == null ? '∞' : `${Math.round(forward.min_trl)}`}
          hint="Minimum Track Record Length: nº de trades necesarios para significancia al 95%. ∞ = no alcanzable con este edge."
        />
        <Stat
          label="P(ruina)"
          value={pct(forward.prob_ruin)}
          color={(forward.prob_ruin ?? 0) > 0.05 ? NEG : undefined}
          hint="Fracción de trayectorias que pierden toda la ganancia histórica acumulada."
        />
      </SimpleGrid>

      <Text size="xs" c="dimmed" mt={8} lh={1.4}>
        No es un pronóstico: es la dispersión de resultados consistente con la muestra histórica
        (bootstrap estacionario). Si la mediana o el P5 cruzan 0, el edge no es defendible tras
        costes — y eso es lo honesto en un mercado casi eficiente.
      </Text>
    </Card>
  );
}
