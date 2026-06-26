'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
 * Animación en Canvas (no DOM), converge a un total fijo de bolas y se detiene (no es infinita),
 * sólo corre cuando es visible (IntersectionObserver) y respeta prefers-reduced-motion.
 */

const HEIGHT = 320;
const N_ROWS = 11;          // filas de clavos
const TARGET_BALLS = 900;   // converge y se detiene
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

interface Sim {
  balls: Ball[];
  counts: Float64Array;
  dropped: number;
  greenDropped: number;
}

function buildCdf(hist: number[]): { cdf: number[]; total: number } {
  const cdf: number[] = [];
  let acc = 0;
  for (const h of hist) {
    acc += Math.max(0, h);
    cdf.push(acc);
  }
  return { cdf, total: acc };
}

export function ProbabilityLattice({ forward }: { forward: ForwardProjection | null }) {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const simRef = useRef<Sim | null>(null);
  const rafRef = useRef<number>(0);
  const visibleRef = useRef(false);
  const [runId, setRunId] = useState(0);
  const [progress, setProgress] = useState(0);

  const hist = useMemo(() => forward?.terminal_hist ?? [], [forward?.terminal_hist]);
  const edges = useMemo(() => forward?.terminal_hist_edges ?? [], [forward?.terminal_hist_edges]);
  const ready = !!forward?.available && hist.length > 1 && edges.length === hist.length + 1;

  const money = (n: number | null | undefined) =>
    n == null ? '—' : `$${n.toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
  const pct = (n: number | null | undefined) => (n == null ? '—' : `${(n * 100).toFixed(0)}%`);

  // Centro de cada bucket y signo (verde si el P&L del bucket es >= 0).
  const bucketGreen = useCallback(
    (i: number) => {
      const c = (edges[i] + edges[i + 1]) / 2;
      return c >= 0;
    },
    [edges],
  );

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const sim = simRef.current;
    if (!canvas || !sim) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.width / dpr;
    const h = canvas.height / dpr;
    ctx.clearRect(0, 0, w, h);

    const n = hist.length;
    const padX = 10;
    const usableW = w - padX * 2;
    const pegTop = 28;
    const bucketsTop = h * 0.52;
    const bucketsBottom = h - 18;
    const bucketsH = bucketsBottom - bucketsTop;
    const bucketW = usableW / n;
    const bucketCenter = (i: number) => padX + (i + 0.5) * bucketW;

    // break-even x: interpolado donde edge cruza 0.
    let beX = padX;
    for (let i = 0; i < n; i++) {
      if (edges[i] <= 0 && edges[i + 1] > 0) {
        const f = (0 - edges[i]) / (edges[i + 1] - edges[i]);
        beX = padX + (i + f) * bucketW;
        break;
      }
      if (edges[i] > 0 && i === 0) {
        beX = padX;
        break;
      }
      if (i === n - 1) beX = padX + usableW;
    }

    // Clavos (pirámide tenue).
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

    // Cubetas (histograma acumulado), normalizadas al máximo.
    let maxC = 1;
    for (let i = 0; i < n; i++) maxC = Math.max(maxC, sim.counts[i]);
    for (let i = 0; i < n; i++) {
      const bh = (sim.counts[i] / maxC) * bucketsH;
      if (bh <= 0) continue;
      const x = padX + i * bucketW;
      const green = bucketGreen(i);
      const grad = ctx.createLinearGradient(0, bucketsBottom - bh, 0, bucketsBottom);
      if (green) {
        grad.addColorStop(0, BRAND);
        grad.addColorStop(1, 'rgba(22,214,127,0.25)');
      } else {
        grad.addColorStop(0, NEG);
        grad.addColorStop(1, 'rgba(246,103,138,0.22)');
      }
      ctx.fillStyle = grad;
      ctx.fillRect(x + 1, bucketsBottom - bh, bucketW - 2, bh);
    }

    // Línea break-even.
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

    // Bolas en vuelo.
    for (const b of sim.balls) {
      ctx.beginPath();
      ctx.fillStyle = b.green ? POS : NEG;
      ctx.shadowColor = b.green ? POS : NEG;
      ctx.shadowBlur = 6;
      ctx.arc(b.x, b.y, 2.4, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.shadowBlur = 0;

    return { bucketsTop, bucketCenter, bucketW, pegTop };
  }, [hist, edges, bucketGreen]);

  // Bucle de simulación.
  useEffect(() => {
    if (!ready) return;
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;

    const n = hist.length;
    simRef.current = {
      balls: [],
      counts: new Float64Array(n),
      dropped: 0,
      greenDropped: 0,
    };
    const { cdf, total } = buildCdf(hist);
    const reduced =
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

    // Modo accesible: pinta la distribución completa de una vez, sin animación.
    if (reduced) {
      const sim = simRef.current;
      for (let i = 0; i < n; i++) sim.counts[i] = hist[i];
      sim.dropped = total;
      sim.greenDropped = hist.reduce((a, h, i) => a + (bucketGreen(i) ? h : 0), 0);
      draw();
      setProgress(1);
      return () => ro.disconnect();
    }

    const io = new IntersectionObserver(
      (entries) => {
        visibleRef.current = entries[0]?.isIntersecting ?? false;
      },
      { threshold: 0.15 },
    );
    io.observe(wrap);

    let spawnAcc = 0;
    const tick = () => {
      const sim = simRef.current;
      if (!sim) return;
      const meta = draw();
      if (meta && visibleRef.current) {
        const { bucketsTop, bucketCenter } = meta;
        const dpr = window.devicePixelRatio || 1;
        const w = canvas.width / dpr;
        // Spawn progresivo hasta el objetivo.
        spawnAcc += 1;
        if (spawnAcc >= 1 && sim.balls.length < MAX_INFLIGHT && sim.dropped + sim.balls.length < TARGET_BALLS) {
          spawnAcc = 0;
          const bucket = sampleBucket();
          const green = bucketGreen(bucket);
          sim.balls.push({
            x: w / 2 + (Math.random() - 0.5) * 8,
            y: 6,
            vy: 1.2,
            targetX: bucketCenter(bucket),
            bucket,
            green,
            phase: Math.random() * Math.PI * 2,
          });
        }
        // Física: gravedad + deriva hacia el bucket con zig-zag por filas.
        const rowGap = (bucketsTop - 12) / N_ROWS;
        for (const b of sim.balls) {
          b.vy = Math.min(b.vy + GRAVITY, 6);
          b.y += b.vy;
          const drift = (b.targetX - b.x) * 0.06;
          const wobble = Math.sin((b.y / rowGap) * Math.PI + b.phase) * 1.1;
          b.x += drift + wobble;
        }
        // Aterrizaje.
        sim.balls = sim.balls.filter((b) => {
          if (b.y >= bucketsTop) {
            sim.counts[b.bucket] += 1;
            sim.dropped += 1;
            if (b.green) sim.greenDropped += 1;
            return false;
          }
          return true;
        });
        setProgress(Math.min(1, sim.dropped / TARGET_BALLS));
        // Convergió: dibuja el frame final y detén el loop (no animación infinita).
        if (sim.dropped >= TARGET_BALLS && sim.balls.length === 0) {
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
  }, [ready, runId, hist, edges, draw, bucketGreen]);

  const sim = simRef.current;
  const landedGreen = sim && sim.dropped > 0 ? sim.greenDropped / sim.dropped : null;

  return (
    <Card h="100%">
      <SectionHeader
        title="Probability Lattice"
        subtitle="cada trade = una bola · el edge inclina el tablero"
        icon={<IconGridDots size={18} />}
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
        <Group align="stretch" gap="lg" wrap="nowrap" style={{ flexWrap: 'wrap' }}>
          <Stack gap="md" style={{ minWidth: 150 }}>
            <LatticeStat label="Bolas lanzadas" value={`${sim?.dropped ?? 0}`} sub={`de ${TARGET_BALLS}`} />
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
            <canvas ref={canvasRef} style={{ display: 'block', width: '100%' }} />
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
