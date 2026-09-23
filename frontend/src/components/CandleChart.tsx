import { useEffect, useRef, useState } from "react";
import {
  CandlestickSeries, HistogramSeries, LineSeries, LineStyle, createChart, type Time,
} from "lightweight-charts";
import { cssVar, useTheme } from "../theme";
import type { Candle, Point } from "../types";
import { chartBaseOptions } from "./TimeChart";
import { price } from "../format";

interface Props {
  candles: Candle[];
  sma50: Point[];
  sma200: Point[];
  rsi: Point[];
  height?: number;
}

interface Readout { time: string; o: number; h: number; l: number; c: number; v: number; rsi?: number }

export function CandleChart({ candles, sma50, sma200, rsi, height = 520 }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const { theme } = useTheme();
  const [readout, setReadout] = useState<Readout | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || !candles.length) return;
    const up = cssVar("--up");
    const down = cssVar("--down");
    const chart = createChart(el, { ...chartBaseOptions(height) });

    const cs = chart.addSeries(CandlestickSeries, {
      upColor: up, downColor: down, borderUpColor: up, borderDownColor: down,
      wickUpColor: up, wickDownColor: down, priceLineVisible: false,
    });
    cs.setData(candles.map((c) => ({ ...c, time: c.time as Time })));

    const line = (data: Point[], colorVar: string, pane = 0) => {
      const s = chart.addSeries(LineSeries, {
        color: cssVar(colorVar), lineWidth: 2, priceLineVisible: false, lastValueVisible: false,
        crosshairMarkerVisible: false,
      }, pane);
      s.setData(data.map((p) => ({ time: p.time as Time, value: p.value })));
      return s;
    };
    line(sma50, "--series-2");
    line(sma200, "--series-3");

    const vol = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" }, priceScaleId: "vol", lastValueVisible: false, priceLineVisible: false,
    });
    vol.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    vol.setData(candles.map((c) => ({
      time: c.time as Time, value: c.volume, color: `${c.close >= c.open ? up : down}55`,
    })));

    const rsiSeries = line(rsi, "--series-1", 1);
    rsiSeries.applyOptions({ lastValueVisible: true });
    for (const lvl of [30, 70]) {
      rsiSeries.createPriceLine({ price: lvl, color: cssVar("--axis"), lineStyle: LineStyle.Solid, lineWidth: 1, axisLabelVisible: false, title: "" });
    }
    const panes = chart.panes();
    if (panes[1]) panes[1].setHeight(Math.round(height * 0.2));
    chart.timeScale().fitContent();

    const byTime = new Map(candles.map((c) => [c.time, c]));
    const rsiByTime = new Map(rsi.map((p) => [p.time, p.value]));
    const last = candles[candles.length - 1];
    const show = (t: string) => {
      const c = byTime.get(t);
      if (c) setReadout({ time: t, o: c.open, h: c.high, l: c.low, c: c.close, v: c.volume, rsi: rsiByTime.get(t) });
    };
    show(last.time);
    chart.subscribeCrosshairMove((p) => show(p.time ? String(p.time) : last.time));
    return () => chart.remove();
  }, [candles, sma50, sma200, rsi, height, theme]);

  return (
    <div>
      <div className="legend" style={{ marginBottom: 8, fontVariantNumeric: "tabular-nums" }}>
        {readout && (
          <span className="muted">
            {readout.time} &nbsp;O <b>{price(readout.o)}</b> H <b>{price(readout.h)}</b> L <b>{price(readout.l)}</b> C{" "}
            <b className={readout.c >= readout.o ? "up" : "down"}>{price(readout.c)}</b>
            {readout.rsi !== undefined && <> &nbsp;RSI <b>{readout.rsi.toFixed(1)}</b></>}
          </span>
        )}
        <span style={{ marginLeft: "auto" }}><span className="sw" style={{ background: "var(--series-2)" }} />SMA 50</span>
        <span><span className="sw" style={{ background: "var(--series-3)" }} />SMA 200</span>
        <span><span className="sw" style={{ background: "var(--series-1)" }} />RSI 14 (lower pane)</span>
      </div>
      <div ref={ref} style={{ height, position: "relative" }} />
    </div>
  );
}
