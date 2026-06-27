'use client';

import { memo, useEffect, useRef, useState } from 'react';
import { Badge, Card, Table, Text } from '@mantine/core';
import { IconBuildingBank } from '@tabler/icons-react';
import type { Quote } from '../hooks/useStream';
import { SectionHeader, VenueTag } from './primitives';

function fmt(n: number | null | undefined): string {
  return n == null
    ? '—'
    : n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** Detecta cambios de un número y devuelve una clase de flash (tick-up/down) por ~280ms. */
function useTickFlash(value: number | null): string {
  const prev = useRef<number | null>(null);
  const [flash, setFlash] = useState('');
  useEffect(() => {
    if (value != null && prev.current != null && value !== prev.current) {
      setFlash(value > prev.current ? 'tick-up' : 'tick-down');
      const id = window.setTimeout(() => setFlash(''), 280);
      prev.current = value;
      return () => window.clearTimeout(id);
    }
    prev.current = value;
    return undefined;
  }, [value]);
  return flash;
}

/** Celda de precio con flash verde/rojo al actualizar (price tick) y resaltado del mejor
 * bid/ask vía píldora con tinte de marca. */
function PriceCell({ value, best }: { value: number | null; best: boolean }) {
  const flash = useTickFlash(value);
  return (
    <Table.Td ta="right" className={flash || undefined}>
      <Text
        component="span"
        ff="monospace"
        className="mono-nums"
        fw={best ? 700 : 500}
        c={best ? '#06210f' : undefined}
        px={best ? 8 : 0}
        py={best ? 2 : 0}
        style={
          best
            ? {
                background: 'var(--brand)',
                borderRadius: 6,
                display: 'inline-block',
              }
            : undefined
        }
      >
        {fmt(value)}
      </Text>
    </Table.Td>
  );
}

export const PricesTable = memo(PricesTableImpl);

function PricesTableImpl({ quotes }: { quotes: Record<string, Quote> }) {
  const rows = Object.values(quotes).sort((a, b) => a.exchange.localeCompare(b.exchange));
  const asks = rows.map((q) => q.usd_ask).filter((x): x is number => x != null);
  const bids = rows.map((q) => q.usd_bid).filter((x): x is number => x != null);
  const bestAsk = asks.length ? Math.min(...asks) : null; // más barato para comprar
  const bestBid = bids.length ? Math.max(...bids) : null; // mejor para vender

  return (
    <Card h="100%">
      <SectionHeader
        title="Precios por exchange"
        subtitle="normalizados a USD · resaltado = mejor compra/venta"
        icon={<IconBuildingBank size={18} />}
      />
      <Table.ScrollContainer minWidth={680}>
        <Table highlightOnHover striped stripedColor="rgba(255,255,255,0.015)">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Exchange</Table.Th>
              <Table.Th>Par</Table.Th>
              <Table.Th ta="right">Bid nativo</Table.Th>
              <Table.Th ta="right">Ask nativo</Table.Th>
              <Table.Th ta="right">Bid USD</Table.Th>
              <Table.Th ta="right">Ask USD</Table.Th>
              <Table.Th ta="right">peg</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.length === 0 && (
              <Table.Tr>
                <Table.Td colSpan={7}>
                  <Text c="dimmed" size="sm" py="md" ta="center">
                    Esperando datos en vivo…
                  </Text>
                </Table.Td>
              </Table.Tr>
            )}
            {rows.map((q) => {
              const f = q.price_norm_factor || 1;
              const nativeBid = q.usd_bid != null ? q.usd_bid / f : null;
              const nativeAsk = q.usd_ask != null ? q.usd_ask / f : null;
              const isBestBid = bestBid != null && q.usd_bid === bestBid;
              const isBestAsk = bestAsk != null && q.usd_ask === bestAsk;
              const pegOff = Math.abs(f - 1) > 0.005;
              return (
                <Table.Tr key={q.exchange}>
                  <Table.Td>
                    <VenueTag name={q.exchange} />
                  </Table.Td>
                  <Table.Td>
                    <Badge variant="default" size="sm" tt="none">
                      {q.symbol}
                    </Badge>
                  </Table.Td>
                  <Table.Td ta="right" ff="monospace" className="mono-nums" c="dimmed">
                    {fmt(nativeBid)}
                  </Table.Td>
                  <Table.Td ta="right" ff="monospace" className="mono-nums" c="dimmed">
                    {fmt(nativeAsk)}
                  </Table.Td>
                  <PriceCell value={q.usd_bid} best={isBestBid} />
                  <PriceCell value={q.usd_ask} best={isBestAsk} />
                  <Table.Td
                    ta="right"
                    ff="monospace"
                    className="mono-nums"
                    c={pegOff ? 'orange.4' : 'dimmed'}
                    fw={pegOff ? 700 : 400}
                  >
                    {f.toFixed(5)}
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Card>
  );
}
