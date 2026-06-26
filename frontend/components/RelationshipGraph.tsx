'use client';

import { useEffect, useMemo, useRef } from 'react';
import { Badge, Box, Card, Group, Text } from '@mantine/core';
import { IconShare3 } from '@tabler/icons-react';
import type { RouteStat } from '../hooks/useStream';
import { POS, NEG, SectionHeader } from './primitives';

/**
 * Relationship Graph — el grafo de rutas de arbitraje de la sesión. Cada nodo es un venue; cada
 * arista una ruta compra→venta observada, coloreada por su edge neto (verde si sobrevive a los
 * costes, roja si no) y con grosor por volumen de detecciones. Un pulso recorre la mejor ruta.
 * Layout force-directed que CONVERGE y se detiene (no animación infinita); reusa routeStats.
 * Respeta prefers-reduced-motion (layout estático).
 */

const HEIGHT = 300;

interface Node {
  id: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
  deg: number;
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

  const { nodes, edges, best } = useMemo(() => {
    const ids = new Set<string>();
    const es: Edge[] = [];
    for (const r of routeStats) {
      ids.add(r.buy_venue);
      ids.add(r.sell_venue);
      es.push({ a: r.buy_venue, b: r.sell_venue, net: r.lastNetPerBtc, detected: r.detected });
    }
    const list = Array.from(ids);
    const deg: Record<string, number> = {};
    for (const e of es) {
      deg[e.a] = (deg[e.a] ?? 0) + e.detected;
      deg[e.b] = (deg[e.b] ?? 0) + e.detected;
    }
    const ns: Node[] = list.map((id, k) => {
      const ang = (k / Math.max(1, list.length)) * Math.PI * 2;
      return { id, x: Math.cos(ang) * 80, y: Math.sin(ang) * 80, vx: 0, vy: 0, deg: deg[id] ?? 0 };
    });
    // Mejor ruta (mayor edge neto) para el pulso.
    let bestEdge: Edge | null = null;
    for (const e of es) {
      if (e.net != null && (bestEdge == null || e.net > (bestEdge.net ?? -Infinity))) bestEdge = e;
    }
    return { nodes: ns, edges: es, best: bestEdge };
  }, [routeStats]);

  const empty = nodes.length === 0;

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

    const byId = new Map(nodes.map((n) => [n.id, n]));
    const maxDeg = Math.max(1, ...nodes.map((n) => n.deg));
    let pulse = 0;
    let frame = 0;

    const stepPhysics = () => {
      // Repulsión todos-contra-todos.
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = nodes[i];
          const b = nodes[j];
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
      // Atracción por aristas (spring a distancia ~70).
      for (const e of edges) {
        const a = byId.get(e.a);
        const b = byId.get(e.b);
        if (!a || !b) continue;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const d = Math.sqrt(dx * dx + dy * dy) || 1;
        const f = (d - 70) * 0.02;
        const ux = dx / d;
        const uy = dy / d;
        a.vx += ux * f;
        a.vy += uy * f;
        b.vx -= ux * f;
        b.vy -= uy * f;
      }
      // Gravedad al centro + damping.
      let energy = 0;
      for (const n of nodes) {
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

    const draw = () => {
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.width / dpr;
      const h = canvas.height / dpr;
      ctx.clearRect(0, 0, w, h);
      const cx = w / 2;
      const cy = h / 2;

      // Aristas.
      for (const e of edges) {
        const a = byId.get(e.a);
        const b = byId.get(e.b);
        if (!a || !b) continue;
        const green = (e.net ?? 0) >= 0;
        ctx.strokeStyle = green ? 'rgba(47,217,140,0.45)' : 'rgba(246,103,138,0.35)';
        ctx.lineWidth = 0.6 + Math.min(3, e.detected / 40);
        ctx.beginPath();
        ctx.moveTo(cx + a.x, cy + a.y);
        ctx.lineTo(cx + b.x, cy + b.y);
        ctx.stroke();
      }

      // Pulso sobre la mejor ruta.
      if (best && !reduce) {
        const a = byId.get(best.a);
        const b = byId.get(best.b);
        if (a && b) {
          const t = (Math.sin(pulse) + 1) / 2;
          const px = cx + a.x + (b.x - a.x) * t;
          const py = cy + a.y + (b.y - a.y) * t;
          ctx.fillStyle = POS;
          ctx.shadowColor = POS;
          ctx.shadowBlur = 10;
          ctx.beginPath();
          ctx.arc(px, py, 3.5, 0, Math.PI * 2);
          ctx.fill();
          ctx.shadowBlur = 0;
        }
      }

      // Nodos.
      ctx.font = '10px monospace';
      for (const n of nodes) {
        const rad = 5 + (n.deg / maxDeg) * 7;
        ctx.fillStyle = 'rgba(19,198,207,0.9)';
        ctx.beginPath();
        ctx.arc(cx + n.x, cy + n.y, rad, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = 'rgba(230,236,245,0.85)';
        ctx.fillText(n.id, cx + n.x + rad + 2, cy + n.y + 3);
      }
    };

    if (reduce) {
      for (let k = 0; k < 200; k++) stepPhysics();
      draw();
      return () => ro.disconnect();
    }

    const tick = () => {
      frame += 1;
      const energy = stepPhysics();
      pulse += 0.05;
      draw();
      // Converge: si la energía es baja tras un mínimo de frames, sigue solo el pulso suave.
      if (energy < 0.5 && frame > 120) {
        // Mantén el pulso animado pero deja de recalcular física pesada.
        const pulseOnly = () => {
          pulse += 0.05;
          draw();
          rafRef.current = requestAnimationFrame(pulseOnly);
        };
        rafRef.current = requestAnimationFrame(pulseOnly);
        return;
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(rafRef.current);
      ro.disconnect();
    };
  }, [empty, nodes, edges, best]);

  return (
    <Card h="100%">
      <SectionHeader
        title="Relationship Graph"
        subtitle="rutas de arbitraje · venues y su edge neto"
        icon={<IconShare3 size={18} />}
        right={
          <Group gap="xs">
            <Badge variant="light" color="aqua">
              {nodes.length} venues
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
            <canvas ref={canvasRef} style={{ display: 'block', width: '100%' }} />
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
