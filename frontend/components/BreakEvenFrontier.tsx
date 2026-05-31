'use client';

import { Badge, Box, Card, Group, Text, Tooltip } from '@mantine/core';
import { IconGridDots } from '@tabler/icons-react';
import type { EdgeFrontier, FrontierBestCell } from '../hooks/useStream';
import { SectionHeader } from './primitives';

/**
 * Projection Suite v2 — Capa 1: Break-even Frontier (Execution-Conditioned). Heatmap tamaño ×
 * fee tier; cada celda = edge NETO/BTC con la aritmética real del pipeline (cost_model). El
 * tooltip añade coste dominante (por qué muere) y P_survive (prob. de sobrevivir la latencia).
 * Verde = sobrevive; rojo = muere. Modo demo (determinista) o live (ruta de mayor spread).
 * Cuenta la tesis: el edge no muere por velocidad sino por fees, profundidad y rebalanceo.
 */

const CAP = 40; // clamp USD/BTC para la intensidad de color
function cellColor(net: number | null): string {
  if (net == null) return 'rgba(255,255,255,0.03)';
  const t = Math.max(-1, Math.min(1, net / CAP));
  if (t >= 0) return `rgba(47, 217, 140, ${0.1 + t * 0.72})`; // --pos
  return `rgba(246, 103, 138, ${0.1 + -t * 0.72})`; // --neg
}

const money = (n: number) => `${n >= 0 ? '+' : ''}${n.toFixed(1)}`;
const COST_LABEL: Record<string, string> = {
  fees: 'fees', slippage: 'slippage', rebalance: 'rebalanceo', none: '—',
};

function BestChip({ label, cell }: { label: string; cell: FrontierBestCell | null }) {
  if (!cell) return null;
  return (
    <Text fz={10} c="dimmed">
      {label}:{' '}
      <Text span c="brand.4" fw={700} ff="monospace">
        {cell.size_btc} BTC @ {cell.fee_bps.toFixed(1)}bps → +{cell.net_per_btc.toFixed(1)} $/BTC
      </Text>
    </Text>
  );
}

export function BreakEvenFrontier({ frontier }: { frontier: EdgeFrontier | null }) {
  if (!frontier) {
    return (
      <Card h="100%">
        <SectionHeader
          title="Break-even Frontier"
          subtitle="dónde sobrevive el edge · tamaño × fee tier"
          icon={<IconGridDots size={18} />}
        />
        <Text size="sm" c="dimmed">Proyectando edge ejecutable…</Text>
      </Card>
    );
  }

  const {
    sizes_btc, fee_tiers, matrix, depth_limited, dominant_cost, p_survive, best,
    gross_top_per_btc, mode, route,
  } = frontier;

  return (
    <Card h="100%">
      <SectionHeader
        title="Break-even Frontier"
        subtitle="edge neto $/BTC proyectado · tamaño × fee tier"
        icon={<IconGridDots size={18} />}
        right={
          <Group gap={6} wrap="nowrap">
            <Badge variant="light" color={mode === 'live' ? 'brand' : 'gray'} tt="none">
              {mode === 'live' && route ? `live ${route.buy}→${route.sell}` : 'demo'}
            </Badge>
            <Badge variant="light" color="gray" tt="none">
              bruto top {gross_top_per_btc.toFixed(0)} $/BTC
            </Badge>
          </Group>
        }
      />

      <Box style={{ overflowX: 'auto' }}>
        <Box style={{ minWidth: 440 }}>
          <Box
            style={{
              display: 'grid',
              gridTemplateColumns: `54px repeat(${sizes_btc.length}, 1fr)`,
              gap: 3,
              marginBottom: 3,
            }}
          >
            <Text fz={9} c="dimmed" fw={700} tt="uppercase" style={{ alignSelf: 'end' }}>
              fee↓ size→
            </Text>
            {sizes_btc.map((s) => (
              <Text key={s} fz={10} c="dimmed" ff="monospace" ta="center" fw={600}>
                {s < 1 ? s : Math.round(s * 100) / 100}
              </Text>
            ))}
          </Box>

          {fee_tiers.map((tier, i) => (
            <Box
              key={tier.label}
              style={{
                display: 'grid',
                gridTemplateColumns: `54px repeat(${sizes_btc.length}, 1fr)`,
                gap: 3,
                marginBottom: 3,
              }}
            >
              <Tooltip label={`${tier.label} · ${tier.bps.toFixed(1)} bps taker`} withArrow position="left">
                <Text fz={10} c="dimmed" ff="monospace" fw={600} style={{ alignSelf: 'center' }}>
                  {tier.bps.toFixed(1)}
                </Text>
              </Tooltip>
              {matrix[i].map((net, j) => {
                const isBest =
                  best.by_unit_edge != null &&
                  best.by_unit_edge.fee_bps === tier.bps &&
                  best.by_unit_edge.size_btc === sizes_btc[j];
                const dl = depth_limited[i][j];
                const ps = p_survive[i]?.[j];
                const dc = dominant_cost[i]?.[j] ?? 'none';
                return (
                  <Tooltip
                    key={j}
                    withArrow
                    multiline
                    label={
                      net == null
                        ? 'sin liquidez'
                        : `${sizes_btc[j]} BTC · ${tier.bps.toFixed(1)}bps → ${money(net)} $/BTC` +
                          `\ncoste dominante: ${COST_LABEL[dc] ?? dc}` +
                          (ps != null ? `\nP(sobrevive) ${(ps * 100).toFixed(0)}%` : '') +
                          (dl ? '\n(profundidad limitada)' : '')
                    }
                  >
                    <Box
                      style={{
                        height: 30,
                        borderRadius: 5,
                        background: cellColor(net),
                        border: isBest
                          ? '1.5px solid var(--brand)'
                          : '1px solid rgba(255,255,255,0.04)',
                        boxShadow: isBest ? '0 0 12px -2px rgba(22,214,127,0.7)' : 'none',
                        display: 'grid',
                        placeItems: 'center',
                      }}
                    >
                      <Text
                        fz={9.5}
                        ff="monospace"
                        fw={600}
                        c={net != null && Math.abs(net) > 6 ? '#0a0e16' : 'dimmed'}
                      >
                        {net == null ? '·' : money(net)}
                      </Text>
                    </Box>
                  </Tooltip>
                );
              })}
            </Box>
          ))}
        </Box>
      </Box>

      <Group justify="space-between" mt="sm" gap="xs" wrap="wrap">
        <Group gap={6}>
          <Box w={12} h={12} style={{ borderRadius: 3, background: cellColor(CAP) }} />
          <Text fz={10} c="dimmed">capturable</Text>
          <Box w={12} h={12} ml={8} style={{ borderRadius: 3, background: cellColor(-CAP) }} />
          <Text fz={10} c="dimmed">muere por costes</Text>
        </Group>
      </Group>

      {/* F3 — tres óptimos: por edge unitario, por edge total y ajustado a riesgo */}
      <Group gap="lg" mt={6} wrap="wrap">
        <BestChip label="mejor $/BTC" cell={best.by_unit_edge} />
        <BestChip label="mejor $ total" cell={best.by_total_edge} />
        <BestChip label="mejor ajustado a riesgo" cell={best.by_risk_adjusted} />
      </Group>

      <Text size="xs" c="dimmed" mt={8} lh={1.4}>
        El edge no muere por velocidad: lo matan fees, profundidad y rebalanceo. Tamaños diminutos
        los penaliza el coste fijo de rebalanceo; los grandes, el slippage del libro. P(sobrevive)
        pondera la deriva durante la latencia.
      </Text>
    </Card>
  );
}
