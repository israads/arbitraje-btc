'use client';

import { Badge, Box, Button, Card, Group, SegmentedControl, Stack, Text, Tooltip } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconAlertTriangle, IconBolt, IconDownload, IconPlayerPlay, IconShieldHalf } from '@tabler/icons-react';
import { useEffect, useState } from 'react';
import { API_BASE, READ_ONLY } from '../lib/config';
import type { BreakerStatus, DemoStatus } from '../hooks/useStream';
import { SectionHeader } from './primitives';

// Texto literal exigido por PRD-010 para todo control deshabilitado en la demo pública.
const RO_HINT = 'Demo pública read-only';

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

  // okMsg: toast de éxito (sólo acciones críticas); errMsg: toast de error siempre.
  const post = async (path: string, okMsg?: string, errMsg = 'No se pudo aplicar la acción') => {
    if (busy) return; // evita acciones solapadas (doble-click / cambio rápido de modo)
    // Read-only: la petición protegida NO sale del navegador (el 401 no es el mecanismo de UX).
    if (READ_ONLY) return;
    setBusy(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/${path}`, { method: 'POST' });
      if (res.status === 401) {
        notifications.show({ message: 'Requiere token de control', color: 'yellow' });
        return;
      }
      if (!res.ok) throw new Error(`${res.status}`);
      if (okMsg) notifications.show({ message: okMsg, color: 'brand' });
    } catch (e) {
      // El estado real llega por SSE/polling, pero el operador debe ENTERARSE del fallo.
      // TypeError = fetch no llegó al backend (red); otro status ya lanzó Error arriba.
      const msg = e instanceof TypeError ? 'Error de conexión con el backend' : errMsg;
      notifications.show({ message: msg, color: 'red' });
    } finally {
      setBusy(false);
    }
  };

  const exportSession = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/session/export`);
      if (!res.ok) throw new Error(`${res.status}`);
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
      notifications.show({ message: 'Sesión exportada', color: 'brand' });
    } catch {
      notifications.show({ message: 'No se pudo exportar la sesión', color: 'red' });
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
        {/* En read-only los controles quedan visibles pero deshabilitados; el Tooltip va
            sobre un Box wrapper porque los elementos disabled no reciben eventos. */}
        <Group gap="xs" grow>
          <Tooltip label={RO_HINT} withArrow disabled={!READ_ONLY}>
            <Box>
              <Button
                fullWidth
                color="red"
                variant="filled"
                leftSection={<IconBolt size={16} />}
                loading={busy && !READ_ONLY}
                disabled={READ_ONLY}
                onClick={() =>
                  post('control/kill-switch', 'Kill switch activado', 'No se pudo activar el kill switch')
                }
                aria-label={`Kill switch: detener inmediatamente toda operación del bot${READ_ONLY ? ` — ${RO_HINT}` : ''}`}
              >
                Kill switch
              </Button>
            </Box>
          </Tooltip>
          <Tooltip label={RO_HINT} withArrow disabled={!READ_ONLY}>
            <Box>
              <Button
                fullWidth
                color="brand"
                variant="light"
                leftSection={<IconPlayerPlay size={16} />}
                loading={busy && !READ_ONLY}
                disabled={READ_ONLY}
                onClick={() =>
                  post('control/resume', 'Operación reanudada', 'No se pudo reanudar la operación')
                }
                aria-label={`Reanudar la operación tras un halt${READ_ONLY ? ` — ${RO_HINT}` : ''}`}
              >
                Resume
              </Button>
            </Box>
          </Tooltip>
        </Group>

        <div>
          <Text size="xs" tt="uppercase" fw={600} c="dimmed" mb={6} style={{ letterSpacing: 0 }}>
            Fallback de demo
          </Text>
          <Tooltip label={RO_HINT} withArrow disabled={!READ_ONLY}>
            <Box>
              <SegmentedControl
                fullWidth
                size="sm"
                aria-label={`Modo del fallback de demo a replay${READ_ONLY ? ` — ${RO_HINT}` : ''}`}
                value={demo.mode}
                disabled={busy || READ_ONLY}
                onChange={(v) => post(`demo?mode=${v}`)}
                data={[
                  { label: 'Auto', value: 'auto' },
                  { label: 'Replay', value: 'on' },
                  { label: 'Jury', value: 'jury' },
                  { label: 'Off', value: 'off' },
                ]}
              />
            </Box>
          </Tooltip>
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
                  loading={busy && !READ_ONLY && demo.scenario === s.name}
                  disabled={READ_ONLY}
                  title={READ_ONLY ? RO_HINT : s.description}
                  onClick={() => post(`demo/scenario/${encodeURIComponent(s.name)}`)}
                >
                  {s.name.replaceAll('_', ' ')}
                </Button>
              ))}
            </Group>
            {READ_ONLY && (
              <Text size="xs" c="dimmed" mt={4}>
                {RO_HINT}: los escenarios se lanzan por CLI del operador.
              </Text>
            )}
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
