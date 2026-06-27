'use client';

import { memo } from 'react';
import { Badge, Card, Grid, Group, Progress, Stack, Table, Text, Title } from '@mantine/core';
import { IconFilter } from '@tabler/icons-react';
import type { Metrics } from '../hooks/useStream';
import { SectionHeader } from './primitives';

function fmt(n: number | null | undefined, d = 2): string {
  return n == null || !Number.isFinite(n)
    ? '—'
    : n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
}

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

const STAGES: { key: keyof Metrics; label: string; color: string }[] = [
  { key: 'detected', label: 'Detectadas', color: 'aqua' },
  { key: 'viable', label: 'Viables', color: 'teal' },
  { key: 'executable', label: 'Ejecutables', color: 'brand' },
  { key: 'captured', label: 'Capturadas', color: 'grape' },
];

/**
 * Embudo del jurado (C13): detectadas→viables→ejecutables→capturadas con motivo de
 * descarte, microestructura (effective/expected/realized/impact) y latencia p50/p99.
 */
export const FunnelPanel = memo(FunnelPanelImpl);

function FunnelPanelImpl({ metrics }: { metrics: Metrics | null }) {
  const m = metrics;
  const detected = m?.detected ?? 0;
  const reasons = Object.entries(m?.discard_reasons ?? {}).sort((a, b) => b[1] - a[1]);

  return (
    <Card h="100%">
      <SectionHeader
        title="Embudo de decisiones"
        subtitle="detectadas → viables → ejecutables → capturadas"
        icon={<IconFilter size={18} />}
        right={
          <Group gap="xs">
            <Badge variant="light" color="aqua">
              p50 {fmt(m?.p50_ms, 3)} ms
            </Badge>
            <Badge variant="default" color="gray">
              p99 {fmt(m?.p99_ms, 3)} ms
            </Badge>
          </Group>
        }
      />

      <Stack gap={10} mb="lg">
        {STAGES.map((s) => {
          const v = (m?.[s.key] as number | undefined) ?? 0;
          const pct = detected > 0 ? (v / detected) * 100 : 0;
          return (
            <div key={s.key}>
              <Group justify="space-between" gap="xs" mb={4}>
                <Text size="sm" fw={500}>
                  {s.label}
                </Text>
                <Text size="sm" ff="monospace" className="mono-nums" c="dimmed">
                  {v.toLocaleString()}{' '}
                  <Text span c={`${s.color}.4`} fw={600}>
                    {pct.toFixed(1)}%
                  </Text>
                </Text>
              </Group>
              <Progress value={pct} color={s.color} size="md" radius="xl" />
            </div>
          );
        })}
        <Group justify="space-between" gap="xs" mt={2}>
          <Text size="sm" c="dimmed">
            Descartadas
          </Text>
          <Text size="sm" ff="monospace" className="mono-nums" c="dimmed">
            {(m?.discarded ?? 0).toLocaleString()}
            {m?.unwound ? ` · ${m.unwound} unwind` : ''}
          </Text>
        </Group>
      </Stack>

      <Grid gutter="lg">
        <Grid.Col span={{ base: 12, sm: 6 }}>
          <Title order={6} mb={6} c="dimmed" tt="uppercase" fz={11} style={{ letterSpacing: 0 }}>
            Microestructura (USD/BTC)
          </Title>
          <Table fz="sm" withRowBorders={false} verticalSpacing={6} horizontalSpacing={0}>
            <Table.Tbody>
              <Tr label="Effective (bruto)" value={`$${fmt(m?.effective_spread)}`} />
              <Tr label="Esperado neto (C6)" value={`$${fmt(m?.expected_net_spread)}`} hint="modelo pre-trade" />
              <Tr
                label="Realized (real)"
                value={m?.realized_spread != null ? `$${fmt(m.realized_spread)}` : '— (sin capturas)'}
              />
              <Tr label="Price impact" value={`$${fmt(m?.price_impact)}`} hint="coste fees+slippage" />
              <Tr label="Capture ratio" value={m?.capture_ratio != null ? `${(m.capture_ratio * 100).toFixed(2)}%` : '—'} />
              <Tr label="Fill ratio" value={m?.fill_ratio != null ? `${(m.fill_ratio * 100).toFixed(1)}%` : '—'} />
            </Table.Tbody>
          </Table>
        </Grid.Col>
        <Grid.Col span={{ base: 12, sm: 6 }}>
          <Title order={6} mb={6} c="dimmed" tt="uppercase" fz={11} style={{ letterSpacing: 0 }}>
            Descartes por motivo
          </Title>
          {reasons.length === 0 ? (
            <Text size="sm" c="dimmed">
              Sin descartes aún…
            </Text>
          ) : (
            <Stack gap={6}>
              {reasons.map(([reason, count]) => (
                <Group key={reason} justify="space-between" gap="xs">
                  <Text size="sm" c="dark.1">
                    {REASON_LABEL[reason] ?? reason}
                  </Text>
                  <Text size="sm" ff="monospace" className="mono-nums" fw={600}>
                    {count.toLocaleString()}
                  </Text>
                </Group>
              ))}
            </Stack>
          )}
          {m?.by_strategy && Object.keys(m.by_strategy).length > 0 && (
            <>
              <Title order={6} mt="md" mb={6} c="dimmed" tt="uppercase" fz={11} style={{ letterSpacing: 0 }}>
                Por estrategia
              </Title>
              <Stack gap={2}>
                {Object.entries(m.by_strategy).map(([strat, counts]) => (
                  <Text key={strat} size="xs" ff="monospace" className="mono-nums" c="dimmed">
                    {strat}: {Object.entries(counts).map(([k, v]) => `${k}=${v}`).join(' ')}
                  </Text>
                ))}
              </Stack>
            </>
          )}
        </Grid.Col>
      </Grid>
    </Card>
  );
}

function Tr({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Table.Tr>
      <Table.Td>
        <Text size="sm" c="dark.1">
          {label}
        </Text>
        {hint && (
          <Text size="xs" c="dimmed">
            {hint}
          </Text>
        )}
      </Table.Td>
      <Table.Td ta="right" ff="monospace" className="mono-nums" fw={600}>
        {value}
      </Table.Td>
    </Table.Tr>
  );
}
