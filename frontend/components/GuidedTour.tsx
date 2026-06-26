'use client';

import { useEffect, useState, useCallback } from 'react';
import { Box, Button, Group, Paper, Text } from '@mantine/core';
import { IconArrowLeft, IconArrowRight, IconX } from '@tabler/icons-react';
import { BRAND } from './primitives';

/**
 * Tour guiado para la defensa ante el jurado: recorre la tesis del proyecto resaltando cada
 * sección del dashboard con un spotlight (box-shadow que oscurece el resto) y un popover con la
 * idea clave. Sin dependencias: usa getBoundingClientRect + scrollIntoView. Respeta el teclado
 * (Esc cierra, ←/→ navegan) y prefers-reduced-motion (scroll instantáneo).
 */

export interface TourStep {
  id: string;
  title: string;
  body: string;
}

export const TOUR_STEPS: TourStep[] = [
  {
    id: 'tour-edge-waterfall',
    title: '1 · Prueba de correctitud',
    body: 'Reconciliamos el ejemplo del reto ($109.75/BTC) e invariantes económicas. La aritmética no está maquillada.',
  },
  {
    id: 'tour-naive-edge',
    title: '2 · Ingenuo vs motor',
    body: 'Un detector de spreads contaría ganancias brutas; el motor descuenta fees, latencia y peg. La mayoría no sobrevive — y mostramos por qué.',
  },
  {
    id: 'tour-frontier',
    title: '3 · Dónde sobrevive el edge',
    body: 'Break-even frontier por tamaño y fee tier: a fee retail casi todo es rojo; a fee institucional aparece el sweet spot.',
  },
  {
    id: 'tour-lattice',
    title: '4 · El edge inclina el tablero',
    body: 'Cada trade es una bola del Monte Carlo forward; la masa cae al verde solo si hay ventaja real tras costes.',
  },
  {
    id: 'tour-forward',
    title: '5 · Honestidad estadística',
    body: 'Forward Monte Carlo (bootstrap estacionario) con P5–P95, prob. de ruina y Deflated Sharpe. No es un pronóstico: es la dispersión consistente con la muestra.',
  },
  {
    id: 'tour-config',
    title: '6 · Operación auditable',
    body: 'Retención de la base de datos con estimación de almacenamiento y parámetros what-if que no mutan el motor vivo.',
  },
];

interface Rect {
  top: number;
  left: number;
  width: number;
  height: number;
}

export function GuidedTour({ steps, onClose }: { steps: TourStep[]; onClose: () => void }) {
  const [i, setI] = useState(0);
  const [rect, setRect] = useState<Rect | null>(null);

  const step = steps[i];

  const locate = useCallback(() => {
    const el = document.getElementById(step.id);
    if (!el) {
      setRect(null);
      return;
    }
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    el.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'center' });
    // Tras el scroll, mide la posición.
    window.setTimeout(
      () => {
        const r = el.getBoundingClientRect();
        setRect({ top: r.top, left: r.left, width: r.width, height: r.height });
      },
      reduce ? 0 : 320,
    );
  }, [step.id]);

  useEffect(() => {
    locate();
  }, [locate]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
      else if (e.key === 'ArrowRight') setI((v) => Math.min(v + 1, steps.length - 1));
      else if (e.key === 'ArrowLeft') setI((v) => Math.max(v - 1, 0));
    };
    const onResize = () => locate();
    window.addEventListener('keydown', onKey);
    window.addEventListener('resize', onResize);
    window.addEventListener('scroll', onResize, true);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('resize', onResize);
      window.removeEventListener('scroll', onResize, true);
    };
  }, [locate, onClose, steps.length]);

  const pad = 8;
  const last = i === steps.length - 1;
  // Popover bajo el elemento, o encima si no cabe.
  const popTop = rect ? (rect.top + rect.height + 180 > window.innerHeight ? Math.max(12, rect.top - 168) : rect.top + rect.height + pad + 6) : 80;

  return (
    <Box style={{ position: 'fixed', inset: 0, zIndex: 1000, pointerEvents: 'none' }}>
      {/* Spotlight: hueco con box-shadow gigante que oscurece el resto */}
      {rect ? (
        <Box
          style={{
            position: 'fixed',
            top: rect.top - pad,
            left: rect.left - pad,
            width: rect.width + pad * 2,
            height: rect.height + pad * 2,
            borderRadius: 16,
            boxShadow: `0 0 0 9999px rgba(5,8,15,0.74), 0 0 0 2px ${BRAND}`,
            transition: 'all 240ms ease',
            pointerEvents: 'none',
          }}
        />
      ) : (
        <Box style={{ position: 'fixed', inset: 0, background: 'rgba(5,8,15,0.74)' }} />
      )}

      <Paper
        shadow="xl"
        radius="md"
        p="md"
        style={{
          position: 'fixed',
          top: popTop,
          left: '50%',
          transform: 'translateX(-50%)',
          width: 'min(440px, 92vw)',
          pointerEvents: 'auto',
          border: `1px solid ${BRAND}`,
          background: 'var(--s-panel, #11161f)',
        }}
      >
        <Group justify="space-between" mb={6} wrap="nowrap">
          <Text fw={700} c="brand.4" fz="sm">
            {step.title}
          </Text>
          <Button
            size="compact-xs"
            variant="subtle"
            color="gray"
            onClick={onClose}
            leftSection={<IconX size={13} />}
          >
            Salir
          </Button>
        </Group>
        <Text size="sm" c="dimmed" lh={1.5}>
          {step.body}
        </Text>
        <Group justify="space-between" mt="md">
          <Text fz="xs" c="dimmed" ff="monospace">
            {i + 1} / {steps.length}
          </Text>
          <Group gap="xs">
            <Button
              size="xs"
              variant="default"
              disabled={i === 0}
              onClick={() => setI((v) => Math.max(v - 1, 0))}
              leftSection={<IconArrowLeft size={14} />}
            >
              Anterior
            </Button>
            <Button
              size="xs"
              color="brand"
              onClick={() => (last ? onClose() : setI((v) => Math.min(v + 1, steps.length - 1)))}
              rightSection={last ? undefined : <IconArrowRight size={14} />}
            >
              {last ? 'Terminar' : 'Siguiente'}
            </Button>
          </Group>
        </Group>
      </Paper>
    </Box>
  );
}
