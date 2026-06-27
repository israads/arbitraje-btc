'use client';

import { Badge, Box, Card, Group, Stack, Text, Tooltip } from '@mantine/core';
import { IconScale, IconEye, IconCpu } from '@tabler/icons-react';
import type { ReactNode } from 'react';
import type { NaiveVsEdgeReport } from '../hooks/useStream';
import { BRAND, NEG, POS, SectionHeader } from './primitives';

/**
 * Panel Naive-vs-Edge: la tesis del motor hecha agregado de sesión. Un detector de spreads
 * ingenuo tradearía toda diferencia bruta positiva; este motor descuenta fees, latencia y peg
 * y solo captura lo que sobrevive. Patrón "comparison": columna del motor resaltada vs la
 * ingenua atenuada, una barra de erosión bruto→neto y el desglose de razones de descarte.
 * Datos de `GET /api/v1/analysis/naive-vs-edge` (agrega recent_opps).
 */

const money = (n: number) =>
  `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const perBtc = (n: number | null) => (n == null ? '—' : `${money(n)}/BTC`);
const clamp = (n: number) => Math.max(0, Math.min(100, n));

/** Columna "versus": el lado del motor se resalta (accent), el ingenuo queda atenuado. */
function Side({
  label,
  icon,
  value,
  accent,
  sub,
  highlight,
}: {
  label: string;
  icon: ReactNode;
  value: string;
  accent: 'muted' | 'pos' | 'neg';
  sub: string;
  highlight: boolean;
}) {
  const color = accent === 'pos' ? POS : accent === 'neg' ? NEG : '#8893a8';
  return (
    <Box
      style={{
        flex: 1,
        padding: '12px 14px',
        borderRadius: 12,
        border: `1px solid ${highlight ? 'rgba(22,214,127,0.28)' : 'var(--s-border)'}`,
        background: highlight
          ? 'linear-gradient(160deg, rgba(22,214,127,0.10), transparent 70%)'
          : 'rgba(255,255,255,0.015)',
      }}
    >
      <Group gap={6} mb={6} wrap="nowrap">
        <Box style={{ display: 'flex', color: highlight ? BRAND : '#6b7689' }}>{icon}</Box>
        <Text size="xs" tt="uppercase" fw={700} c="dimmed" style={{ fontSize: 10, letterSpacing: 0.3 }}>
          {label}
        </Text>
      </Group>
      <Text
        ff="monospace"
        fw={700}
        fz={highlight ? 26 : 22}
        lh={1.1}
        className="mono-nums"
        style={{ color }}
      >
        {value}
      </Text>
      <Text size="xs" c="dimmed" mt={4} lh={1.35}>
        {sub}
      </Text>
    </Box>
  );
}

export function NaiveVsEdgePanel({ report }: { report: NaiveVsEdgeReport | null }) {
  const empty = !report || report.naive_trades === 0;

  const netPositive = !!report && report.engine_net_usd > 0;
  const engineAccent: 'pos' | 'neg' | 'muted' = report
    ? report.engine_net_usd > 0
      ? 'pos'
      : report.engine_net_usd < 0
        ? 'neg'
        : 'muted'
    : 'muted';
  const survivalPct = report?.survival_rate != null ? report.survival_rate * 100 : null;

  // Barra de erosión: del bruto aparente, qué fracción sobrevive como neto.
  const keptPct =
    report && report.naive_gross_usd > 0 && netPositive
      ? clamp((report.engine_net_usd / report.naive_gross_usd) * 100)
      : 0;
  const maxLost = report ? Math.max(1, ...report.rejections.map((r) => r.lost_gross_usd)) : 1;

  return (
    <Card h="100%">
      <SectionHeader
        title="Naive vs Edge"
        subtitle="lo que parece vs lo que queda · sesión"
        icon={<IconScale size={18} />}
        help="Contrasta lo que un detector ingenuo de spreads contaría como ganancia bruta vs el neto que el motor realmente captura tras fees, latencia y peg. Abajo se atribuye la fuga: por qué se descartó cada oportunidad. La tesis del proyecto en un panel."
        right={
          survivalPct != null ? (
            <Tooltip
              label="Fracción de trades del detector ingenuo que el motor realmente captura tras costes"
              withArrow
              multiline
              w={240}
            >
              <Badge
                size="lg"
                variant="light"
                color={survivalPct > 0 ? 'brand' : 'red'}
                style={{ cursor: 'help' }}
              >
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
          {/* Versus: ingenuo (atenuado) vs motor (resaltado) */}
          <Group align="stretch" gap="sm" wrap="nowrap">
            <Side
              label="Detector ingenuo"
              icon={<IconEye size={14} />}
              value={perBtc(report.naive_gross_per_btc)}
              accent="muted"
              sub={`${report.naive_trades} trades · ${money(report.naive_gross_usd)} bruto`}
              highlight={false}
            />
            <Side
              label="Este motor"
              icon={<IconCpu size={14} />}
              value={perBtc(report.engine_net_per_btc)}
              accent={engineAccent}
              sub={`${report.engine_trades} ejecutados · ${money(report.engine_net_usd)} neto`}
              highlight
            />
          </Group>

          {/* Barra de erosión bruto → neto */}
          <Box>
            <Group justify="space-between" mb={5}>
              <Text size="xs" c="dimmed">
                De cada $100 brutos aparentes
              </Text>
              <Text size="xs" ff="monospace" className="mono-nums" fw={600} style={{ color: netPositive ? POS : NEG }}>
                {netPositive ? `$${keptPct.toFixed(0)} sobreviven` : 'neto negativo'}
              </Text>
            </Group>
            <Tooltip
              label={
                netPositive
                  ? `Bruto ${money(report.naive_gross_usd)} → neto ${money(report.engine_net_usd)} (erosión ${money(report.overstatement_usd)})`
                  : `El bruto aparente (${money(report.naive_gross_usd)}) no sobrevive a los costes: neto ${money(report.engine_net_usd)}`
              }
              withArrow
              multiline
              w={280}
              position="bottom"
            >
              <Box
                style={{
                  display: 'flex',
                  height: 12,
                  borderRadius: 999,
                  overflow: 'hidden',
                  background: 'rgba(246,103,138,0.18)',
                  cursor: 'help',
                }}
              >
                <Box
                  style={{
                    width: `${keptPct}%`,
                    background: `linear-gradient(90deg, ${BRAND}, ${POS})`,
                    transition: 'width 350ms ease',
                  }}
                />
                <Box
                  style={{
                    flex: 1,
                    background:
                      'repeating-linear-gradient(135deg, rgba(246,103,138,0.55) 0 6px, rgba(246,103,138,0.30) 6px 12px)',
                  }}
                />
              </Box>
            </Tooltip>
          </Box>

          {/* Razones de descarte: mini-barras proporcionales al bruto perdido */}
          {report.rejections.length > 0 && (
            <Box>
              <Text size="xs" tt="uppercase" fw={700} c="dimmed" mb={8} style={{ fontSize: 10, letterSpacing: 0.3 }}>
                Por qué se descartan
              </Text>
              <Stack gap={10}>
                {report.rejections.slice(0, 4).map((r) => (
                  <Box key={r.reason}>
                    <Group justify="space-between" wrap="nowrap" gap="xs" mb={3}>
                      <Group gap={7} wrap="nowrap">
                        <Badge size="sm" variant="default" color="gray" className="mono-nums">
                          {r.count}
                        </Badge>
                        <Text size="sm">{r.label}</Text>
                      </Group>
                      <Text size="sm" ff="monospace" className="mono-nums" style={{ color: NEG }}>
                        −{money(r.lost_gross_usd)}
                      </Text>
                    </Group>
                    <Box style={{ height: 4, borderRadius: 999, background: 'rgba(255,255,255,0.05)' }}>
                      <Box
                        style={{
                          width: `${clamp((r.lost_gross_usd / maxLost) * 100)}%`,
                          height: '100%',
                          borderRadius: 999,
                          background: NEG,
                          opacity: 0.7,
                          transition: 'width 350ms ease',
                        }}
                      />
                    </Box>
                  </Box>
                ))}
              </Stack>
            </Box>
          )}

          <Text
            size="xs"
            c="dimmed"
            lh={1.5}
            style={{ borderTop: '1px solid var(--s-border)', paddingTop: 10 }}
          >
            {report.headline}
          </Text>
        </Stack>
      )}
    </Card>
  );
}
