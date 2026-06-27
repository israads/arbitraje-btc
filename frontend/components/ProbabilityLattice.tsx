'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { Badge, Box, Button, Card, Group, Stack, Text } from '@mantine/core';
import { IconGridDots, IconReload } from '@tabler/icons-react';
import type { ForwardProjection } from '../hooks/useStream';
import { BRAND, POS, NEG, SectionHeader } from './primitives';

/**
 * Probability Lattice — un tablero de Galton sobre el Forward Monte Carlo (Capa 3). Cada bola es
 * un trade muestreado de la distribución terminal de P&L del bootstrap estacionario; al caer por
 * los clavos se acumula en cubetas y reconstruye esa distribución, verde a la derecha del
 * break-even y roja a la izquierda. El "edge inclina el tablero": si el motor tiene ventaja, la
 * masa cae al verde. Es presentación, no un pronóstico — la forma ES la del Monte Carlo real.
 *
 * Animación en Canvas (no DOM): converge a un total fijo de bolas y se detiene. Sólo se reinicia
 * cuando la distribución cambia de verdad (firma de contenido, no de referencia) o con Re-run;
 * sólo corre cuando es visible (IntersectionObserver); respeta prefers-reduced-motion.
 */

const HEIGHT = 320;
const N_ROWS = 11;
const TARGET_BALLS = 900;
const MAX_INFLIGHT = 36;
const GRAVITY = 0.22;

interface Ball {
  x: number;
  y: number;
  vy: number;
  targetX: number;
  bucket: number;
  green: boolean;
  phase: number;
}

export function ProbabilityLattice({ forward }: { forward: ForwardProjection | null }) {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const rafRef = useRef<number>(0);
  const [runId, setRunId] = useState(0);
  const [progress, setProgress] = useState(0);
  // Stats laterales: snapshot que sólo se actualiza por % entero (no por frame).
  const [stat, setStat] = useState({ dropped: 0, green: 0 });

  const hist = useMemo(() => forward?.terminal_hist ?? [], [forward?.terminal_hist]);
  const edges = useMemo(() => forward?.terminal_hist_edges ?? [], [forward?.terminal_hist_edges]);
  const ready = !!forward?.available && hist.length > 1 && edges.length === hist.length + 1;
  // Firma de CONTENIDO: si la distribución no cambia, no reiniciamos aunque forward sea otro objeto.
  const sig = ready
    ? `${hist.length}:${edges[0]}:${edges[edges.length - 1]}:${hist[0]}:${hist[hist.length - 1]}`
    : '';

  // Refs para leer datos vigentes dentro del efecto sin reiniciarlo por cambio de referencia.
  const histRef = useRef(hist);
  const edgesRef = useRef(edges);
  histRef.current = hist;
  edgesRef.current = edges;

  const money = (n: number | null | undefined) =>
    n == null ? '—' : `$${n.toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
  const pct = (n: number | null | undefined) => (n == null ? '—' : `${(n * 100).toFixed(0)}%`);

  useEffect(() => {
    if (!ready) return;
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;

    const h0 = histRef.current;
    const e0 = edgesRef.current;
    const n = h0.length;
    const counts = new Float64Array(n);
    let balls: Ball[] = [];
    let dropped = 0;
    let greenDropped = 0;
    let lastPctShown = -1;

    const total = h0.reduce((a, v) => a + Math.max(0, v), 0) || 1;
    const cdf: number[] = [];
    { let acc = 0; for (const v of h0) { acc += Math.max(0, v); cdf.push(acc); } }
    const bucketGreen = (i: number) => (e0[i] + e0[i + 1]) / 2 >= 0;
    const reduce =
      typeof window !== 'undefined' &&
      window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

    const setupCanvas = () => {
      const dpr = window.devicePixelRatio || 1;
      const cssW = wrap.clientWidth || 600;
      canvas.width = Math.round(cssW * dpr);
      canvas.height = Math.round(HEIGHT * dpr);
      canvas.style.width = `${cssW}px`;
      canvas.style.height = `${HEIGHT}px`;
      const ctx = canvas.getContext('2d');
      if (ctx) ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    setupCanvas();
    const ro = new ResizeObserver(setupCanvas);
    ro.observe(wrap);

    const sampleBucket = () => {
      const r = Math.random() * total;
      let lo = 0;
      let hi = cdf.length - 1;
      while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (cdf[mid] < r) lo = mid + 1;
        else hi = mid;
      }
      return lo;
    };

    const draw = () => {
      const ctx = canvas.getContext('2d');
      if (!ctx) return null;
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.width / dpr;
      const ht = canvas.height / dpr;
      ctx.clearRect(0, 0, w, ht);

      const padX = 10;
      const usableW = w - padX * 2;
      const pegTop = 28;
      const bucketsTop = ht * 0.52;
      const bucketsBottom = ht - 18;
      const bucketsH = bucketsBottom - bucketsTop;
      const bucketW = usableW / n;
      const bucketCenter = (i: number) => padX + (i + 0.5) * bucketW;

      let beX = padX;
      for (let i = 0; i < n; i++) {
        if (e0[i] <= 0 && e0[i + 1] > 0) {
          const f = (0 - e0[i]) / (e0[i + 1] - e0[i]);
          beX = padX + (i + f) * bucketW;
          break;
        }
        if (e0[i] > 0 && i === 0) { beX = padX; break; }
        if (i === n - 1) beX = padX + usableW;
      }

      ctx.fillStyle = 'rgba(255,255,255,0.12)';
      for (let r = 0; r < N_ROWS; r++) {
        const y = pegTop + (r / (N_ROWS - 1)) * (bucketsTop - pegTop - 16);
        const cnt = r + 1;
        const span = (cnt - 1) * (usableW / (N_ROWS + 2));
        const startX = w / 2 - span / 2;
        for (let c = 0; c < cnt; c++) {
          ctx.beginPath();
          ctx.arc(startX + c * (usableW / (N_ROWS + 2)), y, 1.4, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      let maxC = 1;
      for (let i = 0; i < n; i++) maxC = Math.max(maxC, counts[i]);
      for (let i = 0; i < n; i++) {
        const bh = (counts[i] / maxC) * bucketsH;
        if (bh <= 0) continue;
        const x = padX + i * bucketW;
        const grad = ctx.createLinearGradient(0, bucketsBottom - bh, 0, bucketsBottom);
        if (bucketGreen(i)) {
          grad.addColorStop(0, BRAND);
          grad.addColorStop(1, 'rgba(22,214,127,0.25)');
        } else {
          grad.addColorStop(0, NEG);
          grad.addColorStop(1, 'rgba(246,103,138,0.22)');
        }
        ctx.fillStyle = grad;
        ctx.fillRect(x + 1, bucketsBottom - bh, bucketW - 2, bh);
      }

      ctx.strokeStyle = 'rgba(255,255,255,0.45)';
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(beX, pegTop - 12);
      ctx.lineTo(beX, bucketsBottom);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = 'rgba(255,255,255,0.6)';
      ctx.font = '9px monospace';
      ctx.fillText('BREAK-EVEN', Math.min(beX + 4, w - 64), pegTop - 4);

      for (const b of balls) {
        ctx.beginPath();
        ctx.fillStyle = b.green ? POS : NEG;
        ctx.shadowColor = b.green ? POS : NEG;
        ctx.shadowBlur = 6;
        ctx.arc(b.x, b.y, 2.4, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.shadowBlur = 0;
      return { bucketsTop, bucketCenter };
    };

    // Modo accesible: pinta la distribución completa de una vez, sin animación.
    if (reduce) {
      for (let i = 0; i < n; i++) counts[i] = h0[i];
      dropped = total;
      greenDropped = h0.reduce((a, v, i) => a + (bucketGreen(i) ? v : 0), 0);
      draw();
      setProgress(1);
      setStat({ dropped, green: greenDropped });
      return () => ro.disconnect();
    }

    let visible = true;
    const io = new IntersectionObserver(
      (entries) => { visible = entries[0]?.isIntersecting ?? false; },
      { threshold: 0.15 },
    );
    io.observe(wrap);

    const tick = () => {
      // Fuera de viewport: no dibujar ni avanzar; reintentar más tarde (no quema CPU dibujando).
      if (!visible) {
        rafRef.current = requestAnimationFrame(tick);
        return;
      }
      const meta = draw();
      if (meta) {
        const dpr = window.devicePixelRatio || 1;
        const w = canvas.width / dpr;
        if (balls.length < MAX_INFLIGHT && dropped + balls.length < TARGET_BALLS) {
          const bucket = sampleBucket();
          balls.push({
            x: w / 2 + (Math.random() - 0.5) * 8,
            y: 6,
            vy: 1.2,
            targetX: meta.bucketCenter(bucket),
            bucket,
            green: bucketGreen(bucket),
            phase: Math.random() * Math.PI * 2,
          });
        }
        const rowGap = (meta.bucketsTop - 12) / N_ROWS;
        for (const b of balls) {
          b.vy = Math.min(b.vy + GRAVITY, 6);
          b.y += b.vy;
          b.x += (b.targetX - b.x) * 0.06 + Math.sin((b.y / rowGap) * Math.PI + b.phase) * 1.1;
        }
        balls = balls.filter((b) => {
          if (b.y >= meta.bucketsTop) {
            counts[b.bucket] += 1;
            dropped += 1;
            if (b.green) greenDropped += 1;
            return false;
          }
          return true;
        });
        // Throttle de estado: sólo al cambiar el % entero (no en cada frame).
        const p = Math.min(100, Math.round((dropped / TARGET_BALLS) * 100));
        if (p !== lastPctShown) {
          lastPctShown = p;
          setProgress(p / 100);
          setStat({ dropped, green: greenDropped });
        }
        if (dropped >= TARGET_BALLS && balls.length === 0) {
          draw();
          return;
        }
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(rafRef.current);
      ro.disconnect();
      io.disconnect();
    };
    // sig captura el contenido; runId fuerza re-run manual. No dependemos de las referencias.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, runId, sig]);

  const landedGreen = stat.dropped > 0 ? stat.green / stat.dropped : null;
  const ariaLabel = ready
    ? `Distribución de resultados del Monte Carlo: ${pct(landedGreen)} de los trades caen en zona de ganancia.`
    : 'Tablero de probabilidad sin datos todavía.';

  return (
    <Card h="100%">
      <SectionHeader
        title="Probability Lattice"
        subtitle="cada trade = una bola · el edge inclina el tablero"
        icon={<IconGridDots size={18} />}
        help="Un tablero de Galton sobre la simulación Monte Carlo: cada bola es un trade posible muestreado de la distribución real de P&L. Al caer reconstruye esa distribución — verde si queda ganancia, rojo si pierde. Si el motor tiene ventaja, la masa cae al verde."
        right={
          <Group gap="xs">
            {forward?.n_paths ? (
              <Badge variant="light" color="aqua">
                {forward.n_paths.toLocaleString('en-US')} paths
              </Badge>
            ) : null}
            <Button
              size="compact-xs"
              variant="subtle"
              color="gray"
              leftSection={<IconReload size={13} />}
              onClick={() => setRunId((r) => r + 1)}
              disabled={!ready}
            >
              Re-run
            </Button>
          </Group>
        }
      />

      {!ready ? (
        <Text size="sm" c="dimmed">
          Ejecutando el Monte Carlo forward… el tablero aparece cuando hay distribución terminal.
        </Text>
      ) : (
        <Group align="stretch" gap="lg" wrap="wrap">
          <Stack gap="md" style={{ minWidth: 150, flex: '1 1 150px' }}>
            <LatticeStat label="Bolas lanzadas" value={`${stat.dropped}`} sub={`de ${TARGET_BALLS}`} />
            <LatticeStat
              label="Cayeron en verde"
              value={pct(landedGreen)}
              sub={`objetivo ${pct(forward?.prob_profit)}`}
              color={POS}
            />
            <LatticeStat label="EV / trade" value={money(forward?.block_mean)} color={(forward?.block_mean ?? 0) >= 0 ? POS : NEG} />
            <LatticeStat label="Mediana P&L" value={money(forward?.terminal_p50)} color={(forward?.terminal_p50 ?? 0) >= 0 ? POS : NEG} />
            <LatticeStat label="P(ruina)" value={pct(forward?.prob_ruin)} color={NEG} />
            <LatticeStat label="Sharpe / trade" value={forward?.sharpe_per_trade?.toFixed(2) ?? '—'} />
          </Stack>
          <Box ref={wrapRef} style={{ flex: 1, minWidth: 260, position: 'relative' }}>
            <canvas ref={canvasRef} role="img" aria-label={ariaLabel} style={{ display: 'block', width: '100%' }} />
            <Box
              style={{
                position: 'absolute',
                left: 0,
                right: 0,
                bottom: 4,
                height: 2,
                background: `linear-gradient(90deg, ${BRAND} ${progress * 100}%, transparent ${progress * 100}%)`,
                opacity: 0.5,
                transition: 'background 200ms linear',
              }}
            />
          </Box>
        </Group>
      )}
    </Card>
  );
}

function LatticeStat({
  label,
  value,
  sub,
  color,
}: {
  label: string;
  value: string;
  sub?: string;
  color?: string;
}) {
  return (
    <Box>
      <Text fz={9} tt="uppercase" c="dimmed" fw={700} style={{ letterSpacing: 0.3 }}>
        {label}
      </Text>
      <Text ff="monospace" className="mono-nums" fw={700} fz={20} lh={1.15} c={color}>
        {value}
      </Text>
      {sub && (
        <Text fz={10} c="dimmed">
          {sub}
        </Text>
      )}
    </Box>
  );
}
