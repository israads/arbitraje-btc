'use client';

import { Badge, Button, Card, Group, SegmentedControl, Stack, Text } from '@mantine/core';
import { IconAlertTriangle, IconBolt, IconDownload, IconPlayerPlay, IconShieldHalf } from '@tabler/icons-react';
import { useEffect, useState } from 'react';
import { API_BASE } from '../lib/config';
import type { BreakerStatus, DemoStatus } from '../hooks/useStream';
import { SectionHeader } from './primitives';

const BREAKER_LABEL: Record<string, string> = {
  stale_data: 'Datos stale',
  volatility: 'Volatilidad',
  inventory_skew: 'Skew inventario',
  max_drawdown: 'Drawdown',
  kill_switch: 'Kill switch',
};

interface JuryScenarioInfo {
  name: string;
  description: string;
  kind: string;
  expected_result: string | null;
}

/**
 * Panel de control del operador (C18): kill switch / resume (C8) y modo del fallback de
 * demo (C16), más el estado vivo de los circuit breakers. Las acciones hacen POST al
 * backend; el estado resultante llega de vuelta por SSE (breaker/demo) y polling.
 */
export function ControlPanel({ breakers, demo }: { breakers: BreakerStatus; demo: DemoStatus }) {
  const [busy, setBusy] = useState(false);
  const [scenarios, setScenarios] = useState<JuryScenarioInfo[]>([]);

  useEffect(() => {
    fetch(`${API_BASE}/api/v1/demo/scenarios`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { scenarios?: JuryScenarioInfo[] } | null) => {
        if (Array.isArray(d?.scenarios)) setScenarios(d.scenarios);
      })
      .catch(() => undefined);
  }, []);

  const post = async (path: string) => {
    if (busy) return; // evita acciones solapadas (doble-click / cambio rápido de modo)
    setBusy(true);
    try {
      await fetch(`${API_BASE}/api/v1/${path}`, { method: 'POST' });
    } catch {
      /* el estado real llega por SSE/polling; un fallo de red no rompe la UI */
    } finally {
      setBusy(false);
    }
  };

  const exportSession = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/session/export`);
      if (!res.ok) return;
      const data = await res.json();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      const stamp = new Date().toISOString().replace(/[:.]/g, '-');
      a.href = url;
      a.download = `arbitraje-session-${stamp}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      /* el export es auxiliar; si falla no bloquea la operación */
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card h="100%">
      <SectionHeader
        title="Control"
        icon={<IconShieldHalf size={18} />}
        help="Controles del operador. Kill switch = freno de emergencia (detiene toda ejecución al instante). Resume = reanuda tras un kill switch o un breaker. Fallback de demo: Auto/Replay/Jury/Off (Jury reproduce 7 escenarios y avanza solo). Circuit breakers: pausas automáticas por datos viejos, volatilidad, inventario o drawdown."
        right={
          <Badge color={breakers.halted ? 'red' : 'brand'} variant={breakers.halted ? 'filled' : 'light'}>
            {breakers.halted ? 'HALTED' : 'OPERANDO'}
          </Badge>
        }
      />

      <Stack gap="md">
        <Group gap="xs" grow>
          <Button
            color="red"
            variant="filled"
            leftSection={<IconBolt size={16} />}
            loading={busy}
            onClick={() => post('control/kill-switch')}
            aria-label="Kill switch: detener inmediatamente toda operación del bot"
          >
            Kill switch
          </Button>
          <Button
            color="brand"
            variant="light"
            leftSection={<IconPlayerPlay size={16} />}
            loading={busy}
            onClick={() => post('control/resume')}
            aria-label="Reanudar la operación tras un halt"
          >
            Resume
          </Button>
        </Group>

        <div>
          <Text size="xs" tt="uppercase" fw={600} c="dimmed" mb={6} style={{ letterSpacing: 0 }}>
            Fallback de demo
          </Text>
          <SegmentedControl
            fullWidth
            size="sm"
            aria-label="Modo del fallback de demo a replay"
            value={demo.mode}
            disabled={busy}
            onChange={(v) => post(`demo?mode=${v}`)}
            data={[
              { label: 'Auto', value: 'auto' },
              { label: 'Replay', value: 'on' },
              { label: 'Jury', value: 'jury' },
              { label: 'Off', value: 'off' },
            ]}
          />
          {demo.active && (
            <Badge color="orange" variant="light" mt="xs" fullWidth>
              {demo.mode === 'jury' && demo.scenario
                ? `JURY · ${demo.scenario_index ?? 0}/${demo.n_scenarios ?? 0} · ${demo.scenario}`
                : `DEMO DATA · ${demo.n_replay_ticks ?? 0} ticks`}
            </Badge>
          )}
        </div>

        {scenarios.length > 0 && (
          <div>
            <Text size="xs" tt="uppercase" fw={600} c="dimmed" mb={6} style={{ letterSpacing: 0 }}>
              Escenarios adversos
            </Text>
            <Group gap={6}>
              {scenarios.map((s) => (
                <Button
                  key={s.name}
                  size="compact-xs"
                  variant={demo.scenario === s.name ? 'filled' : 'light'}
                  color={s.kind === 'execution' ? 'red' : 'yellow'}
                  leftSection={s.kind === 'execution' ? <IconAlertTriangle size={13} /> : undefined}
                  loading={busy && demo.scenario === s.name}
                  title={s.description}
                  onClick={() => post(`demo/scenario/${encodeURIComponent(s.name)}`)}
                >
                  {s.name.replaceAll('_', ' ')}
                </Button>
              ))}
            </Group>
            {demo.expected_result && (
              <Badge color="gray" variant="default" mt="xs" tt="none">
                esperado: {demo.expected_result.replaceAll('_', ' ')}
              </Badge>
            )}
          </div>
        )}

        <Button
          variant="light"
          color="gray"
          leftSection={<IconDownload size={16} />}
          loading={busy}
          onClick={exportSession}
        >
          Export session
        </Button>

        <div>
          <Text size="xs" tt="uppercase" fw={600} c="dimmed" mb={6} style={{ letterSpacing: 0 }}>
            Circuit breakers
          </Text>
          <Group gap={6}>
            {breakers.breakers.length === 0 && (
              <Text size="xs" c="dimmed">
                sin breakers configurados
              </Text>
            )}
            {breakers.breakers.map((b) => (
              <Badge
                key={b.type}
                variant={b.active ? 'filled' : 'default'}
                color={b.active ? 'red' : 'gray'}
                tt="none"
                title={b.reason ?? undefined}
              >
                {BREAKER_LABEL[b.type] ?? b.type}
              </Badge>
            ))}
          </Group>
        </div>
      </Stack>
    </Card>
  );
}
