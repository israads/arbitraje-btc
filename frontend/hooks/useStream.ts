'use client';

import { useEffect, useRef, useState } from 'react';
import { API_BASE } from '../lib/config';

export type ConnStatus =
  | 'connecting'
  | 'live'
  | 'reconnecting'
  | 'stale'
  | 'replay';

export interface Quote {
  exchange: string;
  symbol: string;
  quote_ccy: string;
  usd_bid: number | null;
  usd_ask: number | null;
  price_norm_factor: number;
  ts_exchange: number | null;
}

export interface Opportunity {
  id: string;
  strategy: string;
  symbol: string;
  buy_venue: string;
  sell_venue: string;
  q_target: number;
  vwap_buy: number | null;
  vwap_sell: number | null;
  net_pnl: number | null;
  score: number | null;
  z_score: number | null;
  status: string;
  discard_reason: string | null;
  latency_ms: number | null;
}

export interface StageLatency {
  stage: string;
  count: number;
  p50_ms: number | null;
  p99_ms: number | null;
  max_ms: number | null;
}

export interface Metrics {
  detected: number;
  viable: number;
  executable: number;
  captured: number;
  discarded: number;
  unwound: number;
  discard_reasons: Record<string, number>;
  by_strategy: Record<string, Record<string, number>>;
  detect_latency: StageLatency | null;
  exec_latency: StageLatency | null;
  p50_ms: number | null;
  p99_ms: number | null;
  effective_spread: number | null;
  expected_net_spread: number | null;
  price_impact: number | null;
  realized_spread: number | null;
  capture_ratio: number | null;
  fill_ratio: number | null;
  opp_lifetime_hist: number[];
  opp_lifetime_buckets_ms: number[];
  opp_lifetime_p50_ms: number | null;
  opp_lifetime_p99_ms: number | null;
}

export interface BreakerState {
  type: string;
  active: boolean;
  reason: string | null;
  since: number | null;
}

export interface BreakerStatus {
  halted: boolean;
  active: string[];
  breakers: BreakerState[];
}

export interface DemoStatus {
  active: boolean;
  mode: string;
  source: string;
  badge: string | null;
  since: number | null;
  n_replay_ticks?: number;
}

export interface Pnl {
  realized_pnl: number;
  unrealized_pnl: number;
  total_pnl: number;
  equity_usd: number;
  equity_series: { ts: number; equity: number }[];
  skew: Record<string, unknown>;
}

/** Reconciliación del reto ($109.75/BTC) + invariantes (C15, GET /api/v1/validation).
 * Determinista: se obtiene una vez (no cambia con el feed) y alimenta el HERO Edge Waterfall. */
export interface ValidationReport {
  reconciliation: {
    target: number;
    computed: number;
    diff: number;
    tolerance: number;
    passed: boolean;
    qty_btc: number;
    breakdown: { gross: number; fees: number; rebalance: number; net: number };
    notes: string;
  };
  invariants: { name: string; passed: boolean; detail: string }[];
  all_passed: boolean;
}

/** Projection Suite v2 — Capa 1: Break-even Frontier (Execution-Conditioned, /api/v1/projection). */
export interface FrontierBestCell {
  size_btc: number;
  fee_bps: number;
  net_per_btc: number;
  net_usd: number;
  expected_edge_usd: number | null;
  p_survive: number | null;
}

export interface EdgeFrontier {
  mode: string;
  route: { buy: string; sell: string; symbol: string } | null;
  asof_monotonic: number | null;
  sizes_btc: number[];
  fee_tiers: { label: string; bps: number }[];
  matrix: (number | null)[][];
  net_usd: (number | null)[][];
  p_survive: (number | null)[][];
  expected_edge: (number | null)[][];
  depth_limited: boolean[][];
  dominant_cost: string[][];
  best: {
    by_unit_edge: FrontierBestCell | null;
    by_total_edge: FrontierBestCell | null;
    by_risk_adjusted: FrontierBestCell | null;
  };
  gross_top_per_btc: number;
  survival_model: string | null;
  notes: string;
}

/** Capa 2: Capacity Curve (/api/v1/capacity). */
export interface CapacityPoint {
  q_btc: number;
  edge_total_usd: number;
  edge_marginal_per_btc: number;
  sqrt_impact_usd: number | null;
}

export interface EdgeCapacity {
  mode: string;
  route: { buy: string; sell: string; symbol: string } | null;
  fee_bps: number;
  points: CapacityPoint[];
  q_star_btc: number | null;
  q_star_edge_usd: number | null;
  hard_capacity_btc: number | null;
  throughput_usd_per_opp: number | null;
  notes: string;
}

/** Capa 3: Forward de P&L (/api/v1/forward). */
export interface ForwardBands {
  step: number[];
  p5: number[];
  p25: number[];
  p50: number[];
  p75: number[];
  p95: number[];
}

export interface ForwardProjection {
  available: boolean;
  n_trades: number;
  n_paths: number;
  block_mean: number | null;
  bands: ForwardBands;
  terminal_p5: number | null;
  terminal_p50: number | null;
  terminal_p95: number | null;
  terminal_hist: number[];
  terminal_hist_edges: number[];
  max_dd_p50: number | null;
  max_dd_p95: number | null;
  prob_profit: number | null;
  prob_ruin: number | null;
  sharpe_per_trade: number | null;
  psr: number | null;
  dsr: number | null;
  min_trl: number | null;
  n_configs: number;
  notes: string;
}

/** Estadística acumulada por ruta (buy→sell) durante toda la sesión, no solo el buffer. */
export interface RouteStat {
  route: string;
  buy_venue: string;
  sell_venue: string;
  detected: number;
  viable: number; // viable + executable + captured
  captured: number;
  bestNetPerBtc: number | null; // mejor neto histórico visto (sesión)
  lastGrossPerBtc: number | null;
  lastNetPerBtc: number | null;
  lastStatus: string;
  lastReason: string | null;
  lastLatencyMs: number | null;
}

const MAX_OPPS = 50;
const EMPTY_BREAKERS: BreakerStatus = { halted: false, active: [], breakers: [] };
const EMPTY_DEMO: DemoStatus = { active: false, mode: 'auto', source: 'live', badge: null, since: null };

/** Parse defensivo de un evento SSE: nunca lanza. Un frame corrupto/incompleto del backend
 * no debe romper el listener (que dejaría de procesar los eventos siguientes de ese tipo). */
function parseEvent<T>(e: Event): T | null {
  try {
    return JSON.parse((e as MessageEvent).data) as T;
  } catch {
    return null;
  }
}

/** fetch JSON que rechaza en respuestas no-2xx (evita parsear un cuerpo de error como datos). */
function fetchJson<T>(url: string, opt?: RequestInit): Promise<T> {
  return fetch(url, opt).then((r) => {
    if (!r.ok) throw new Error(`${r.status} ${url}`);
    return r.json() as Promise<T>;
  });
}

/**
 * Suscripción SSE al backend (C18). Patrón buffer-ref + requestAnimationFrame:
 * los eventos se acumulan en refs y se vuelcan a estado a lo sumo una vez por
 * frame (~60 fps), evitando re-renders por tick y manteniendo la UI fluida.
 *
 * STORY-023: además de quotes/opportunities, consume los eventos `metrics`, `breaker`
 * y `demo` (C13/C8/C16) y hace polling de `/pnl` (equity curve) cada 2 s.
 */
export function useStream() {
  const [status, setStatus] = useState<ConnStatus>('connecting');
  const [quotes, setQuotes] = useState<Record<string, Quote>>({});
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [detectedCount, setDetectedCount] = useState(0);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [breakers, setBreakers] = useState<BreakerStatus>(EMPTY_BREAKERS);
  const [demo, setDemo] = useState<DemoStatus>(EMPTY_DEMO);
  const [pnl, setPnl] = useState<Pnl | null>(null);
  const [routeStats, setRouteStats] = useState<RouteStat[]>([]);
  const [validation, setValidation] = useState<ValidationReport | null>(null);
  const [projection, setProjection] = useState<EdgeFrontier | null>(null);
  const [capacity, setCapacity] = useState<EdgeCapacity | null>(null);
  const [forward, setForward] = useState<ForwardProjection | null>(null);

  const quotesBuf = useRef<Record<string, Quote>>({});
  const oppsBuf = useRef<Opportunity[]>([]);
  const routeStatsRef = useRef<Map<string, RouteStat>>(new Map());
  const detectedRef = useRef(0);
  const metricsBuf = useRef<Metrics | null>(null);
  const dirty = useRef(false);

  useEffect(() => {
    // Snapshot inicial (estado antes del primer evento).
    fetchJson<{ quotes?: Quote[] }>(`${API_BASE}/api/v1/quotes`)
      .then((d) => {
        for (const q of Array.isArray(d.quotes) ? d.quotes : []) quotesBuf.current[q.exchange] = q;
        dirty.current = true;
      })
      .catch(() => undefined);
    fetchJson<Metrics>(`${API_BASE}/api/v1/metrics`)
      .then((m) => { metricsBuf.current = m; dirty.current = true; })
      .catch(() => undefined);
    // Reconciliación + invariantes y Break-even Frontier: deterministas → una sola vez.
    fetchJson<ValidationReport>(`${API_BASE}/api/v1/validation`)
      .then(setValidation)
      .catch(() => undefined);
    fetchJson<EdgeFrontier>(`${API_BASE}/api/v1/projection?mode=live`)
      .then(setProjection)
      .catch(() => undefined);
    fetchJson<EdgeCapacity>(`${API_BASE}/api/v1/capacity?mode=live`)
      .then(setCapacity)
      .catch(() => undefined);
    fetchJson<ForwardProjection>(`${API_BASE}/api/v1/forward?n_paths=4000`)
      .then(setForward)
      .catch(() => undefined);

    const es = new EventSource(`${API_BASE}/api/v1/stream`);
    es.onopen = () => setStatus('live');
    // EventSource reintenta solo; reflejamos "reconnecting" sólo si la conexión se cerró.
    es.onerror = () => {
      if (es.readyState !== EventSource.OPEN) setStatus('reconnecting');
    };

    es.addEventListener('quote', (e) => {
      const q = parseEvent<Quote>(e);
      if (!q) return;
      quotesBuf.current[q.exchange] = q;
      dirty.current = true;
    });

    es.addEventListener('opportunity', (e) => {
      const o = parseEvent<Opportunity>(e);
      if (!o) return;
      oppsBuf.current = [o, ...oppsBuf.current].slice(0, MAX_OPPS);
      detectedRef.current += 1;

      // Acumula estadística por ruta a lo largo de TODA la sesión (no solo el buffer de 50).
      const key = `${o.buy_venue}→${o.sell_venue}`;
      const gross =
        o.vwap_buy != null && o.vwap_sell != null ? o.vwap_sell - o.vwap_buy : null;
      const net =
        o.net_pnl != null && o.q_target != null && o.q_target > 0 ? o.net_pnl / o.q_target : null;
      const viableNow =
        o.status === 'viable' || o.status === 'executable' || o.status === 'captured';
      const s = routeStatsRef.current.get(key) ?? {
        route: key,
        buy_venue: o.buy_venue,
        sell_venue: o.sell_venue,
        detected: 0,
        viable: 0,
        captured: 0,
        bestNetPerBtc: null,
        lastGrossPerBtc: null,
        lastNetPerBtc: null,
        lastStatus: o.status,
        lastReason: null,
        lastLatencyMs: null,
      };
      s.detected += 1;
      if (viableNow) s.viable += 1;
      if (o.status === 'captured') s.captured += 1;
      if (net != null) s.bestNetPerBtc = s.bestNetPerBtc == null ? net : Math.max(s.bestNetPerBtc, net);
      s.lastGrossPerBtc = gross;
      s.lastNetPerBtc = net;
      s.lastStatus = o.status;
      s.lastReason = o.discard_reason;
      s.lastLatencyMs = o.latency_ms;
      routeStatsRef.current.set(key, s);
      dirty.current = true;
    });

    es.addEventListener('metrics', (e) => {
      const m = parseEvent<Metrics>(e);
      if (!m) return;
      metricsBuf.current = m;
      dirty.current = true;
    });

    // P&L en tiempo real (push tras cada ejecución, throttled). Antes era polling /pnl cada 2s.
    es.addEventListener('pnl', (e) => {
      const p = parseEvent<Pnl>(e);
      if (p) setPnl(p);
    });

    // breaker/demo son de baja frecuencia (sólo al cambiar) → setState directo.
    es.addEventListener('breaker', (e) => {
      const b = parseEvent<BreakerStatus>(e);
      if (b) setBreakers(b);
    });
    // `status` refleja SÓLO la conectividad SSE (onopen/onerror); el badge "DEMO DATA" se
    // deriva de `demo.active` en la página (evita que un reconnect pise el estado de demo).
    es.addEventListener('demo', (e) => {
      const d = parseEvent<DemoStatus>(e);
      if (d) setDemo(d);
    });

    let raf = 0;
    const tick = () => {
      if (dirty.current) {
        dirty.current = false;
        setQuotes({ ...quotesBuf.current });
        setOpportunities([...oppsBuf.current]);
        setDetectedCount(detectedRef.current);
        setRouteStats(Array.from(routeStatsRef.current.values()).map((s) => ({ ...s })));
        if (metricsBuf.current) setMetrics(metricsBuf.current);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);

    // Estado inicial de breakers/demo (sin esperar al primer cambio) + polling de P&L.
    // AbortController: cancela los fetch en vuelo al desmontar (evita setState huérfano,
    // relevante bajo StrictMode que monta→desmonta→monta).
    const ac = new AbortController();
    // P&L, breakers y demo llegan por SSE (push). Este pull es sólo BACKSTOP de baja
    // frecuencia: estado inicial antes del primer evento + resync si se perdió un push.
    const pull = () => {
      const opt = { signal: ac.signal };
      fetchJson<Pnl>(`${API_BASE}/api/v1/pnl`, opt).then(setPnl).catch(() => undefined);
      fetchJson<BreakerStatus>(`${API_BASE}/api/v1/control/status`, opt).then(setBreakers).catch(() => undefined);
      fetchJson<DemoStatus>(`${API_BASE}/api/v1/demo`, opt).then(setDemo).catch(() => undefined);
      // Proyección viva: la frontier/capacity dependen del book actual (el backend cae a demo
      // sin ruta viva); forward re-muestrea la grabación. Fallos no rompen el resto.
      fetchJson<EdgeFrontier>(`${API_BASE}/api/v1/projection?mode=live`, opt).then(setProjection).catch(() => undefined);
      fetchJson<EdgeCapacity>(`${API_BASE}/api/v1/capacity?mode=live`, opt).then(setCapacity).catch(() => undefined);
      fetchJson<ForwardProjection>(`${API_BASE}/api/v1/forward?n_paths=4000`, opt).then(setForward).catch(() => undefined);
    };
    pull();
    const poll = setInterval(pull, 5000);

    return () => {
      ac.abort();
      es.close();
      cancelAnimationFrame(raf);
      clearInterval(poll);
    };
  }, []);

  return {
    status, quotes, opportunities, routeStats, detectedCount,
    metrics, breakers, demo, pnl, validation, projection, capacity, forward,
  };
}
