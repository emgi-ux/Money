import { useEffect, useState, type FormEvent } from "react";
import { api } from "./api";
import { AuthModal } from "./components/AuthModal";
import { StoreProvider, go, useRoute, useStore } from "./store";
import { useTheme } from "./theme";
import type { Meta } from "./types";
import { Screener } from "./views/Screener";
import { StockView } from "./views/StockView";
import { Backtest } from "./views/Backtest";
import { Portfolio } from "./views/Portfolio";
import { Analysis } from "./views/Analysis";
import { DayTrade } from "./views/DayTrade";
import { Pricing } from "./views/Pricing";
import { Account } from "./views/Account";
import { Trade } from "./views/Trade";
import { Leaders, Trader } from "./views/Leaders";
import { ResetPassword } from "./views/ResetPassword";

const NAV = [
  { id: "screener", label: "Screener", icon: "M4 6h16M7 12h10M10 18h4" },
  { id: "daytrade", label: "Day Trade", icon: "M4 18l5-6 4 3 7-9" },
  { id: "leaders", label: "Top Traders", icon: "M8 21h8M12 17v4M7 4h10v5a5 5 0 01-10 0V4z" },
  { id: "trade", label: "Paper", icon: "M3 7h18v12H3zM3 11h18" },
  { id: "backtest", label: "Backtest", icon: "M4 20V10M10 20V4M16 20v-7M22 20H2" },
  { id: "portfolio", label: "Risk", icon: "M12 3a9 9 0 109 9h-9z" },
];

export function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [metaError, setMetaError] = useState<string | null>(null);
  useEffect(() => {
    api.meta().then(setMeta).catch((e) => setMetaError(String(e.message ?? e)));
  }, []);
  return (
    <StoreProvider meta={meta} metaError={metaError}>
      <Shell />
    </StoreProvider>
  );
}

function Shell() {
  const { meta, metaError, user, openAuth } = useStore();
  const { parts, query } = useRoute();
  const { theme, toggle } = useTheme();
  const [q, setQ] = useState("");
  const view = parts[0];
  const arg = parts[1];
  // Navigating (links, back button, emailed reset links) dismisses any open sign-in dialog.
  useEffect(() => { openAuth(null); }, [view, arg, openAuth]);

  const onSearch = (e: FormEvent) => {
    e.preventDefault();
    const t = q.trim().toUpperCase();
    if (t) { go(`stock/${t}`); setQ(""); }
  };

  const active = (id: string) => view === id || (id === "leaders" && view === "trader");

  return (
    <div className="app">
      <div>
        <header className="topbar">
          <a className="brand" href="#/screener">
            <span className="brand-mark">
              <svg width="14" height="14" viewBox="0 0 32 32"><path d="M5 23l7-8 6 5 9-12" stroke="#fff" strokeWidth="4" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
            </span>
            Money
          </a>
          <nav className="nav desktop-only">
            {NAV.map((n) => (
              <a key={n.id} href={`#/${n.id}`} className={active(n.id) ? "active" : ""}>{n.label}</a>
            ))}
          </nav>
          <div className="spacer" />
          <form onSubmit={onSearch} className="search-form">
            <input className="search" placeholder="Ticker…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Go to ticker" />
          </form>
          {meta && <span className="pill desktop-only" title="Data provider">data: {meta.provider}</span>}
          {user ? (
            <a href="#/account" className="account-chip" title={user.email}>
              <span className="avatar">{user.display_name[0]?.toUpperCase()}</span>
              <span className="desktop-only">{user.display_name}</span>
              {user.is_pro && <span className="pro-badge">PRO</span>}
            </a>
          ) : (
            <>
              <button className="btn sm desktop-only" onClick={() => openAuth("login")}>Sign in</button>
              <button className="btn sm primary" onClick={() => (meta?.paywall ? go("pricing") : openAuth("register"))}>
                {meta?.paywall ? "Go Pro" : "Sign up"}
              </button>
            </>
          )}
          {user && !user.is_pro && meta?.paywall && (
            <button className="btn sm primary desktop-only" onClick={() => go("pricing")}>Upgrade</button>
          )}
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
        {view === "stock" && arg ? <StockView ticker={arg.toUpperCase()} key={arg} />
          : view === "analysis" && arg ? <Analysis ticker={arg.toUpperCase()} key={arg} />
          : view === "daytrade" ? <DayTrade ticker={(arg ?? "AAPL").toUpperCase()} key={arg ?? "AAPL"} />
          : view === "backtest" ? <Backtest />
          : view === "portfolio" ? <Portfolio />
          : view === "pricing" ? <Pricing />
          : view === "account" ? <Account query={query} />
          : view === "trade" ? <Trade />
          : view === "leaders" ? <Leaders />
          : view === "trader" && arg ? <Trader id={Number(arg)} key={arg} />
          : view === "reset" ? <ResetPassword token={query.get("token")} />
          : <Screener />}
      </main>
      <nav className="tabbar mobile-only">
        {NAV.slice(0, 5).map((n) => (
          <a key={n.id} href={`#/${n.id}`} className={active(n.id) ? "active" : ""}>
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d={n.icon} /></svg>
            <span>{n.label}</span>
          </a>
        ))}
      </nav>
      <AuthModal />
    </div>
  );
}
