import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { Card, Grade, ScoreBar, ZCell } from "../components/bits";
import { FACTOR_LABEL, money, num, pct, price, signedPct, tone } from "../format";
import { go, useStore } from "../store";
import type { FactorKey, ScreenRequest, ScreenResponse, ScreenRow, Weights } from "../types";

const PRESETS: { name: string; weights: Weights }[] = [
  { name: "Balanced", weights: { value: 25, quality: 25, momentum: 25, growth: 15, low_vol: 10 } },
  { name: "Deep value", weights: { value: 70, quality: 20, momentum: 10, growth: 0, low_vol: 0 } },
  { name: "Quality compounders", weights: { value: 10, quality: 55, momentum: 15, growth: 20, low_vol: 0 } },
  { name: "Momentum", weights: { value: 0, quality: 15, momentum: 75, growth: 10, low_vol: 0 } },
  { name: "GARP", weights: { value: 35, quality: 15, momentum: 10, growth: 40, low_vol: 0 } },
  { name: "Defensive", weights: { value: 15, quality: 35, momentum: 0, growth: 0, low_vol: 50 } },
];

const FACTORS: FactorKey[] = ["value", "quality", "momentum", "growth", "low_vol"];

type SortKey = keyof ScreenRow;

interface Filters {
  minCapB: string; maxPe: string; minDiv: string; maxDe: string; maxVol: string;
  aboveSma: boolean; sectors: string[]; watchOnly: boolean;
}

const EMPTY_FILTERS: Filters = { minCapB: "", maxPe: "", minDiv: "", maxDe: "", maxVol: "", aboveSma: false, sectors: [], watchOnly: false };

const n = (s: string) => (s.trim() === "" || Number.isNaN(Number(s)) ? null : Number(s));

export function Screener() {
  const { meta, watchlist, toggleWatch, setDraft } = useStore();
  const [weights, setWeights] = useState<Weights>(PRESETS[0].weights);
  const [sectorNeutral, setSectorNeutral] = useState(true);
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [data, setData] = useState<ScreenResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "score", desc: true });
  const [topN, setTopN] = useState(15);
  const reqId = useRef(0);

  const request: ScreenRequest = useMemo(() => ({
    weights,
    sector_neutral: sectorNeutral,
    min_market_cap: n(filters.minCapB) === null ? null : n(filters.minCapB)! * 1e9,
    max_pe: n(filters.maxPe),
    min_dividend_yield: n(filters.minDiv) === null ? null : n(filters.minDiv)! / 100,
    max_debt_to_equity: n(filters.maxDe),
    max_vol: n(filters.maxVol) === null ? null : n(filters.maxVol)! / 100,
    above_sma200: filters.aboveSma,
    sectors: filters.sectors,
  }), [weights, sectorNeutral, filters]);

  useEffect(() => {
    if (!Object.values(weights).some((w) => (w ?? 0) > 0)) return;
    const id = ++reqId.current;
    setLoading(true);
    const t = setTimeout(() => {
      api.screen(request)
        .then((d) => { if (id === reqId.current) { setData(d); setError(null); } })
        .catch((e) => id === reqId.current && setError(e.message))
        .finally(() => id === reqId.current && setLoading(false));
    }, 250);
    return () => clearTimeout(t);
  }, [request, weights]);

  const rows = useMemo(() => {
    let r = data?.rows ?? [];
    if (filters.watchOnly) r = r.filter((x) => watchlist.includes(x.ticker));
    const { key, desc } = sort;
    return [...r].sort((a, b) => {
      const av = a[key], bv = b[key];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      const c = typeof av === "string" ? av.localeCompare(String(bv)) : (av as number) - (bv as number);
      return desc ? -c : c;
    });
  }, [data, sort, filters.watchOnly, watchlist]);

  const totalW = FACTORS.reduce((s, f) => s + (weights[f] ?? 0), 0);

  const th = (key: SortKey, label: string, cls = "") => (
    <th className={`${cls} ${sort.key === key ? "sorted" : ""}`}
      onClick={() => setSort((s) => ({ key, desc: s.key === key ? !s.desc : typeof rows[0]?.[key] !== "string" }))}>
      {label}{sort.key === key ? (sort.desc ? " ↓" : " ↑") : ""}
    </th>
  );

  const buildPortfolio = () => {
    const picks = rows.filter((r) => r.score != null).slice(0, topN);
    setDraft(Object.fromEntries(picks.map((r) => [r.ticker, 1 / picks.length])));
    go("portfolio");
  };

  const exportCsv = () => {
    const cols = ["rank", "ticker", "name", "sector", "price", "market_cap", "pe", "dividend_yield", ...FACTORS, "score", "grade"];
    const esc = (v: unknown) => (v == null ? "" : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));
    const csv = [cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = `screen-${data?.as_of ?? "export"}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const setF = <K extends keyof Filters>(k: K, v: Filters[K]) => setFilters((f) => ({ ...f, [k]: v }));

  return (
    <>
      <div className="page-head">
        <h1>Multi-factor screener</h1>
        <span className="sub">
          {data ? `${rows.length} of ${data.universe_size} stocks · as of ${data.as_of}` : "Loading…"}
        </span>
      </div>
      <div className="split">
        <div className="stack sticky">
          <Card title="Factor weights" right={<span className="hint">{totalW ? "" : "set a weight"}</span>}>
            <div className="chips" style={{ marginBottom: 14 }}>
              {PRESETS.map((p) => (
                <button key={p.name} className={`chip ${JSON.stringify(p.weights) === JSON.stringify(weights) ? "on" : ""}`}
                  onClick={() => setWeights(p.weights)}>{p.name}</button>
              ))}
            </div>
            {FACTORS.map((f) => (
              <div className="slider-row" key={f} title={meta?.factors[f]}>
                <span className="label">{FACTOR_LABEL[f]}</span>
                <input type="range" min={0} max={100} step={5} value={weights[f] ?? 0}
                  onChange={(e) => setWeights((w) => ({ ...w, [f]: Number(e.target.value) }))} />
                <span className="v">{totalW ? Math.round(((weights[f] ?? 0) / totalW) * 100) : 0}%</span>
              </div>
            ))}
            <label className="check" style={{ marginTop: 10 }}>
              <input type="checkbox" checked={sectorNeutral} onChange={(e) => setSectorNeutral(e.target.checked)} />
              Sector-neutral scoring
            </label>
          </Card>

          <Card title="Filters" right={<button className="btn sm" onClick={() => setFilters(EMPTY_FILTERS)}>Reset</button>}>
            <div className="row">
              <div className="field"><label>Min mkt cap ($B)</label>
                <input type="number" value={filters.minCapB} onChange={(e) => setF("minCapB", e.target.value)} /></div>
              <div className="field"><label>Max P/E</label>
                <input type="number" value={filters.maxPe} onChange={(e) => setF("maxPe", e.target.value)} /></div>
            </div>
            <div className="row">
              <div className="field"><label>Min div yield (%)</label>
                <input type="number" value={filters.minDiv} onChange={(e) => setF("minDiv", e.target.value)} /></div>
              <div className="field"><label>Max debt/equity</label>
                <input type="number" value={filters.maxDe} onChange={(e) => setF("maxDe", e.target.value)} /></div>
            </div>
            <div className="field"><label>Max 1y volatility (%)</label>
              <input type="number" value={filters.maxVol} onChange={(e) => setF("maxVol", e.target.value)} /></div>
            <label className="check" style={{ marginBottom: 8 }}>
              <input type="checkbox" checked={filters.aboveSma} onChange={(e) => setF("aboveSma", e.target.checked)} />
              Price above 200-day SMA
            </label>
            <label className="check" style={{ marginBottom: 12 }}>
              <input type="checkbox" checked={filters.watchOnly} onChange={(e) => setF("watchOnly", e.target.checked)} />
              Watchlist only ({watchlist.length})
            </label>
            <div className="label" style={{ marginBottom: 6 }}>Sectors</div>
            <div className="chips">
              {(meta?.sectors ?? []).map((s) => (
                <button key={s} className={`chip ${filters.sectors.includes(s) ? "on" : ""}`}
                  onClick={() => setF("sectors", filters.sectors.includes(s) ? filters.sectors.filter((x) => x !== s) : [...filters.sectors, s])}>
                  {s}
                </button>
              ))}
            </div>
          </Card>
        </div>

        <Card pad={false} title="Ranked results" sub="z-scores: ±3 cap · blue = favourable"
          right={<>
            <span className="hint">Top</span>
            <input type="number" min={2} max={100} value={topN} style={{ width: 60 }} onChange={(e) => setTopN(Number(e.target.value) || 10)} />
            <button className="btn sm primary" onClick={buildPortfolio} disabled={!rows.length}>Build portfolio →</button>
            <button className="btn sm" onClick={exportCsv} disabled={!rows.length}>Export CSV</button>
          </>}>
          {error && <div className="error" style={{ margin: 12 }}>{error}</div>}
          <div className={`table-wrap ${loading && data ? "loading" : ""}`}>
            <table className="data">
              <thead>
                <tr>
                  <th className="l" />
                  {th("rank", "#")}
                  {th("ticker", "Ticker", "l")}
                  {th("sector", "Sector", "l")}
                  {th("price", "Price")}
                  {th("ret_1m", "1M")}
                  {th("market_cap", "Mkt cap")}
                  {th("pe", "P/E")}
                  {th("dividend_yield", "Yield")}
                  {FACTORS.map((f) => th(f, FACTOR_LABEL[f]))}
                  {th("score", "Score")}
                  {th("grade", "Grade")}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.ticker} onClick={() => go(`stock/${r.ticker}`)}>
                    <td className="l">
                      <button className={`star ${watchlist.includes(r.ticker) ? "on" : ""}`}
                        onClick={(e) => { e.stopPropagation(); toggleWatch(r.ticker); }}
                        aria-label="Toggle watchlist">★</button>
                    </td>
                    <td className="muted">{r.rank ?? "–"}</td>
                    <td className="l"><span className="tkr">{r.ticker}</span> <span className="nm">{r.name}</span></td>
                    <td className="l muted" style={{ fontSize: 12 }}>{r.sector}</td>
                    <td>{price(r.price)}</td>
                    <td className={tone(r.ret_1m)}>{signedPct(r.ret_1m)}</td>
                    <td>{money(r.market_cap)}</td>
                    <td>{num(r.pe, 1)}</td>
                    <td>{pct(r.dividend_yield)}</td>
                    {FACTORS.map((f) => <td key={f}><ZCell z={r[f] as number | null} /></td>)}
                    <td><ScoreBar score={r.score} /></td>
                    <td><Grade g={r.grade} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!loading && data && rows.length === 0 && <div className="empty">No stocks match these filters.</div>}
            {!data && !error && <div className="empty">Scoring universe…</div>}
          </div>
        </Card>
      </div>
    </>
  );
}
