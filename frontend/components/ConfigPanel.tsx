'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  Alert, Badge, Box, Button, Card, Group, NumberInput, ScrollArea,
  Switch, Table, Text,
} from '@mantine/core';
import { IconDeviceFloppy, IconSettings2, IconAlertTriangle } from '@tabler/icons-react';
import { API_BASE } from '../lib/config';
import { SectionHeader, VenueTag } from './primitives';

/**
 * Panel de CONFIGURACIÓN BASE editable (no what-if): balances pre-posicionados por venue, fees,
 * venues habilitados y umbrales económicos. Se guarda persistente y el motor la aplica
 * (re-siembra el portfolio). Sigue siendo simulación: no opera con dinero real.
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
    setBusy(true);
    try {
      const payload = {
        exchanges: Object.fromEntries(
          Object.entries(cfg.exchanges).map(([k, e]) => [
            k,
            {
              enabled: e.enabled,
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
      if (r.ok) {
        const data = await r.json();
        if (data.config) setCfg(data.config);
        setDirty(false);
        setSaved(true);
      }
    } catch {
      /* sin cambios si falla */
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
        help="La configuración REAL de la simulación (no what-if): los fondos iniciales por exchange, las comisiones, qué venues están activos y los umbrales. Se guarda y el motor la usa al instante (re-siembra los balances). Es simulación: no opera con dinero real."
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
                      <Switch
                        size="sm"
                        color="brand"
                        checked={e.enabled}
                        onChange={(ev) => patchVenue(venue, { enabled: ev.currentTarget.checked })}
                        aria-label={`Activar ${venue}`}
                      />
                    </Table.Td>
                    <Table.Td>
                      <NumberInput
                        size="xs"
                        min={0}
                        max={100}
                        step={1}
                        decimalScale={2}
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
              value={cfg.default_trade_qty_btc}
              onChange={(v) => patchGlobal({ default_trade_qty_btc: num(v, cfg.default_trade_qty_btc) })}
              w={140}
            />
            <NumberInput
              label="Min neto (USD)"
              size="xs"
              step={1}
              decimalScale={2}
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
              Guardar aplica la config al motor y <b>re-siembra los balances</b> (reinicia P&L de la
              sesión). Es simulación: no ejecuta operaciones reales.
            </Text>
          </Alert>

          <Button
            mt="sm"
            size="xs"
            color={dirty ? 'brand' : 'gray'}
            variant={dirty ? 'filled' : 'light'}
            leftSection={<IconDeviceFloppy size={15} />}
            loading={busy}
            disabled={!dirty}
            onClick={save}
            style={{ alignSelf: 'flex-start' }}
          >
            Guardar configuración base
          </Button>
        </>
      )}
    </Card>
  );
}
