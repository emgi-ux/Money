import { useMemo, useState, type FormEvent } from "react";
import { api } from "../api";
import { Gate } from "../components/Gate";
import { IntradayChart } from "../components/IntradayChart";
import { Card, KV, Seg, Stat } from "../components/bits";
import { num, pct, price, signedPct, tone } from "../format";
import { go, useLoad, useStore } from "../store";
import type { ScanRow } from "../types";

const INTERVALS = [{ v: "1m", label: "1m" }, { v: "5m", label: "5m" }, { v: "15m", label: "15m" }];
type ScanSort = "gap" | "rvol" | "change" | "range_vs_atr";

export function DayTrade({ ticker }: { ticker: string }) {
  const [interval, setInterval] = useState("5m");
  const [bands, setBands] = useState(false);
  const [pivotsOn, setPivotsOn] = useState(true);
  const [input, setInput] = useState(ticker);
  const { user } = useStore();
  const { data, error, loading } = useLoad(() => api.daytrade(ticker, interval, interval === "1m" ? 2 : 5),
    [ticker, interval, user?.id, user?.is_pro]);
  const scan = useLoad(() => api.scanner(), [user?.id, user?.is_pro]);

  const onGo = (e: FormEvent) => {
    e.preventDefault();
    if (input.trim()) go(`daytrade/${input.trim().toUpperCase()}`);
  };

  return (
    <>
      <div className="page-head" style={{ alignItems: "center" }}>
        <h1>Day trading desk</h1>
        <form onSubmit={onGo} className="row" style={{ flex: "0 0 auto" }}>
          <input type="text" value={input} onChange={(e) => setInput(e.target.value)} style={{ width: 110, textTransform: "uppercase" }} />
          <button className="btn sm">Load</button>
        </form>
        <Seg value={interval} options={INTERVALS} onChange={setInterval} />
        <span className="sub">{data ? `Session ${data.session} · exchange time` : ""}</span>
      </div>
      <Gate error={error} feature="The day trading desk">
        {data && (
          <div className={`stack ${loading ? "loading" : ""}`}>
            <Card pad={false}>
              <div className="stats">
                <Stat k={data.ticker} v={price(data.summary.price)} s={<span className={tone(data.summary.change)}>{signedPct(data.summary.change, 2)} today</span>} />
                <Stat k="Bias" v={<span className={data.summary.bias === "Bullish" ? "up" : data.summary.bias === "Bearish" ? "down" : ""}>{data.summary.bias}</span>} s="VWAP + EMA trend" />
                <Stat k="Gap" v={signedPct(data.summary.gap, 2)} tone={tone(data.summary.gap)} s={`prev close ${price(data.levels.prev_close)}`} />
                <Stat k="vs VWAP" v={signedPct(data.summary.vs_vwap, 2)} tone={tone(data.summary.vs_vwap)} s={`VWAP ${price(data.summary.vwap)}`} />
                <Stat k="RSI 14" v={num(data.summary.rsi, 1)} s={data.summary.rsi == null ? "" : data.summary.rsi > 70 ? "overbought" : data.summary.rsi < 30 ? "oversold" : "neutral"} />
                <Stat k="Rel. volume" v={data.summary.rvol == null ? "–" : `${data.summary.rvol.toFixed(2)}x`} s="vs prior sessions, same time" />
                <Stat k="ATR (daily)" v={price(data.summary.daily_atr)} s={data.summary.day_range_used == null ? "" : `${pct(data.summary.day_range_used, 0)} of ATR used`} />
              </div>
            </Card>
            <div className="split" style={{ gridTemplateColumns: "minmax(0,1fr) 320px" }}>
              <Card title="Chart" right={<>
                <label className="check"><input type="checkbox" checked={bands} onChange={(e) => setBands(e.target.checked)} />VWAP bands</label>
                <label className="check"><input type="checkbox" checked={pivotsOn} onChange={(e) => setPivotsOn(e.target.checked)} />Pivots</label>
              </>}>
                <IntradayChart data={data} showBands={bands} showPivots={pivotsOn} />
              </Card>
              <div className="stack">
                <Card title="Signals" sub="latest session">
                  <div style={{ maxHeight: 250, overflow: "auto" }}>
                    {data.signals.length === 0 && <div className="hint">No signals yet this session.</div>}
                    {data.signals.map((s, i) => (
                      <div key={i} className="signal">
                        <span className="muted mono">{s.clock}</span>
                        <span className={`dir ${s.direction}`}>{s.direction === "long" ? "▲" : "▼"}</span>
                        <span style={{ flex: 1 }}>{s.text}</span>
                        <span className="mono">{price(s.price)}</span>
                      </div>
                    ))}
                  </div>
                </Card>
                <Card title="Key levels">
                  <KV rows={([
                    ["High of day", data.levels.hod], ["Low of day", data.levels.lod],
                    ["Opening range high", data.levels.opening_range_high], ["Opening range low", data.levels.opening_range_low],
                    ["Prev high", data.levels.prev_high], ["Prev low", data.levels.prev_low],
                    ...Object.entries(data.levels.pivots).map(([k, v]) => [`Pivot ${k}`, v]),
                  ] as [string, number | null][]).map(([k, v]) => [k, price(v)])} />
                </Card>
                <RiskCalc price={data.summary.price} longStop={data.summary.long_stop} shortStop={data.summary.short_stop} ticker={data.ticker} />
              </div>
            </div>
          </div>
        )}
      </Gate>
      {!error && <Scanner rows={scan.data?.rows} error={scan.error} />}
      <p className="hint" style={{ marginTop: 16 }}>
        Educational tool, not trading advice. Day trading carries substantial risk of loss; in the US, margin
        accounts that day trade 4+ times in 5 business days are subject to pattern-day-trader rules.
      </p>
    </>
  );
}

function RiskCalc({ price: px, longStop, shortStop, ticker }: { price: number; longStop: number; shortStop: number; ticker: string }) {
  const { user, openAuth } = useStore();
  const [account, setAccount] = useState("25000");
  const [riskPct, setRiskPct] = useState("1");
  const [side, setSide] = useState<"long" | "short">("long");
  const [entry, setEntry] = useState(px.toFixed(2));
  const [stop, setStop] = useState((side === "long" ? longStop : shortStop).toFixed(2));
  const [msg, setMsg] = useState<string | null>(null);

  const e = Number(entry), s = Number(stop);
  const perShare = Math.abs(e - s);
  const riskDollars = (Number(account) * Number(riskPct)) / 100;
  const shares = perShare > 0 ? Math.floor(riskDollars / perShare) : 0;
  const dir = side === "long" ? 1 : -1;
  const valid = perShare > 0 && (side === "long" ? s < e : s > e);

  const paper = async () => {
    if (!user) { openAuth("login"); return; }
    try {
      const r = await api.order(ticker, side === "long" ? "buy" : "sell", shares);
      setMsg(`Filled ${r.qty} @ ${price(r.price)}`);
    } catch (err) {
      setMsg(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <Card title="Position sizing">
      <div className="row" style={{ marginBottom: 10 }}>
        <Seg value={side} onChange={(v) => { setSide(v); setStop((v === "long" ? longStop : shortStop).toFixed(2)); }}
          options={[{ v: "long", label: "Long" }, { v: "short", label: "Short" }]} />
      </div>
      <div className="row">
        <div className="field"><label>Account ($)</label><input type="number" value={account} onChange={(ev) => setAccount(ev.target.value)} /></div>
        <div className="field"><label>Risk / trade (%)</label><input type="number" step={0.25} value={riskPct} onChange={(ev) => setRiskPct(ev.target.value)} /></div>
      </div>
      <div className="row">
        <div className="field"><label>Entry</label><input type="number" value={entry} onChange={(ev) => setEntry(ev.target.value)} /></div>
        <div className="field"><label>Stop (1.5 ATR)</label><input type="number" value={stop} onChange={(ev) => setStop(ev.target.value)} /></div>
      </div>
      {valid ? (
        <KV style={{ marginBottom: 12 }} rows={[
          ["Shares", <b>{shares.toLocaleString()}</b>],
          ["Position size", `$${(shares * e).toLocaleString(undefined, { maximumFractionDigits: 0 })}`],
          ["Dollar risk", `$${(shares * perShare).toFixed(0)}`],
          ...[1, 2, 3].map((r): [string, string] => [`${r}R target`, price(e + dir * r * perShare)]),
        ]} />
      ) : <div className="hint" style={{ marginBottom: 12 }}>Stop must be {side === "long" ? "below" : "above"} entry.</div>}
      {side === "long" && (
        <button className="btn sm" style={{ width: "100%" }} disabled={!valid || shares < 1} onClick={paper}>
          Paper buy {shares} {ticker}
        </button>
      )}
      {msg && <div className="hint" style={{ marginTop: 8 }}>{msg}</div>}
    </Card>
  );
}

function Scanner({ rows, error }: { rows?: ScanRow[]; error: unknown }) {
  const [sort, setSort] = useState<ScanSort>("gap");
  const [setupOnly, setSetupOnly] = useState(false);
  const sorted = useMemo(() => {
    let r = rows ?? [];
    if (setupOnly) r = r.filter((x) => x.setups.length);
    const key = (x: ScanRow) => Math.abs((x[sort] as number | null) ?? 0);
    return [...r].sort((a, b) => key(b) - key(a)).slice(0, 40);
  }, [rows, sort, setupOnly]);
  if (error) return null;
  return (
    <Card pad={false} title="Scanner" sub="latest session · daily bars" className="mt"
      right={<>
        <label className="check"><input type="checkbox" checked={setupOnly} onChange={(e) => setSetupOnly(e.target.checked)} />Setups only</label>
        <Seg value={sort} onChange={setSort} options={[
          { v: "gap", label: "Gap" }, { v: "rvol", label: "Rel vol" }, { v: "change", label: "% chg" }, { v: "range_vs_atr", label: "Range/ATR" },
        ]} />
      </>}>
      <div className="table-wrap" style={{ maxHeight: 520 }}>
        <table className="data">
          <thead><tr>
            <th className="l">Ticker</th><th>Price</th><th>Change</th><th>Gap</th><th>Rel vol</th><th>ATR %</th>
            <th>Range/ATR</th><th>Close in range</th><th className="l">20 days</th><th className="l">Setups</th>
          </tr></thead>
          <tbody>
            {sorted.map((r) => (
              <tr key={r.ticker} onClick={() => go(`daytrade/${r.ticker}`)}>
                <td className="l"><span className="tkr">{r.ticker}</span></td>
                <td>{price(r.price)}</td>
                <td className={tone(r.change)}>{signedPct(r.change, 2)}</td>
                <td className={tone(r.gap)}>{signedPct(r.gap, 2)}</td>
                <td>{r.rvol == null ? "–" : `${r.rvol.toFixed(2)}x`}</td>
                <td>{pct(r.atr_pct, 1)}</td>
                <td>{num(r.range_vs_atr, 2)}</td>
                <td>{pct(r.close_in_range, 0)}</td>
                <td className="l"><Spark points={r.spark.map((p) => p.value)} /></td>
                <td className="l">{r.setups.map((s) => <span key={s} className="tag">{s}</span>)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!rows && <div className="empty">Scanning…</div>}
      </div>
    </Card>
  );
}

export function Spark({ points, w = 90, h = 22 }: { points: number[]; w?: number; h?: number }) {
  if (points.length < 2) return null;
  const lo = Math.min(...points), hi = Math.max(...points);
  const d = points.map((v, i) => `${(i / (points.length - 1)) * w},${h - 2 - ((v - lo) / (hi - lo || 1)) * (h - 4)}`).join(" ");
  const up = points[points.length - 1] >= points[0];
  return (
    <svg width={w} height={h} aria-hidden="true">
      <polyline points={d} fill="none" stroke={up ? "var(--up)" : "var(--down)"} strokeWidth="1.5" />
    </svg>
  );
}
