'use client';

import { memo } from 'react';
import { Badge, Box, Card, Group, ScrollArea, Table, Text } from '@mantine/core';
import { IconTrophy, IconCircleCheck } from '@tabler/icons-react';
import type { WinsReport } from '../hooks/useStream';
import { POS, SectionHeader, VenueTag } from './primitives';

/**
 * Evidencia de ganancias: los spreads que SÍ funcionaron (capturados rentables, net > 0),
 * persistidos. Prueba de que el motor no solo descarta — también captura cuando hay edge real.
 * Datos de GET /api/v1/analysis/wins.
 */

const money = (n: number) => `$${n.toLocaleString('en-US', { maximumFractionDigits: 2 })}`;
const perBtc = (n: number | null) => (n == null ? '—' : `${money(n)}/BTC`);

function ts(epoch: number): string {
  try {
    return new Date(epoch * 1000).toLocaleTimeString('es-MX', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return '—';
  }
}

function WinsPanelImpl({ report }: { report: WinsReport | null }) {
  const empty = !report || report.count === 0;

  return (
    <Card h="100%">
      <SectionHeader
        title="Evidencia de ganancias"
        subtitle="spreads que SÍ funcionaron · capturados rentables"
        icon={<IconTrophy size={18} />}
        help="El registro de las oportunidades que el motor capturó con ganancia neta real (tras todos los costes). Es la contraparte del descarte: prueba de que cuando hay edge defendible, se ejecuta. Persistente entre sesiones."
        right={
          report && report.count > 0 ? (
            <Badge size="lg" variant="light" color="brand" leftSection={<IconCircleCheck size={13} />}>
              {report.count} ganadores
            </Badge>
          ) : null
        }
      />

      {empty ? (
        <Text size="sm" c="dimmed">
          Aún no hay capturas rentables en esta sesión. Aparecerán aquí cuando un spread sobreviva a
          todos los costes (a comisión retail es raro — ese es el punto de la tesis).
        </Text>
      ) : (
        <>
          <Group gap="xl" mb="sm">
            <Box>
              <Text fz={10} tt="uppercase" fw={700} c="dimmed">
                Total capturado
              </Text>
              <Text ff="monospace" fw={700} fz={22} className="mono-nums" style={{ color: POS }}>
                {money(report.total_net_usd)}
              </Text>
            </Box>
            <Box>
              <Text fz={10} tt="uppercase" fw={700} c="dimmed">
                Mejor edge
              </Text>
              <Text ff="monospace" fw={700} fz={22} className="mono-nums" style={{ color: POS }}>
                {perBtc(report.best_net_per_btc)}
              </Text>
            </Box>
            <Box>
              <Text fz={10} tt="uppercase" fw={700} c="dimmed">
                Trades
              </Text>
              <Text ff="monospace" fw={700} fz={22} className="mono-nums">
                {report.count}
              </Text>
            </Box>
          </Group>

          <ScrollArea.Autosize mah={240}>
            <Table highlightOnHover stickyHeader>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Hora</Table.Th>
                  <Table.Th>Ruta</Table.Th>
                  <Table.Th ta="right">Neto/BTC</Table.Th>
                  <Table.Th ta="right">Neto USD</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {report.wins.map((w, i) => (
                  <Table.Tr key={`${w.id}-${i}`}>
                    <Table.Td>
                      <Text size="xs" ff="monospace" c="dimmed">
                        {ts(w.created_at)}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Group gap={4} wrap="nowrap">
                        <VenueTag name={w.buy_venue} fw={500} />
                        <Text c="dimmed">→</Text>
                        <VenueTag name={w.sell_venue} fw={500} />
                      </Group>
                    </Table.Td>
                    <Table.Td ta="right">
                      <Text size="sm" ff="monospace" className="mono-nums" style={{ color: POS }}>
                        {perBtc(w.net_per_btc)}
                      </Text>
                    </Table.Td>
                    <Table.Td ta="right">
                      <Text size="sm" ff="monospace" className="mono-nums" style={{ color: POS }}>
                        {money(w.net_usd)}
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </ScrollArea.Autosize>
        </>
      )}
    </Card>
  );
}

export const WinsPanel = memo(WinsPanelImpl);
