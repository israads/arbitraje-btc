'use client';

import { useEffect, useState } from 'react';
import { Badge, Button, Card, Group, NumberInput, SimpleGrid, Stack, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconAdjustmentsHorizontal, IconRefresh, IconSettingsCheck } from '@tabler/icons-react';
import { API_BASE } from '../lib/config';
import type { StrategyLabParams } from '../hooks/useStream';
import { SectionHeader } from './primitives';

function asNumber(value: string | number, fallback: number): number {
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) ? n : fallback;
}

export function StrategyLabPanel({
  params,
  onApply,
}: {
  params: StrategyLabParams;
  onApply: (params: StrategyLabParams) => void;
}) {
  const [draft, setDraft] = useState<StrategyLabParams>(params);
  const [busy, setBusy] = useState(false);

  useEffect(() => setDraft(params), [params]);

  const update = (patch: Partial<StrategyLabParams>) => {
    setDraft((prev) => ({ ...prev, ...patch }));
  };

  const apply = async () => {
    if (busy) return;
    setBusy(true);
    onApply(draft);
    try {
      const res = await fetch(`${API_BASE}/api/v1/params`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          default_trade_qty_btc: draft.size_btc,
          fee_bps: draft.fee_bps,
          exec_latency_ms: Math.round(draft.latency_ms),
          max_slippage: draft.max_slippage,
          expected_trades_per_rebalance: draft.expected_trades_per_rebalance,
          n_paths: Math.round(draft.n_paths),
        }),
      });
      if (!res.ok) throw new Error(`${res.status}`);
      notifications.show({ message: 'Parámetros aplicados', color: 'brand' });
    } catch {
      // Los parámetros locales siguen activos aunque el backend rechace la persistencia.
      notifications.show({ message: 'No se pudieron persistir los parámetros', color: 'red' });
    } finally {
      setBusy(false);
    }
  };

  const reset = () => {
    const defaults: StrategyLabParams = {
      size_btc: 1,
      fee_bps: 10,
      latency_ms: 150,
      max_slippage: 0.001,
      expected_trades_per_rebalance: 1,
      n_paths: 2000,
    };
    setDraft(defaults);
    onApply(defaults);
  };

  return (
    <Card h="100%">
      <SectionHeader
        title="Strategy Lab"
        icon={<IconAdjustmentsHorizontal size={18} />}
        right={<Badge color="aqua" variant="light">WHAT-IF</Badge>}
      />

      <Stack gap="sm">
        <SimpleGrid cols={{ base: 1, xs: 2 }} spacing="sm">
          <NumberInput
            label="Tamaño BTC"
            min={0.00001}
            step={0.05}
            decimalScale={5}
            value={draft.size_btc}
            onChange={(v) => update({ size_btc: asNumber(v, draft.size_btc) })}
          />
          <NumberInput
            label="Fee bps"
            min={0}
            max={100}
            step={1}
            value={draft.fee_bps}
            onChange={(v) => update({ fee_bps: asNumber(v, draft.fee_bps) })}
          />
          <NumberInput
            label="Latencia ms"
            min={1}
            max={10_000}
            step={25}
            value={draft.latency_ms}
            onChange={(v) => update({ latency_ms: asNumber(v, draft.latency_ms) })}
          />
          <NumberInput
            label="Max slippage"
            min={0}
            max={0.02}
            step={0.0001}
            decimalScale={4}
            value={draft.max_slippage}
            onChange={(v) => update({ max_slippage: asNumber(v, draft.max_slippage) })}
          />
          <NumberInput
            label="Trades/rebalance"
            min={1}
            max={50}
            step={1}
            decimalScale={1}
            value={draft.expected_trades_per_rebalance}
            onChange={(v) => update({
              expected_trades_per_rebalance: asNumber(v, draft.expected_trades_per_rebalance),
            })}
          />
          <NumberInput
            label="Monte Carlo paths"
            min={100}
            max={20_000}
            step={100}
            value={draft.n_paths}
            onChange={(v) => update({ n_paths: asNumber(v, draft.n_paths) })}
          />
        </SimpleGrid>

        <Group gap="xs" grow>
          <Button
            size="xs"
            color="brand"
            leftSection={<IconSettingsCheck size={15} />}
            loading={busy}
            onClick={apply}
          >
            Aplicar
          </Button>
          <Button
            size="xs"
            color="gray"
            variant="light"
            leftSection={<IconRefresh size={15} />}
            disabled={busy}
            onClick={reset}
          >
            Reset
          </Button>
        </Group>

        <Text size="xs" c="dimmed" ff="monospace">
          {draft.size_btc.toFixed(4)} BTC · {draft.fee_bps.toFixed(1)} bps · {Math.round(draft.latency_ms)} ms
        </Text>
      </Stack>
    </Card>
  );
}
