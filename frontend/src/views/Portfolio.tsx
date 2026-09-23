import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { TimeChart, type SeriesSpec } from "../components/TimeChart";
import { Card, Stat, divergingBg, textOn } from "../components/bits";
import { num, pct, signedPct, tone } from "../format";
import { go, useStore } from "../store";
import type { RiskResponse } from "../types";

interface Row { ticker: string; weight: string }

const toRows = (w: Record<string, number>): Row[] =>
  Object.entries(w).map(([ticker, v]) => ({ ticker, weight: (v * 100).toFixed(1) }));

export function Portfolio() {
  const { meta, draft, setDraft } = useStore();
  const [rows, setRows] = useState<Row[]>(() =>
    Object.keys(draft).length ? toRows(draft) : toRows({ AAPL: 0.25, MSFT: 0.25, JPM: 0.2, JNJ: 0.15, XOM: 0.15 }));
  const [method, setMethod] = useState("risk_parity");
  const [maxW, setMaxW] = useState(15);
  const [lookback, setLookback] = useState(365);
  const [res, setRes] = useState<RiskResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const weights = useMemo(() => {
    const w: Record<string, number> = {};
    for (const r of rows) {
      const t = r.ticker.trim().toUpperCase();
      const v = Number(r.weight);
      if (t && v > 0) w[t] = (w[t] ?? 0) + v / 100;
    }
    return w;
  }, [rows]);
  const total = Object.values(weights).reduce((a, b) => a + b, 0);

  const analyze = (w = weights) => {
    if (!Object.keys(w).length) return;
    setBusy(true);
    setDraft(w);
    api.analyze(w, lookback)
      .then((r) => { setRes(r); setError(null); })
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false));
  };

  // Analyse on first load (e.g. after "Build portfolio" from the screener).
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { analyze(); }, []);

  const optimize = (fromScreen: boolean) => {
    setBusy(true);
    const body = fromScreen
      ? { top_n: Object.keys(weights).length || 15, method, max_weight: maxW / 100 }
      : { tickers: Object.keys(weights), method, max_weight: maxW / 100 };
    api.construct(body)
      .then((r) => { setRows(toRows(r.weights)); analyze(r.weights); })
      .catch((e) => { setError(e.message); setBusy(false); });
  };

  const eqSeries: SeriesSpec[] = useMemo(() => res ? [
    { name: "Portfolio", colorVar: "--series-1", data: res.equity },
    { name: `Benchmark (${meta?.benchmark ?? "SPY"})`, colorVar: "--series-3", data: res.benchmark_equity },
  ] : [], [res, meta]);
  const s = res?.summary;

  return (
    <>
      <div className="page-head">
        <h1>Portfolio &amp; risk</h1>
        <span className="sub">Historical simulation with static weights · Ledoit-Wolf shrinkage covariance</span>
      </div>
      <div className="split">
        <div className="stack sticky">
          <Card title="Holdings" right={<span className={`hint ${Math.abs(total - 1) > 0.001 ? "down" : ""}`}>Σ {pct(total)}</span>}>
            <div className="table-wrap" style={{ maxHeight: 340 }}>
              {rows.map((r, i) => (
                <div className="row" key={i} style={{ marginBottom: 6 }}>
                  <input type="text" value={r.ticker} placeholder="Ticker" style={{ textTransform: "uppercase" }}
                    onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, ticker: e.target.value } : x)))} />
                  <input type="number" value={r.weight} step={0.5}
                    onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, weight: e.target.value } : x)))} />
                  <button className="icon-btn" style={{ flex: "0 0 30px" }} aria-label="Remove"
                    onClick={() => setRows(rows.filter((_, j) => j !== i))}>×</button>
                </div>
              ))}
            </div>
            <div className="row" style={{ marginTop: 8 }}>
              <button className="btn sm" onClick={() => setRows([...rows, { ticker: "", weight: "5" }])}>+ Add</button>
              <button className="btn sm" onClick={() => {
                const n = Object.keys(weights).length;
                setRows(Object.keys(weights).map((t) => ({ ticker: t, weight: (100 / n).toFixed(2) })));
              }}>Equalize</button>
            </div>
            <div className="divider" />
            <div className="field"><label>Lookback</label>
              <select value={lookback} onChange={(e) => setLookback(Number(e.target.value))}>
                <option value={182}>6 months</option><option value={365}>1 year</option>
                <option value={730}>2 years</option><option value={1825}>5 years</option>
              </select></div>
            <button className="btn primary" style={{ width: "100%" }} disabled={busy} onClick={() => analyze()}>
              {busy ? "Working…" : "Analyze risk"}
            </button>
          </Card>
          <Card title="Optimizer">
            <div className="field"><label>Method</label>
              <select value={method} onChange={(e) => setMethod(e.target.value)}>
                {Object.entries(meta?.weighting_methods ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select></div>
            <div className="field"><label>Max position (%)</label>
              <input type="number" value={maxW} onChange={(e) => setMaxW(Number(e.target.value))} /></div>
            <div className="row">
              <button className="btn sm" disabled={busy} onClick={() => optimize(false)}>Reweight these</button>
              <button className="btn sm" disabled={busy} onClick={() => optimize(true)}>Top-ranked stocks</button>
            </div>
          </Card>
        </div>

        <div className={`stack ${busy && res ? "loading" : ""}`}>
          {error && <div className="error">{error}</div>}
          {!res && !error && <Card><div className="empty">Add holdings and analyze.</div></Card>}
          {res && s && (
            <>
              <Card pad={false}>
                <div className="stats">
                  <Stat k="Volatility (ann.)" v={pct(s.volatility)} s={`ex-ante ${pct(s.ex_ante_volatility)}`} />
                  <Stat k="Beta" v={num(s.beta)} s={`corr ${num(s.correlation)}`} />
                  <Stat k="Return (period)" v={signedPct(s.total_return)} tone={tone(s.total_return)} s={`Sharpe ${num(s.sharpe)}`} />
                  <Stat k="Max drawdown" v={pct(s.max_drawdown)} s={`worst week ${pct(s.worst_week)}`} />
                  <Stat k="VaR 95% (1d)" v={pct(s.var_95, 2)} s={`CVaR ${pct(s.cvar_95, 2)}`} />
                  <Stat k="Diversification" v={num(s.diversification_ratio)} s={`effective N ${num(s.effective_n, 1)}`} />
                </div>
              </Card>
              <Card title="Portfolio vs benchmark" sub={`${res.observations} trading days`}>
                <TimeChart series={eqSeries} height={260} format={(v) => `${v.toFixed(3)}x`} />
              </Card>
              <div className="grid-2">
                <Card pad={false} title="Positions" sub="risk contribution = share of portfolio variance">
                  <div className="table-wrap" style={{ maxHeight: 460 }}>
                    <table className="data">
                      <thead><tr><th className="l">Ticker</th><th>Weight</th><th>Vol</th><th>Beta</th><th>Risk contrib.</th><th>Return</th></tr></thead>
                      <tbody>
                        {res.positions.map((p) => (
                          <tr key={p.ticker} onClick={() => go(`stock/${p.ticker}`)}>
                            <td className="l"><span className="tkr">{p.ticker}</span> <span className="nm">{p.sector}</span></td>
                            <td>{pct(p.weight)}</td>
                            <td>{pct(p.volatility)}</td>
                            <td>{num(p.beta)}</td>
                            <td className={p.risk_contribution > p.weight * 1.25 ? "down" : ""}>{pct(p.risk_contribution)}</td>
                            <td className={tone(p.return)}>{signedPct(p.return)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Card>
                <Card title="Sector exposure" sub="weight vs risk">
                  <SectorBars sectors={res.sectors} />
                </Card>
              </div>
              <Card title="Correlation matrix" sub="daily returns over the lookback">
                <CorrMatrix tickers={res.correlation.tickers} matrix={res.correlation.matrix} />
              </Card>
            </>
          )}
        </div>
      </div>
    </>
  );
}

function SectorBars({ sectors }: { sectors: RiskResponse["sectors"] }) {
  const max = Math.max(...sectors.flatMap((s) => [s.weight, s.risk_contribution]), 0.01);
  return (
    <div>
      <div className="legend" style={{ marginBottom: 12 }}>
        <span><span className="sw" style={{ background: "var(--series-1)", height: 8 }} />Weight</span>
        <span><span className="sw" style={{ background: "var(--series-2)", height: 8 }} />Risk contribution</span>
      </div>
      {sectors.map((s) => (
        <div key={s.sector} style={{ marginBottom: 12 }}>
          <div className="row" style={{ justifyContent: "space-between", marginBottom: 4 }}>
            <span className="label" style={{ flex: "none" }}>{s.sector}</span>
            <span className="muted" style={{ flex: "none", fontFamily: "var(--mono)", fontSize: 12 }}>
              {pct(s.weight)} / {pct(s.risk_contribution)}
            </span>
          </div>
          {[{ v: s.weight, c: "--series-1" }, { v: s.risk_contribution, c: "--series-2" }].map((b, i) => (
            <div key={i} style={{ height: 6, marginBottom: 2 }}>
              <div style={{ width: `${(Math.max(b.v, 0) / max) * 100}%`, height: "100%", background: `var(${b.c})`, borderRadius: 3 }} />
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function CorrMatrix({ tickers, matrix }: { tickers: string[]; matrix: number[][] }) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table className="heat" style={{ width: "auto" }}>
        <thead><tr><th />{tickers.map((t) => <th key={t}>{t}</th>)}</tr></thead>
        <tbody>
          {matrix.map((row, i) => (
            <tr key={tickers[i]}>
              <th style={{ textAlign: "right" }}>{tickers[i]}</th>
              {row.map((v, j) => (
                <td key={j} title={`${tickers[i]} / ${tickers[j]}: ${v.toFixed(2)}`}
                  style={{ background: divergingBg(v, 1), color: textOn(v, 1) }}>
                  {i === j ? "" : v.toFixed(2)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
