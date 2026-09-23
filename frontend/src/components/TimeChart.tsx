import { useEffect, useRef, useState } from "react";
import {
  AreaSeries, ColorType, CrosshairMode, LineSeries, LineStyle, createChart,
  type IChartApi, type ISeriesApi, type Time,
} from "lightweight-charts";
import { cssVar, useTheme } from "../theme";
import type { Point } from "../types";

export interface SeriesSpec {
  name: string;
  colorVar: string;          // CSS custom property, e.g. "--series-1"
  data: Point[];
  area?: boolean;            // filled area (used for drawdowns)
  width?: number;
}

interface Props {
  series: SeriesSpec[];
  height?: number;
  format?: (v: number) => string;
  logScale?: boolean;
  showLegend?: boolean;
}

interface TipState { x: number; y: number; time: string; rows: { name: string; color: string; v: number }[] }

/** Browser locale, falling back when it isn't a valid BCP 47 tag (e.g. "en-US@posix"). */
function safeLocale(): string {
  try {
    new Intl.DateTimeFormat(navigator.language);
    return navigator.language;
  } catch {
    return "en-US";
  }
}

export function chartBaseOptions(height: number) {
  return {
    height,
    localization: { locale: safeLocale() },
    autoSize: true,
    layout: {
      background: { type: ColorType.Solid, color: "transparent" },
      textColor: cssVar("--muted"),
      fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif",
      fontSize: 11,
      attributionLogo: false,
    },
    grid: {
      vertLines: { visible: false },
      horzLines: { color: cssVar("--grid"), style: LineStyle.Solid },
    },
    rightPriceScale: { borderColor: cssVar("--axis") },
    timeScale: { borderColor: cssVar("--axis"), timeVisible: false },
    crosshair: {
      mode: CrosshairMode.Magnet,
      vertLine: { color: cssVar("--axis"), style: LineStyle.Solid, labelBackgroundColor: cssVar("--surface-3") },
      horzLine: { color: cssVar("--axis"), style: LineStyle.Solid, labelBackgroundColor: cssVar("--surface-3") },
    },
  } as const;
}

export function TimeChart({ series, height = 300, format = (v) => v.toFixed(2), logScale, showLegend = true }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const { theme } = useTheme();
  const [tip, setTip] = useState<TipState | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const chart: IChartApi = createChart(el, {
      ...chartBaseOptions(height),
      rightPriceScale: { borderColor: cssVar("--axis"), mode: logScale ? 1 : 0 },
      localization: { locale: safeLocale(), priceFormatter: format },
    });
    const handles: { spec: SeriesSpec; color: string; api: ISeriesApi<"Line"> | ISeriesApi<"Area"> }[] = [];
    for (const s of series) {
      const color = cssVar(s.colorVar);
      const common = { priceLineVisible: false, lastValueVisible: true, lineWidth: (s.width ?? 2) as 1 | 2 | 3 | 4 };
      const api = s.area
        ? chart.addSeries(AreaSeries, { ...common, lineColor: color, topColor: `${color}08`, bottomColor: `${color}40`, invertFilledArea: true })
        : chart.addSeries(LineSeries, { ...common, color });
      api.setData(s.data.map((p) => ({ time: p.time as Time, value: p.value })));
      handles.push({ spec: s, color, api });
    }
    chart.timeScale().fitContent();

    chart.subscribeCrosshairMove((param) => {
      if (!param.point || !param.time || param.point.x < 0 || param.point.y < 0) {
        setTip(null);
        return;
      }
      const rows = handles.flatMap((h) => {
        const d = param.seriesData.get(h.api) as { value?: number } | undefined;
        return d?.value === undefined ? [] : [{ name: h.spec.name, color: h.color, v: d.value }];
      });
      const w = el.clientWidth;
      setTip({
        x: param.point.x > w - 190 ? param.point.x - 180 : param.point.x + 14,
        y: Math.max(4, param.point.y - 30),
        time: String(param.time),
        rows,
      });
    });
    return () => chart.remove();
    // Series identity is captured by data refs; re-create on any change.
  }, [series, height, theme, logScale, format]);

  return (
    <div>
      {showLegend && series.length > 1 && (
        <div className="legend" style={{ marginBottom: 8 }}>
          {series.map((s) => (
            <span key={s.name}><span className="sw" style={{ background: `var(${s.colorVar})` }} />{s.name}</span>
          ))}
        </div>
      )}
      <div style={{ position: "relative", height }} ref={ref}>
        {tip && (
          <div className="chart-tip" style={{ left: tip.x, top: tip.y }}>
            <div className="d">{tip.time}</div>
            {tip.rows.map((r) => (
              <div className="r" key={r.name}>
                <span><span className="sw" style={{ display: "inline-block", width: 8, height: 8, borderRadius: 2, background: r.color, marginRight: 6 }} />{r.name}</span>
                <b>{format(r.v)}</b>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
