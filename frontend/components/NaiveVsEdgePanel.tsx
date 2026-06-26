'use client';

import { Badge, Box, Card, Group, Progress, Stack, Text, Tooltip } from '@mantine/core';
import { IconScale, IconArrowDownRight } from '@tabler/icons-react';
import type { NaiveVsEdgeReport } from '../hooks/useStream';
import { NEG, POS, SectionHeader } from './primitives';

/**
 * Panel Naive-vs-Edge: la tesis del motor hecha agregado de sesión. Un detector de spreads
 * ingenuo tradearía toda diferencia bruta positiva; este motor descuenta fees, latencia y peg
 * y solo captura lo que sobrevive. Contrasta bruto aparente vs neto real y atribuye la fuga a
 * las razones de descarte. Datos de `GET /api/v1/analysis/naive-vs-edge` (agrega recent_opps).
 */

const money = (n: number) =>
  `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const perBtc = (n: number | null) => (n == null ? '—' : `${money(n)}/BTC`);

function Side({
  title,
  value,
  accent,
  sub,
}: {
  title: string;
  value: string;
  accent: 'neutral' | 'pos' | 'neg';
  sub: string;
}) {
  const color = accent === 'pos' ? POS : accent === 'neg' ? NEG : '#8893a8';
  return (
    <Box style={{ flex: 1 }}>
      <Text size="xs" tt="uppercase" fw={600} c="dimmed" style={{ fontSize: 10.5 }}>
        {title}
      </Text>
      <Text ff="monospace" fw={700} fz={24} lh={1.15} className="mono-nums" style={{ color }}>
        {value}
      </Text>
      <Text size="xs" c="dimmed" mt={4}>
        {sub}
      </Text>
    </Box>
  );
}

export function NaiveVsEdgePanel({ report }: { report: NaiveVsEdgeReport | null }) {
  const empty = !report || report.naive_trades === 0;
  const engineAccent: 'pos' | 'neg' | 'neutral' = report
    ? report.engine_net_usd > 0
      ? 'pos'
      : report.engine_net_usd < 0
        ? 'neg'
        : 'neutral'
    : 'neutral';
  const survivalPct = report?.survival_rate != null ? report.survival_rate * 100 : null;

  return (
    <Card h="100%">
      <SectionHeader
        title="Naive vs Edge"
        subtitle="lo que parece vs lo que queda · sesión"
        icon={<IconScale size={18} />}
        right={
          survivalPct != null ? (
            <Tooltip
              label="Fracción de trades del detector ingenuo que el motor realmente captura"
              withArrow
              multiline
              w={240}
            >
              <Badge size="lg" variant="light" color={survivalPct > 0 ? 'brand' : 'red'}>
                {survivalPct.toFixed(0)}% sobreviven
              </Badge>
            </Tooltip>
          ) : null
        }
      />

      {empty ? (
        <Text size="sm" c="dimmed">
          Aún no hay spreads brutos en esta sesión. El contraste aparece cuando el motor evalúa
          oportunidades.
        </Text>
      ) : (
        <Stack gap="md">
          <Group align="flex-start" gap="md" wrap="nowrap">
            <Side
              title="Detector ingenuo"
              value={perBtc(report.naive_gross_per_btc)}
              accent="neutral"
              sub={`${report.naive_trades} trades · ${money(report.naive_gross_usd)} bruto`}
            />
            <Box style={{ alignSelf: 'center', color: NEG, display: 'flex' }}>
              <IconArrowDownRight size={26} />
            </Box>
            <Side
              title="Este motor"
              value={perBtc(report.engine_net_per_btc)}
              accent={engineAccent}
              sub={`${report.engine_trades} ejecutados · ${money(report.engine_net_usd)} neto`}
            />
          </Group>

          {survivalPct != null && (
            <Box>
              <Group justify="space-between" mb={4}>
                <Text size="xs" c="dimmed">
                  Supervivencia tras costes
                </Text>
                <Text size="xs" ff="monospace" className="mono-nums" c="dimmed">
                  {report.engine_trades}/{report.naive_trades}
                </Text>
              </Group>
              <Progress
                value={survivalPct}
                color={survivalPct > 0 ? 'brand' : 'red'}
                size="sm"
                radius="xl"
              />
            </Box>
          )}

          {report.rejections.length > 0 && (
            <Box>
              <Text size="xs" tt="uppercase" fw={600} c="dimmed" mb={6} style={{ fontSize: 10.5 }}>
                Por qué se descartan
              </Text>
              <Stack gap={6}>
                {report.rejections.slice(0, 4).map((r) => (
                  <Group key={r.reason} justify="space-between" wrap="nowrap" gap="xs">
                    <Group gap={8} wrap="nowrap">
                      <Badge size="sm" variant="default" color="gray">
                        {r.count}
                      </Badge>
                      <Text size="sm">{r.label}</Text>
                    </Group>
                    <Text size="sm" ff="monospace" className="mono-nums" style={{ color: NEG }}>
                      −{money(r.lost_gross_usd)}
                    </Text>
                  </Group>
                ))}
              </Stack>
            </Box>
          )}

          <Text size="xs" c="dimmed" lh={1.45} style={{ borderTop: '1px solid var(--s-border)', paddingTop: 10 }}>
            {report.headline}
          </Text>
        </Stack>
      )}
    </Card>
  );
}
