'use client';

import { memo, useMemo } from 'react';
import { ActionIcon, Badge, Card, Group, Table, Text, Tooltip } from '@mantine/core';
import { IconArrowNarrowRight, IconInfoCircle, IconTargetArrow } from '@tabler/icons-react';
import type { RouteStat } from '../hooks/useStream';
import { SectionHeader, VenueTag } from './primitives';

const STATUS_COLOR: Record<string, string> = {
  detected: 'aqua',
  viable: 'brand',
  executable: 'brand',
  captured: 'grape',
  discarded: 'gray',
};

const STATUS_LABEL: Record<string, string> = {
  detected: 'detectada',
  viable: 'viable',
  executable: 'ejecutable',
  captured: 'capturada',
  discarded: 'descartada',
};

const REASON_LABEL: Record<string, string> = {
  not_profitable_fees: 'No rentable (fees)',
  thin_book: 'Libro fino',
  peg_adverse: 'Peg adverso',
  slippage_over_limit: 'Slippage > límite',
  breaker_active: 'Breaker activo',
  stale_venue: 'Venue stale',
  insufficient_balance: 'Saldo insuficiente',
  z_below_threshold: 'z bajo umbral',
};

function fmt(n: number | null | undefined, signed = false): string {
  if (n == null || !Number.isFinite(n)) return '—';
  const s = n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return signed && n > 0 ? `+${s}` : s;
}

/**
 * Estadísticas por ruta de arbitraje (acumuladas en sesión por `useStream`). Colapsa el
 * firehose de detecciones a UNA fila por ruta y expone las cifras que deciden:
 *  · Bruto $/BTC  → lo que "parece" (vwap_sell − vwap_buy).
 *  · Neto $/BTC   → lo real tras fees/slippage (net_pnl / q_target); normalmente negativo.
 *  · Mejor neto   → mejor neto histórico visto en la sesión (¿hubo algún momento rentable?).
 *  · % viable     → de las detecciones de esa ruta, cuántas pasaron el filtro neto.
 * Orden estable por neto desc (sin parpadeo).
 */
export const OpportunitiesTable = memo(OpportunitiesTableImpl);

function OpportunitiesTableImpl({
  routeStats,
  detectedCount,
  onExplain,
}: {
  routeStats: RouteStat[];
  detectedCount: number;
  onExplain?: (opportunityId: string) => void;
}) {
  const rows = useMemo(
    () =>
      [...routeStats].sort((a, b) => {
        const an = a.lastNetPerBtc ?? -Infinity;
        const bn = b.lastNetPerBtc ?? -Infinity;
        if (bn !== an) return bn - an;
        return a.route.localeCompare(b.route);
      }),
    [routeStats],
  );

  return (
    <Card>
      <SectionHeader
        title="Estadísticas por ruta"
        subtitle="bruto = lo que parece · neto = lo real tras fees/slippage (decide)"
        icon={<IconTargetArrow size={18} />}
        right={
          <Group gap="xs">
            <Badge variant="default" color="gray">
              {rows.length} rutas
            </Badge>
            <Badge variant="light" color="aqua" size="lg">
              {detectedCount.toLocaleString()} detectadas
            </Badge>
          </Group>
        }
      />
      <Table.ScrollContainer minWidth={880}>
        <Table highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Ruta</Table.Th>
              <Table.Th ta="right">Bruto $/BTC</Table.Th>
              <Table.Th ta="right">Neto $/BTC</Table.Th>
              <Table.Th ta="right">Mejor neto</Table.Th>
              <Table.Th ta="right">% viable</Table.Th>
              <Table.Th>Motivo descarte</Table.Th>
              <Table.Th ta="right">Estado</Table.Th>
              <Table.Th ta="right">Detalle</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.length === 0 && (
              <Table.Tr>
                <Table.Td colSpan={8}>
                  <Text c="dimmed" size="sm" py="md" ta="center">
                    Sin oportunidades aún (mercado eficiente o feeds cargando)…
                  </Text>
                </Table.Td>
              </Table.Tr>
            )}
            {rows.map((r) => {
              const net = r.lastNetPerBtc;
              const best = r.bestNetPerBtc;
              const viablePct = r.detected > 0 ? (r.viable / r.detected) * 100 : 0;
              return (
                <Table.Tr key={r.route}>
                  <Table.Td>
                    <Group gap={6} wrap="nowrap" align="center">
                      <VenueTag name={r.buy_venue} fw={500} />
                      <IconArrowNarrowRight size={16} color="var(--mantine-color-dark-2)" />
                      <VenueTag name={r.sell_venue} fw={500} />
                      <Tooltip label={`${r.detected.toLocaleString()} detecciones en sesión`} withArrow>
                        <Text size="xs" c="dimmed" ff="monospace" ml={4}>
                          ×{r.detected.toLocaleString()}
                        </Text>
                      </Tooltip>
                    </Group>
                  </Table.Td>
                  <Table.Td
                    ta="right"
                    ff="monospace"
                    className="mono-nums"
                    c={r.lastGrossPerBtc != null && r.lastGrossPerBtc > 0 ? 'dark.1' : 'dimmed'}
                  >
                    {fmt(r.lastGrossPerBtc, true)}
                  </Table.Td>
                  <Table.Td
                    ta="right"
                    ff="monospace"
                    className="mono-nums"
                    fw={700}
                    c={net == null ? 'dimmed' : net >= 0 ? 'brand.4' : 'red.4'}
                  >
                    {fmt(net, true)}
                  </Table.Td>
                  <Table.Td
                    ta="right"
                    ff="monospace"
                    className="mono-nums"
                    c={best == null ? 'dimmed' : best >= 0 ? 'brand.4' : 'dark.2'}
                  >
                    {fmt(best, true)}
                  </Table.Td>
                  <Table.Td ta="right">
                    <Text
                      component="span"
                      size="sm"
                      ff="monospace"
                      className="mono-nums"
                      fw={600}
                      c={viablePct > 0 ? 'brand.4' : 'dimmed'}
                    >
                      {viablePct.toFixed(viablePct > 0 && viablePct < 1 ? 2 : 1)}%
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    {r.lastReason ? (
                      <Badge variant="default" color="gray" tt="none" size="sm">
                        {REASON_LABEL[r.lastReason] ?? r.lastReason}
                      </Badge>
                    ) : (
                      <Text size="xs" c="dimmed">
                        —
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td ta="right">
                    <Badge variant="dot" color={STATUS_COLOR[r.lastStatus] ?? 'gray'} tt="none">
                      {STATUS_LABEL[r.lastStatus] ?? r.lastStatus}
                    </Badge>
                  </Table.Td>
                  <Table.Td ta="right">
                    <Tooltip label="Explicar última oportunidad de esta ruta" withArrow>
                      <ActionIcon
                        variant="subtle"
                        color="aqua"
                        aria-label="Explicar oportunidad"
                        disabled={!r.lastOpportunityId || !onExplain}
                        onClick={() => r.lastOpportunityId && onExplain?.(r.lastOpportunityId)}
                      >
                        <IconInfoCircle size={18} />
                      </ActionIcon>
                    </Tooltip>
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      <Text size="xs" c="dimmed" mt="sm">
        El <Text span c="dark.1" fw={600}>bruto</Text> parece ganancia, pero el{' '}
        <Text span c="red.4" fw={600}>neto</Text> tras fees/slippage suele ser negativo →{' '}
        <Text span c="brand.4" fw={600}>% viable</Text> ≈ 0. Esa brecha <b>es la tesis</b>: el
        mercado está casi arbitrado.
      </Text>
    </Card>
  );
}
