import { useEffect, useRef, useState } from "react";
import {
  CandlestickSeries, HistogramSeries, LineSeries, LineStyle, createChart, createSeriesMarkers,
  type SeriesMarker, type Time, type UTCTimestamp,
} from "lightweight-charts";
import { cssVar, useTheme } from "../theme";
import type { DaytradeResponse, TimePoint } from "../types";
import { chartBaseOptions } from "./TimeChart";
import { price } from "../format";

interface Props { data: DaytradeResponse; height?: number; showBands: boolean; showPivots: boolean }

export function IntradayChart({ data, height = 540, showBands, showPivots }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const { theme } = useTheme();
  const [readout, setReadout] = useState<string>("");

  useEffect(() => {
    const el = ref.current;
    if (!el || !data.candles.length) return;
    const up = cssVar("--up");
    const down = cssVar("--down");
    const base = chartBaseOptions(height);
    const chart = createChart(el, { ...base, timeScale: { ...base.timeScale, timeVisible: true, secondsVisible: false } });

    const cs = chart.addSeries(CandlestickSeries, {
      upColor: up, downColor: down, borderUpColor: up, borderDownColor: down, wickUpColor: up, wickDownColor: down,
      priceLineVisible: true,
    });
    cs.setData(data.candles.map((c) => ({ ...c, time: c.time as UTCTimestamp })));

    const line = (pts: TimePoint[], colorVar: string, width: 1 | 2 = 2, pane = 0, dotted = false) => {
      const s = chart.addSeries(LineSeries, {
        color: cssVar(colorVar), lineWidth: width, priceLineVisible: false, lastValueVisible: false,
        crosshairMarkerVisible: false, lineStyle: dotted ? LineStyle.Dotted : LineStyle.Solid,
      }, pane);
      s.setData(pts.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })));
      return s;
    };
    const o = data.overlays;
    line(o.vwap, "--series-1", 2);
    if (showBands) {
      for (const k of ["vwap_u1", "vwap_l1", "vwap_u2", "vwap_l2"] as const) line(o[k], "--muted", 1, 0, true);
    }
    line(o.ema9, "--series-2", 1);
    line(o.ema21, "--series-3", 1);

    const L = data.levels;
    const level = (p: number | null, title: string, colorVar: string) => {
      if (p == null) return;
      cs.createPriceLine({ price: p, color: cssVar(colorVar), lineWidth: 1, lineStyle: LineStyle.Solid, axisLabelVisible: true, title });
    };
    level(L.opening_range_high, "OR high", "--axis");
    level(L.opening_range_low, "OR low", "--axis");
    level(L.prev_close, "Prev close", "--muted");
    if (showPivots) for (const [k, v] of Object.entries(L.pivots)) level(v, k, "--grid");

    createSeriesMarkers(cs, data.signals
      .filter((s) => s.kind !== "rsi")
      .map((s): SeriesMarker<Time> => ({
        time: s.time as UTCTimestamp,
        position: s.direction === "long" ? "belowBar" : "aboveBar",
        shape: s.direction === "long" ? "arrowUp" : "arrowDown",
        color: s.direction === "long" ? up : down,
        text: s.kind.toUpperCase(),
      }))
      .sort((a, b) => (a.time as number) - (b.time as number)));

    const vol = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "vol", lastValueVisible: false, priceLineVisible: false });
    vol.priceScale().applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
    vol.setData(data.candles.map((c) => ({ time: c.time as UTCTimestamp, value: c.volume, color: `${c.close >= c.open ? up : down}50` })));

    const rsi = line(o.rsi, "--series-1", 1, 1);
    rsi.applyOptions({ lastValueVisible: true });
    for (const lvl of [30, 70]) rsi.createPriceLine({ price: lvl, color: cssVar("--axis"), lineWidth: 1, lineStyle: LineStyle.Solid, axisLabelVisible: false, title: "" });
    chart.panes()[1]?.setHeight(Math.round(height * 0.18));

    // Default view: the latest session.
    const sessionStart = data.candles.findIndex((c) => new Date(c.time * 1000).toISOString().slice(0, 10) === data.session);
    if (sessionStart > 0) chart.timeScale().setVisibleLogicalRange({ from: sessionStart - 5, to: data.candles.length + 3 });
    else chart.timeScale().fitContent();

    const byTime = new Map(data.candles.map((c) => [c.time, c]));
    const vwapBy = new Map(o.vwap.map((p) => [p.time, p.value]));
    chart.subscribeCrosshairMove((p) => {
      const c = p.time ? byTime.get(p.time as number) : data.candles[data.candles.length - 1];
      if (!c) return;
      const t = new Date(c.time * 1000).toISOString();
      setReadout(`${t.slice(5, 10)} ${t.slice(11, 16)}  O ${price(c.open)}  H ${price(c.high)}  L ${price(c.low)}  C ${price(c.close)}  VWAP ${price(vwapBy.get(c.time))}`);
    });
    const last = data.candles[data.candles.length - 1];
    const t = new Date(last.time * 1000).toISOString();
    setReadout(`${t.slice(5, 10)} ${t.slice(11, 16)}  O ${price(last.open)}  H ${price(last.high)}  L ${price(last.low)}  C ${price(last.close)}  VWAP ${price(vwapBy.get(last.time))}`);
    return () => chart.remove();
  }, [data, height, theme, showBands, showPivots]);

  return (
    <div>
      <div className="legend" style={{ marginBottom: 8, fontVariantNumeric: "tabular-nums" }}>
        <span className="muted" style={{ fontFamily: "var(--mono)", fontSize: 11.5 }}>{readout}</span>
        <span style={{ marginLeft: "auto" }}><span className="sw" style={{ background: "var(--series-1)" }} />VWAP</span>
        <span><span className="sw" style={{ background: "var(--series-2)" }} />EMA 9</span>
        <span><span className="sw" style={{ background: "var(--series-3)" }} />EMA 21</span>
      </div>
      <div ref={ref} style={{ height, position: "relative" }} />
    </div>
  );
}
