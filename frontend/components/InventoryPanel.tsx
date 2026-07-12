'use client';

import { Badge, Box, Card, Group, SimpleGrid, Stack, Table, Text } from '@mantine/core';
import { IconBuildingBank, IconInfoCircle } from '@tabler/icons-react';
import type {
  BalancesResponse,
  DecisionRebalanceCost,
  InventorySkew,
  Pnl,
  RebalanceSummary,
} from '../hooks/useStream';
import { FetchFallback, NEG, POS, SectionHeader, StatCard, VenueTag } from './primitives';

/**
 * Panel Inventario & Rebalanceo (PRD-012, criterio C3): responde "¿dónde está el BTC?" sin
 * abrir DevTools. Presentación pura (patrón NaiveVsEdgePanel): cero fetch, cero copia de
 * estado — el I/O vive en useStream porque la pestaña Operación usa keepMounted={false}.
 * Reglas de datos: /balances manda en saldos/equity/skew; /pnl es respaldo independiente y
 * la ÚNICA fuente de eventos de rebalanceo. Ausencia se pinta "—", nunca 0.
 */

export interface InventoryPanelProps {
  balances: BalancesResponse | null;
  pnl: Pnl | null;
  decisionCost: DecisionRebalanceCost | null;
  loading: boolean;
  error: boolean;
  updatedAt: number | null;
  onRetry: () => void;
}

const money = (n: number) =>
  `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const fin = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n);
const record = (value: unknown): value is Record<string, unknown> =>
  value != null && typeof value === 'object' && !Array.isArray(value);

/** Guard runtime: el backend devuelve `skew: {}` sin portfolio; TS no valida JSON. */
function isSkew(s: unknown): s is InventorySkew {
  if (!record(s)) return false;
  const x = s as Partial<InventorySkew>;
  return (
    record(x.btc_by_venue) && fin(x.total_btc) && fin(x.skew) && fin(x.limit) &&
    typeof x.breached === 'boolean'
  );
}

function isRebalance(r: unknown): r is RebalanceSummary {
  if (!record(r)) return false;
  const x = r as Partial<RebalanceSummary>;
  return (
    fin(x.count) && fin(x.cost_total_usd) && Array.isArray(x.recent) &&
    x.recent.every(record)
  );
}

function isBalanceShape(value: unknown): value is { exchange: string; asset: string; amount: number } {
  if (!record(value)) return false;
  return typeof value.exchange === 'string' && typeof value.asset === 'string' &&
    typeof value.amount === 'number';
}

/** Barra horizontal comparable: escala por columna contra el máximo |valor| finito.
 * Negativo usa NEG (no una barra positiva engañosa); máximo 0 → barra 0 %. */
function MetricBar({
  value,
  max,
  format,
  label,
}: {
  value: number | null;
  max: number;
  format: (n: number) => string;
  label: string;
}) {
  if (value == null) {
    return (
      <Text size="sm" c="dimmed" ff="monospace" className="mono-nums" aria-label={`${label}: sin dato`}>
        —
      </Text>
    );
  }
  const pct = max > 0 ? Math.min(100, (Math.abs(value) / max) * 100) : 0;
  const color = value < 0 ? NEG : POS;
  return (
    <Box aria-label={`${label}: ${format(value)}`}>
      <Text size="sm" ff="monospace" className="mono-nums" fw={600} style={{ color: value < 0 ? NEG : undefined }}>
        {format(value)}
      </Text>
      <Box mt={3} style={{ height: 4, borderRadius: 999, background: 'rgba(255,255,255,0.05)' }}>
        <Box
          style={{
            width: `${pct}%`,
            height: '100%',
            borderRadius: 999,
            background: color,
            opacity: 0.65,
            transition: 'width 350ms ease',
          }}
        />
      </Box>
    </Box>
  );
}

/** Fila por venue: BTC / Quote / Equity simulada. `null` = dato ausente (se pinta "—"). */
interface VenueRow {
  exchange: string;
  btc: number | null;
  quote: number | null;
  quoteCcy: string | null;
  equity: number | null;
}

function buildRows(balances: BalancesResponse | null, equityByVenue: Record<string, number>, skew: InventorySkew | null): VenueRow[] {
  const names = new Set<string>();
  const items = Array.isArray(balances?.balances)
    ? balances.balances.filter(isBalanceShape)
    : [];
  for (const b of items) if (b.exchange) names.add(b.exchange);
  for (const v of Object.keys(equityByVenue)) names.add(v);
  if (skew) for (const v of Object.keys(skew.btc_by_venue)) names.add(v);
  return Array.from(names).sort().map((exchange) => {
    const btcAmount = items.find((b) => b.exchange === exchange && b.asset === 'BTC')?.amount;
    const quoteItem = items.find((b) => b.exchange === exchange && b.asset !== 'BTC');
    const quoteAmount = quoteItem?.amount;
    const skewBtc = skew?.btc_by_venue[exchange];
    const equity = equityByVenue[exchange];
    return {
      exchange,
      btc: fin(btcAmount) ? btcAmount : fin(skewBtc) ? skewBtc : null,
      quote: fin(quoteAmount) ? quoteAmount : null,
      quoteCcy: quoteItem?.asset ?? null,
      equity: fin(equity) ? equity : null,
    };
  });
}

function tsLabel(ts: number): string {
  if (!fin(ts) || ts <= 0) return 'timestamp no disponible';
  return new Date(ts * 1000).toLocaleTimeString();
}

export function InventoryPanel({
  balances,
  pnl,
  decisionCost,
  loading,
  error,
  updatedAt,
  onRetry,
}: InventoryPanelProps) {
  // /balances manda cuando la forma está completa; /pnl es respaldo independiente por sección.
  const balSkew = balances?.skew;
  const pnlSkew = pnl?.skew;
  const skew: InventorySkew | null = isSkew(balSkew) ? balSkew : isSkew(pnlSkew) ? pnlSkew : null;
  const balancesEq = record(balances?.equity_by_venue)
    ? balances.equity_by_venue
    : null;
  const pnlEq = record(pnl?.equity_by_venue) ? pnl.equity_by_venue : {};
  const equityByVenue: Record<string, number> =
    balancesEq && Object.keys(balancesEq).length > 0
      ? balancesEq
      : pnlEq;
  const pnlRebalance = pnl?.rebalance;
  const rebalance = isRebalance(pnlRebalance) ? pnlRebalance : null;
  const rawEquityUsd = balances?.equity_usd;
  const equityUsd = fin(rawEquityUsd) ? rawEquityUsd : null;

  const rows = buildRows(balances, equityByVenue, skew);
  const maxBtc = Math.max(0, ...rows.map((r) => (r.btc != null ? Math.abs(r.btc) : 0)));
  const maxQuote = Math.max(0, ...rows.map((r) => (r.quote != null ? Math.abs(r.quote) : 0)));
  const maxEquity = Math.max(0, ...rows.map((r) => (r.equity != null ? Math.abs(r.equity) : 0)));

  // Vacío honesto del backend (sin portfolio): no fabricamos venues ni $0.00.
  const emptyPortfolio =
    !!balances && Array.isArray(balances.balances) && balances.balances.length === 0 &&
    balances.snapshot === null;
  const stale = error && balances != null;

  // Skew: `breached` del backend manda sobre color/estado; limit<=0 = dato no disponible.
  const skewPct = skew && skew.limit > 0 ? Math.min(Math.abs(skew.skew) / skew.limit, 1) : null;

  return (
    <Card>
      <SectionHeader
        title="Inventario & Rebalanceo"
        subtitle="capital simulado por venue · dónde está el BTC"
        icon={<IconBuildingBank size={18} />}
        help="Saldos simulados por exchange (BTC y quote), equity marcada a mercado, skew de inventario frente a su límite y los rebalanceos ejecutados con su coste debitado. Todo es capital simulado: ninguna cifra es un saldo real."
        right={
          <Group gap="xs" wrap="nowrap">
            {stale && (
              <Badge variant="light" color="yellow">
                DATOS DESACTUALIZADOS
                {updatedAt != null ? ` · ${new Date(updatedAt).toLocaleTimeString()}` : ''}
              </Badge>
            )}
            <Badge variant="light" color="gray">
              SIMULADO
            </Badge>
          </Group>
        }
      />

      <Stack gap="md">
        {/* Saldos por venue (fuente: /balances; respaldo parcial: /pnl) */}
        {balances == null && !(skew || rows.length > 0) ? (
          <FetchFallback error={error} onRetry={onRetry} loading="Cargando inventario simulado…" />
        ) : emptyPortfolio ? (
          <Text size="sm" c="dimmed">
            Portfolio no inicializado: el backend aún no tiene balances simulados que mostrar.
          </Text>
        ) : rows.length === 0 && loading ? (
          <FetchFallback error={error} onRetry={onRetry} loading="Cargando inventario simulado…" />
        ) : (
          <Table.ScrollContainer minWidth={680}>
            <Table verticalSpacing={8} horizontalSpacing="md" withRowBorders={false}>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>
                  <Text size="xs" tt="uppercase" fw={700} c="dimmed" style={{ fontSize: 10 }}>Venue</Text>
                </Table.Th>
                <Table.Th>
                  <Text size="xs" tt="uppercase" fw={700} c="dimmed" style={{ fontSize: 10 }}>BTC</Text>
                </Table.Th>
                <Table.Th>
                  <Text size="xs" tt="uppercase" fw={700} c="dimmed" style={{ fontSize: 10 }}>Quote</Text>
                </Table.Th>
                <Table.Th>
                  <Text size="xs" tt="uppercase" fw={700} c="dimmed" style={{ fontSize: 10 }}>Equity simulada</Text>
                </Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map((r) => (
                <Table.Tr key={r.exchange}>
                  <Table.Td style={{ width: 140 }}>
                    <VenueTag name={r.exchange} />
                  </Table.Td>
                  <Table.Td>
                    <MetricBar
                      value={r.btc}
                      max={maxBtc}
                      format={(n) => `${n.toFixed(4)} BTC`}
                      label={`${r.exchange} BTC simulado`}
                    />
                  </Table.Td>
                  <Table.Td>
                    <MetricBar
                      value={r.quote}
                      max={maxQuote}
                      format={(n) => `${money(n)}${r.quoteCcy && r.quoteCcy !== 'USD' ? ` ${r.quoteCcy}` : ''}`}
                      label={`${r.exchange} quote simulado`}
                    />
                  </Table.Td>
                  <Table.Td>
                    <MetricBar
                      value={r.equity}
                      max={maxEquity}
                      format={money}
                      label={`${r.exchange} equity simulada`}
                    />
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}

        {/* Línea de skew: valor, límite y estado del backend (breached manda, no recálculo) */}
        {skew && (
          <Box>
            <Group justify="space-between" mb={5} wrap="nowrap">
              <Text size="xs" c="dimmed">
                Skew de inventario{' '}
                <Text span size="xs" ff="monospace" className="mono-nums" fw={600} c={skew.breached ? 'red.4' : undefined}>
                  {(skew.skew * 100).toFixed(1)}%
                </Text>
                {skew.limit > 0 && (
                  <Text span size="xs" c="dimmed">
                    {' '}· límite {(skew.limit * 100).toFixed(0)}%
                  </Text>
                )}
              </Text>
              <Badge size="sm" variant="light" color={skew.breached ? 'red' : 'brand'}>
                {skew.breached ? 'BREACH' : 'NORMAL'}
              </Badge>
            </Group>
            {skewPct == null ? (
              <Text size="xs" c="dimmed">límite no disponible</Text>
            ) : (
              <Box
                role="img"
                aria-label={`Skew de inventario ${(skew.skew * 100).toFixed(1)} por ciento sobre un límite de ${(skew.limit * 100).toFixed(0)} por ciento, estado ${skew.breached ? 'breach' : 'normal'}.`}
                style={{ height: 8, borderRadius: 999, background: 'rgba(255,255,255,0.06)' }}
              >
                <Box
                  style={{
                    width: `${skewPct * 100}%`,
                    height: '100%',
                    borderRadius: 999,
                    background: skew.breached ? NEG : POS,
                    opacity: 0.8,
                    transition: 'width 350ms ease',
                  }}
                />
              </Box>
            )}
          </Box>
        )}

        {/* Dos costes DISTINTOS, nunca sumados: decisión (amortizado) vs ledger (debitado) */}
        <SimpleGrid cols={{ base: 1, sm: equityUsd != null ? 3 : 2 }} spacing="sm">
          <StatCard
            label="Coste rebalanceo · decisión amortizada"
            value={decisionCost ? money(decisionCost.usd) : '—'}
            accent="neutral"
            sub={
              decisionCost
                ? `última oportunidad ${decisionCost.opportunityId} · estimación usada al decidir, no un cargo`
                : 'sin oportunidad explicada aún · estimación usada al decidir, no un cargo'
            }
          />
          <StatCard
            label="Coste rebalanceo · debitado al ledger"
            value={rebalance ? money(rebalance.cost_total_usd) : '—'}
            accent="neutral"
            sub="sesión completa · ya incluido en el P&L realizado (no sumar con la decisión)"
          />
          {equityUsd != null && (
            <StatCard
              label="Equity simulada total"
              value={money(equityUsd)}
              accent="neutral"
              sub="suma marcada a mercado de todos los venues · capital simulado"
            />
          )}
        </SimpleGrid>

        {/* Eventos reales de rebalanceo (fuente: /pnl.rebalance.recent). Sin origen/destino:
            el algoritmo reparte BTC libre hacia una cuota común, no una transferencia A→B. */}
        <Box>
          <Text size="xs" tt="uppercase" fw={700} c="dimmed" mb={6} style={{ fontSize: 10, letterSpacing: 0.3 }}>
            Rebalanceos de la sesión{rebalance ? ` · ${rebalance.count}` : ''}
          </Text>
          {!rebalance ? (
            <Text size="sm" c="dimmed">Historial de rebalanceos no disponible.</Text>
          ) : rebalance.count === 0 ? (
            <Text size="sm" c="dimmed">Sin rebalanceos en la sesión.</Text>
          ) : (
            <Table.ScrollContainer minWidth={700}>
              <Table verticalSpacing={4} horizontalSpacing="md" withRowBorders={false}>
              <Table.Thead>
                <Table.Tr>
                  {['Hora', 'Skew antes → después', 'Fee BTC', 'Coste USD', 'Mark ref.'].map((h) => (
                    <Table.Th key={h}>
                      <Text size="xs" tt="uppercase" fw={700} c="dimmed" style={{ fontSize: 10 }}>{h}</Text>
                    </Table.Th>
                  ))}
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {rebalance.recent.map((ev, i) => (
                  <Table.Tr key={`${ev.ts}-${i}`}>
                    <Table.Td>
                      <Text size="sm" ff="monospace" className="mono-nums">{tsLabel(ev.ts)}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm" ff="monospace" className="mono-nums">
                        {fin(ev.skew_before) ? `${(ev.skew_before * 100).toFixed(1)}%` : '—'}
                        {' → '}
                        {fin(ev.skew_after) ? `${(ev.skew_after * 100).toFixed(1)}%` : '—'}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm" ff="monospace" className="mono-nums">
                        {fin(ev.fee_btc) ? ev.fee_btc.toFixed(6) : '—'}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm" ff="monospace" className="mono-nums" style={{ color: NEG }}>
                        {fin(ev.cost_usd) ? `−${money(ev.cost_usd)}` : '—'}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm" ff="monospace" className="mono-nums">
                        {fin(ev.ref_mark) ? money(ev.ref_mark) : '—'}
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          )}
        </Box>

        {/* Nota de alcance siempre visible (decisión de diseño explícita, no un olvido) */}
        <Group
          gap={7}
          wrap="nowrap"
          style={{ borderTop: '1px solid var(--s-border)', paddingTop: 10 }}
        >
          <Box c="dimmed" style={{ display: 'flex', flex: '0 0 auto' }}>
            <IconInfoCircle size={14} />
          </Box>
          <Text size="xs" c="dimmed" lh={1.5}>
            Inventario pre-posicionado. Reposición fiat por wire off-line, fuera de alcance de
            esta simulación: el rebalanceo periódico solo redistribuye BTC libre entre venues.
          </Text>
        </Group>
      </Stack>
    </Card>
  );
}
