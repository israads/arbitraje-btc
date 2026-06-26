'use client';

import { useCallback, useEffect, useState } from 'react';
import { Badge, Box, Button, Card, Group, SegmentedControl, Stack, Text, Tooltip } from '@mantine/core';
import { IconDatabase, IconDeviceFloppy, IconAlertTriangle } from '@tabler/icons-react';
import { API_BASE } from '../lib/config';
import { POS, NEG, SectionHeader } from './primitives';

/**
 * Panel de Almacenamiento: uso real de la DB + política de retención. Mide tasa de inserción
 * y bytes/fila desde la propia DB y proyecta el tamaño en estado estacionario por ventana
 * (1/6/12/18/24 h). Autónomo: hace su propio fetch a `/storage` (evita el count(*) en el poll
 * global) y re-mide tras aplicar. Datos de `GET /storage` · `PATCH /storage/retention`.
 */

interface StorageEstimate {
  retention_hours: number;
  bytes: number;
  mb: number;
}
interface StorageStats {
  file_mb: number;
  file_gb: number;
  opp_rows: number;
  exec_rows: number;
  rows_per_second: number;
  rows_per_hour: number;
  mb_per_hour: number;
  mb_per_day: number;
  bytes_per_row: number;
  span_days: number;
  retention_hours: number;
  disk_free_gb: number;
  estimates: StorageEstimate[];
}

const CHOICES = [
  { value: '0', label: '∞' },
  { value: '1', label: '1h' },
  { value: '6', label: '6h' },
  { value: '12', label: '12h' },
  { value: '18', label: '18h' },
  { value: '24', label: '24h' },
];

const fmtSize = (mb: number) => (mb >= 1000 ? `${(mb / 1000).toFixed(2)} GB` : `${mb.toFixed(0)} MB`);
const intl = (n: number) => n.toLocaleString('en-US');

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  const body = (
    <Box>
      <Text size="xs" tt="uppercase" fw={600} c="dimmed" style={{ fontSize: 10 }}>
        {label}
      </Text>
      <Text ff="monospace" fw={700} fz={18} className="mono-nums" lh={1.2}>
        {value}
      </Text>
    </Box>
  );
  return hint ? (
    <Tooltip label={hint} withArrow position="top">
      <Box style={{ cursor: 'help' }}>{body}</Box>
    </Tooltip>
  ) : (
    body
  );
}

export function StoragePanel() {
  const [stats, setStats] = useState<StorageStats | null>(null);
  const [selected, setSelected] = useState('24');
  const [busy, setBusy] = useState(false);
  const [loadingStats, setLoadingStats] = useState(true);

  const load = useCallback(async () => {
    setLoadingStats(true);
    try {
      const r = await fetch(`${API_BASE}/api/v1/storage`);
      if (!r.ok) throw new Error(String(r.status));
      const s: StorageStats = await r.json();
      setStats(s);
      setSelected(String(Math.round(s.retention_hours)));
    } catch {
      /* el panel muestra estado vacío si /storage falla */
    } finally {
      setLoadingStats(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const apply = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const r = await fetch(`${API_BASE}/api/v1/storage/retention`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ retention_hours: Number(selected) }),
      });
      if (r.ok) {
        const data = await r.json();
        if (data.storage) setStats(data.storage);
      }
    } catch {
      /* sin cambios si el backend rechaza */
    } finally {
      setBusy(false);
    }
  };

  const selHours = Number(selected);
  const estimate =
    selHours === 0
      ? null
      : stats?.estimates.find((e) => Math.round(e.retention_hours) === selHours) ?? null;
  const bloated = !!stats && stats.file_gb >= 2;
  const dirty = !!stats && Math.round(stats.retention_hours) !== selHours;

  return (
    <Card h="100%">
      <SectionHeader
        title="Almacenamiento"
        subtitle="base de datos · política de retención"
        icon={<IconDatabase size={18} />}
        right={
          stats ? (
            <Badge
              size="lg"
              variant="light"
              color={stats.retention_hours > 0 ? 'brand' : 'red'}
              leftSection={stats.retention_hours > 0 ? null : <IconAlertTriangle size={13} />}
            >
              {stats.retention_hours > 0 ? `retención ${Math.round(stats.retention_hours)}h` : 'sin límite'}
            </Badge>
          ) : null
        }
      />

      {loadingStats && !stats ? (
        <Text size="sm" c="dimmed">
          Midiendo la base de datos… (un primer cálculo sobre una DB grande puede tardar)
        </Text>
      ) : !stats ? (
        <Text size="sm" c="dimmed">
          No se pudo leer el estado de almacenamiento.
        </Text>
      ) : (
        <Stack gap="md">
          <Group gap="xl">
            <Metric
              label="Tamaño actual"
              value={stats.file_gb >= 1 ? `${stats.file_gb.toFixed(2)} GB` : `${stats.file_mb.toFixed(0)} MB`}
              hint={`${intl(stats.opp_rows)} oportunidades · ${intl(stats.exec_rows)} ejecuciones`}
            />
            <Metric
              label="Ritmo"
              value={`${stats.mb_per_day.toFixed(0)} MB/día`}
              hint={`${stats.rows_per_second.toFixed(1)} filas/s · ${stats.bytes_per_row.toFixed(0)} B/fila`}
            />
            <Metric label="Disco libre" value={`${stats.disk_free_gb.toFixed(0)} GB`} />
          </Group>

          {bloated && (
            <Group gap={6} wrap="nowrap" style={{ color: NEG }}>
              <IconAlertTriangle size={15} />
              <Text size="xs" style={{ color: NEG }}>
                La DB acumuló {stats.file_gb.toFixed(1)} GB sin poda. Aplica una retención para acotarla.
              </Text>
            </Group>
          )}

          <Box>
            <Text size="xs" tt="uppercase" fw={600} c="dimmed" mb={6} style={{ fontSize: 10 }}>
              Conservar histórico
            </Text>
            <SegmentedControl
              fullWidth
              size="xs"
              value={selected}
              onChange={setSelected}
              data={CHOICES}
              color="brand"
            />
          </Box>

          <Box
            style={{
              borderRadius: 12,
              border: '1px solid rgba(22,214,127,0.22)',
              background: 'linear-gradient(160deg, rgba(22,214,127,0.08), transparent 70%)',
              padding: '12px 14px',
            }}
          >
            <Text size="xs" c="dimmed">
              {selHours === 0 ? 'Sin límite' : `Retención ${selHours}h`} · estimación en estado estacionario
            </Text>
            <Text ff="monospace" fw={700} fz={26} className="mono-nums" style={{ color: selHours === 0 ? NEG : POS }}>
              {selHours === 0 ? 'crece sin fin' : estimate ? fmtSize(estimate.mb) : '—'}
            </Text>
            <Text size="xs" c="dimmed">
              {selHours === 0
                ? 'No recomendado: la DB seguirá creciendo ~' + stats.mb_per_day.toFixed(0) + ' MB/día'
                : `de ${fmtSize(stats.file_mb)} actuales · sobra disco (${stats.disk_free_gb.toFixed(0)} GB libres)`}
            </Text>
          </Box>

          <Button
            size="xs"
            color={dirty ? 'brand' : 'gray'}
            variant={dirty ? 'filled' : 'light'}
            leftSection={<IconDeviceFloppy size={15} />}
            loading={busy}
            onClick={apply}
            style={{ alignSelf: 'flex-start' }}
          >
            {dirty ? 'Aplicar y podar ahora' : 'Guardado'}
          </Button>
        </Stack>
      )}
    </Card>
  );
}
