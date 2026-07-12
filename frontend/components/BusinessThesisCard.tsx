'use client';

import { Box, Button, Card, SimpleGrid, Text } from '@mantine/core';
import { IconArrowRight, IconBulb } from '@tabler/icons-react';
import type { EdgeFrontier, ForwardProjection } from '../hooks/useStream';
import { FetchFallback, NEG, POS, SectionHeader } from './primitives';

/**
 * Tesis de negocio (BN-1/BN-2): responde "¿dónde SÍ hay negocio?" en <90s con números VIVOS
 * que ya calcula el dashboard — nada hardcodeado:
 *  · Retail: mejor neto $/BTC alcanzable en el fee tier más caro del Break-even Frontier
 *    (típicamente negativo: el spread bruto muere en fees+peg).
 *  · Institucional: la mejor celda del frontier (best.by_unit_edge) — el mismo trade con
 *    comisiones negociadas queda positivo.
 *  · P(P&L>0): probabilidad de terminar en positivo según el Forward fan (Monte Carlo).
 * Cada bloque enlaza al panel que lo demuestra (pestaña Proyección).
 */

const money = (n: number) =>
  `${n < 0 ? '−' : '+'}$${Math.abs(n).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

/** Índice del fee tier más caro (retail) del frontier. */
function retailTierIndex(frontier: EdgeFrontier): number {
  let idx = -1;
  frontier.fee_tiers.forEach((t, i) => {
    if (idx < 0 || t.bps > frontier.fee_tiers[idx].bps) idx = i;
  });
  return idx;
}

/** Mejor neto $/BTC alcanzable dentro de una fila (tier) de la matriz; null si no hay celdas. */
function bestOfRow(row: (number | null)[] | undefined): number | null {
  const vals = (row ?? []).filter((v): v is number => v != null && Number.isFinite(v));
  return vals.length ? Math.max(...vals) : null;
}

function ThesisBlock({
  label,
  value,
  valueColor,
  sub,
  cta,
  onClick,
}: {
  label: string;
  value: string;
  valueColor: string;
  sub: string;
  cta: string;
  onClick: () => void;
}) {
  return (
    <Box
      style={{
        padding: '12px 14px',
        borderRadius: 12,
        border: '1px solid var(--s-border)',
        background: 'rgba(255,255,255,0.015)',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <Text size="xs" tt="uppercase" fw={700} c="dimmed" style={{ fontSize: 10, letterSpacing: 0.3 }}>
        {label}
      </Text>
      <Text ff="monospace" className="mono-nums" fw={700} fz={24} lh={1.15} mt={4} style={{ color: valueColor }}>
        {value}
      </Text>
      <Text size="xs" c="dimmed" mt={6} lh={1.4} style={{ flex: 1 }}>
        {sub}
      </Text>
      <Button
        size="compact-xs"
        variant="subtle"
        color="gray"
        mt={8}
        rightSection={<IconArrowRight size={13} />}
        onClick={onClick}
        style={{ alignSelf: 'flex-start' }}
      >
        {cta}
      </Button>
    </Box>
  );
}

export function BusinessThesisCard({
  frontier,
  forward,
  projectionError = false,
  forwardError = false,
  onRetry,
  onNavigate,
}: {
  frontier: EdgeFrontier | null;
  forward: ForwardProjection | null;
  projectionError?: boolean;
  forwardError?: boolean;
  onRetry?: () => void;
  onNavigate: (tab: string, anchorId?: string) => void;
}) {
  const header = (
    <SectionHeader
      title="Tesis de negocio"
      subtitle="dónde sí hay negocio — y dónde no"
      icon={<IconBulb size={18} />}
      help="Entre exchanges grandes BTC es demasiado eficiente: un spread bruto positivo se vuelve negativo tras peg y fees a comisión retail. El negocio aparece con fees institucionales (mismo trade, comisiones negociadas) y en corredores regionales como MXN. Y la honestidad: medimos capturabilidad con datos vivos, no prometemos retorno. Cada número de esta tarjeta sale de los paneles de Proyección."
    />
  );

  // Retail: mejor neto alcanzable en el tier MÁS CARO del frontier (aún así suele ser negativo).
  const iRetail = frontier ? retailTierIndex(frontier) : -1;
  const retailTier = frontier && iRetail >= 0 ? frontier.fee_tiers[iRetail] : null;
  const retailNet = frontier && iRetail >= 0 ? bestOfRow(frontier.matrix[iRetail]) : null;
  // Institucional: la mejor celda del frontier (tamaño × fee tier) por edge unitario.
  const bestCell = frontier?.best.by_unit_edge ?? null;
  const probProfit = forward?.available ? forward.prob_profit : null;

  const goFrontier = () => onNavigate('proyeccion', 'tour-frontier');
  const goForward = () => onNavigate('proyeccion', 'tour-forward');

  return (
    <Card>
      {header}
      <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm">
        {retailTier && retailNet != null ? (
          <ThesisBlock
            label={`Retail · ${retailTier.bps.toFixed(1)} bps`}
            value={`${money(retailNet)}/BTC`}
            valueColor={retailNet >= 0 ? POS : NEG}
            sub={
              retailNet < 0
                ? `Incluso en su mejor tamaño, el spread queda negativo a fee retail: el bruto${
                    frontier ? ` (top ${frontier.gross_top_per_btc.toFixed(0)} $/BTC)` : ''
                  } muere en fees + peg. Aquí NO hay negocio.`
                : 'Ahora mismo el mejor tamaño sobrevive incluso a fee retail — condición poco común, verifícala en el frontier.'
            }
            cta="Verlo en el frontier"
            onClick={goFrontier}
          />
        ) : (
          <Box p="sm">
            <FetchFallback
              error={projectionError}
              onRetry={onRetry}
              loading="Proyectando tier retail…"
            />
          </Box>
        )}

        {bestCell ? (
          <ThesisBlock
            label={`Institucional · ${bestCell.fee_bps.toFixed(1)} bps`}
            value={`${money(bestCell.net_per_btc)}/BTC`}
            valueColor={bestCell.net_per_btc >= 0 ? POS : NEG}
            sub={`El mismo trade con comisiones negociadas (${bestCell.size_btc} BTC @ ${bestCell.fee_bps.toFixed(1)} bps) ${
              bestCell.net_per_btc >= 0 ? 'queda positivo: aquí SÍ hay negocio' : 'sigue negativo en esta ventana'
            }. El fee tier decide el negocio, no la velocidad.`}
            cta="Verlo en el frontier"
            onClick={goFrontier}
          />
        ) : (
          <Box p="sm">
            <FetchFallback
              error={projectionError}
              onRetry={onRetry}
              loading="Buscando el mejor fee tier…"
            />
          </Box>
        )}

        {forward && !forward.available ? (
          <ThesisBlock
            label="P(P&L>0) · forward"
            value="—"
            valueColor="var(--mantine-color-dimmed)"
            sub="Muestra insuficiente para proyectar: honestidad ante todo — sin trades suficientes no afirmamos retorno."
            cta="Ver forward de P&L"
            onClick={goForward}
          />
        ) : probProfit != null ? (
          <ThesisBlock
            label="P(P&L>0) · forward"
            value={`${(probProfit * 100).toFixed(0)}%`}
            valueColor={probProfit >= 0.5 ? POS : NEG}
            sub={`${(probProfit * 100).toFixed(0)}% de las trayectorias simuladas terminan en positivo (mediana ${
              forward?.terminal_p50 != null ? money(forward.terminal_p50) : '—'
            }). Medimos capturabilidad; no prometemos retorno.`}
            cta="Ver forward de P&L"
            onClick={goForward}
          />
        ) : (
          <Box p="sm">
            <FetchFallback
              error={forwardError}
              onRetry={onRetry}
              loading="Simulando trayectorias…"
            />
          </Box>
        )}
      </SimpleGrid>
      <Text size="xs" c="dimmed" mt="sm" lh={1.4}>
        Tercera pata de la tesis: el corredor MXN (prima regional sobre el peg USD/MXN),
        identificado como expansión — aún sin medición en vivo en este dashboard, por eso no
        mostramos una cifra.
      </Text>
    </Card>
  );
}
