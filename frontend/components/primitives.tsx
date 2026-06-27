'use client';

import { Box, Card, Group, Text, ThemeIcon, Title } from '@mantine/core';
import type { ReactNode } from 'react';
import { InfoHint } from './InfoHint';

/** Color de la marca para acentos puntuales fuera del sistema de Mantine. */
export const BRAND = '#16d67f';
export const AQUA = '#13c6cf';
// Semántica de datos (P&L, dirección): verde/rojo ligeramente desaturados (menos fatiga).
export const POS = '#2fd98c';
export const NEG = '#f6678a';

// Color estable por exchange (punto identificador en tablas).
const VENUE_COLORS: Record<string, string> = {
  binance: '#F0B90B',
  kraken: '#7B5CFF',
  coinbase: '#3B82F6',
  bitstamp: '#16D67F',
  okx: '#9CA3AF',
  bybit: '#F59E0B',
};

function venueColor(name: string): string {
  return VENUE_COLORS[name.toLowerCase()] ?? '#5C6982';
}

/** Exchange con punto de color identificador, consistente en toda la app. */
export function VenueTag({ name, fw = 600 }: { name: string; fw?: number }) {
  return (
    <Group gap={8} wrap="nowrap" align="center">
      <span
        style={{
          width: 8,
          height: 8,
          borderRadius: 999,
          background: venueColor(name),
          boxShadow: `0 0 8px -1px ${venueColor(name)}`,
          flex: '0 0 auto',
        }}
      />
      <Text size="sm" fw={fw} tt="capitalize">
        {name}
      </Text>
    </Group>
  );
}

/**
 * Cabecera de sección consistente: título (geométrico), ícono de acento opcional y
 * slot de acciones a la derecha. Unifica el look de todas las tarjetas.
 */
export function SectionHeader({
  title,
  icon,
  right,
  subtitle,
  help,
}: {
  title: string;
  icon?: ReactNode;
  right?: ReactNode;
  subtitle?: string;
  help?: string;
}) {
  return (
    <Group justify="space-between" align="flex-start" mb="md" wrap="nowrap">
      <Group gap="sm" wrap="nowrap">
        {icon && (
          <ThemeIcon
            variant="light"
            color="brand"
            size={34}
            radius="md"
            style={{ background: 'var(--brand-soft)', border: '1px solid rgba(22,214,127,0.22)' }}
          >
            {icon}
          </ThemeIcon>
        )}
        <Box>
          <Group gap={4} wrap="nowrap">
            <Title order={4} fz="md" lh={1.2}>
              {title}
            </Title>
            {help && <InfoHint title={title} body={help} />}
          </Group>
          {subtitle && (
            <Text size="xs" c="dimmed" mt={2}>
              {subtitle}
            </Text>
          )}
        </Box>
      </Group>
      {right}
    </Group>
  );
}

/**
 * KPI "hero": etiqueta técnica en mayúsculas, valor grande en monospace tabular y
 * una barra de acento superior cuyo color comunica el signo (verde/rojo/neutro).
 */
export function StatCard({
  label,
  value,
  accent = 'neutral',
  icon,
  sub,
  emphasize = false,
  hint,
}: {
  label: string;
  value: string;
  accent?: 'pos' | 'neg' | 'neutral' | 'brand';
  icon?: ReactNode;
  sub?: ReactNode;
  emphasize?: boolean;
  hint?: string;
}) {
  const accentColor =
    accent === 'pos' ? POS : accent === 'neg' ? NEG : accent === 'brand' ? BRAND : '#5C6982';
  const valueColor =
    accent === 'pos' ? 'var(--pos)' : accent === 'neg' ? 'var(--neg)' : undefined;

  return (
    <Card
      radius="lg"
      p="md"
      withBorder
      style={{
        position: 'relative',
        overflow: 'hidden',
        background: emphasize
          ? 'linear-gradient(160deg, rgba(22,214,127,0.09), var(--s-panel) 58%)'
          : undefined,
      }}
    >
      <Box
        style={{
          position: 'absolute',
          inset: '0 0 auto 0',
          height: 3,
          background: `linear-gradient(90deg, ${accentColor}, transparent 80%)`,
          opacity: 0.9,
        }}
      />
      <Group justify="space-between" align="center" gap="xs" mb={8}>
        <Group gap={2} wrap="nowrap">
          <Text size="xs" tt="uppercase" fw={600} c="dimmed" style={{ letterSpacing: 0, fontSize: 10.5 }}>
            {label}
          </Text>
          {hint && <InfoHint title={label} body={hint} size={12} />}
        </Group>
        {icon && (
          <Box c={accent === 'neutral' ? 'dimmed' : accentColor} style={{ display: 'flex' }}>
            {icon}
          </Box>
        )}
      </Group>
      <Text
        ff="monospace"
        fw={600}
        fz={27}
        lh={1.1}
        c={valueColor}
        className="mono-nums"
        style={{ letterSpacing: 0 }}
      >
        {value}
      </Text>
      {sub && (
        <Text size="xs" c="dimmed" mt={6}>
          {sub}
        </Text>
      )}
    </Card>
  );
}
