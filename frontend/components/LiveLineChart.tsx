'use client';

import { useEffect, useRef } from 'react';
import {
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from 'lightweight-charts';
import { Card, Group, Text, Title } from '@mantine/core';

const POS = '#2fd98c';
const NEG = '#f6678a';

/** Convierte un hex (#rrggbb) a rgba con alpha (para el relleno de área). */
function rgba(hex: string, a: number): string {
  const h = hex.replace('#', '');
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${a})`;
}

/**
 * Línea temporal en vivo con lightweight-charts (C18). Patrón INCREMENTAL: el chart/series
 * se crean UNA vez (mount); cada valor nuevo entra por `series.update()` (no `setData`
 * completo), barato y fluido. El tiempo se fuerza estrictamente creciente (sub-segundo
 * monotónico) para cumplir el contrato de lightweight-charts. Serie de ÁREA con relleno
 * degradado para un acabado más premium.
 */
export function LiveLineChart({
  title,
  value,
  color = '#16d67f',
  suffix = '',
  precision = 2,
  zeroLine = false,
  baseline = false,
  hint,
}: {
  title: string;
  value: number | null;
  color?: string;
  suffix?: string;
  precision?: number;
  zeroLine?: boolean;
  /** Serie BASELINE: colorea verde por encima de 0 y rojo por debajo (ideal para P&L). */
  baseline?: boolean;
  hint?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Area'> | ISeriesApi<'Baseline'> | null>(null);
  const lastTimeRef = useRef(0);

  // Crea el chart una sola vez.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const chart = createChart(el, {
      height: 188,
      layout: {
        background: { color: 'transparent' },
        textColor: '#8995ac',
        fontFamily: 'var(--font-mono), ui-monospace, SFMono-Regular, Menlo, monospace',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(255,255,255,0.03)' },
        horzLines: { color: 'rgba(255,255,255,0.05)' },
      },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.06)' },
      timeScale: {
        borderColor: 'rgba(255,255,255,0.06)',
        timeVisible: true,
        secondsVisible: true,
      },
      crosshair: {
        vertLine: { color: 'rgba(255,255,255,0.15)', labelBackgroundColor: '#19212d' },
        horzLine: { color: 'rgba(255,255,255,0.15)', labelBackgroundColor: '#19212d' },
      },
      handleScroll: false,
      handleScale: false,
    });
    const priceFormat = { type: 'price' as const, precision, minMove: 1 / 10 ** precision };
    const series: ISeriesApi<'Area'> | ISeriesApi<'Baseline'> = baseline
      ? chart.addBaselineSeries({
          baseValue: { type: 'price', price: 0 },
          topLineColor: POS,
          topFillColor1: rgba(POS, 0.28),
          topFillColor2: rgba(POS, 0.0),
          bottomLineColor: NEG,
          bottomFillColor1: rgba(NEG, 0.0),
          bottomFillColor2: rgba(NEG, 0.28),
          lineWidth: 2,
          priceLineVisible: false,
          priceFormat,
        })
      : chart.addAreaSeries({
          lineColor: color,
          topColor: rgba(color, 0.28),
          bottomColor: rgba(color, 0.0),
          lineWidth: 2,
          priceLineVisible: false,
          crosshairMarkerBackgroundColor: color,
          priceFormat,
        });
    if (zeroLine) {
      series.createPriceLine({
        price: 0,
        color: 'rgba(255,255,255,0.22)',
        lineWidth: 1,
        lineStyle: 2,
        axisLabelVisible: false,
        title: '',
      });
    }
    chartRef.current = chart;
    seriesRef.current = series;
    // Semilla del valor actual al (re)crear la serie — cubre el remount de StrictMode y el
    // caso de un valor estable que no vuelve a disparar el effect de push.
    if (value != null && Number.isFinite(value)) {
      lastTimeRef.current = Math.floor(Date.now() / 1000);
      series.update({ time: lastTimeRef.current as UTCTimestamp, value });
    }

    const ro = new ResizeObserver(() => chart.applyOptions({ width: el.clientWidth }));
    ro.observe(el);
    chart.applyOptions({ width: el.clientWidth });

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Empuja cada valor nuevo de forma incremental.
  useEffect(() => {
    if (value == null || !Number.isFinite(value) || !seriesRef.current) return;
    let t = Math.floor(Date.now() / 1000);
    if (t <= lastTimeRef.current) t = lastTimeRef.current + 1; // estrictamente creciente
    lastTimeRef.current = t;
    seriesRef.current.update({ time: t as UTCTimestamp, value });
  }, [value]);

  return (
    <Card h="100%" p="md">
      <Group justify="space-between" mb="xs" align="center">
        <Title order={6} fz="sm">
          {title}
        </Title>
        <Text
          ff="monospace"
          className="mono-nums"
          size="sm"
          fw={700}
          c={value != null && value < 0 ? 'var(--neg)' : color}
        >
          {value != null && Number.isFinite(value)
            ? `${value.toLocaleString('en-US', { minimumFractionDigits: precision, maximumFractionDigits: precision })}${suffix}`
            : '—'}
        </Text>
      </Group>
      <div ref={containerRef} style={{ width: '100%' }} />
      {hint && (
        <Text size="xs" c="dimmed" mt={6}>
          {hint}
        </Text>
      )}
    </Card>
  );
}
