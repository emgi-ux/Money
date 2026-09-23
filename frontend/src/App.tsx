import { useEffect, useState, type FormEvent } from "react";
import { api } from "./api";
import { StoreProvider, go, useRoute } from "./store";
import { useTheme } from "./theme";
import type { Meta } from "./types";
import { Screener } from "./views/Screener";
import { StockView } from "./views/StockView";
import { Backtest } from "./views/Backtest";
import { Portfolio } from "./views/Portfolio";

const NAV = [
  { id: "screener", label: "Screener" },
  { id: "backtest", label: "Backtest" },
  { id: "portfolio", label: "Portfolio & Risk" },
];

export function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [metaError, setMetaError] = useState<string | null>(null);
  const route = useRoute();
  const { theme, toggle } = useTheme();
  const [q, setQ] = useState("");

  useEffect(() => {
    api.meta().then(setMeta).catch((e) => setMetaError(String(e.message ?? e)));
  }, []);

  const onSearch = (e: FormEvent) => {
    e.preventDefault();
    const t = q.trim().toUpperCase();
    if (t) { go(`stock/${t}`); setQ(""); }
  };

  const view = route[0];
  return (
    <StoreProvider meta={meta} metaError={metaError}>
      <div className="app">
        <div>
          <header className="topbar">
            <div className="brand">
              <span className="brand-mark">
                <svg width="14" height="14" viewBox="0 0 32 32"><path d="M5 23l7-8 6 5 9-12" stroke="#fff" strokeWidth="4" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
              </span>
              Money
            </div>
            <nav className="nav">
              {NAV.map((n) => (
                <a key={n.id} href={`#/${n.id}`} className={view === n.id ? "active" : ""}>{n.label}</a>
              ))}
            </nav>
            <div className="spacer" />
            <form onSubmit={onSearch}>
              <input className="search" placeholder="Go to ticker…" value={q} onChange={(e) => setQ(e.target.value)} />
            </form>
            {meta && <span className="pill" title="Data provider">data: {meta.provider}</span>}
            <button className="icon-btn" onClick={toggle} title="Toggle theme" aria-label="Toggle theme">
              {theme === "dark" ? "☀" : "☾"}
            </button>
          </header>
          {meta?.provider === "synthetic" && (
            <div className="banner">
              <b>Demo data.</b> Prices and fundamentals are simulated. Start the server with{" "}
              <code>MONEY_PROVIDER=yahoo</code> for live market data.
            </div>
          )}
        </div>
        <main className="page">
          {metaError && <div className="error">Cannot reach the API ({metaError}). Is the backend running on port 8000?</div>}
          {view === "stock" && route[1] ? <StockView ticker={route[1].toUpperCase()} key={route[1]} />
            : view === "backtest" ? <Backtest />
            : view === "portfolio" ? <Portfolio />
            : <Screener />}
        </main>
      </div>
    </StoreProvider>
  );
}
