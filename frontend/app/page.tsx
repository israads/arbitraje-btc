'use client';

import { useState } from 'react';
import Image from 'next/image';
import { AppShell, Badge, Box, Button, Divider, Grid, Group, SimpleGrid, Stack, Tabs, Text } from '@mantine/core';
import {
  IconActivity,
  IconAdjustments,
  IconArrowDownRight,
  IconArrowUpRight,
  IconChartHistogram,
  IconHelp,
  IconLayoutDashboard,
  IconRosetteDiscountCheck,
  IconRoute,
  IconWallet,
} from '@tabler/icons-react';
import { DEFAULT_STRATEGY_PARAMS, useStream, type ConnStatus } from '../hooks/useStream';
import { PricesTable } from '../components/PricesTable';
import { OpportunitiesTable } from '../components/OpportunitiesTable';
import { FunnelPanel } from '../components/FunnelPanel';
import { LifetimeHistogram } from '../components/LifetimeHistogram';
import { ControlPanel } from '../components/ControlPanel';
import { LiveLineChart } from '../components/LiveLineChart';
import { EdgeWaterfall } from '../components/EdgeWaterfall';
import { BreakEvenFrontier } from '../components/BreakEvenFrontier';
import { CapacityCurve } from '../components/CapacityCurve';
import { ForwardFanChart } from '../components/ForwardFanChart';
import { SurvivalCalibrationPanel } from '../components/SurvivalCalibrationPanel';
import { OpportunityExplainDrawer } from '../components/OpportunityExplainDrawer';
import { StrategyLabPanel } from '../components/StrategyLabPanel';
import { NaiveVsEdgePanel } from '../components/NaiveVsEdgePanel';
import { StoragePanel } from '../components/StoragePanel';
import { WinsPanel } from '../components/WinsPanel';
import { ConfigPanel } from '../components/ConfigPanel';
import { ProbabilityLattice } from '../components/ProbabilityLattice';
import { RelationshipGraph } from '../components/RelationshipGraph';
import { GuidedTour, TOUR_STEPS } from '../components/GuidedTour';
import { GuideDrawer } from '../components/GuideDrawer';
import { StatCard, AQUA } from '../components/primitives';

function statusColor(s: ConnStatus): string {
  if (s === 'live') return 'brand';
  if (s === 'reconnecting' || s === 'connecting') return 'yellow';
  if (s === 'replay') return 'aqua';
  return 'red';
}

const STATUS_LABEL: Record<ConnStatus, string> = {
  live: 'EN VIVO',
  connecting: 'CONECTANDO',
  reconnecting: 'RECONECTANDO',
  stale: 'SIN DATOS',
  replay: 'REPLAY',
};

function crossVenueSpread(
  quotes: Record<string, { usd_bid: number | null; usd_ask: number | null }>,
): number | null {
  const fin = (x: number | null): x is number => x != null && Number.isFinite(x);
  const asks = Object.values(quotes).map((q) => q.usd_ask).filter(fin);
  const bids = Object.values(quotes).map((q) => q.usd_bid).filter(fin);
  if (!asks.length || !bids.length) return null;
  // Gap bruto: vender al mejor bid, comprar al mejor ask (normalizados a USD).
  return Math.max(...bids) - Math.min(...asks);
}

function usd(n: number | null | undefined): string {
  return n == null || !Number.isFinite(n)
    ? '—'
    : `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

type Q = { usd_bid: number | null; usd_ask: number | null };

/** Mid de referencia de BTC: media de los mids válidos por venue (USD normalizado). */
function btcReference(quotes: Record<string, Q>): number | null {
  const mids = Object.values(quotes)
    .map((q) => (q.usd_bid != null && q.usd_ask != null ? (q.usd_bid + q.usd_ask) / 2 : null))
    .filter((x): x is number => x != null && Number.isFinite(x));
  if (!mids.length) return null;
  return mids.reduce((a, b) => a + b, 0) / mids.length;
}

/** Venues que cotizan con ambos lados finitos ahora mismo. */
function venuesLive(quotes: Record<string, Q>): number {
  return Object.values(quotes).filter(
    (q) =>
      q.usd_bid != null && q.usd_ask != null &&
      Number.isFinite(q.usd_bid) && Number.isFinite(q.usd_ask),
  ).length;
}

/** Métrica compacta del header: etiqueta técnica diminuta + valor monospace tabular. */
function HeaderStat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <Box style={{ minWidth: 0 }}>
      <Text fz={9} tt="uppercase" c="dimmed" fw={700} lh={1} style={{ letterSpacing: 0 }}>
        {label}
      </Text>
      <Text ff="monospace" className="mono-nums" fz="sm" fw={600} lh={1.25} c={color}>
        {value}
      </Text>
    </Box>
  );
}

/** Franja de métricas en vivo del header (estilo terminal): ref BTC · venues · cruces. */
function HeaderStats({
  quotes,
  detected,
}: {
  quotes: Record<string, Q>;
  detected: number;
}) {
  const ref = btcReference(quotes);
  const live = venuesLive(quotes);
  return (
    <Group gap="md" wrap="nowrap" visibleFrom="md">
      <HeaderStat label="BTC ref" value={usd(ref)} color="aqua.4" />
      <Divider orientation="vertical" my={6} />
      <HeaderStat label="Venues" value={live ? `${live} live` : '—'} />
      <Divider orientation="vertical" my={6} />
      <HeaderStat label="Cruces" value={detected.toLocaleString('en-US')} color="brand.4" />
    </Group>
  );
}

/** Pill de conectividad con punto "live" latente. */
function ConnPill({ status }: { status: ConnStatus }) {
  const color = statusColor(status);
  const live = status === 'live';
  return (
    <Group
      gap={8}
      px="sm"
      py={6}
      wrap="nowrap"
      style={{
        borderRadius: 999,
        border: `1px solid var(--mantine-color-${color}-9)`,
        background: `var(--mantine-color-${color}-light)`,
      }}
    >
      <span
        className={live ? 'live-dot' : undefined}
        style={{
          width: 8,
          height: 8,
          borderRadius: 999,
          background: `var(--mantine-color-${color}-5)`,
        }}
      />
      <Text size="xs" fw={700} c={`${color}.4`} style={{ letterSpacing: 0 }}>
        {STATUS_LABEL[status]}
      </Text>
    </Group>
  );
}

/** Logotipo: marca geométrica con acento verde (identidad tipo exchange). */
function BrandMark() {
  return (
    <Group gap="sm" wrap="nowrap">
      <Image
        src="/logo.png"
        alt="arbitraje·btc"
        width={36}
        height={36}
        priority
        style={{
          borderRadius: 10,
          boxShadow: '0 6px 16px -8px rgba(22,214,127,0.55)',
        }}
      />
      <Box>
        <Text
          fw={700}
          fz="lg"
          lh={1}
          ff="var(--font-outfit), sans-serif"
          style={{ letterSpacing: 0 }}
        >
          arbitraje
          <Text span c="brand.4" inherit>
            ·btc
          </Text>
        </Text>
        <Text size="xs" c="dimmed" lh={1.2} visibleFrom="sm">
          motor de medición de edge ejecutable
        </Text>
      </Box>
    </Group>
  );
}

export default function DashboardPage() {
  const [strategyParams, setStrategyParams] = useState(DEFAULT_STRATEGY_PARAMS);
  const {
    status, quotes, routeStats, detectedCount, metrics, breakers, demo, pnl, validation,
    projection, capacity, forward, survival, naiveVsEdge, wins,
  } = useStream(strategyParams);
  const spread = crossVenueSpread(quotes);
  const total = pnl?.total_pnl ?? 0;
  const [selectedOpportunityId, setSelectedOpportunityId] = useState<string | null>(null);
  const [tourOpen, setTourOpen] = useState(false);
  const [guideOpen, setGuideOpen] = useState(false);
  const [tab, setTab] = useState<string>('resumen');

  return (
    <AppShell header={{ height: 64 }} padding={{ base: 'sm', sm: 'lg' }}>
      <AppShell.Header
        style={{
          background: 'rgba(11,15,26,0.72)',
          backdropFilter: 'blur(12px)',
          borderBottom: '1px solid rgba(255,255,255,0.06)',
        }}
      >
        <Group h="100%" px="lg" justify="space-between" wrap="nowrap" gap="md">
          <BrandMark />
          <HeaderStats quotes={quotes} detected={detectedCount} />
          <Group gap="xs" wrap="nowrap">
            <Button
              size="compact-sm"
              variant="subtle"
              color="gray"
              leftSection={<IconHelp size={15} />}
              onClick={() => setGuideOpen(true)}
            >
              Guía
            </Button>
            <Button
              size="compact-sm"
              variant="light"
              color="brand"
              leftSection={<IconRoute size={15} />}
              onClick={() => setTourOpen(true)}
              visibleFrom="sm"
            >
              Tour
            </Button>
            {demo.active && (
              <Badge color="orange" variant="light" visibleFrom="xs">
                DEMO DATA
              </Badge>
            )}
            {breakers.halted && (
              <Badge color="red" variant="filled">
                HALTED
              </Badge>
            )}
            <ConnPill status={status} />
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Main>
        <Stack gap="lg" maw={1400} mx="auto">
          <Text c="dimmed" size="sm" maw={820}>
            Medimos cada spread como si fuera una operación real. La mayoría muere por fees,
            slippage, peg o latencia: aquí está{' '}
            <Text span c="brand.4" fw={600}>
              exactamente dónde muere
            </Text>
            , cuánto falta para break-even y bajo qué condiciones sería capturable.
          </Text>

          {/* Fila de KPIs de P&L */}
          <SimpleGrid cols={{ base: 1, xs: 2, sm: 4 }} spacing="md">
            <StatCard
              label="P&L total"
              value={usd(pnl?.total_pnl)}
              accent={total < 0 ? 'neg' : total > 0 ? 'pos' : 'neutral'}
              emphasize
              icon={total < 0 ? <IconArrowDownRight size={18} /> : <IconArrowUpRight size={18} />}
              sub="realized + unrealized"
              hint="Ganancia o pérdida total de la sesión: lo ya cerrado (realized) más lo abierto valorado a mercado (unrealized). Verde = ganas, rojo = pierdes."
            />
            <StatCard
              label="Realized"
              value={usd(pnl?.realized_pnl)}
              accent={(pnl?.realized_pnl ?? 0) < 0 ? 'neg' : 'neutral'}
              icon={<IconActivity size={18} />}
              sub="capturado y cerrado"
              hint="P&L de operaciones ya completadas y cerradas. Es ganancia/pérdida realizada, no estimada."
            />
            <StatCard
              label="Unrealized"
              value={usd(pnl?.unrealized_pnl)}
              accent={(pnl?.unrealized_pnl ?? 0) < 0 ? 'neg' : 'neutral'}
              icon={<IconChartHistogram size={18} />}
              sub="mark-to-market abierto"
              hint="Ganancia/pérdida de posiciones aún abiertas, valoradas al precio actual de mercado. Cambia con el precio hasta que se cierran."
            />
            <StatCard
              label="Equity"
              value={usd(pnl?.equity_usd)}
              accent="brand"
              icon={<IconWallet size={18} />}
              sub="capital simulado total"
              hint="Capital total simulado: efectivo + valor de BTC en todos los venues. Es el tamaño de la cuenta del bot."
            />
          </SimpleGrid>

          {/* Dashboard agrupado en pestañas: menos scroll, narrativa clara */}
          <Tabs value={tab} onChange={(v) => setTab(v || 'resumen')} radius="md" keepMounted={false}>
            <Tabs.List mb="lg">
              <Tabs.Tab value="resumen" leftSection={<IconLayoutDashboard size={15} />}>
                Resumen
              </Tabs.Tab>
              <Tabs.Tab value="correctitud" leftSection={<IconRosetteDiscountCheck size={15} />}>
                Correctitud
              </Tabs.Tab>
              <Tabs.Tab value="proyeccion" leftSection={<IconChartHistogram size={15} />}>
                Proyección
              </Tabs.Tab>
              <Tabs.Tab value="operacion" leftSection={<IconAdjustments size={15} />}>
                Operación
              </Tabs.Tab>
            </Tabs.List>

            {/* RESUMEN: la tesis de un vistazo */}
            <Tabs.Panel value="resumen">
              <Stack gap="lg">
                <Grid gutter="lg" align="stretch">
                  <Grid.Col span={{ base: 12, md: 4 }} id="tour-naive-edge">
                    <NaiveVsEdgePanel report={naiveVsEdge} />
                  </Grid.Col>
                  <Grid.Col span={{ base: 12, md: 4 }}>
                    <LiveLineChart
                      title="Spread bruto cross-venue"
                      value={spread}
                      color={AQUA}
                      suffix=" $"
                      zeroLine
                      hint="best bid − best ask normalizados; >0 = cruce aparente (antes de fees)"
                    />
                  </Grid.Col>
                  <Grid.Col span={{ base: 12, md: 4 }}>
                    <LiveLineChart
                      title="P&L total"
                      value={pnl?.total_pnl ?? null}
                      baseline
                      suffix=" $"
                      zeroLine
                      hint="verde sobre 0 / rojo bajo 0 · plano-negativo tras costes ES el punto"
                    />
                  </Grid.Col>
                </Grid>
                <WinsPanel report={wins} />
              </Stack>
            </Tabs.Panel>

            {/* CORRECTITUD: la prueba de que la aritmética es real */}
            <Tabs.Panel value="correctitud">
              <Stack gap="lg">
                <Box id="tour-edge-waterfall">
                  <EdgeWaterfall report={validation} />
                </Box>
                <PricesTable quotes={quotes} />
                <FunnelPanel metrics={metrics} />
              </Stack>
            </Tabs.Panel>

            {/* PROYECCIÓN: las 3 capas + el tablero */}
            <Tabs.Panel value="proyeccion">
              <Stack gap="lg">
                <Grid gutter="lg" align="stretch">
                  <Grid.Col span={{ base: 12, md: 7 }} id="tour-frontier">
                    <BreakEvenFrontier frontier={projection} />
                  </Grid.Col>
                  <Grid.Col span={{ base: 12, md: 5 }}>
                    <LifetimeHistogram metrics={metrics} />
                  </Grid.Col>
                </Grid>
                <Grid gutter="lg" align="stretch">
                  <Grid.Col span={{ base: 12, md: 5 }}>
                    <CapacityCurve capacity={capacity} />
                  </Grid.Col>
                  <Grid.Col span={{ base: 12, md: 7 }} id="tour-forward">
                    <ForwardFanChart forward={forward} />
                  </Grid.Col>
                </Grid>
                <Box id="tour-lattice">
                  <ProbabilityLattice forward={forward} />
                </Box>
                <SurvivalCalibrationPanel report={survival} />
              </Stack>
            </Tabs.Panel>

            {/* OPERACIÓN: control, configuración y rutas */}
            <Tabs.Panel value="operacion">
              <Stack gap="lg">
                <ControlPanel breakers={breakers} demo={demo} />
                <Box id="tour-config">
                  <ConfigPanel />
                </Box>
                <Grid gutter="lg" align="stretch">
                  <Grid.Col span={{ base: 12, md: 7 }}>
                    <StoragePanel />
                  </Grid.Col>
                  <Grid.Col span={{ base: 12, md: 5 }}>
                    <StrategyLabPanel params={strategyParams} onApply={setStrategyParams} />
                  </Grid.Col>
                </Grid>
                <RelationshipGraph routeStats={routeStats} />
                <OpportunitiesTable
                  routeStats={routeStats}
                  detectedCount={detectedCount}
                  onExplain={setSelectedOpportunityId}
                />
              </Stack>
            </Tabs.Panel>
          </Tabs>
        </Stack>
      </AppShell.Main>
      <OpportunityExplainDrawer
        opportunityId={selectedOpportunityId}
        strategyParams={strategyParams}
        opened={selectedOpportunityId != null}
        onClose={() => setSelectedOpportunityId(null)}
      />
      {tourOpen && (
        <GuidedTour steps={TOUR_STEPS} onClose={() => setTourOpen(false)} onNavigate={setTab} />
      )}
      <GuideDrawer opened={guideOpen} onClose={() => setGuideOpen(false)} />
    </AppShell>
  );
}
