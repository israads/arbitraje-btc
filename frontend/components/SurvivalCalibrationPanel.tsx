'use client';

import { Badge, Box, Card, Group, Progress, SimpleGrid, Text, Tooltip } from '@mantine/core';
import { IconAdjustmentsCheck } from '@tabler/icons-react';
import type { SurvivalCalibration } from '../hooks/useStream';
import { SectionHeader } from './primitives';

function pct(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return `${(value * 100).toFixed(0)}%`;
}

function confidenceColor(c: string): string {
  if (c === 'high') return 'brand';
  if (c === 'medium') return 'yellow';
  return 'gray';
}

export function SurvivalCalibrationPanel({ report }: { report: SurvivalCalibration | null }) {
  if (!report) {
    return (
      <Card h="100%">
        <SectionHeader
          title="Survival Calibration"
          subtitle="estimado vs observado · shadow replay"
          icon={<IconAdjustmentsCheck size={18} />}
        />
        <Text size="sm" c="dimmed">Midiendo supervivencia observe-only…</Text>
      </Card>
    );
  }

  return (
    <Card h="100%">
      <SectionHeader
        title="Survival Calibration"
        subtitle={`P_survive contra replay futuro · ${report.latency_ms}ms`}
        icon={<IconAdjustmentsCheck size={18} />}
        right={
          <Group gap={6} wrap="nowrap">
            <Badge color={confidenceColor(report.confidence)} variant="light" tt="none">
              {report.confidence}
            </Badge>
            <Badge color="gray" variant="light" tt="none">
              {report.mode}
            </Badge>
          </Group>
        }
      />

      <SimpleGrid cols={3} spacing="xs" mb="md">
        <Box>
          <Text fz={10} tt="uppercase" c="dimmed" fw={700}>samples</Text>
          <Text ff="monospace" fw={700}>{report.n_samples}</Text>
        </Box>
        <Box>
          <Text fz={10} tt="uppercase" c="dimmed" fw={700}>observed</Text>
          <Text ff="monospace" fw={700} c="brand.4">{report.n_observed}</Text>
        </Box>
        <Box>
          <Text fz={10} tt="uppercase" c="dimmed" fw={700}>missing</Text>
          <Text ff="monospace" fw={700} c={report.n_missing ? 'yellow.4' : undefined}>
            {report.n_missing}
          </Text>
        </Box>
      </SimpleGrid>

      <Box style={{ display: 'grid', gap: 8 }}>
        {report.buckets.map((bucket) => (
          <Tooltip
            key={`${bucket.p_low}-${bucket.p_high}`}
            withArrow
            label={
              `estimado ${pct(bucket.estimated_mid)} · observado ${pct(bucket.observed_rate)}` +
              ` · n=${bucket.n}` +
              (bucket.abs_error != null ? ` · error ${pct(bucket.abs_error)}` : '')
            }
          >
            <Box>
              <Group justify="space-between" mb={4}>
                <Text fz={10} c="dimmed" ff="monospace">
                  {pct(bucket.p_low)}-{pct(bucket.p_high)}
                </Text>
                <Text fz={10} c="dimmed" ff="monospace">
                  obs {pct(bucket.observed_rate)} · n={bucket.n}
                </Text>
              </Group>
              <Progress.Root size={12} radius="sm">
                <Progress.Section
                  value={(bucket.estimated_mid ?? 0) * 100}
                  color="gray"
                  style={{ opacity: 0.35 }}
                />
                {bucket.observed_rate != null && (
                  <Progress.Section
                    value={Math.max(1, bucket.observed_rate * 100)}
                    color={confidenceColor(bucket.confidence)}
                  />
                )}
              </Progress.Root>
            </Box>
          </Tooltip>
        ))}
      </Box>

      <Text size="xs" c="dimmed" mt="sm" lh={1.4}>
        La calibración es observe-only: compara la probabilidad estimada contra el book futuro
        del recorder y no modifica ranking ni decisión de ejecución.
      </Text>
    </Card>
  );
}
