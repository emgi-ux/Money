import { useMemo, useState } from "react";
import { api } from "../api";
import { TimeChart, type SeriesSpec } from "../components/TimeChart";
import { Card, Seg, Stat, divergingBg, textOn } from "../components/bits";
import { FACTOR_LABEL, num, pct, signedPct, tone } from "../format";
import { go, useStore } from "../store";
import type { BacktestRequest, BacktestResponse, Stats } from "../types";

const today = new Date();
const iso = (d: Date) => d.toISOString().slice(0, 10);
const tenYearsAgo = new Date(today.getFullYear() - 10, today.getMonth(), today.getDate());
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const ROWS: { k: string; label: string; f: (x: number | null | undefined) => string }[] = [
  { k: "total_return", label: "Total return", f: pct },
  { k: "cagr", label: "CAGR", f: pct },
  { k: "volatility", label: "Volatility", f: pct },
  { k: "sharpe", label: "Sharpe", f: num },
  { k: "sortino", label: "Sortino", f: num },
  { k: "max_drawdown", label: "Max drawdown", f: pct },
  { k: "calmar", label: "Calmar", f: num },
  { k: "var_95", label: "VaR 95% (1d)", f: (x) => pct(x, 2) },
  { k: "cvar_95", label: "CVaR 95% (1d)", f: (x) => pct(x, 2) },
  { k: "best_month", label: "Best month", f: pct },
  { k: "worst_month", label: "Worst month", f: pct },
  { k: "pct_positive_months", label: "% positive months", f: pct },
  { k: "beta", label: "Beta vs benchmark", f: num },
  { k: "alpha", label: "Alpha (ann.)", f: pct },
  { k: "tracking_error", label: "Tracking error", f: pct },
  { k: "information_ratio", label: "Information ratio", f: num },
  { k: "hit_rate_vs_benchmark", label: "Monthly hit rate", f: pct },
  { k: "annual_turnover", label: "Annual turnover", f: (x) => pct(x, 0) },
];

export function Backtest() {
  const { meta, setDraft } = useStore();
  const [req, setReq] = useState<BacktestRequest>({
    start: iso(tenYearsAgo), end: iso(today), weights: { momentum: 70, low_vol: 30 },
    top_n: 20, rebalance: "monthly", weighting: "equal", max_weight: 0.1, cost_bps: 10, sector_neutral: false,
  });
  const [res, setRes] = useState<BacktestResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [log, setLog] = useState(true);
  const [holdIdx, setHoldIdx] = useState(-1);

  const run = () => {
    setLoading(true);
    api.backtest(req)
      .then((r) => { setRes(r); setError(null); setHoldIdx(r.holdings.length - 1); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  const set = <K extends keyof BacktestRequest>(k: K, v: BacktestRequest[K]) => setReq((r) => ({ ...r, [k]: v }));
  const priceFactors = meta?.price_factors ?? ["momentum", "low_vol"];

  const equitySeries: SeriesSpec[] = useMemo(() => res ? [
    { name: "Strategy", colorVar: "--series-1", data: res.equity.strategy },
    { name: "Universe (equal weight)", colorVar: "--series-2", data: res.equity.universe },
    { name: `Benchmark (${meta?.benchmark ?? "SPY"})`, colorVar: "--series-3", data: res.equity.benchmark },
  ] : [], [res, meta]);
  const ddSeries: SeriesSpec[] = useMemo(() => res ? [
    { name: "Strategy", colorVar: "--series-1", data: res.drawdown.strategy, area: true },
    { name: `Benchmark (${meta?.benchmark ?? "SPY"})`, colorVar: "--series-3", data: res.drawdown.benchmark },
  ] : [], [res, meta]);
  const pctFmt = (v: number) => `${(v * 100).toFixed(1)}%`;
  const multFmt = (v: number) => `${v.toFixed(2)}x`;

  const s: Stats | undefined = res?.summary.strategy;
  const holding = res?.holdings[holdIdx];

  return (
    <>
      <div className="page-head">
        <h1>Strategy backtest</h1>
        <span className="sub">Walk-forward · next-day execution · costs on turnover · price factors only</span>
      </div>
      <div className="split">
        <div className="stack sticky">
          <Card title="Strategy">
            <div className="label" style={{ marginBottom: 8 }}>Factor weights</div>
            {priceFactors.map((f) => (
              <div className="slider-row" key={f}>
                <span className="label">{FACTOR_LABEL[f]}</span>
                <input type="range" min={0} max={100} step={5} value={req.weights[f] ?? 0}
                  onChange={(e) => set("weights", { ...req.weights, [f]: Number(e.target.value) })} />
                <span className="v">{req.weights[f] ?? 0}</span>
              </div>
            ))}
            <p className="hint" style={{ marginTop: 4 }}>
              Value, quality and growth need point-in-time fundamentals, which free data feeds don't
              provide, so they're excluded here to avoid look-ahead bias.
            </p>
            <div className="divider" />
            <div className="row">
              <div className="field"><label>Start</label><input type="date" value={req.start} onChange={(e) => set("start", e.target.value)} /></div>
              <div className="field"><label>End</label><input type="date" value={req.end} onChange={(e) => set("end", e.target.value)} /></div>
            </div>
            <div className="row">
              <div className="field"><label>Holdings</label><input type="number" min={1} value={req.top_n} onChange={(e) => set("top_n", Number(e.target.value))} /></div>
              <div className="field"><label>Rebalance</label>
                <select value={req.rebalance} onChange={(e) => set("rebalance", e.target.value as "monthly" | "quarterly")}>
                  <option value="monthly">Monthly</option><option value="quarterly">Quarterly</option>
                </select></div>
            </div>
            <div className="field"><label>Weighting</label>
              <select value={req.weighting} onChange={(e) => set("weighting", e.target.value)}>
                {Object.entries(meta?.weighting_methods ?? { equal: "Equal weight" }).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select></div>
            <div className="row">
              <div className="field"><label>Max weight (%)</label><input type="number" value={Math.round(req.max_weight * 100)} onChange={(e) => set("max_weight", Number(e.target.value) / 100)} /></div>
              <div className="field"><label>Cost (bps)</label><input type="number" value={req.cost_bps} onChange={(e) => set("cost_bps", Number(e.target.value))} /></div>
            </div>
            <label className="check" style={{ marginBottom: 14 }}>
              <input type="checkbox" checked={req.sector_neutral} onChange={(e) => set("sector_neutral", e.target.checked)} />
              Sector-neutral ranking
            </label>
            <button className="btn primary" style={{ width: "100%" }} onClick={run} disabled={loading}>
              {loading ? "Running…" : "Run backtest"}
            </button>
          </Card>
        </div>

        <div className={`stack ${loading && res ? "loading" : ""}`}>
          {error && <div className="error">{error}</div>}
          {!res && !error && (
            <Card><div className="empty">Configure a strategy and run the backtest.</div></Card>
          )}
          {res && s && (
            <>
              <Card pad={false}>
                <div className="stats">
                  <Stat k="CAGR" v={pct(s.cagr)} tone={tone(s.cagr)} s={`bench ${pct(res.summary.benchmark.cagr)}`} />
                  <Stat k="Sharpe" v={num(s.sharpe)} s={`bench ${num(res.summary.benchmark.sharpe)}`} />
                  <Stat k="Max drawdown" v={pct(s.max_drawdown)} s={`bench ${pct(res.summary.benchmark.max_drawdown)}`} />
                  <Stat k="Alpha (ann.)" v={signedPct(s.alpha)} tone={tone(s.alpha)} s={`beta ${num(s.beta)}`} />
                  <Stat k="Info ratio" v={num(s.information_ratio)} s={`TE ${pct(s.tracking_error)}`} />
                  <Stat k="Turnover / yr" v={pct(s.annual_turnover, 0)} s={`${req.cost_bps} bps per trade`} />
                </div>
              </Card>
              <Card title="Growth of $1" right={<Seg value={log ? "log" : "lin"} onChange={(v) => setLog(v === "log")} options={[{ v: "lin", label: "Linear" }, { v: "log", label: "Log" }]} />}>
                <TimeChart series={equitySeries} height={320} format={multFmt} logScale={log} />
              </Card>
              <Card title="Drawdown">
                <TimeChart series={ddSeries} height={180} format={pctFmt} />
              </Card>
              <div className="grid-2">
                <Card pad={false} title="Performance statistics">
                  <table className="data">
                    <thead><tr><th className="l">Metric</th><th>Strategy</th><th>Universe EW</th><th>Benchmark</th></tr></thead>
                    <tbody>
                      {ROWS.map((r) => (
                        <tr key={r.k} style={{ cursor: "default" }}>
                          <td className="l">{r.label}</td>
                          <td><b>{r.f(res.summary.strategy[r.k])}</b></td>
                          <td>{r.f(res.summary.universe[r.k])}</td>
                          <td>{r.f(res.summary.benchmark[r.k])}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </Card>
                <Card pad={false} title="Holdings" right={
                  <>
                    <select value={holdIdx} onChange={(e) => setHoldIdx(Number(e.target.value))} style={{ width: 130 }}>
                      {res.holdings.map((h, i) => <option key={h.date} value={i}>{h.date}</option>)}
                    </select>
                    <button className="btn sm" onClick={() => {
                      if (!holding) return;
                      setDraft(Object.fromEntries(holding.positions.map((p) => [p.ticker, p.weight])));
                      go("portfolio");
                    }}>Analyze →</button>
                  </>}>
                  <div className="table-wrap" style={{ maxHeight: 560 }}>
                    <table className="data">
                      <thead><tr><th className="l">Ticker</th><th>Weight</th><th>Score</th></tr></thead>
                      <tbody>
                        {holding?.positions.map((p) => (
                          <tr key={p.ticker} onClick={() => go(`stock/${p.ticker}`)}>
                            <td className="l"><span className="tkr">{p.ticker}</span></td>
                            <td>{pct(p.weight)}</td>
                            <td>{p.score.toFixed(0)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Card>
              </div>
              <Card title="Monthly returns" sub="blue = gain, red = loss">
                <MonthlyHeatmap monthly={res.monthly} />
              </Card>
            </>
          )}
        </div>
      </div>
    </>
  );
}

function MonthlyHeatmap({ monthly }: { monthly: BacktestResponse["monthly"] }) {
  const years = [...new Set(monthly.map((m) => m.year))].sort();
  const lookup = new Map(monthly.map((m) => [`${m.year}-${m.month}`, m.ret]));
  const max = 0.08;
  return (
    <div style={{ overflowX: "auto" }}>
      <table className="heat">
        <thead>
          <tr><th />{MONTHS.map((m) => <th key={m}>{m}</th>)}<th>Year</th></tr>
        </thead>
        <tbody>
          {years.map((y) => {
            const rets = MONTHS.map((_, i) => lookup.get(`${y}-${i + 1}`));
            const yr = rets.reduce<number>((acc, r) => (r == null ? acc : acc * (1 + r)), 1) - 1;
            return (
              <tr key={y}>
                <th>{y}</th>
                {rets.map((r, i) => (
                  <td key={i} title={r == null ? "" : `${MONTHS[i]} ${y}: ${signedPct(r)}`}
                    style={r == null ? {} : { background: divergingBg(r, max), color: textOn(r, max) }}>
                    {r == null ? "" : (r * 100).toFixed(1)}
                  </td>
                ))}
                <td className="yr" style={{ background: divergingBg(yr, max * 3), color: textOn(yr, max * 3) }}>
                  {(yr * 100).toFixed(1)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
