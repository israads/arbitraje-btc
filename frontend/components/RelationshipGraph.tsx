'use client';

import { useEffect, useMemo, useRef } from 'react';
import { Badge, Box, Card, Group, Text } from '@mantine/core';
import { IconShare3 } from '@tabler/icons-react';
import type { RouteStat } from '../hooks/useStream';
import { POS, NEG, SectionHeader } from './primitives';

/**
 * Relationship Graph — el grafo de rutas de arbitraje de la sesión. Cada nodo es un venue; cada
 * arista una ruta compra→venta observada, coloreada por su edge neto (verde si sobrevive a los
 * costes, roja si no, gris si aún sin neto) y con grosor por detecciones. Un pulso recorre la
 * mejor ruta. Layout force-directed que CONVERGE y se detiene.
 *
 * Las posiciones persisten en un ref entre updates: routeStats cambia de referencia en cada tick,
 * pero la simulación sólo se reinicia cuando aparece/desaparece un venue (firma topológica). Color
 * y grosor de aristas se leen frescos por ref sin reiniciar la física. Respeta reduced-motion.
 */

const HEIGHT = 300;

interface Pos {
  x: number;
  y: number;
  vx: number;
  vy: number;
}
interface Edge {
  a: string;
  b: string;
  net: number | null;
  detected: number;
}

export function RelationshipGraph({ routeStats }: { routeStats: RouteStat[] }) {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const rafRef = useRef<number>(0);
  const posRef = useRef<Map<string, Pos>>(new Map());

  const { venueIds, edges, best, sig } = useMemo(() => {
    const ids = new Set<string>();
    const es: Edge[] = [];
    for (const r of routeStats) {
      ids.add(r.buy_venue);
      ids.add(r.sell_venue);
      es.push({ a: r.buy_venue, b: r.sell_venue, net: r.lastNetPerBtc, detected: r.detected });
    }
    const list = Array.from(ids);
    let bestEdge: Edge | null = null;
    for (const e of es) {
      if (e.net != null && (bestEdge == null || e.net > (bestEdge.net ?? -Infinity))) bestEdge = e;
    }
    return { venueIds: list, edges: es, best: bestEdge, sig: [...list].sort().join('|') };
  }, [routeStats]);

  // Refs con datos vigentes: el loop los lee sin reiniciar la simulación.
  const edgesRef = useRef(edges);
  const bestRef = useRef<Edge | null>(best);
  const venuesRef = useRef(venueIds);
  edgesRef.current = edges;
  bestRef.current = best;
  venuesRef.current = venueIds;

  const empty = venueIds.length === 0;

  useEffect(() => {
    if (empty) return;
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;

    const setup = () => {
      const dpr = window.devicePixelRatio || 1;
      const w = wrap.clientWidth || 600;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(HEIGHT * dpr);
      canvas.style.width = `${w}px`;
      canvas.style.height = `${HEIGHT}px`;
      const ctx = canvas.getContext('2d');
      if (ctx) ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    setup();
    const ro = new ResizeObserver(setup);
    ro.observe(wrap);

    // Reusa posiciones existentes; los venues nuevos entran en círculo. Poda los que ya no están.
    const ids = venuesRef.current;
    const pos = posRef.current;
    ids.forEach((id, k) => {
      if (!pos.has(id)) {
        const ang = (k / Math.max(1, ids.length)) * Math.PI * 2;
        pos.set(id, { x: Math.cos(ang) * 80, y: Math.sin(ang) * 80, vx: 0, vy: 0 });
      }
    });
    for (const id of Array.from(pos.keys())) if (!ids.includes(id)) pos.delete(id);

    const stepPhysics = () => {
      const ns = ids.map((id) => pos.get(id)!).filter(Boolean);
      for (let i = 0; i < ns.length; i++) {
        for (let j = i + 1; j < ns.length; j++) {
          const a = ns[i];
          const b = ns[j];
          let dx = a.x - b.x;
          let dy = a.y - b.y;
          let d2 = dx * dx + dy * dy;
          if (d2 < 1) d2 = 1;
          const f = 1400 / d2;
          const d = Math.sqrt(d2);
          dx /= d;
          dy /= d;
          a.vx += dx * f;
          a.vy += dy * f;
          b.vx -= dx * f;
          b.vy -= dy * f;
        }
      }
      for (const e of edgesRef.current) {
        const a = pos.get(e.a);
        const b = pos.get(e.b);
        if (!a || !b) continue;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const d = Math.sqrt(dx * dx + dy * dy) || 1;
        const f = (d - 70) * 0.02;
        a.vx += (dx / d) * f;
        a.vy += (dy / d) * f;
        b.vx -= (dx / d) * f;
        b.vy -= (dy / d) * f;
      }
      let energy = 0;
      for (const n of ns) {
        n.vx += -n.x * 0.01;
        n.vy += -n.y * 0.01;
        n.vx *= 0.82;
        n.vy *= 0.82;
        n.x += n.vx;
        n.y += n.vy;
        energy += n.vx * n.vx + n.vy * n.vy;
      }
      return energy;
    };

    let pulse = 0;
    const draw = () => {
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.width / dpr;
      const h = canvas.height / dpr;
      ctx.clearRect(0, 0, w, h);
      const cx = w / 2;
      const cy = h / 2;
      const es = edgesRef.current;
      const maxDet = Math.max(1, ...es.map((e) => e.detected));

      for (const e of es) {
        const a = pos.get(e.a);
        const b = pos.get(e.b);
        if (!a || !b) continue;
        ctx.strokeStyle =
          e.net == null
            ? 'rgba(140,150,170,0.30)'
            : e.net >= 0
              ? 'rgba(47,217,140,0.45)'
              : 'rgba(246,103,138,0.35)';
        ctx.lineWidth = 0.6 + Math.min(3, e.detected / 40);
        ctx.beginPath();
        ctx.moveTo(cx + a.x, cy + a.y);
        ctx.lineTo(cx + b.x, cy + b.y);
        ctx.stroke();
      }

      const bestE = bestRef.current;
      if (bestE && !reduce) {
        const a = pos.get(bestE.a);
        const b = pos.get(bestE.b);
        if (a && b) {
          const t = (Math.sin(pulse) + 1) / 2;
          ctx.fillStyle = POS;
          ctx.shadowColor = POS;
          ctx.shadowBlur = 10;
          ctx.beginPath();
          ctx.arc(cx + a.x + (b.x - a.x) * t, cy + a.y + (b.y - a.y) * t, 3.5, 0, Math.PI * 2);
          ctx.fill();
          ctx.shadowBlur = 0;
        }
      }

      const deg: Record<string, number> = {};
      for (const e of es) {
        deg[e.a] = (deg[e.a] ?? 0) + e.detected;
        deg[e.b] = (deg[e.b] ?? 0) + e.detected;
      }
      ctx.font = '10px monospace';
      for (const id of ids) {
        const n = pos.get(id);
        if (!n) continue;
        const rad = 5 + ((deg[id] ?? 0) / maxDet) * 7;
        ctx.fillStyle = 'rgba(19,198,207,0.9)';
        ctx.beginPath();
        ctx.arc(cx + n.x, cy + n.y, rad, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = 'rgba(230,236,245,0.85)';
        ctx.fillText(id, cx + n.x + rad + 2, cy + n.y + 3);
      }
    };

    if (reduce) {
      for (let k = 0; k < 200; k++) stepPhysics();
      draw();
      return () => ro.disconnect();
    }

    let frame = 0;
    let settled = false;
    const tick = () => {
      frame += 1;
      pulse += 0.05;
      if (!settled) {
        const energy = stepPhysics();
        if (energy < 0.5 && frame > 120) settled = true;
      }
      draw();
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(rafRef.current);
      ro.disconnect();
    };
    // Sólo reinicia cuando cambia el conjunto de venues; net/detected se leen por ref.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [empty, sig]);

  return (
    <Card h="100%">
      <SectionHeader
        title="Relationship Graph"
        subtitle="rutas de arbitraje · venues y su edge neto"
        icon={<IconShare3 size={18} />}
        right={
          <Group gap="xs">
            <Badge variant="light" color="aqua">
              {venueIds.length} venues
            </Badge>
            <Badge variant="light" color="gray">
              {edges.length} rutas
            </Badge>
          </Group>
        }
      />
      {empty ? (
        <Text size="sm" c="dimmed">
          Aún no hay rutas observadas. El grafo aparece cuando el motor detecta oportunidades.
        </Text>
      ) : (
        <>
          <Box ref={wrapRef} style={{ width: '100%' }}>
            <canvas
              ref={canvasRef}
              role="img"
              aria-label={`Grafo de ${venueIds.length} venues y ${edges.length} rutas de arbitraje, coloreadas por edge neto.`}
              style={{ display: 'block', width: '100%' }}
            />
          </Box>
          <Group gap="lg" mt="xs">
            <Group gap={6}>
              <Box style={{ width: 18, height: 3, background: POS, borderRadius: 2 }} />
              <Text size="xs" c="dimmed">
                edge neto ≥ 0
              </Text>
            </Group>
            <Group gap={6}>
              <Box style={{ width: 18, height: 3, background: NEG, borderRadius: 2 }} />
              <Text size="xs" c="dimmed">
                edge neto &lt; 0 (no sobrevive)
              </Text>
            </Group>
          </Group>
        </>
      )}
    </Card>
  );
}
