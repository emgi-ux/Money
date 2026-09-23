import { useMemo, useState } from "react";
import { api } from "../api";
import { Gate } from "../components/Gate";
import { TimeChart, type SeriesSpec } from "../components/TimeChart";
import { Card, Seg, Stat } from "../components/bits";
import { money, num, pct, price, signedPct, tone } from "../format";
import { go, useLoad, useStore } from "../store";

const SORTS = [
  { v: "total_return", label: "All-time" }, { v: "return_3m", label: "3M" }, { v: "return_1m", label: "1M" },
  { v: "sharpe", label: "Sharpe" }, { v: "followers", label: "Copiers" },
];

export function Leaders() {
  const [sort, setSort] = useState("total_return");
  const { data, error, loading } = useLoad(() => api.leaderboard(sort), [sort]);
  return (
    <>
      <div className="page-head" style={{ alignItems: "center" }}>
        <h1>Top traders</h1>
        <span className="sub">Public paper-trading accounts · copy any of them in one click</span>
        <span style={{ marginLeft: "auto" }}><Seg value={sort} onChange={setSort} options={SORTS} /></span>
      </div>
      {error && <div className="error">{error.message}</div>}
      <Card pad={false}>
        <div className={`table-wrap ${loading && data ? "loading" : ""}`}>
          <table className="data">
            <thead><tr>
              <th>#</th><th className="l">Trader</th><th>Return</th><th>3M</th><th>1M</th><th>Sharpe</th>
              <th>Max DD</th><th>Win rate</th><th>Trades</th><th>Copiers</th><th className="l">Top holdings</th>
            </tr></thead>
            <tbody>
              {data?.rows.map((r) => (
                <tr key={r.id} onClick={() => go(`trader/${r.id}`)}>
                  <td className="muted">{r.rank}</td>
                  <td className="l"><b>{r.display_name}</b>{r.is_bot ? <span className="tag">strategy bot</span> : null}
                    <div className="nm" style={{ maxWidth: 320 }}>{r.bio}</div></td>
                  <td className={tone(r.total_return)}><b>{signedPct(r.total_return)}</b></td>
                  <td className={tone(r.return_3m)}>{signedPct(r.return_3m)}</td>
                  <td className={tone(r.return_1m)}>{signedPct(r.return_1m)}</td>
                  <td>{num(r.sharpe)}</td>
                  <td>{pct(r.max_drawdown)}</td>
                  <td>{pct(r.win_rate, 0)}</td>
                  <td>{r.trades}</td>
                  <td>{r.followers}</td>
                  <td className="l muted">{r.top_holdings.join(" ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!data && !error && <div className="empty">Loading leaderboard…</div>}
          {data && data.rows.length === 0 && <div className="empty">No public traders yet. Be the first — go public from your account page.</div>}
        </div>
      </Card>
      <p className="hint" style={{ marginTop: 12 }}>
        Rankings reflect simulated paper trading. Past performance does not guarantee future results. Strategy bots are
        automated model portfolios run by Money.
      </p>
    </>
  );
}

export function Trader({ id }: { id: number }) {
  const { user, openAuth } = useStore();
  const { data, error, reload } = useLoad(() => api.trader(id), [id, user?.id]);
  const [alloc, setAlloc] = useState("10000");
  const [copyErr, setCopyErr] = useState<unknown>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const curve: SeriesSpec[] = useMemo(() => data ? [{ name: "Equity", colorVar: "--series-1", data: data.equity_curve }] : [], [data]);

  if (error) return <div className="error">{error.message}</div>;
  if (!data) return <div className="empty">Loading…</div>;
  const s = data.stats;
  const isSelf = user?.id === data.trader.id;

  const copy = async () => {
    if (!user) { openAuth("register"); return; }
    setCopyErr(null);
    try {
      const r = await api.copy(id, Number(alloc));
      setMsg(`Now copying ${data.trader.display_name}: opened ${r.positions_opened} positions.`);
      reload();
    } catch (e) {
      setCopyErr(e);
    }
  };
  const stop = async () => { await api.uncopy(id); setMsg(null); reload(); };

  return (
    <>
      <div className="page-head" style={{ alignItems: "center" }}>
        <a href="#/leaders" className="hint">← Top traders</a>
        <h1>{data.trader.display_name}</h1>
        {data.trader.is_bot ? <span className="tag">strategy bot</span> : null}
        <span className="sub">{data.trader.bio}</span>
      </div>
      <div className="stack">
        <Card pad={false}>
          <div className="stats">
            <Stat k="Total return" v={signedPct(s.total_return)} tone={tone(s.total_return)} s={`since ${s.since}`} />
            <Stat k="3 months" v={signedPct(s.return_3m)} tone={tone(s.return_3m)} />
            <Stat k="1 month" v={signedPct(s.return_1m)} tone={tone(s.return_1m)} />
            <Stat k="Sharpe" v={num(s.sharpe)} s={`vol ${pct(s.volatility)}`} />
            <Stat k="Max drawdown" v={pct(s.max_drawdown)} />
            <Stat k="Win rate" v={pct(s.win_rate, 0)} s={`${s.trades} trades`} />
            <Stat k="Copiers" v={s.followers} />
          </div>
        </Card>
        <div className="split" style={{ gridTemplateColumns: "minmax(0,1fr) 320px" }}>
          <div className="stack">
            <Card title="Equity"><TimeChart series={curve} height={240} format={(v) => money(v)} /></Card>
            <div className="grid-2">
              <Card pad={false} title="Holdings">
                <table className="data">
                  <thead><tr><th className="l">Ticker</th><th>Weight</th><th>Unrealized</th></tr></thead>
                  <tbody>
                    {data.positions.map((p) => (
                      <tr key={p.ticker} onClick={() => go(`stock/${p.ticker}`)}>
                        <td className="l"><span className="tkr">{p.ticker}</span></td><td>{pct(p.weight)}</td>
                        <td className={tone(p.unrealized_pct)}>{signedPct(p.unrealized_pct)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {data.positions.length === 0 && <div className="empty">All cash.</div>}
              </Card>
              <Card pad={false} title="Recent trades">
                <div className="table-wrap" style={{ maxHeight: 400 }}>
                  <table className="data">
                    <thead><tr><th className="l">Date</th><th className="l">Ticker</th><th className="l">Side</th><th>Price</th></tr></thead>
                    <tbody>
                      {data.trades.map((t, i) => (
                        <tr key={i} style={{ cursor: "default" }}>
                          <td className="l muted">{t.ts.slice(0, 10)}</td><td className="l"><span className="tkr">{t.ticker}</span></td>
                          <td className={`l ${t.side === "buy" ? "up" : "down"}`}>{t.side}</td><td>{price(t.price)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            </div>
          </div>
          <Card title="Copy this trader" className="sticky">
            {isSelf ? <div className="hint">This is you.</div> : data.is_copying ? (
              <>
                <p>You're copying {data.trader.display_name}. New trades are mirrored into your paper account automatically.</p>
                <button className="btn" onClick={stop}>Stop copying</button>
              </>
            ) : (
              <>
                <p className="hint" style={{ marginTop: 0 }}>
                  Mirror this trader's current portfolio and every future trade, scaled to the amount you allocate from
                  your paper account.
                </p>
                <div className="field"><label>Allocation ($)</label>
                  <input type="number" min={100} value={alloc} onChange={(e) => setAlloc(e.target.value)} /></div>
                <button className="btn primary" style={{ width: "100%" }} onClick={copy}>Copy {data.trader.display_name}</button>
              </>
            )}
            {msg && <div className="hint up" style={{ marginTop: 10 }}>{msg}</div>}
            {copyErr != null && <div style={{ marginTop: 12 }}><Gate error={copyErr} feature="Copy trading" /></div>}
            <p className="hint">Simulated trading only. Copying real-money accounts requires a licensed broker.</p>
          </Card>
        </div>
      </div>
    </>
  );
}
