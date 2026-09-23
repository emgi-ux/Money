import { useEffect, useState } from "react";
import { api } from "../api";
import { CandleChart } from "../components/CandleChart";
import { Card, FactorBars, Grade, Seg, Stat, ZCell } from "../components/bits";
import { formatMetric, money, num, pct, price, signedPct, tone } from "../format";
import { go, useStore } from "../store";
import type { StockResponse } from "../types";

const RANGES = [
  { v: "0.5", label: "6M" }, { v: "1", label: "1Y" }, { v: "2", label: "2Y" }, { v: "5", label: "5Y" },
];

export function StockView({ ticker }: { ticker: string }) {
  const { meta, watchlist, toggleWatch } = useStore();
  const [years, setYears] = useState("2");
  const [data, setData] = useState<StockResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api.stock(ticker, Number(years))
      .then((d) => { if (live) { setData(d); setError(null); } })
      .catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [ticker, years]);

  if (error) return <div className="error">{error}</div>;
  if (!data) return <div className="empty">Loading {ticker}…</div>;

  const p = data.profile;
  const f = data.fundamentals ?? {};
  const last = data.candles[data.candles.length - 1];
  const prev = data.candles[data.candles.length - 2];
  const dayChg = last && prev ? last.close / prev.close - 1 : null;
  const pcts = Object.fromEntries(
    ["value", "quality", "momentum", "growth", "low_vol"].map((k) => [k, p[`${k}_pct`] as number | undefined]),
  );
  const onWatch = watchlist.includes(ticker);

  const fundRows: [string, string][] = [
    ["Market cap", money(f.market_cap as number)],
    ["P/E (ttm)", num(f.pe as number, 1)],
    ["Forward P/E", num(f.forward_pe as number, 1)],
    ["P/B", num(f.pb as number, 2)],
    ["P/S", num(f.ps as number, 2)],
    ["EV/EBITDA", num(f.ev_ebitda as number, 1)],
    ["FCF yield", pct(f.fcf_yield as number)],
    ["Dividend yield", pct(f.dividend_yield as number, 2)],
    ["ROE", pct(f.roe as number)],
    ["ROA", pct(f.roa as number)],
    ["Gross margin", pct(f.gross_margin as number)],
    ["Operating margin", pct(f.operating_margin as number)],
    ["Net margin", pct(f.profit_margin as number)],
    ["Debt / equity", num(f.debt_to_equity as number, 2)],
    ["Current ratio", num(f.current_ratio as number, 2)],
    ["Revenue growth", signedPct(f.revenue_growth as number)],
    ["Earnings growth", signedPct(f.earnings_growth as number)],
    ["Beta", num(f.beta as number, 2)],
  ];

  return (
    <>
      <div className="page-head" style={{ alignItems: "center" }}>
        <a href="#/screener" className="hint">← Screener</a>
        <h1>{ticker}</h1>
        <span className="sub">{String(f.name ?? "")} · {String(f.sector ?? p.sector ?? "")}</span>
        <button className={`btn sm ${onWatch ? "primary" : ""}`} onClick={() => toggleWatch(ticker)}>
          {onWatch ? "★ Watching" : "☆ Watch"}
        </button>
        <a className="btn sm primary" href={`#/analysis/${ticker}`}>Deep analysis →</a>
        <a className="btn sm" href={`#/daytrade/${ticker}`}>Day trade →</a>
      </div>

      <div className="stack">
        <Card pad={false}>
          <div className="stats">
            <Stat k="Last price" v={<span className="hero"><span>{price(last?.close)}</span></span>}
              s={<span className={tone(dayChg)}>{signedPct(dayChg, 2)} today</span>} />
            <Stat k="Composite score" v={p.score != null ? p.score.toFixed(0) : "–"}
              s={p.rank ? `Rank ${p.rank} in universe` : "not ranked"} />
            <Stat k="Grade" v={<Grade g={p.grade} />} />
            {Object.entries(data.returns).map(([k, v]) => (
              <Stat key={k} k={`Return ${k}`} v={signedPct(v)} tone={tone(v)} />
            ))}
          </div>
        </Card>

        <div className="split" style={{ gridTemplateColumns: "minmax(0,1fr) 320px" }}>
          <Card title="Price" right={<Seg value={years} options={RANGES} onChange={setYears} />}>
            <CandleChart candles={data.candles} sma50={data.overlays.sma50} sma200={data.overlays.sma200} rsi={data.overlays.rsi14} />
          </Card>
          <div className="stack">
            <Card title="Factor profile"><FactorBars pcts={pcts} /></Card>
            <Card title="Factor metrics" sub="raw values">
              <div className="kv">
                {(meta?.metrics ?? []).map((m) => (
                  <FragmentRow key={m.key} k={m.label} title={m.description}
                    v={formatMetric(p[`m_${m.key}`] as number | null, m.fmt)} />
                ))}
              </div>
            </Card>
          </div>
        </div>

        <div className="grid-2">
          <Card title="Fundamentals">
            <div className="kv" style={{ gridTemplateColumns: "1fr auto 1fr auto", columnGap: 20 }}>
              {fundRows.map(([k, v]) => <FragmentRow key={k} k={k} v={v} />)}
            </div>
          </Card>
          <Card pad={false} title="Sector peers" sub={String(p.sector ?? "")}>
            <div className="table-wrap" style={{ maxHeight: 420 }}>
              <table className="data">
                <thead>
                  <tr>
                    <th className="l">Ticker</th><th>P/E</th><th>Value</th><th>Quality</th><th>Mom</th><th>Score</th><th>Grade</th>
                  </tr>
                </thead>
                <tbody>
                  {data.peers.map((r) => (
                    <tr key={r.ticker} className={r.is_self ? "self" : ""} onClick={() => go(`stock/${r.ticker}`)}>
                      <td className="l"><span className="tkr">{r.ticker}</span></td>
                      <td>{num(r.pe as number, 1)}</td>
                      <td><ZCell z={r.value as number} /></td>
                      <td><ZCell z={r.quality as number} /></td>
                      <td><ZCell z={r.momentum as number} /></td>
                      <td>{r.score != null ? (r.score as number).toFixed(0) : "–"}</td>
                      <td><Grade g={r.grade as string} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}

function FragmentRow({ k, v, title }: { k: string; v: string; title?: string }) {
  return (
    <>
      <span className="k" title={title}>{k}</span>
      <span className="v">{v}</span>
    </>
  );
}
