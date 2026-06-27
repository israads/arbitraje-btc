'use client';

import { Accordion, Badge, Box, Drawer, Group, List, Stack, Text, ThemeIcon, Title } from '@mantine/core';
import {
  IconBook2,
  IconTargetArrow,
  IconCalculator,
  IconChartHistogram,
  IconShieldCheck,
  IconVocabulary,
  IconRocket,
} from '@tabler/icons-react';
import type { ReactNode } from 'react';
import { BRAND } from './primitives';

/**
 * Guía explicativa completa y navegable: pensada para que alguien sin contexto entienda QUÉ hace
 * el sistema, POR QUÉ funciona, QUÉ calcula y CÓMO lo calcula. Lenguaje llano + el ejemplo
 * canónico del reto. Contenido estructurado (secciones) → fácil de mantener/ampliar.
 */

interface Section {
  value: string;
  icon: ReactNode;
  title: string;
  body: ReactNode;
}

const C = ({ children }: { children: ReactNode }) => (
  <Text span fw={700} c="brand.4">
    {children}
  </Text>
);

const P = ({ children }: { children: ReactNode }) => (
  <Text size="sm" c="dimmed" lh={1.6} mb="sm">
    {children}
  </Text>
);

const SECTIONS: Section[] = [
  {
    value: 'que-es',
    icon: <IconTargetArrow size={18} />,
    title: '¿Qué es esto y por qué importa?',
    body: (
      <>
        <P>
          Es un motor de <C>arbitraje de Bitcoin</C>: busca comprar BTC barato en un exchange y
          venderlo más caro en otro. Suena fácil, pero la mayoría de esas “oportunidades” son una
          trampa.
        </P>
        <P>
          La idea central: <C>no basta con que el precio se vea más barato</C>. Cuando ejecutas de
          verdad pagas comisiones, mueves el precio al comprar/vender en cantidad, y el dólar
          digital (USDT) no vale exactamente 1 USD. Este sistema <C>mide cuánto queda realmente</C>{' '}
          después de todos esos costes — y casi siempre, no queda nada.
        </P>
        <P>
          Por eso el dashboard no te promete ganancias: te muestra <C>dónde muere el spread</C> y
          bajo qué condiciones sí sería rentable (por ejemplo, con comisiones de nivel
          institucional).
        </P>
      </>
    ),
  },
  {
    value: 'como-decide',
    icon: <IconRocket size={18} />,
    title: '¿Cómo decide el motor? (el embudo)',
    body: (
      <>
        <P>Cada oportunidad pasa por un embudo. En cada paso muere o avanza:</P>
        <List size="sm" spacing="xs" c="dimmed">
          <List.Item><C>Detectada:</C> hay un cruce aparente de precios entre dos venues.</List.Item>
          <List.Item><C>Viable:</C> tras fees y profundidad, el neto sigue siendo positivo.</List.Item>
          <List.Item><C>Ejecutable:</C> sobrevive a la latencia y a la liquidez disponible.</List.Item>
          <List.Item><C>Capturada:</C> se simula la ejecución y se contabiliza el P&L.</List.Item>
          <List.Item><C>Descartada:</C> murió por fees, slippage, peg, libro fino o latencia.</List.Item>
        </List>
        <P>
          El panel <C>Naive vs Edge</C> resume esto: cuánto contaría un detector ingenuo vs cuánto
          captura de verdad el motor, y por qué se descartó el resto.
        </P>
      </>
    ),
  },
  {
    value: 'que-calcula',
    icon: <IconCalculator size={18} />,
    title: '¿Qué calcula? (las métricas clave)',
    body: (
      <>
        <List size="sm" spacing="xs" c="dimmed">
          <List.Item><C>Spread bruto:</C> diferencia aparente de precio entre venues, antes de costes.</List.Item>
          <List.Item><C>Edge neto:</C> lo que queda por BTC tras fees, slippage, rebalanceo y peg. Es la métrica honesta.</List.Item>
          <List.Item><C>P&L:</C> ganancia/pérdida. <C>Realized</C> = ya cerrada; <C>Unrealized</C> = posición abierta valorada a mercado; <C>Equity</C> = capital total.</List.Item>
          <List.Item><C>Capture ratio / supervivencia:</C> de lo que un ingenuo tradearía, qué fracción sobrevive a los costes.</List.Item>
        </List>
        <P>
          Ejemplo canónico del reto: bruto <C>$109.75/BTC</C> → tras fees y rebalanceo, ese es el
          neto reconciliado que ves en el <C>Edge Waterfall</C> (la “prueba de correctitud”).
        </P>
      </>
    ),
  },
  {
    value: 'proyecciones',
    icon: <IconChartHistogram size={18} />,
    title: 'Las proyecciones (3 capas)',
    body: (
      <>
        <List size="sm" spacing="xs" c="dimmed">
          <List.Item>
            <C>Break-even Frontier:</C> un mapa tamaño × comisión que muestra dónde el edge cruza
            cero. A comisión retail casi todo es rojo; a comisión institucional aparece el “sweet spot”.
          </List.Item>
          <List.Item>
            <C>Capacity Curve:</C> cuánto capital absorbe la oportunidad antes de que el propio
            volumen mate el edge (mover el precio cuesta).
          </List.Item>
          <List.Item>
            <C>Forward (Monte Carlo) + Probability Lattice:</C> simula miles de futuros posibles
            con la estadística real de la sesión. El tablero de Galton hace visible esa distribución:
            si hay ventaja, las bolas caen al verde.
          </List.Item>
        </List>
      </>
    ),
  },
  {
    value: 'como-calcula',
    icon: <IconBook2 size={18} />,
    title: '¿Cómo lo calcula? (el motor por dentro)',
    body: (
      <>
        <List size="sm" spacing="xs" c="dimmed">
          <List.Item><C>VWAP por profundidad:</C> no usa el mejor precio, sino el precio promedio real de ejecutar tu tamaño caminando el libro de órdenes.</List.Item>
          <List.Item><C>Costes:</C> fees taker por venue + rebalanceo (mover BTC entre exchanges) restados al bruto. La fórmula es única (mismo cálculo en motor y proyecciones).</List.Item>
          <List.Item><C>Peg USDT:</C> ajusta que USDT ≠ 1 USD; penaliza cruces que dependen de un peg desviado.</List.Item>
          <List.Item><C>z-score:</C> mide cuán anómalo es el spread frente a su historia reciente (arbitraje estadístico).</List.Item>
          <List.Item><C>Monte Carlo (bootstrap estacionario):</C> remuestrea la serie real de P&L respetando que las oportunidades llegan en ráfagas, y reporta honestidad estadística (PSR, Deflated Sharpe).</List.Item>
        </List>
      </>
    ),
  },
  {
    value: 'controles',
    icon: <IconShieldCheck size={18} />,
    title: 'Controles y seguridad',
    body: (
      <>
        <List size="sm" spacing="xs" c="dimmed">
          <List.Item><C>Kill switch:</C> freno de emergencia. Detiene al instante toda captura/ejecución.</List.Item>
          <List.Item><C>Resume:</C> reanuda tras un kill switch o tras un circuit breaker.</List.Item>
          <List.Item><C>Circuit breakers:</C> pausas automáticas por datos viejos (stale), volatilidad, desbalance de inventario o drawdown.</List.Item>
          <List.Item><C>Fallback de demo:</C> <C>Auto</C> (cae a demo si no hay feeds), <C>Replay</C> (reproduce grabado), <C>Jury</C> (secuencia guiada de 7 escenarios que <b>avanza sola</b> — por eso “cambia constantemente”), <C>Off</C>.</List.Item>
        </List>
        <P>Todo es simulación: el sistema no opera con dinero real.</P>
      </>
    ),
  },
  {
    value: 'glosario',
    icon: <IconVocabulary size={18} />,
    title: 'Glosario rápido',
    body: (
      <List size="sm" spacing="xs" c="dimmed">
        <List.Item><C>Spread:</C> diferencia de precio entre dos mercados.</List.Item>
        <List.Item><C>Slippage:</C> empeoramiento del precio al ejecutar cantidad.</List.Item>
        <List.Item><C>Fee taker:</C> comisión por ejecutar contra el libro.</List.Item>
        <List.Item><C>Rebalanceo:</C> mover BTC entre exchanges para reponer inventario.</List.Item>
        <List.Item><C>Peg:</C> qué tan cerca está USDT de valer 1 USD.</List.Item>
        <List.Item><C>Drawdown:</C> caída desde el pico de capital.</List.Item>
        <List.Item><C>Sharpe / PSR / Deflated Sharpe:</C> medidas de si el rendimiento es real o suerte.</List.Item>
      </List>
    ),
  },
];

export function GuideDrawer({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      position="right"
      size="lg"
      title={
        <Group gap="sm">
          <ThemeIcon variant="light" color="brand" size={34} radius="md">
            <IconBook2 size={18} />
          </ThemeIcon>
          <Box>
            <Title order={4} fz="md">
              Guía del sistema
            </Title>
            <Text size="xs" c="dimmed">
              qué hace · por qué · qué calcula · cómo
            </Text>
          </Box>
        </Group>
      }
      overlayProps={{ backgroundOpacity: 0.55, blur: 2 }}
    >
      <Badge variant="light" color="brand" mb="md">
        Para entenderlo sin saber de trading
      </Badge>
      <Accordion variant="separated" defaultValue="que-es" radius="md">
        {SECTIONS.map((s) => (
          <Accordion.Item key={s.value} value={s.value} style={{ borderColor: 'var(--s-border)' }}>
            <Accordion.Control
              icon={
                <ThemeIcon variant="light" color="brand" size={28} radius="md">
                  {s.icon}
                </ThemeIcon>
              }
            >
              <Text fw={600} fz="sm">
                {s.title}
              </Text>
            </Accordion.Control>
            <Accordion.Panel>
              <Stack gap={0} style={{ borderLeft: `2px solid ${BRAND}33`, paddingLeft: 12 }}>
                {s.body}
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>
        ))}
      </Accordion>
    </Drawer>
  );
}
