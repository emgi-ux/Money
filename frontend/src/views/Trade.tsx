import { useMemo, useState, type FormEvent } from "react";
import { api } from "../api";
import { TimeChart, type SeriesSpec } from "../components/TimeChart";
import { Card, Seg, Stat } from "../components/bits";
import { money, pct, price, signedPct, tone } from "../format";
import { go, useLoad, useStore } from "../store";

export function Trade() {
  const { user, openAuth } = useStore();
  const { data, error, reload } = useLoad(() => (user ? api.paper() : Promise.resolve(null)), [user?.id]);
  const [ticker, setTicker] = useState("");
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [qty, setQty] = useState("10");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const curve: SeriesSpec[] = useMemo(() => data ? [{ name: "Equity", colorVar: "--series-1", data: data.equity_curve }] : [], [data]);

  if (!user) {
    return (
      <Card><div className="empty">
        <h2 style={{ color: "var(--text)" }}>Paper trading</h2>
        <p>Practice with a $100,000 virtual account, climb the public leaderboard, and let others copy you.</p>
        <button className="btn primary" onClick={() => openAuth("register")}>Create free account</button>
      </div></Card>
    );
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.order(ticker, side, Number(qty));
      setMsg({ ok: true, text: `${r.side === "buy" ? "Bought" : "Sold"} ${r.qty} ${r.ticker} @ ${price(r.price)}${r.mirrored_to ? ` · mirrored to ${r.mirrored_to} copier(s)` : ""}` });
      reload();
    } catch (err) {
      setMsg({ ok: false, text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(false);
    }
  };

  const reset = async () => {
    if (!confirm("Reset your paper account to $100,000? All positions and history will be deleted.")) return;
    await api.resetPaper();
    reload();
  };

  return (
    <>
      <div className="page-head">
        <h1>Paper trading</h1>
        <span className="sub">{user.is_public ? "Your profile is public — others can copy you" : <>Private · <a href="#/account">go public</a> to join the leaderboard</>}</span>
      </div>
      {error && <div className="error">{error.message}</div>}
      {data && (
        <div className="stack">
          <Card pad={false}>
            <div className="stats">
              <Stat k="Equity" v={money(data.equity)} s={<span className={tone(data.total_return)}>{signedPct(data.total_return, 2)} all time</span>} />
              <Stat k="Cash" v={money(data.cash)} s={`${pct(data.cash / data.equity, 0)} of equity`} />
              <Stat k="Invested" v={money(data.market_value)} s={`${data.positions.length} positions`} />
              <Stat k="Realized P&L" v={money(data.realized_pnl)} tone={tone(data.realized_pnl)} />
              <Stat k="Copying" v={data.copying.length} s={data.copying.map((c) => c.display_name).join(", ") || "nobody yet"} />
            </div>
          </Card>
          <div className="split">
            <Card title="Order ticket" className="sticky">
              <form onSubmit={submit}>
                <div className="field"><Seg value={side} onChange={setSide} options={[{ v: "buy", label: "Buy" }, { v: "sell", label: "Sell" }]} /></div>
                <div className="field"><label>Ticker</label>
                  <input type="text" value={ticker} onChange={(e) => setTicker(e.target.value.toUpperCase())} placeholder="AAPL" required /></div>
                <div className="field"><label>Shares</label>
                  <input type="number" min={0.0001} step="any" value={qty} onChange={(e) => setQty(e.target.value)} required /></div>
                <button className={`btn ${side === "buy" ? "primary" : ""}`} style={{ width: "100%" }} disabled={busy || !ticker}>
                  {busy ? "…" : `${side === "buy" ? "Buy" : "Sell"} ${ticker || ""} at market`}
                </button>
                {msg && <div className={msg.ok ? "hint up" : "hint down"} style={{ marginTop: 10 }}>{msg.text}</div>}
                <p className="hint" style={{ marginTop: 12 }}>Simulated fills at the latest price. No real money is involved.</p>
              </form>
              <div className="divider" />
              <button className="btn sm" onClick={reset}>Reset account</button>
            </Card>
            <div className="stack">
              <Card title="Equity curve"><TimeChart series={curve} height={220} format={(v) => money(v)} /></Card>
              <Card pad={false} title="Positions">
                {data.positions.length === 0 ? <div className="empty">No open positions.</div> : (
                  <div className="table-wrap">
                    <table className="data">
                      <thead><tr><th className="l">Ticker</th><th>Shares</th><th>Avg cost</th><th>Price</th><th>Value</th><th>Weight</th><th>Unrealized</th></tr></thead>
                      <tbody>
                        {data.positions.map((p) => (
                          <tr key={p.ticker} onClick={() => { setTicker(p.ticker); setSide("sell"); setQty(String(p.qty)); }}>
                            <td className="l"><span className="tkr">{p.ticker}</span></td>
                            <td>{+p.qty.toFixed(4)}</td><td>{price(p.avg_cost)}</td><td>{price(p.price)}</td>
                            <td>{money(p.value)}</td><td>{pct(p.weight)}</td>
                            <td className={tone(p.unrealized)}>{money(p.unrealized)} ({signedPct(p.unrealized_pct)})</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Card>
              {data.copying.length > 0 && (
                <Card pad={false} title="Copy trading">
                  <table className="data">
                    <thead><tr><th className="l">Trader</th><th>Allocation</th><th>Since</th><th /></tr></thead>
                    <tbody>
                      {data.copying.map((c) => (
                        <tr key={c.leader_id} onClick={() => go(`trader/${c.leader_id}`)}>
                          <td className="l"><b>{c.display_name}</b>{c.is_bot ? <span className="tag">bot</span> : null}</td>
                          <td>{money(c.allocation)}</td><td>{c.created_at.slice(0, 10)}</td>
                          <td><button className="btn sm" onClick={async (e) => { e.stopPropagation(); await api.uncopy(c.leader_id); reload(); }}>Stop</button></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </Card>
              )}
              <Card pad={false} title="History">
                <div className="table-wrap" style={{ maxHeight: 360 }}>
                  <table className="data">
                    <thead><tr><th className="l">Time</th><th className="l">Ticker</th><th className="l">Side</th><th>Shares</th><th>Price</th><th className="l">Source</th></tr></thead>
                    <tbody>
                      {data.trades.map((t) => (
                        <tr key={t.id} style={{ cursor: "default" }}>
                          <td className="l muted">{t.ts.slice(0, 16).replace("T", " ")}</td>
                          <td className="l"><span className="tkr">{t.ticker}</span></td>
                          <td className={`l ${t.side === "buy" ? "up" : "down"}`}>{t.side}</td>
                          <td>{+t.qty.toFixed(4)}</td><td>{price(t.price)}</td>
                          <td className="l muted">{t.source}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {data.trades.length === 0 && <div className="empty">No trades yet.</div>}
                </div>
              </Card>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
