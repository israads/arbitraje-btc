'use client';

import { Badge, Card, Group, Stack, Text, Tooltip } from '@mantine/core';
import { IconChartBar } from '@tabler/icons-react';
import type { Metrics } from '../hooks/useStream';
import { SectionHeader } from './primitives';

/**
 * Histograma "opportunity lifetime vs latencia" (C13): cuánto VIVE un cruce (ms) frente a
 * la latencia de detección (sub-ms). La tesis visual: el edge existe decenas-cientos de ms
 * → capturarlo es cuestión de latencia, pero no rinde tras fees.
 */
export function LifetimeHistogram({ metrics }: { metrics: Metrics | null }) {
  const hist = metrics?.opp_lifetime_hist ?? [];
  const buckets = metrics?.opp_lifetime_buckets_ms ?? [];
  const total = hist.reduce((a, b) => a + b, 0);
  const max = Math.max(1, ...hist);

  const labels = buckets.map((edge, i) => {
    const prev = i === 0 ? 0 : buckets[i - 1];
    return `${prev}–${edge}`;
  });
  labels.push(`>${buckets[buckets.length - 1] ?? 0}`);

  return (
    <Card h="100%">
      <SectionHeader
        title="Opportunity lifetime"
        subtitle="vida del cruce (ms) vs latencia de detección"
        icon={<IconChartBar size={18} />}
        right={
          <Badge variant="default" color="gray">
            p50 {fmt(metrics?.opp_lifetime_p50_ms)} · p99 {fmt(metrics?.opp_lifetime_p99_ms)}
          </Badge>
        }
      />
      {total === 0 ? (
        <Text size="sm" c="dimmed">
          Sin episodios aún…
        </Text>
      ) : (
        <Stack gap={6}>
          {hist.map((count, i) => (
            <Group key={i} gap="sm" wrap="nowrap" align="center">
              <Text size="xs" ff="monospace" className="mono-nums" c="dimmed" w={64} ta="right">
                {labels[i] ?? ''}
              </Text>
              <Tooltip label={`${count} cruces`} disabled={count === 0} withArrow>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    style={{
                      height: 16,
                      width: `${Math.max((count / max) * 100, count > 0 ? 3 : 0)}%`,
                      background: 'linear-gradient(90deg, #13c6cf, #16d67f)',
                      borderRadius: 6,
                      boxShadow: count > 0 ? '0 0 10px -3px rgba(22,214,127,0.5)' : 'none',
                      transition: 'width 300ms ease',
                    }}
                  />
                </div>
              </Tooltip>
              <Text size="xs" ff="monospace" className="mono-nums" c={count > 0 ? 'dark.1' : 'dimmed'} w={36}>
                {count > 0 ? count : ''}
              </Text>
            </Group>
          ))}
        </Stack>
      )}
      <Text size="xs" c="dimmed" mt="md">
        Latencia de detección p50 {fmt(metrics?.p50_ms, 3)} ms ≪ vida del cruce → detectable; el
        neto tras fees decide si rinde.
      </Text>
    </Card>
  );
}

function fmt(n: number | null | undefined, d = 0): string {
  return n == null || !Number.isFinite(n) ? '—' : n.toFixed(d);
}
