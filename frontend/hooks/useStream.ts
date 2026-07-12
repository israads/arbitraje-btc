'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
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
  /** Monotónico del proceso backend (ingesta): comparable con `scenario_started_at`
   * (PRD-013). Ya viaja en el SSE (model_dump del backend); aquí sólo se tipa. */
  t_recv?: number | null;
  legs?: StrategyLeg[] | null;
  strategy_payload?: Record<string, unknown>;
}

export interface StrategyLeg {
  venue: string;
  symbol: string;
  side: 'buy' | 'sell' | 'funding' | 'fx';
  asset_in: string;
  asset_out: string;
  qty_in: number;
  qty_out: number;
  price: number | null;
  fee: number;
  fee_rate: number;
}

export interface StrategyInfo {
  id: string;
  enabled: boolean;
  mode: 'primary' | 'adapter' | 'demo_replay' | 'read_only' | 'experimental';
  description: string;
}

export interface CostComponent {
  key: string;
  label: string;
  usd: number | null;
  per_btc: number | null;
}

export interface OpportunityExplanation {
  id: string;
  route: {
    symbol: string;
    buy_venue: string;
    sell_venue: string;
  };
  q_target: number;
  naive: {
    buy_price: number | null;
    sell_price: number | null;
    spread_usd_per_btc: number | null;
    gross_usd: number | null;
    would_trade: boolean;
  };
  engine: {
    status: string;
    reason: string | null;
    net_usd: number | null;
    net_per_btc: number | null;
    dominant_cost: string | null;
    trades: boolean;
  };
  breakdown: CostComponent[];
  peg: Record<string, number | string | null>;
  timestamps: Record<string, number | null>;
  notes: string[];
}

export interface StageLatency {
  stage: string;
  count: number;
  p50_ms: number | null;
  p99_ms: number | null;
  max_ms: number | null;
}

export interface Metrics {
  /** Reloj monotónico al construir el evento SSE. GET /metrics puede omitirlo. */
  asof_monotonic?: number;
  detected: number;
  viable: number;
  executable: number;
  captured: number;
  discarded: number;
  unwound: number;
  discard_reasons: Record<string, number>;
  by_strategy: Record<string, Record<string, number>>;
  preflight_results?: Record<string, Record<string, number>>;
  test_order_results?: Record<string, Record<string, number>>;
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
  integrity?: Record<string, {
    validator: string;
    accepted: number;
    rejected: number;
    last_reason: string | null;
    last_seq: number | null;
    last_checksum: string | null;
    checksum_failures: number;
    sequence_gaps: number;
    last_valid_at: number | null;
  }>;
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
  scenario?: string | null;
  scenario_description?: string | null;
  scenario_kind?: string | null;
  expected_result?: string | null;
  scenario_index?: number;
  n_scenarios?: number;
  /** Identidad de activación (PRD-013): monotónico por proceso backend; `scenario` y
   * `scenario_index` se repiten en cada ciclo y NUNCA sirven de clave. */
  scenario_run_id?: number | null;
  /** Reloj monotónico del backend al primer frame; comparable con `Opportunity.t_recv`. */
  scenario_started_at?: number | null;
}

/** PRD-013 — ventana de observación `esperado → observado` de UNA activación jury.
 * El estado vive sólo en el frontend (useRef en useStream); la UI recibe snapshots
 * inmutables y NO recalcula nada. */
export type ScenarioObservationStatus = 'pending' | 'observed' | 'absent';
export type ScenarioObservationDetail =
  | 'awaiting_evidence'
  | 'no_claim'
  | 'no_effect'
  | 'telemetry_restarted'
  | 'telemetry_insufficient'
  | 'evidence_inconsistent';

export interface ScenarioObservationWindow {
  runId: number;
  scenario: string | null;
  expectedReason: string | null;
  backendStartedAt: number | null;
  /** null hasta copiar el PRIMER snapshot SSE de métricas POSTERIOR a abrir la ventana.
   * Nunca `{}` ni el último acumulado conocido (convertirían historia en delta). */
  baselineReasons: Record<string, number> | null;
  latestReasons: Record<string, number>;
  /** Evidencia primaria: eventos `opportunity` con `t_recv >= backendStartedAt`. La clave
   * `captured` cuenta status=captured (good_edge); el resto son `discard_reason`. */
  directReasons: Record<string, number>;
  /** Sólo eventos posteriores a fijar la baseline: única fuente temporalmente
   * equivalente al delta de métricas. */
  directReasonsSinceBaseline: Record<string, number>;
  baselineCaptured: number | null;
  latestCaptured: number;
  postBaselineMetricSamples: number;
  directSamples: number;
  /** stale_feed (mínimo RF-002.5): estado feed/breaker COPIADO con su timestamp; no se
   * afirma que la activación lo causó (la transición posterior es stretch). */
  staleSignal: { active: boolean; since: number | null } | null;
  telemetryRestarted: boolean;
  status: ScenarioObservationStatus;
  detail: ScenarioObservationDetail | null; // null sólo cuando status=observed
}

/** RF-003B: contrato literal de `order_failure` (claim de ejecución retirado). Debe ser
 * idéntico a `ORDER_FAILURE_NO_CLAIM` del backend (app/demo/scenarios.py). */
export const SCENARIO_NO_CLAIM = 'sin claim de ejecución; sólo books deterministas';

function evaluateScenarioWindow(w: ScenarioObservationWindow): void {
  // RF-003B / RF-001.2: sin claim → `absent` honesto SIEMPRE; nunca se infiere éxito.
  if (w.expectedReason == null || w.expectedReason === SCENARIO_NO_CLAIM) {
    w.status = 'absent';
    w.detail = 'no_claim';
    return;
  }
  if (w.scenario === 'stale_feed') {
    // Fuente aplicable: UNA muestra feed/breaker; no se exige oportunidad ni delta
    // (el propio comportamiento del escenario los evita).
    if (w.staleSignal?.active) { w.status = 'observed'; w.detail = null; return; }
    if (w.staleSignal != null || w.postBaselineMetricSamples >= 1) {
      w.status = 'absent';
      w.detail = 'no_effect';
      return;
    }
    w.status = 'pending';
    w.detail = 'awaiting_evidence';
    return;
  }
  const key = w.expectedReason;
  const direct = w.directReasons[key] ?? 0;
  const directSince = w.directReasonsSinceBaseline[key] ?? 0;
  let delta: number | null = null;
  if (w.baselineReasons != null && w.postBaselineMetricSamples > 0) {
    delta = key === 'captured'
      ? w.latestCaptured - (w.baselineCaptured ?? 0)
      : (w.latestReasons[key] ?? 0) - (w.baselineReasons[key] ?? 0);
  }
  // Fuentes temporalmente equivalentes que discrepan: el delta atribuye MÁS de lo que el
  // canal directo vio tras la baseline (eventos SSE perdidos o atribución cruzada) →
  // `absent`, nunca se conserva éxito. delta <= directSince es lag normal del throttle.
  if (delta != null && directSince > 0 && delta > directSince) {
    w.status = 'absent';
    w.detail = 'evidence_inconsistent';
    return;
  }
  if (direct > 0) { w.status = 'observed'; w.detail = null; return; }
  // Delta sin evento directo equivalente: los acumulados no llevan timestamp por
  // incremento (una cola anterior pudo vaciarse tras abrir la ventana) → no cuenta.
  if (delta != null && delta > 0) {
    w.status = 'absent';
    w.detail = 'telemetry_insufficient';
    return;
  }
  if (w.postBaselineMetricSamples >= 1) { w.status = 'absent'; w.detail = 'no_effect'; return; }
  if (w.telemetryRestarted) { w.status = 'absent'; w.detail = 'telemetry_restarted'; return; }
  w.status = 'pending';
  w.detail = 'awaiting_evidence';
}

function newScenarioWindow(d: DemoStatus, breakers: BreakerStatus): ScenarioObservationWindow {
  const w: ScenarioObservationWindow = {
    runId: d.scenario_run_id ?? 0,
    scenario: d.scenario ?? null,
    expectedReason: d.expected_result ?? null,
    backendStartedAt: d.scenario_started_at ?? null,
    baselineReasons: null,
    latestReasons: {},
    directReasons: {},
    directReasonsSinceBaseline: {},
    baselineCaptured: null,
    latestCaptured: 0,
    postBaselineMetricSamples: 0,
    directSamples: 0,
    staleSignal: null,
    telemetryRestarted: false,
    status: 'pending',
    detail: 'awaiting_evidence',
  };
  if (w.scenario === 'stale_feed') {
    // Mínimo RF-002.5: copiar el estado feed/breaker VIGENTE (con su timestamp).
    const stale = breakers.breakers.find((b) => b.type === 'stale_data');
    if (stale) w.staleSignal = { active: stale.active, since: stale.since };
  }
  evaluateScenarioWindow(w);
  return w;
}

function applyMetricsToScenarioWindow(w: ScenarioObservationWindow, m: Metrics): void {
  // El poll de /demo y SSE son transportes independientes: un snapshot emitido antes del
  // cambio puede entregarse después de que el poll abra la ventana. Sin este corte temporal
  // no es una baseline segura. Un backend antiguo sin sello queda visible como insuficiente.
  if (
    w.backendStartedAt == null
    || typeof m.asof_monotonic !== 'number'
    || m.asof_monotonic < w.backendStartedAt
  ) {
    w.status = 'absent';
    w.detail = 'telemetry_insufficient';
    return;
  }
  const reasons = m.discard_reasons ?? {};
  if (w.baselineReasons == null) {
    // Primer snapshot POSTERIOR a abrir la ventana → baseline COPIADA (no referenciada);
    // claves ausentes valen 0 al calcular el delta. La baseline no cuenta como muestra.
    w.baselineReasons = { ...reasons };
    w.baselineCaptured = m.captured;
    w.latestReasons = { ...reasons };
    w.latestCaptured = m.captured;
    w.directReasonsSinceBaseline = {};
  } else {
    const keys = new Set([...Object.keys(w.baselineReasons), ...Object.keys(reasons)]);
    let restarted = m.captured < (w.baselineCaptured ?? 0);
    for (const k of keys) {
      if ((reasons[k] ?? 0) < (w.baselineReasons[k] ?? 0)) restarted = true;
    }
    if (restarted) {
      // Delta negativo = reinicio/resync del backend: la muestra pasa a ser la NUEVA
      // baseline y la evidencia previa se descarta; nunca se muestra un número negativo.
      w.baselineReasons = { ...reasons };
      w.baselineCaptured = m.captured;
      w.latestReasons = { ...reasons };
      w.latestCaptured = m.captured;
      w.directReasons = {};
      w.directReasonsSinceBaseline = {};
      w.directSamples = 0;
      w.postBaselineMetricSamples = 0;
      w.telemetryRestarted = true;
    } else {
      w.latestReasons = { ...reasons };
      w.latestCaptured = m.captured;
      w.postBaselineMetricSamples += 1;
    }
  }
  evaluateScenarioWindow(w);
}

function applyOpportunityToScenarioWindow(
  w: ScenarioObservationWindow,
  o: Opportunity,
): boolean {
  // Corte monotónico: sin t_recv o anterior al arranque del escenario → book del escenario
  // previo que seguía en la cola del motor; no se atribuye.
  if (w.backendStartedAt == null || typeof o.t_recv !== 'number') return false;
  if (o.t_recv < w.backendStartedAt) return false;
  w.directSamples += 1;
  const key = o.status === 'captured' ? 'captured' : o.discard_reason;
  if (key) {
    w.directReasons[key] = (w.directReasons[key] ?? 0) + 1;
    if (w.baselineReasons != null) {
      w.directReasonsSinceBaseline[key] = (w.directReasonsSinceBaseline[key] ?? 0) + 1;
    }
  }
  evaluateScenarioWindow(w);
  return true;
}

function applyBreakersToScenarioWindow(
  w: ScenarioObservationWindow,
  b: BreakerStatus,
): boolean {
  if (w.scenario !== 'stale_feed') return false;
  const stale = b.breakers.find((x) => x.type === 'stale_data');
  w.staleSignal = stale
    ? { active: stale.active, since: stale.since }
    : { active: b.active.includes('stale_data'), since: null };
  evaluateScenarioWindow(w);
  return true;
}

/** Snapshot inmutable para la UI (los records internos se mutan en el ref). */
function snapshotScenarioWindow(w: ScenarioObservationWindow): ScenarioObservationWindow {
  return {
    ...w,
    baselineReasons: w.baselineReasons ? { ...w.baselineReasons } : null,
    latestReasons: { ...w.latestReasons },
    directReasons: { ...w.directReasons },
    directReasonsSinceBaseline: { ...w.directReasonsSinceBaseline },
    staleSignal: w.staleSignal ? { ...w.staleSignal } : null,
  };
}

/** Inventario & rebalanceo (PRD-012): contratos de GET /balances y la sección de /pnl.
 * Las propiedades opcionales reflejan la rama real SIN portfolio del backend
 * (router.py: `{balances: [], equity_by_venue: {}, skew: {}, snapshot: null}` y /pnl sin
 * `initial_quote_usd`/`equity_by_venue`/`rebalance`), no una preferencia de diseño. */
export interface BalanceItem {
  exchange: string;
  asset: string;
  amount: number;
}

export interface InventorySkew {
  btc_by_venue: Record<string, number>;
  total_btc: number;
  skew: number;
  limit: number;
  breached: boolean;
}

export interface RebalanceEvent {
  ts: number;
  cost_usd: number;
  fee_btc: number;
  ref_mark: number;
  skew_before: number;
  skew_after: number;
}

export interface RebalanceSummary {
  count: number;
  cost_total_usd: number;
  recent: RebalanceEvent[];
}

export interface InventorySnapshot {
  ts: number;
  balances: BalanceItem[];
  total_usd: number | null;
}

export interface BalancesResponse {
  balances: BalanceItem[];
  equity_by_venue: Record<string, number>;
  equity_usd?: number; // ausente sin portfolio
  skew: InventorySkew | Record<string, never>;
  snapshot: InventorySnapshot | null;
}

/** Coste amortizado de rebalanceo usado para DECIDIR la última oportunidad (breakdown
 * `rebalance` de /explain, magnitud de un `usd` negativo). Distinto del debitado al ledger. */
export interface DecisionRebalanceCost {
  opportunityId: string;
  usd: number;
}

export interface Pnl {
  realized_pnl: number;
  unrealized_pnl: number;
  total_pnl: number;
  equity_usd: number;
  initial_quote_usd?: number;
  equity_by_venue?: Record<string, number>;
  equity_series: { ts: number; equity: number }[];
  skew: InventorySkew | Record<string, never>;
  rebalance?: RebalanceSummary;
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

export interface SurvivalCalibrationBucket {
  p_low: number;
  p_high: number;
  n: number;
  estimated_mid: number;
  observed_rate: number | null;
  abs_error: number | null;
  confidence: 'low' | 'medium' | 'high';
}

export interface SurvivalCalibration {
  mode: string;
  latency_ms: number;
  n_samples: number;
  n_observed: number;
  n_missing: number;
  confidence: 'low' | 'medium' | 'high';
  buckets: SurvivalCalibrationBucket[];
  observations: {
    opportunity_id: string;
    latency_ms: number;
    observed: boolean | null;
    future_net_usd: number | null;
    reason: string | null;
  }[];
}

/** Naive-vs-edge: contraste agregado de sesión (GET /api/v1/analysis/naive-vs-edge).
 * Lo que un detector de spreads ingenuo contaría como bruto vs el neto que el motor captura. */
export interface RejectionBucket {
  reason: string;
  label: string;
  count: number;
  lost_gross_usd: number;
}

export interface NaiveVsEdgeReport {
  sample_size: number;
  naive_trades: number;
  naive_gross_usd: number;
  naive_gross_per_btc: number | null;
  engine_trades: number;
  engine_net_usd: number;
  engine_net_per_btc: number | null;
  naive_q_btc: number;
  engine_q_btc: number;
  overstatement_usd: number;
  survival_rate: number | null;
  rejections: RejectionBucket[];
  dominant_rejection: string | null;
  headline: string;
}

/** Evidencia de ganancias: spreads capturados rentables (GET /api/v1/analysis/wins). */
export interface Win {
  id: string;
  created_at: number;
  buy_venue: string;
  sell_venue: string;
  q_target: number;
  net_usd: number;
  net_per_btc: number | null;
}

export interface WinsReport {
  wins: Win[];
  count: number;
  total_net_usd: number;
  best_net_per_btc: number | null;
}

export interface StrategyLabParams {
  size_btc: number;
  fee_bps: number;
  latency_ms: number;
  max_slippage: number;
  expected_trades_per_rebalance: number;
  n_paths: number;
}

export const DEFAULT_STRATEGY_PARAMS: StrategyLabParams = {
  size_btc: 1,
  fee_bps: 10,
  latency_ms: 150,
  max_slippage: 0.001,
  expected_trades_per_rebalance: 1,
  n_paths: 2000,
};

/** Estadística acumulada por ruta (buy→sell) durante toda la sesión, no solo el buffer. */
export interface RouteStat {
  route: string;
  buy_venue: string;
  sell_venue: string;
  lastOpportunityId: string | null;
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
// Watchdog de staleness: si el socket está abierto pero no llega NINGÚN evento en este
// intervalo, "EN VIVO" estaría mintiendo → status pasa a `stale` hasta el siguiente evento.
const STALE_AFTER_MS = 10_000;
const STALE_CHECK_MS = 2_000;
const BALANCES_REQUEST_WINDOW_MS = 15_000;
const BALANCES_MAX_REQUESTS_PER_WINDOW = 4;

/** Fetches con estado de error visible en UI (para distinguir "cargando" de "falló"). */
export type FetchErrorKey = 'validation' | 'projection' | 'capacity' | 'forward' | 'survival';
export type FetchErrors = Record<FetchErrorKey, boolean>;
const NO_ERRORS: FetchErrors = {
  validation: false,
  projection: false,
  capacity: false,
  forward: false,
  survival: false,
};

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

function projectionUrl(params: StrategyLabParams): string {
  return `${API_BASE}/api/v1/projection?mode=live&latency_ms=${params.latency_ms}`;
}

function capacityUrl(params: StrategyLabParams): string {
  return `${API_BASE}/api/v1/capacity?mode=live&fee_bps=${params.fee_bps}`;
}

function forwardUrl(params: StrategyLabParams): string {
  return `${API_BASE}/api/v1/forward?n_paths=${params.n_paths}`;
}

function survivalUrl(params: StrategyLabParams): string {
  return `${API_BASE}/api/v1/calibration/survival?latency_ms=${params.latency_ms}`;
}

/**
 * Suscripción SSE al backend (C18). Patrón buffer-ref + requestAnimationFrame:
 * los eventos se acumulan en refs y se vuelcan a estado a lo sumo una vez por
 * frame (~60 fps), evitando re-renders por tick y manteniendo la UI fluida.
 *
 * STORY-023: además de quotes/opportunities, consume los eventos `metrics`, `breaker`
 * y `demo` (C13/C8/C16) y hace polling de `/pnl` (equity curve) cada 2 s.
 */
export function useStream(strategyParams: StrategyLabParams = DEFAULT_STRATEGY_PARAMS) {
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
  const [survival, setSurvival] = useState<SurvivalCalibration | null>(null);
  const [naiveVsEdge, setNaiveVsEdge] = useState<NaiveVsEdgeReport | null>(null);
  const [wins, setWins] = useState<WinsReport | null>(null);
  const [errors, setErrors] = useState<FetchErrors>(NO_ERRORS);
  // Inventario (PRD-012): /balances con frescura y retry propios. Un fallo conserva el
  // último snapshot exitoso (el panel lo marca "desactualizado"); un éxito limpia el error.
  const [balances, setBalances] = useState<BalancesResponse | null>(null);
  const [balancesLoading, setBalancesLoading] = useState(true);
  const [balancesError, setBalancesError] = useState(false);
  const [balancesUpdatedAt, setBalancesUpdatedAt] = useState<number | null>(null);
  const [decisionCost, setDecisionCost] = useState<DecisionRebalanceCost | null>(null);
  // PRD-013: snapshot inmutable de la ventana de observación jury para la UI.
  const [scenarioWindow, setScenarioWindow] = useState<ScenarioObservationWindow | null>(null);

  const quotesBuf = useRef<Record<string, Quote>>({});
  const oppsBuf = useRef<Opportunity[]>([]);
  const routeStatsRef = useRef<Map<string, RouteStat>>(new Map());
  const detectedRef = useRef(0);
  const metricsBuf = useRef<Metrics | null>(null);
  // Flags de "sucio" POR SLICE: un tick de quote (10/s) no debe re-renderizar opps/routeStats
  // (que clona todo el Map) ni metrics. Cada rAF vuelca sólo lo que cambió.
  const dirtyQuotes = useRef(false);
  const dirtyOpps = useRef(false);
  const dirtyMetrics = useRef(false);
  // PRD-013: dueño ÚNICO del estado de la ventana (identidad, baseline, deltas, directos).
  const scenarioWinRef = useRef<ScenarioObservationWindow | null>(null);
  const dirtyScenario = useRef(false);
  // Tras un corte SSE no se acepta evidencia hasta confirmar por /demo (o SSE demo) qué
  // run_id sigue vigente; durante el hueco pudo ocurrir una o varias transiciones.
  const scenarioNeedsDemoResync = useRef(false);
  // Espejo del último BreakerStatus para sembrar la muestra "vigente" de stale_feed.
  const breakersRef = useRef<BreakerStatus>(EMPTY_BREAKERS);
  // Params actuales accesibles desde closures estables (retryHeavy) sin recrear el SSE.
  const paramsRef = useRef(strategyParams);
  paramsRef.current = strategyParams;
  // Timestamp del último evento SSE recibido (watchdog de staleness).
  const lastEventRef = useRef(Date.now());
  // AbortController vigente de los fetch pesados (para que retryHeavy comparta su señal).
  const heavyAcRef = useRef<AbortController | null>(null);
  // AbortController del ciclo ligero (para que retryBalances comparta su señal).
  const lightAcRef = useRef<AbortController | null>(null);
  // Request vigente de /balances. Guardar su identidad evita que el `finally` de un request
  // abortado por StrictMode/cleanup libere por error un request del ciclo siguiente.
  const balancesRequestRef = useRef<{
    signal: AbortSignal;
    start: { startedAt: number };
  } | null>(null);
  // Incluye polling y retry en el mismo límite: ningún camino de UI puede saltarse el cap.
  const balancesRequestStartsRef = useRef<{ startedAt: number }[]>([]);
  // Última oportunidad ya consultada en /explain (coste de decisión): no reconsultar el mismo ID.
  const lastExplainedIdRef = useRef<string | null>(null);

  const markError = useCallback((key: FetchErrorKey, value: boolean) => {
    setErrors((prev) => (prev[key] === value ? prev : { ...prev, [key]: value }));
  }, []);

  /** Reconciliación + invariantes: determinista → una vez al montar; reintentable desde la UI. */
  const retryValidation = useCallback(() => {
    fetchJson<ValidationReport>(`${API_BASE}/api/v1/validation`)
      .then((v) => { setValidation(v); markError('validation', false); })
      .catch(() => markError('validation', true));
  }, [markError]);

  /** /balances (PRD-012): dentro del ciclo ligero de 5 s, sin intervalo propio. Reintentable
   * desde la UI (`retryBalances`); guard de in-flight para no solapar requests. */
  const pullBalances = useCallback((isRetry = false) => {
    const active = balancesRequestRef.current;
    if (active && !active.signal.aborted) return;

    const signal = lightAcRef.current?.signal;
    if (!signal || signal.aborted) return;

    const startedAt = Date.now();
    const recentStarts = balancesRequestStartsRef.current.filter(
      (start) => startedAt - start.startedAt < BALANCES_REQUEST_WINDOW_MS,
    );
    if (recentStarts.length >= BALANCES_MAX_REQUESTS_PER_WINDOW) {
      balancesRequestStartsRef.current = recentStarts;
      return;
    }
    const start = { startedAt };
    balancesRequestStartsRef.current = [...recentStarts, start];
    const request = { signal, start };
    balancesRequestRef.current = request;
    if (isRetry) {
      setBalancesError(false);
      setBalancesLoading(true);
    }

    fetchJson<BalancesResponse>(`${API_BASE}/api/v1/balances`, { signal })
      .then((b) => {
        setBalances(b);
        setBalancesError(false);
        setBalancesUpdatedAt(Date.now());
      })
      .catch(() => {
        // Abort al desmontar no es un error de datos; un fallo real conserva el último
        // snapshot (el panel lo marca "DATOS DESACTUALIZADOS" con su hora).
        if (!signal.aborted) {
          setBalancesError(true);
        } else {
          // Un montaje abortado no debe consumir cuota del montaje que lo reemplaza.
          balancesRequestStartsRef.current = balancesRequestStartsRef.current.filter(
            (entry) => entry !== start,
          );
        }
      })
      .finally(() => {
        if (balancesRequestRef.current === request) {
          balancesRequestRef.current = null;
          if (!signal.aborted) setBalancesLoading(false);
        }
      });
  }, []);

  const retryBalances = useCallback(() => pullBalances(true), [pullBalances]);

  /** Fetch pesados (numpy/Monte Carlo): projection/capacity/forward/survival. Los únicos que
   * dependen de los params del Strategy Lab — se relanzan al cambiarlos SIN tocar el SSE. */
  const pullHeavy = useCallback((params: StrategyLabParams, signal: AbortSignal) => {
    const opt = { signal };
    const track = <T,>(key: FetchErrorKey, promise: Promise<T>, set: (d: T) => void) => {
      promise
        .then((d) => { set(d); markError(key, false); })
        .catch(() => { if (!signal.aborted) markError(key, true); });
    };
    track('projection', fetchJson<EdgeFrontier>(projectionUrl(params), opt), setProjection);
    track('capacity', fetchJson<EdgeCapacity>(capacityUrl(params), opt), setCapacity);
    track('forward', fetchJson<ForwardProjection>(forwardUrl(params), opt), setForward);
    track('survival', fetchJson<SurvivalCalibration>(survivalUrl(params), opt), setSurvival);
  }, [markError]);

  const retryHeavy = useCallback(() => {
    const signal = heavyAcRef.current?.signal ?? new AbortController().signal;
    pullHeavy(paramsRef.current, signal);
  }, [pullHeavy]);

  // Ciclo de vida del SSE + polling ligero: SIN dependencias de los params de estrategia.
  // Cambiar el Strategy Lab NO debe cerrar/reabrir el EventSource (parpadeo de status) ni
  // re-pedir los snapshots deterministas.
  useEffect(() => {
    // Snapshot inicial (estado antes del primer evento).
    fetchJson<{ quotes?: Quote[] }>(`${API_BASE}/api/v1/quotes`)
      .then((d) => {
        for (const q of Array.isArray(d.quotes) ? d.quotes : []) quotesBuf.current[q.exchange] = q;
        dirtyQuotes.current = true;
      })
      .catch(() => undefined);
    fetchJson<Metrics>(`${API_BASE}/api/v1/metrics`)
      .then((m) => { metricsBuf.current = m; dirtyMetrics.current = true; })
      .catch(() => undefined);
    // Reconciliación + invariantes: determinista → una sola vez. Las 4 proyecciones
    // (projection/capacity/forward/survival) las dispara el effect de params (pullHeavy).
    retryValidation();

    // PRD-013: el run_id llega por DOS transportes (evento SSE `demo` — sólo al cambiar —
    // y el poll backstop de GET /demo); la ventana se abre con el primer valor nuevo que se
    // vea, venga por donde venga. Ambos pasan por status() → valores idénticos.
    const applyDemo = (d: DemoStatus) => {
      setDemo(d);
      const w = scenarioWinRef.current;
      if (!d.active || d.mode !== 'jury' || d.scenario_run_id == null) {
        // Salir de jury / demo inactiva → la ventana y su evidencia se invalidan.
        if (w != null) {
          scenarioWinRef.current = null;
          dirtyScenario.current = true;
        }
        scenarioNeedsDemoResync.current = false;
        return;
      }
      if (
        w == null
        || w.runId !== d.scenario_run_id
        || w.backendStartedAt !== (d.scenario_started_at ?? null)
      ) {
        // started_at distingue también un proceso nuevo cuyo primer run_id=0 coincide por
        // casualidad con el 0 que el cliente ya tenía antes de la reconexión.
        scenarioWinRef.current = newScenarioWindow(d, breakersRef.current);
        dirtyScenario.current = true;
      }
      scenarioNeedsDemoResync.current = false;
    };
    const applyBreakers = (b: BreakerStatus) => {
      breakersRef.current = b;
      setBreakers(b);
      const w = scenarioWinRef.current;
      if (w && applyBreakersToScenarioWindow(w, b)) dirtyScenario.current = true;
    };

    const ac = new AbortController();
    // Evita que una respuesta de poll iniciada antes de un evento SSE más nuevo haga
    // retroceder el run_id. Varias llamadas concurrentes conservan sólo la última.
    let demoRevision = 0;
    let demoRequestSeq = 0;
    const resyncDemo = () => {
      const requestSeq = ++demoRequestSeq;
      const revision = demoRevision;
      fetchJson<DemoStatus>(`${API_BASE}/api/v1/demo`, { signal: ac.signal })
        .then((d) => {
          if (requestSeq === demoRequestSeq && revision === demoRevision) applyDemo(d);
        })
        .catch(() => undefined);
    };
    const es = new EventSource(`${API_BASE}/api/v1/stream`);
    // Cada evento recibido "toca" el watchdog; si estábamos en `stale`, volvemos a `live`.
    const touch = () => {
      lastEventRef.current = Date.now();
      setStatus((s) => (s === 'stale' ? 'live' : s));
    };
    es.onopen = () => {
      lastEventRef.current = Date.now();
      setStatus('live');
      // También en reconexión: no esperar hasta 5 s (un escenario dura 2.25 s).
      resyncDemo();
    };
    // EventSource reintenta solo; reflejamos "reconnecting" sólo si la conexión se cerró.
    es.onerror = () => {
      if (es.readyState !== EventSource.OPEN) {
        setStatus('reconnecting');
        scenarioNeedsDemoResync.current = true;
        const w = scenarioWinRef.current;
        if (w) {
          // La identidad puede haber cambiado durante el hueco. El poll abrirá una ventana
          // nueva o confirmará ésta; hasta entonces no se conserva evidencia anterior.
          w.baselineReasons = null;
          w.latestReasons = {};
          w.directReasons = {};
          w.directReasonsSinceBaseline = {};
          w.baselineCaptured = null;
          w.latestCaptured = 0;
          w.postBaselineMetricSamples = 0;
          w.directSamples = 0;
          w.telemetryRestarted = false;
          w.status = 'absent';
          w.detail = 'telemetry_insufficient';
          dirtyScenario.current = true;
        }
      }
    };
    // Watchdog de staleness: socket abierto pero sin eventos >10s ⇒ "EN VIVO" mentiría.
    const watchdog = setInterval(() => {
      if (
        es.readyState === EventSource.OPEN &&
        Date.now() - lastEventRef.current > STALE_AFTER_MS
      ) {
        setStatus('stale');
      }
    }, STALE_CHECK_MS);

    es.addEventListener('quote', (e) => {
      touch();
      const q = parseEvent<Quote>(e);
      if (!q) return;
      quotesBuf.current[q.exchange] = q;
      dirtyQuotes.current = true;
    });

    es.addEventListener('opportunity', (e) => {
      touch();
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
        lastOpportunityId: null,
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
      s.lastOpportunityId = o.id;
      routeStatsRef.current.set(key, s);
      dirtyOpps.current = true;

      // PRD-013: evidencia primaria de la ventana jury (corte por t_recv monotónico).
      const win = scenarioWinRef.current;
      if (
        !scenarioNeedsDemoResync.current
        && win
        && applyOpportunityToScenarioWindow(win, o)
      ) dirtyScenario.current = true;
    });

    es.addEventListener('metrics', (e) => {
      touch();
      const m = parseEvent<Metrics>(e);
      if (!m) return;
      metricsBuf.current = m;
      dirtyMetrics.current = true;
      // PRD-013: baseline (primer snapshot posterior) y delta de la ventana jury.
      const w = scenarioWinRef.current;
      if (!scenarioNeedsDemoResync.current && w) {
        applyMetricsToScenarioWindow(w, m);
        dirtyScenario.current = true;
      }
    });

    // P&L en tiempo real (push tras cada ejecución, throttled). Antes era polling /pnl cada 2s.
    es.addEventListener('pnl', (e) => {
      touch();
      const p = parseEvent<Pnl>(e);
      if (p) setPnl(p);
    });

    // breaker/demo son de baja frecuencia (sólo al cambiar) → setState directo.
    es.addEventListener('breaker', (e) => {
      touch();
      const b = parseEvent<BreakerStatus>(e);
      if (b) applyBreakers(b);
    });
    // `status` refleja SÓLO la conectividad SSE (onopen/onerror); el badge "DEMO DATA" se
    // deriva de `demo.active` en la página (evita que un reconnect pise el estado de demo).
    es.addEventListener('demo', (e) => {
      touch();
      const d = parseEvent<DemoStatus>(e);
      if (d) {
        demoRevision += 1;
        applyDemo(d);
      }
    });

    let raf = 0;
    const tick = () => {
      // Vuelca SÓLO la slice que cambió: evita re-render de opps/routeStats (clon del Map) y
      // metrics cuando sólo llegaron quotes, y viceversa.
      if (dirtyQuotes.current) {
        dirtyQuotes.current = false;
        setQuotes({ ...quotesBuf.current });
      }
      if (dirtyOpps.current) {
        dirtyOpps.current = false;
        setOpportunities([...oppsBuf.current]);
        setDetectedCount(detectedRef.current);
        setRouteStats(Array.from(routeStatsRef.current.values()).map((s) => ({ ...s })));
      }
      if (dirtyMetrics.current) {
        dirtyMetrics.current = false;
        if (metricsBuf.current) setMetrics(metricsBuf.current);
      }
      if (dirtyScenario.current) {
        dirtyScenario.current = false;
        const w = scenarioWinRef.current;
        setScenarioWindow(w ? snapshotScenarioWindow(w) : null);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);

    // Estado inicial de breakers/demo (sin esperar al primer cambio) + polling de P&L.
    // AbortController: cancela los fetch en vuelo al desmontar (evita setState huérfano,
    // relevante bajo StrictMode que monta→desmonta→monta).
    // P&L, breakers y demo llegan por SSE (push). Este pull es sólo BACKSTOP de baja
    // frecuencia: estado inicial antes del primer evento + resync si se perdió un push.
    const pullLight = () => {
      const opt = { signal: ac.signal };
      fetchJson<Pnl>(`${API_BASE}/api/v1/pnl`, opt).then(setPnl).catch(() => undefined);
      fetchJson<BreakerStatus>(`${API_BASE}/api/v1/control/status`, opt).then(applyBreakers).catch(() => undefined);
      resyncDemo();
      // Agregado de sesión: barato (suma sobre recent_opps) → con el poll ligero de 5s.
      fetchJson<NaiveVsEdgeReport>(`${API_BASE}/api/v1/analysis/naive-vs-edge`, opt)
        .then(setNaiveVsEdge)
        .catch(() => undefined);
      fetchJson<WinsReport>(`${API_BASE}/api/v1/analysis/wins?limit=50`, opt)
        .then(setWins)
        .catch(() => undefined);
      // Inventario (PRD-012): /balances comparte este ciclo (sin segundo intervalo).
      pullBalances();
      // Coste amortizado de decisión: a lo sumo UNA consulta /explain por ciclo, sólo si la
      // oportunidad más reciente cambió. `usd` real es `number | null`: sólo un número finito
      // produce dato (magnitud: en el waterfall es una resta); lo demás deja el valor previo
      // (etiquetado con SU id) o "—" si nunca hubo.
      const lastOppId = oppsBuf.current[0]?.id;
      if (lastOppId && lastOppId !== lastExplainedIdRef.current) {
        lastExplainedIdRef.current = lastOppId;
        fetchJson<OpportunityExplanation>(
          `${API_BASE}/api/v1/opportunities/${lastOppId}/explain`, opt,
        )
          .then((ex) => {
            const comp = Array.isArray(ex.breakdown)
              ? ex.breakdown.find((c) => c.key === 'rebalance')
              : undefined;
            if (comp && typeof comp.usd === 'number' && Number.isFinite(comp.usd)) {
              setDecisionCost({ opportunityId: lastOppId, usd: Math.abs(comp.usd) });
            }
          })
          .catch(() => undefined); // 404/409/parcial → sin dato nuevo, nunca 0
      }
    };
    lightAcRef.current = ac;
    pullLight();
    const pollLight = setInterval(pullLight, 5000);

    return () => {
      if (lightAcRef.current === ac) lightAcRef.current = null;
      ac.abort();
      es.close();
      cancelAnimationFrame(raf);
      clearInterval(pollLight);
      clearInterval(watchdog);
      // PRD-013: desmontar el hook borra la ventana (nunca sobrevive evidencia huérfana).
      scenarioWinRef.current = null;
      scenarioNeedsDemoResync.current = false;
    };
  }, [retryValidation, pullBalances]);

  // Proyección viva (fetch pesados): la frontier/capacity dependen del book actual (el backend
  // cae a demo sin ruta viva); forward re-muestrea la grabación. Cómputo numpy/Monte Carlo
  // pesado ⇒ refresco espaciado (no a 5s) para no saturar el único worker del backend en
  // 2 cores. Este effect SÍ depende de los params del Strategy Lab: al aplicarlos se relanzan
  // sólo estos 4 fetch — el SSE del effect anterior no se toca. AbortController propio:
  // cancela los fetch en vuelo al cambiar params o desmontar (patrón seguro bajo StrictMode).
  useEffect(() => {
    const ac = new AbortController();
    heavyAcRef.current = ac;
    const params = paramsRef.current;
    pullHeavy(params, ac.signal);
    const pollHeavy = setInterval(() => pullHeavy(params, ac.signal), 30000);
    return () => {
      ac.abort();
      clearInterval(pollHeavy);
      if (heavyAcRef.current === ac) heavyAcRef.current = null;
    };
    // Depende de los 6 valores primitivos (no del objeto) para no refetchear por identidad.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    pullHeavy,
    strategyParams.fee_bps,
    strategyParams.latency_ms,
    strategyParams.n_paths,
    strategyParams.size_btc,
    strategyParams.max_slippage,
    strategyParams.expected_trades_per_rebalance,
  ]);

  return {
    status, quotes, opportunities, routeStats, detectedCount,
    metrics, breakers, demo, pnl, validation, projection, capacity, forward, survival, naiveVsEdge,
    wins, errors, retryValidation, retryHeavy,
    balances, balancesLoading, balancesError, balancesUpdatedAt,
    retryBalances, decisionCost, scenarioWindow,
  };
}
