'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Box,
  Button,
  Drawer,
  Group,
  Loader,
  SimpleGrid,
  Stack,
  Table,
  Text,
} from '@mantine/core';
import { IconArrowNarrowRight, IconChecklist, IconScale, IconSend, IconShieldCheck } from '@tabler/icons-react';
import { API_BASE } from '../lib/config';
import type { OpportunityExplanation } from '../hooks/useStream';
import { SectionHeader, VenueTag } from './primitives';

function money(n: number | null | undefined, signed = false): string {
  if (n == null || !Number.isFinite(n)) return '—';
  const s = `$${Math.abs(n).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
  if (!signed) return n < 0 ? `-${s}` : s;
  return n > 0 ? `+${s}` : n < 0 ? `-${s}` : s;
}

function price(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '—';
  return `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function pctFromBps(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '—';
  return `${(n / 100).toFixed(3)}%`;
}

function reasonLabel(reason: string | null): string {
  if (!reason) return '—';
  return reason.replaceAll('_', ' ');
}

interface PreflightCheck {
  name: string;
  passed: boolean;
  detail: string | null;
}

interface PreflightResult {
  mode: string;
  accepted: boolean;
  venue: string;
  symbol: string;
  checks: PreflightCheck[];
  sanitized_order: Record<string, string>;
}

interface TestOrderResult {
  mode: string;
  accepted: boolean;
  venue: string;
  symbol: string;
  status: string;
  checks: PreflightCheck[];
  submitted_order: Record<string, string>;
  exchange_response: Record<string, string | boolean | number | null>;
}

interface ExecutionPayload {
  opportunity_id: string;
  venue: string;
  side: 'buy' | 'sell';
  symbol: string;
  quantity_btc: number;
  order_type: 'market';
  reference_price?: number;
}

function MiniMetric({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <Box
      p="sm"
      style={{
        border: '1px solid rgba(255,255,255,0.08)',
        borderRadius: 8,
        background: 'rgba(255,255,255,0.025)',
      }}
    >
      <Text size="xs" c="dimmed" tt="uppercase" fw={700} style={{ letterSpacing: 0 }}>
        {label}
      </Text>
      <Text ff="monospace" className="mono-nums" fw={700} c={color} mt={4}>
        {value}
      </Text>
    </Box>
  );
}

export function OpportunityExplainDrawer({
  opportunityId,
  opened,
  onClose,
}: {
  opportunityId: string | null;
  opened: boolean;
  onClose: () => void;
}) {
  const [data, setData] = useState<OpportunityExplanation | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preflight, setPreflight] = useState<PreflightResult | null>(null);
  const [testOrder, setTestOrder] = useState<TestOrderResult | null>(null);
  const [executionError, setExecutionError] = useState<string | null>(null);
  const [preflightLoading, setPreflightLoading] = useState(false);
  const [testOrderLoading, setTestOrderLoading] = useState(false);

  useEffect(() => {
    if (!opened || !opportunityId) return;
    const ac = new AbortController();
    setLoading(true);
    setError(null);
    fetch(`${API_BASE}/api/v1/opportunities/${opportunityId}/explain`, { signal: ac.signal })
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status}`);
        return r.json() as Promise<OpportunityExplanation>;
      })
      .then(setData)
      .catch((e: Error) => {
        if (e.name !== 'AbortError') setError(e.message);
      })
      .finally(() => setLoading(false));
    return () => ac.abort();
  }, [opened, opportunityId]);

  useEffect(() => {
    setPreflight(null);
    setTestOrder(null);
    setExecutionError(null);
  }, [opportunityId]);

  const delta = useMemo(() => {
    if (!data || data.naive.gross_usd == null || data.engine.net_usd == null) return null;
    return data.engine.net_usd - data.naive.gross_usd;
  }, [data]);

  const executionPayload = useMemo<ExecutionPayload | null>(() => {
    if (!data) return null;
    const buyIsBinance = data.route.buy_venue.toLowerCase() === 'binance';
    const sellIsBinance = data.route.sell_venue.toLowerCase() === 'binance';
    if (!buyIsBinance && !sellIsBinance) return null;
    const side = buyIsBinance ? 'buy' : 'sell';
    const reference = side === 'buy' ? data.naive.buy_price : data.naive.sell_price;
    return {
      opportunity_id: data.id,
      venue: 'binance',
      side,
      symbol: 'BTCUSDT',
      quantity_btc: Math.max(data.q_target, 0.00001),
      order_type: 'market',
      ...(reference != null && Number.isFinite(reference) ? { reference_price: reference } : {}),
    };
  }, [data]);

  async function postExecution<T>(path: 'preflight' | 'test-order', payload: ExecutionPayload): Promise<T> {
    const res = await fetch(`${API_BASE}/api/v1/execution/${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const body = await res.json().catch(() => null);
    if (!res.ok) {
      const detail = body && typeof body.detail === 'string' ? body.detail : `${res.status}`;
      throw new Error(detail);
    }
    return body as T;
  }

  async function runPreflight() {
    if (!executionPayload) return;
    setPreflightLoading(true);
    setExecutionError(null);
    setTestOrder(null);
    try {
      setPreflight(await postExecution<PreflightResult>('preflight', executionPayload));
    } catch (e) {
      setExecutionError(e instanceof Error ? e.message : 'preflight failed');
    } finally {
      setPreflightLoading(false);
    }
  }

  async function runTestOrder() {
    if (!executionPayload) return;
    setTestOrderLoading(true);
    setExecutionError(null);
    try {
      setTestOrder(await postExecution<TestOrderResult>('test-order', executionPayload));
    } catch (e) {
      setExecutionError(e instanceof Error ? e.message : 'test order failed');
    } finally {
      setTestOrderLoading(false);
    }
  }

  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      position="right"
      size="lg"
      title="Explicación de oportunidad"
    >
      {loading && (
        <Group py="xl" justify="center">
          <Loader size="sm" />
        </Group>
      )}
      {!loading && error && (
        <Text c="red.4" size="sm">
          No se pudo cargar la explicación ({error}).
        </Text>
      )}
      {!loading && !error && data && (
        <Stack gap="lg">
          <SectionHeader
            title="Naive vs engine"
            subtitle="spread aparente contra edge ejecutable"
            icon={<IconScale size={18} />}
            right={
              <Badge color={data.engine.trades ? 'brand' : 'gray'} variant="light" tt="none">
                {data.engine.status}
              </Badge>
            }
          />

          <Group gap="xs" wrap="nowrap">
            <VenueTag name={data.route.buy_venue} />
            <IconArrowNarrowRight size={16} color="var(--mantine-color-dark-2)" />
            <VenueTag name={data.route.sell_venue} />
            <Text size="sm" c="dimmed" ff="monospace">
              {data.q_target.toFixed(4)} BTC
            </Text>
          </Group>

          <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm">
            <MiniMetric
              label="Naive gross"
              value={money(data.naive.gross_usd, true)}
              color={data.naive.would_trade ? 'aqua.4' : 'dimmed'}
            />
            <MiniMetric
              label="Engine net"
              value={money(data.engine.net_usd, true)}
              color={(data.engine.net_usd ?? 0) >= 0 ? 'brand.4' : 'red.4'}
            />
            <MiniMetric
              label="Delta"
              value={money(delta, true)}
              color={(delta ?? 0) >= 0 ? 'brand.4' : 'red.4'}
            />
          </SimpleGrid>

          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
            <MiniMetric label="Naive spread / BTC" value={money(data.naive.spread_usd_per_btc, true)} />
            <MiniMetric label="Engine net / BTC" value={money(data.engine.net_per_btc, true)} />
            <MiniMetric label="Buy top" value={price(data.naive.buy_price)} />
            <MiniMetric label="Sell top" value={price(data.naive.sell_price)} />
          </SimpleGrid>

          <Box>
            <Text size="xs" c="dimmed" tt="uppercase" fw={700} mb={6}>
              Decisión
            </Text>
            <Group gap="xs">
              <Badge color={data.engine.trades ? 'brand' : 'gray'} variant="dot" tt="none">
                {data.engine.trades ? 'operable' : 'rechazada'}
              </Badge>
              <Badge color="gray" variant="default" tt="none">
                {reasonLabel(data.engine.reason)}
              </Badge>
              {data.engine.dominant_cost && (
                <Badge color="red" variant="light" tt="none">
                  costo dominante: {data.engine.dominant_cost}
                </Badge>
              )}
            </Group>
          </Box>

          <Box>
            <SectionHeader
              title="Testnet preflight"
              subtitle="Binance Spot Testnet"
              icon={<IconShieldCheck size={18} />}
              right={
                <Badge
                  color={preflight?.accepted ? 'brand' : executionPayload ? 'yellow' : 'gray'}
                  variant="light"
                  tt="none"
                >
                  {preflight?.accepted ? 'ready' : executionPayload ? 'pending' : 'unsupported'}
                </Badge>
              }
            />
            <Group gap="xs" mb="sm">
              <Button
                size="xs"
                variant="light"
                color="brand"
                leftSection={<IconChecklist size={15} />}
                disabled={!executionPayload}
                loading={preflightLoading}
                onClick={runPreflight}
              >
                Preflight
              </Button>
              <Button
                size="xs"
                variant="outline"
                color="aqua"
                leftSection={<IconSend size={15} />}
                disabled={!executionPayload || !preflight?.accepted}
                loading={testOrderLoading}
                onClick={runTestOrder}
              >
                Test order
              </Button>
              {executionPayload && (
                <Text size="xs" c="dimmed" ff="monospace">
                  {executionPayload.side.toUpperCase()} · {executionPayload.quantity_btc.toFixed(5)} BTC
                </Text>
              )}
            </Group>
            {!executionPayload && (
              <Text size="sm" c="dimmed">
                Sólo Binance está habilitado para ejecución PRD-003.
              </Text>
            )}
            {executionError && (
              <Alert color="red" variant="light" my="sm">
                {executionError}
              </Alert>
            )}
            {preflight && (
              <Table.ScrollContainer minWidth={420}>
                <Table>
                  <Table.Tbody>
                    {preflight.checks.map((check) => (
                      <Table.Tr key={check.name}>
                        <Table.Td>
                          <Badge
                            color={check.passed ? 'brand' : 'red'}
                            variant={check.passed ? 'light' : 'filled'}
                            tt="none"
                          >
                            {check.passed ? 'pass' : 'fail'}
                          </Badge>
                        </Table.Td>
                        <Table.Td>{reasonLabel(check.name)}</Table.Td>
                        <Table.Td c="dimmed" ff="monospace" className="mono-nums">
                          {check.detail ?? '—'}
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </Table.ScrollContainer>
            )}
            {testOrder && (
              <Alert color={testOrder.accepted ? 'brand' : 'red'} variant="light" mt="sm">
                <Text size="sm" fw={700}>
                  {reasonLabel(testOrder.status)}
                </Text>
                <Text size="xs" c="dimmed" ff="monospace">
                  {String(testOrder.exchange_response.client_order_id ?? 'rejected')}
                </Text>
              </Alert>
            )}
          </Box>

          <Box>
            <Text size="xs" c="dimmed" tt="uppercase" fw={700} mb={8}>
              Breakdown
            </Text>
            <Table.ScrollContainer minWidth={420}>
              <Table>
                <Table.Tbody>
                  {data.breakdown.map((c) => (
                    <Table.Tr key={c.key}>
                      <Table.Td>{c.label}</Table.Td>
                      <Table.Td ta="right" ff="monospace" className="mono-nums">
                        {money(c.usd, true)}
                      </Table.Td>
                      <Table.Td ta="right" ff="monospace" className="mono-nums" c="dimmed">
                        {money(c.per_btc, true)} / BTC
                      </Table.Td>
                    </Table.Tr>
                  ))}
                  {data.breakdown.length === 0 && (
                    <Table.Tr>
                      <Table.Td colSpan={3}>
                        <Text size="sm" c="dimmed">
                          Explicación parcial: la oportunidad se descartó antes del cálculo neto.
                        </Text>
                      </Table.Td>
                    </Table.Tr>
                  )}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          </Box>

          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
            <MiniMetric label="Buy quote/factor" value={`${data.peg.buy_quote ?? '—'} · ${data.peg.buy_factor ?? '—'}`} />
            <MiniMetric label="Sell quote/factor" value={`${data.peg.sell_quote ?? '—'} · ${data.peg.sell_factor ?? '—'}`} />
            <MiniMetric label="Peg adverse" value={pctFromBps(data.peg.peg_adverse_bps as number | null)} />
            <MiniMetric label="Notas" value={data.notes.length ? data.notes.join(', ') : '—'} />
          </SimpleGrid>
        </Stack>
      )}
    </Drawer>
  );
}
