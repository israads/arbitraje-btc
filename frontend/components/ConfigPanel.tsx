'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  Alert, Badge, Box, Button, Card, Group, NumberInput, ScrollArea,
  Switch, Table, Text,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconDeviceFloppy, IconSettings2, IconAlertTriangle } from '@tabler/icons-react';
import { API_BASE, READ_ONLY } from '../lib/config';
import { SectionHeader, VenueTag } from './primitives';

// Texto literal exigido por PRD-010 para todo control deshabilitado en la demo pública.
const RO_HINT = 'Demo pública read-only';

/**
 * Panel de CONFIGURACIÓN BASE editable (no what-if): balances pre-posicionados por venue, fees
 * y umbrales económicos. Se guarda persistente; fees/umbrales aplican en caliente y cambiar los
 * balances iniciales re-siembra el portfolio. `enabled` NO es editable en caliente (PRD-009):
 * requiere reiniciar el servicio. Sigue siendo simulación: no opera con dinero real.
 * GET/PUT /api/v1/config/sim.
 */

interface ExchangeCfg {
  enabled: boolean;
  fee_bps: number;
  initial_btc: number;
  initial_quote: number;
  quote_ccy: string;
  symbol: string;
}
interface SimConfig {
  exchanges: Record<string, ExchangeCfg>;
  default_trade_qty_btc: number;
  min_net_profit_usd: number;
  max_slippage: number;
}

const num = (v: string | number, fb: number) => {
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : fb;
};

export function ConfigPanel() {
  const [cfg, setCfg] = useState<SimConfig | null>(null);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/api/v1/config/sim`);
      if (r.ok) {
        setCfg(await r.json());
        setDirty(false);
      }
    } catch {
      /* empty state si falla */
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const patchVenue = (venue: string, patch: Partial<ExchangeCfg>) => {
    setCfg((c) => (c ? { ...c, exchanges: { ...c.exchanges, [venue]: { ...c.exchanges[venue], ...patch } } } : c));
    setDirty(true);
    setSaved(false);
  };
  const patchGlobal = (patch: Partial<SimConfig>) => {
    setCfg((c) => (c ? { ...c, ...patch } : c));
    setDirty(true);
    setSaved(false);
  };

  const save = async () => {
    if (!cfg || busy) return;
    // Read-only: el PUT protegido NO sale del navegador (el 401 no es el mecanismo de UX).
    if (READ_ONLY) return;
    setBusy(true);
    try {
      // `enabled` NO se envía: no es editable en caliente (requiere reiniciar el servicio).
      const payload = {
        exchanges: Object.fromEntries(
          Object.entries(cfg.exchanges).map(([k, e]) => [
            k,
            {
              fee_taker: e.fee_bps / 10_000,
              initial_btc: e.initial_btc,
              initial_quote: e.initial_quote,
            },
          ]),
        ),
        default_trade_qty_btc: cfg.default_trade_qty_btc,
        min_net_profit_usd: cfg.min_net_profit_usd,
        max_slippage: cfg.max_slippage,
      };
      const r = await fetch(`${API_BASE}/api/v1/config/sim`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (r.status === 401) {
        // Con token configurado, el backend responde 401 ANTES que el 409 de venues (PRD-010).
        notifications.show({ message: 'Requiere token de control', color: 'yellow' });
        return;
      }
      if (r.status === 409) {
        // Rama específica del bloqueo de venues (PRD-009): mensaje del backend, no genérico.
        const body409 = await r.json().catch(() => null);
        const detail = body409?.detail;
        const msg =
          detail?.code === 'venue_restart_required' && typeof detail?.message === 'string'
            ? detail.message
            : 'Cambiar los venues activos requiere reiniciar el servicio.';
        notifications.show({ title: 'Requiere reinicio', message: msg, color: 'yellow' });
        return;
      }
      if (!r.ok) throw new Error(`${r.status}`);
      const data = await r.json();
      if (data.config) setCfg(data.config);
      setDirty(false);
      setSaved(true);
      notifications.show({ message: 'Configuración guardada', color: 'brand' });
    } catch (e) {
      // TypeError = fetch no llegó al backend (red); otro status ya lanzó Error arriba.
      const msg =
        e instanceof TypeError
          ? 'Error de conexión con el backend'
          : 'No se pudo guardar la configuración';
      notifications.show({ message: msg, color: 'red' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card h="100%">
      <SectionHeader
        title="Configuración base"
        subtitle="balances, fees y venues · persistente"
        icon={<IconSettings2 size={18} />}
        help="La configuración REAL de la simulación (no what-if): los fondos iniciales por exchange, las comisiones y los umbrales. Fees y umbrales aplican en caliente; cambiar los balances iniciales re-siembra el portfolio. Activar/desactivar venues requiere reiniciar el servicio. Es simulación: no opera con dinero real."
        right={
          saved ? (
            <Badge variant="light" color="brand">
              Guardado
            </Badge>
          ) : dirty ? (
            <Badge variant="light" color="yellow">
              Sin guardar
            </Badge>
          ) : null
        }
      />

      {!cfg ? (
        <Text size="sm" c="dimmed">
          Cargando configuración…
        </Text>
      ) : (
        <>
          <ScrollArea.Autosize mah={280}>
            <Table verticalSpacing="xs">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Venue</Table.Th>
                  <Table.Th ta="center">Activo</Table.Th>
                  <Table.Th ta="right">Fee bps</Table.Th>
                  <Table.Th ta="right">BTC inicial</Table.Th>
                  <Table.Th ta="right">Quote inicial</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {Object.entries(cfg.exchanges).map(([venue, e]) => (
                  <Table.Tr key={venue} style={{ opacity: e.enabled ? 1 : 0.5 }}>
                    <Table.Td>
                      <VenueTag name={venue} />
                    </Table.Td>
                    <Table.Td ta="center">
                      {/* `enabled` no es editable en caliente (PRD-009): switch deshabilitado
                          + texto explícito (no sólo color) con el procedimiento. */}
                      <Switch
                        size="sm"
                        color="brand"
                        checked={e.enabled}
                        disabled
                        aria-label={`${venue} ${e.enabled ? 'activo' : 'inactivo'} — cambiarlo requiere reiniciar el servicio`}
                      />
                      <Text size="10px" c="dimmed" mt={2}>
                        Requiere reiniciar el servicio
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <NumberInput
                        size="xs"
                        min={0}
                        max={100}
                        step={1}
                        decimalScale={2}
                        disabled={READ_ONLY}
                        value={e.fee_bps}
                        onChange={(v) => patchVenue(venue, { fee_bps: num(v, e.fee_bps) })}
                        styles={{ input: { textAlign: 'right' } }}
                      />
                    </Table.Td>
                    <Table.Td>
                      <NumberInput
                        size="xs"
                        min={0}
                        step={0.5}
                        decimalScale={4}
                        disabled={READ_ONLY}
                        value={e.initial_btc}
                        onChange={(v) => patchVenue(venue, { initial_btc: num(v, e.initial_btc) })}
                        styles={{ input: { textAlign: 'right' } }}
                      />
                    </Table.Td>
                    <Table.Td>
                      <NumberInput
                        size="xs"
                        min={0}
                        step={10_000}
                        thousandSeparator=","
                        disabled={READ_ONLY}
                        value={e.initial_quote}
                        onChange={(v) => patchVenue(venue, { initial_quote: num(v, e.initial_quote) })}
                        styles={{ input: { textAlign: 'right' } }}
                      />
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </ScrollArea.Autosize>

          <Group gap="md" mt="md" align="flex-end">
            <NumberInput
              label="Tamaño trade (BTC)"
              size="xs"
              min={0.00001}
              step={0.05}
              decimalScale={5}
              disabled={READ_ONLY}
              value={cfg.default_trade_qty_btc}
              onChange={(v) => patchGlobal({ default_trade_qty_btc: num(v, cfg.default_trade_qty_btc) })}
              w={140}
            />
            <NumberInput
              label="Min neto (USD)"
              size="xs"
              step={1}
              decimalScale={2}
              disabled={READ_ONLY}
              value={cfg.min_net_profit_usd}
              onChange={(v) => patchGlobal({ min_net_profit_usd: num(v, cfg.min_net_profit_usd) })}
              w={130}
            />
            <NumberInput
              label="Max slippage"
              size="xs"
              min={0}
              max={0.05}
              step={0.0005}
              decimalScale={4}
              disabled={READ_ONLY}
              value={cfg.max_slippage}
              onChange={(v) => patchGlobal({ max_slippage: num(v, cfg.max_slippage) })}
              w={130}
            />
          </Group>

          <Alert
            mt="md"
            variant="light"
            color="gray"
            icon={<IconAlertTriangle size={15} />}
            p="xs"
          >
            <Text size="xs">
              Fees y umbrales aplican en caliente sin tocar el P&L. Cambiar los{' '}
              <b>balances iniciales re-siembra el portfolio</b> (reinicia P&L de la sesión).
              Activar/desactivar venues requiere reiniciar el servicio. Es simulación: no
              ejecuta operaciones reales.
            </Text>
          </Alert>

          <Button
            mt="sm"
            size="xs"
            color={dirty ? 'brand' : 'gray'}
            variant={dirty ? 'filled' : 'light'}
            leftSection={<IconDeviceFloppy size={15} />}
            loading={busy}
            disabled={!dirty || READ_ONLY}
            onClick={save}
            style={{ alignSelf: 'flex-start' }}
            aria-label={READ_ONLY ? `Guardar configuración base — ${RO_HINT}` : undefined}
          >
            Guardar configuración base
          </Button>
          {READ_ONLY && (
            <Text size="xs" c="dimmed" mt={4}>
              {RO_HINT}: la configuración se muestra pero no es editable.
            </Text>
          )}
        </>
      )}
    </Card>
  );
}
