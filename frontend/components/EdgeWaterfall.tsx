'use client';

import { Badge, Box, Card, Group, Stack, Text, Tooltip } from '@mantine/core';
import { IconCheck, IconRosetteDiscountCheck, IconX } from '@tabler/icons-react';
import type { ValidationReport } from '../hooks/useStream';
import { AQUA, BRAND, NEG, SectionHeader } from './primitives';

/**
 * HERO Edge Waterfall (STORY-023, C15): la "prueba de correctitud" del bot. Descompone el
 * ejemplo canónico del reto — bruto → −fees → −rebalanceo = NETO ($109.75/BTC) — en una
 * cascada visual, y reconcilia nuestro cálculo (NetEvaluator) contra la referencia oficial.
 * Debajo, la batería de invariantes (conservación de valor, fee única por leg, slippage ≥0…)
 * como sellos pasa/falla. Datos deterministas de `GET /api/v1/validation` (no dependen del feed).
 */

const TRACK_H = 168; // alto del área de barras (px)
const money = (n: number) =>
  `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

interface Step {
  label: string;
  delta: number; // contribución firmada al neto
  start: number; // base acumulada (USD) — para flotar la barra
  end: number; // tope acumulado (USD)
  kind: 'total' | 'neg' | 'final';
}

export function EdgeWaterfall({ report }: { report: ValidationReport | null }) {
  if (!report) {
    return (
      <Card h="100%">
        <SectionHeader
          title="Edge Waterfall"
          subtitle="reconciliación del reto · prueba de correctitud"
          help="La 'prueba de correctitud': descompone el ejemplo oficial del reto en cascada — bruto, menos fees, menos rebalanceo = neto ($109.75/BTC) — y verifica que nuestra aritmética coincide con la referencia. Las insignias de abajo son invariantes económicas que deben cumplirse siempre."
          icon={<IconRosetteDiscountCheck size={18} />}
        />
        <Text size="sm" c="dimmed">
          Cargando reconciliación…
        </Text>
      </Card>
    );
  }

  const { reconciliation: rec, invariants, all_passed } = report;
  const { gross, fees, rebalance, net } = rec.breakdown;

  // Cascada: bruto (0→gross) ▸ −fees ▸ −rebalanceo ▸ neto (0→net).
  const steps: Step[] = [
    { label: 'Bruto', delta: gross, start: 0, end: gross, kind: 'total' },
    { label: '− Fees', delta: -fees, start: gross - fees, end: gross, kind: 'neg' },
    {
      label: '− Rebalanceo',
      delta: -rebalance,
      start: gross - fees - rebalance,
      end: gross - fees,
      kind: 'neg',
    },
    { label: 'Neto', delta: net, start: 0, end: net, kind: 'final' },
  ];
  const scaleMax = Math.max(gross, net, 1); // bruto domina, pero robusto ante datos raros
  const pct = (usd: number) => `${(usd / scaleMax) * 100}%`;

  const passed = rec.passed;

  return (
    <Card h="100%">
      <SectionHeader
        title="Edge Waterfall"
        subtitle="reconciliación del reto · prueba de correctitud"
        icon={<IconRosetteDiscountCheck size={18} />}
        right={
          <Tooltip
            label={`computado ${money(rec.computed)} vs objetivo ${money(rec.target)} (Δ ${rec.diff.toFixed(4)})`}
            withArrow
            multiline
            w={260}
          >
            <Badge
              size="lg"
              variant="light"
              color={passed ? 'brand' : 'red'}
              leftSection={passed ? <IconCheck size={13} /> : <IconX size={13} />}
            >
              {money(rec.computed)}/BTC
            </Badge>
          </Tooltip>
        }
      />

      {/* Cascada de barras */}
      <Box
        style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${steps.length}, 1fr)`,
          gap: 14,
          alignItems: 'end',
          height: TRACK_H,
          marginTop: 4,
        }}
      >
        {steps.map((s) => {
          const isFinal = s.kind === 'final';
          const isNeg = s.kind === 'neg';
          const barColor = isFinal
            ? `linear-gradient(180deg, ${BRAND}, ${AQUA})`
            : isNeg
              ? `linear-gradient(180deg, ${NEG}, rgba(246,103,138,0.45))`
              : 'linear-gradient(180deg, rgba(110,124,150,0.9), rgba(110,124,150,0.4))';
          // Altura mínima visible para deltas ~0 (p.ej. rebalanceo = 0) sin falsear la escala.
          const h = Math.max(Math.abs(s.end - s.start) / scaleMax, 0.012) * 100;
          const bottom = pct(Math.min(s.start, s.end));
          return (
            <Box key={s.label} style={{ position: 'relative', height: '100%' }}>
              {/* etiqueta de valor flotante sobre la barra */}
              <Text
                ff="monospace"
                className="mono-nums"
                size="xs"
                fw={700}
                ta="center"
                c={isFinal ? 'brand.4' : isNeg ? undefined : 'dimmed'}
                style={{
                  position: 'absolute',
                  bottom: `calc(${pct(Math.max(s.start, s.end))} + 6px)`,
                  left: 0,
                  right: 0,
                  color: isNeg ? NEG : undefined,
                }}
              >
                {s.kind === 'neg' ? money(s.delta) : money(s.end)}
              </Text>
              <Tooltip
                label={`${s.label}: ${money(s.delta)}/BTC`}
                withArrow
                position="top"
              >
                <Box
                  style={{
                    position: 'absolute',
                    left: '14%',
                    right: '14%',
                    bottom,
                    height: `${h}%`,
                    background: barColor,
                    borderRadius: 7,
                    boxShadow: isFinal
                      ? '0 0 16px -4px rgba(22,214,127,0.55)'
                      : isNeg
                        ? '0 0 12px -5px rgba(246,103,138,0.5)'
                        : 'none',
                    transition: 'height 350ms ease, bottom 350ms ease',
                  }}
                />
              </Tooltip>
            </Box>
          );
        })}
      </Box>

      {/* etiquetas de paso */}
      <Box
        style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${steps.length}, 1fr)`,
          gap: 14,
          marginTop: 8,
        }}
      >
        {steps.map((s) => (
          <Text key={s.label} size="xs" c="dimmed" ta="center" fw={s.kind === 'final' ? 700 : 500}>
            {s.label}
          </Text>
        ))}
      </Box>

      {/* Invariantes: sellos pasa/falla (prueba de correctitud) */}
      <Group gap={6} mt="md" wrap="wrap">
        <Badge
          variant="light"
          color={all_passed ? 'brand' : 'red'}
          leftSection={all_passed ? <IconCheck size={12} /> : <IconX size={12} />}
        >
          {all_passed ? 'Invariantes OK' : 'Revisar invariantes'}
        </Badge>
        {invariants.map((inv) => (
          <Tooltip key={inv.name + inv.detail.slice(0, 8)} label={inv.detail} withArrow multiline w={280}>
            <Badge
              variant="default"
              color={inv.passed ? 'gray' : 'red'}
              leftSection={
                inv.passed ? (
                  <IconCheck size={11} style={{ color: BRAND }} />
                ) : (
                  <IconX size={11} style={{ color: NEG }} />
                )
              }
              style={{ textTransform: 'none', cursor: 'help' }}
            >
              {inv.name}
            </Badge>
          </Tooltip>
        ))}
      </Group>

      {rec.notes && (
        <Text size="xs" c="dimmed" mt="sm" lh={1.4}>
          {rec.notes}
        </Text>
      )}
    </Card>
  );
}
