import { useMemo } from "react";
import { api } from "../api";
import { Gate } from "../components/Gate";
import { TimeChart, type SeriesSpec } from "../components/TimeChart";
import { Card, KV, Stat, divergingBg, textOn } from "../components/bits";
import { money, num, pct, price, signedPct, tone } from "../format";
import { useLoad, useStore } from "../store";
import type { AnalysisResponse } from "../types";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function Analysis({ ticker }: { ticker: string }) {
  const { user } = useStore();
  const { data, error } = useLoad(() => api.analysis(ticker), [ticker, user?.id, user?.is_pro]);
  return (
    <>
      <div className="page-head" style={{ alignItems: "center" }}>
        <a href={`#/stock/${ticker}`} className="hint">← {ticker}</a>
        <h1>Deep analysis · {ticker}</h1>
        {data && <span className="sub">{data.name} · {data.sector} · as of {data.as_of}</span>}
      </div>
      <Gate error={error} feature="Deep analysis">
        {!data ? <div className="empty">Running models…</div> : <Body a={data} />}
      </Gate>
    </>
  );
}

function ratingClass(r: string) {
  return r === "Strong" || r === "Favorable" ? "up" : r === "Weak" || r === "Unfavorable" ? "down" : "";
}

function Body({ a }: { a: AnalysisResponse }) {
  const v = a.valuation;
  const ddSeries: SeriesSpec[] = useMemo(() => [{ name: "Drawdown", colorVar: "--series-1", data: a.risk.drawdown, area: true }], [a]);
  return (
    <div className="stack">
      <Card pad={false}>
        <div className="stats">
          <Stat k="Price" v={price(a.price)} />
          <Stat k="Model rating" v={<span className={ratingClass(a.thesis.rating)}>{a.thesis.rating}</span>} s={`score ${a.thesis.rating_score.toFixed(0)} / 100`} />
          <Stat k="DCF fair value" v={v.available ? price(v.fair_value) : "n/a"}
            s={v.available ? <span className={tone(v.upside)}>{signedPct(v.upside)} vs price</span> : v.reason} />
          <Stat k="Piotroski F-Score" v={a.piotroski.available ? `${a.piotroski.score}/9` : "n/a"} s={a.piotroski.label ?? a.piotroski.reason} />
          <Stat k="Altman Z" v={a.altman.available ? num(a.altman.z) : "n/a"} s={a.altman.zone ? `${a.altman.zone} zone` : a.altman.reason} />
          <Stat k="Max drawdown (5y)" v={pct(a.risk.stats.max_drawdown)} s={`vol ${pct(a.risk.stats.volatility)}`} />
        </div>
      </Card>

      <div className="grid-2">
        <Card title="Investment thesis" sub="rule-based summary of the models below">
          <div className="grid-2" style={{ gap: 20 }}>
            <div>
              <div className="label up" style={{ marginBottom: 8 }}>▲ Bull case</div>
              {a.thesis.bull.length ? <ul className="bullets">{a.thesis.bull.map((b) => <li key={b}>{b}</li>)}</ul>
                : <div className="hint">No strong positives flagged.</div>}
            </div>
            <div>
              <div className="label down" style={{ marginBottom: 8 }}>▼ Bear case</div>
              {a.thesis.bear.length ? <ul className="bullets">{a.thesis.bear.map((b) => <li key={b}>{b}</li>)}</ul>
                : <div className="hint">No major red flags.</div>}
            </div>
          </div>
        </Card>
        <Card title="Valuation range" sub={v.method}>
          {v.available && v.scenarios ? <FootballField a={a} /> : <div className="hint">{v.reason}</div>}
        </Card>
      </div>

      {v.available && v.sensitivity && (
        <div className="grid-2">
          <Card title="DCF assumptions">
            <KV rows={[
              ["Normalised free cash flow (3y avg)", money(v.normalized_fcf)],
              ["Base-case growth, years 1-5", pct(v.base_growth)],
              ["Historical revenue CAGR", pct(v.historical_revenue_cagr)],
              ["Discount rate (CAPM)", pct(v.discount_rate, 2)],
              ["Terminal growth", pct(v.terminal_growth, 1)],
              ["Growth implied by today's price", pct(v.implied_growth)],
              ["Margin of safety (base)", pct(v.margin_of_safety)],
              ["Terminal value share of worth", pct(v.scenarios?.base.terminal_share)],
            ]} />
            <p className="hint" style={{ marginTop: 12 }}>
              Growth fades linearly from the base rate to terminal over years 6-10. Bear / bull shift growth by ∓5 pts
              and the discount rate by ±1 pt.
            </p>
          </Card>
          <Card title="Sensitivity" sub="fair value per share · rows = discount rate, columns = terminal growth">
            <div style={{ overflowX: "auto" }}>
              <table className="heat">
                <thead><tr><th />{v.sensitivity.terminal_growth.map((t) => <th key={t}>{pct(t, 1)}</th>)}</tr></thead>
                <tbody>
                  {v.sensitivity.values.map((row, i) => (
                    <tr key={i}>
                      <th>{pct(v.sensitivity!.discount_rates[i], 1)}</th>
                      {row.map((x, j) => {
                        const rel = x == null ? 0 : x / a.price - 1;
                        return (
                          <td key={j} title={x == null ? "" : `${signedPct(rel)} vs price`}
                            style={x == null ? {} : { background: divergingBg(rel, 0.6), color: textOn(rel, 0.6) }}>
                            {x == null ? "–" : price(x)}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="hint" style={{ marginTop: 8 }}>Blue = above today's price, red = below.</p>
          </Card>
        </div>
      )}

      <div className="grid-2">
        <Card title="Piotroski F-Score" sub={a.piotroski.available ? `${a.piotroski.score} of 9 · ${a.piotroski.label}` : ""}>
          {a.piotroski.available && a.piotroski.checks ? (
            <div className="checks">
              {a.piotroski.checks.map((c) => (
                <div key={c.name} className="check-row">
                  <span className={`mark ${c.pass === null ? "na" : c.pass ? "ok" : "bad"}`}>{c.pass === null ? "–" : c.pass ? "✓" : "✗"}</span>
                  <span style={{ flex: 1 }}>{c.name}<div className="hint">{c.group} · {c.detail}</div></span>
                </div>
              ))}
            </div>
          ) : <div className="hint">{a.piotroski.reason}</div>}
        </Card>
        <Card title="Altman Z-Score" sub="bankruptcy-risk model">
          {a.altman.available && a.altman.components ? (
            <>
              <ZGauge z={a.altman.z!} />
              <table className="data" style={{ marginTop: 12 }}>
                <thead><tr><th className="l">Component</th><th>Ratio</th><th>× weight</th><th>Contribution</th></tr></thead>
                <tbody>
                  {a.altman.components.map((c) => (
                    <tr key={c.name} style={{ cursor: "default" }}>
                      <td className="l">{c.name}</td><td>{num(c.value, 3)}</td><td>{c.weight}</td><td>{num(c.contribution, 2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : <div className="hint">{a.altman.reason}</div>}
        </Card>
      </div>

      <Card pad={false} title="Financial trends" sub="fiscal years">
        <Trends a={a} />
      </Card>

      <div className="grid-2">
        <Card pad={false} title="Relative valuation" sub={`vs ${a.sector} median`}>
          <table className="data">
            <thead><tr><th className="l">Metric</th><th>{a.ticker}</th><th>Sector median</th><th>Verdict</th></tr></thead>
            <tbody>
              {a.relative.map((r) => {
                const isPct = !["P/E", "P/B", "EV/EBITDA"].includes(r.metric);
                const f = (x: number | null) => (isPct ? pct(x) : num(x, 1));
                const better = r.stock == null || r.sector == null ? null
                  : r.lower_is_better ? r.stock < r.sector : r.stock > r.sector;
                return (
                  <tr key={r.metric} style={{ cursor: "default" }}>
                    <td className="l">{r.metric}</td><td>{f(r.stock)}</td><td>{f(r.sector)}</td>
                    <td className={better == null ? "muted" : better ? "up" : "down"}>
                      {better == null ? "–" : better ? "Favourable" : "Unfavourable"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
        <Card title="Risk profile" sub="5 years, daily">
          <KV rows={[
            ["Annualised return", pct(a.risk.stats.cagr)],
            ["Volatility", pct(a.risk.stats.volatility)],
            ["Beta vs benchmark", num(a.risk.stats.beta)],
            ["Sharpe", num(a.risk.stats.sharpe)],
            ["Sortino", num(a.risk.stats.sortino)],
            ["VaR 95% (1 day)", pct(a.risk.stats.var_95, 2)],
            ["CVaR 95% (1 day)", pct(a.risk.stats.cvar_95, 2)],
            ["Best / worst month", `${pct(a.risk.stats.best_month)} / ${pct(a.risk.stats.worst_month)}`],
          ]} />
        </Card>
      </div>

      <div className="grid-2">
        <Card title="Drawdowns"><TimeChart series={ddSeries} height={200} format={(x) => `${(x * 100).toFixed(1)}%`} /></Card>
        <Card title="Seasonality" sub="average return by calendar month">
          <Seasonality rows={a.risk.seasonality} />
        </Card>
      </div>
      <p className="hint">
        Model outputs from public data for research and education. Not investment advice; do your own due diligence.
      </p>
    </div>
  );
}

function FootballField({ a }: { a: AnalysisResponse }) {
  const s = a.valuation.scenarios!;
  const vals = [s.bear.fair_value, s.base.fair_value, s.bull.fair_value, a.price];
  const lo = Math.min(...vals) * 0.9, hi = Math.max(...vals) * 1.05;
  const x = (v: number) => `${((v - lo) / (hi - lo)) * 100}%`;
  return (
    <div>
      <div className="ff">
        <div className="ff-bar" style={{ left: x(s.bear.fair_value), width: `calc(${x(s.bull.fair_value)} - ${x(s.bear.fair_value)})` }} />
        <div className="ff-base" style={{ left: x(s.base.fair_value) }} title="Base case" />
        <div className="ff-price" style={{ left: x(a.price) }}><span>Price {price(a.price)}</span></div>
      </div>
      <div className="grid-3" style={{ marginTop: 18, gap: 8 }}>
        {(["bear", "base", "bull"] as const).map((k) => (
          <div key={k} className="scenario">
            <div className="label" style={{ textTransform: "capitalize" }}>{k}</div>
            <div className="big">{price(s[k].fair_value)}</div>
            <div className={tone(s[k].upside)}>{signedPct(s[k].upside)}</div>
            <div className="hint">g {pct(s[k].growth)} · r {pct(s[k].discount_rate, 1)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ZGauge({ z }: { z: number }) {
  const max = 6;
  const pos = Math.max(0, Math.min(z, max)) / max * 100;
  return (
    <div>
      <div className="zg">
        <div className="zg-seg" style={{ width: `${1.81 / max * 100}%`, background: "var(--div-neg)" }} />
        <div className="zg-seg" style={{ width: `${(2.99 - 1.81) / max * 100}%`, background: "var(--div-mid)" }} />
        <div className="zg-seg" style={{ flex: 1, background: "var(--div-pos)" }} />
        <div className="zg-mark" style={{ left: `${pos}%` }} />
      </div>
      <div className="row hint" style={{ justifyContent: "space-between", marginTop: 6 }}>
        <span style={{ flex: "none" }}>Distress &lt; 1.81</span><span style={{ flex: "none" }}>Grey</span><span style={{ flex: "none" }}>Safe &gt; 2.99</span>
      </div>
    </div>
  );
}

const TREND_ROWS: [string, string, "money" | "pct"][] = [
  ["revenue", "Revenue", "money"], ["gross_profit", "Gross profit", "money"], ["operating_income", "Operating income", "money"],
  ["net_income", "Net income", "money"], ["free_cash_flow", "Free cash flow", "money"],
  ["gross_margin", "Gross margin", "pct"], ["operating_margin", "Operating margin", "pct"],
  ["net_margin", "Net margin", "pct"], ["fcf_margin", "FCF margin", "pct"],
  ["total_debt", "Total debt", "money"], ["cash", "Cash", "money"], ["shares", "Shares outstanding", "money"],
];

function Trends({ a }: { a: AnalysisResponse }) {
  const t = a.trends;
  if (!t.years.length) return <div className="empty">No financial statements available.</div>;
  return (
    <div style={{ overflowX: "auto" }}>
      <table className="data">
        <thead><tr><th className="l">Metric</th>{t.years.map((y) => <th key={y}>FY{y}</th>)}<th>CAGR</th><th className="l">Trend</th></tr></thead>
        <tbody>
          {TREND_ROWS.filter(([k]) => t.rows[k]?.some((v) => v != null)).map(([k, label, fmt]) => {
            const vals = t.rows[k];
            const cagr = t.cagr?.[k];
            return (
              <tr key={k} style={{ cursor: "default" }}>
                <td className="l">{label}</td>
                {vals.map((v, i) => <td key={i}>{fmt === "pct" ? pct(v) : k === "shares" ? (v == null ? "–" : `${(v / 1e6).toFixed(0)}M`) : money(v)}</td>)}
                <td className={tone(cagr)}>{cagr == null ? "" : signedPct(cagr)}</td>
                <td className="l"><Bars values={vals} /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Bars({ values }: { values: (number | null)[] }) {
  const nums = values.map((v) => v ?? 0);
  const max = Math.max(...nums.map(Math.abs), 1e-9);
  return (
    <span className="minibars">
      {nums.map((v, i) => (
        <span key={i} style={{ height: `${Math.max(2, (Math.abs(v) / max) * 18)}px`, background: v < 0 ? "var(--down)" : "var(--series-1)" }} />
      ))}
    </span>
  );
}

function Seasonality({ rows }: { rows: AnalysisResponse["risk"]["seasonality"] }) {
  const max = Math.max(...rows.map((r) => Math.abs(r.avg)), 0.01);
  return (
    <div className="season">
      {rows.map((r) => (
        <div key={r.month} className="season-col" title={`${MONTHS[r.month - 1]}: avg ${signedPct(r.avg)}, up ${pct(r.pct_positive, 0)} of ${r.n} years`}>
          <div className="season-plot">
            <div className="season-bar" style={{
              height: `${(Math.abs(r.avg) / max) * 50}%`,
              [r.avg >= 0 ? "bottom" : "top"]: "50%",
              background: r.avg >= 0 ? "var(--div-pos)" : "var(--div-neg)",
            }} />
          </div>
          <div className="season-lbl">{MONTHS[r.month - 1][0]}</div>
          <div className="season-val">{(r.avg * 100).toFixed(1)}</div>
        </div>
      ))}
    </div>
  );
}
