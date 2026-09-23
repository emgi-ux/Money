import { useState } from "react";
import { api } from "../api";
import { useLoad, useStore } from "../store";

const FREE = [
  "Multi-factor stock screener",
  "Stock charts, fundamentals and factor grades",
  "Paper trading with a $100k virtual account",
  "Public leaderboard",
];
const PRO = [
  "Everything in Free",
  "Deep analysis: DCF, F-Score, Altman Z, thesis",
  "Day trading desk + gap / volume scanner",
  "Strategy backtester (10+ years)",
  "Portfolio optimizer and risk analytics",
  "Copy top traders automatically",
];

export function Pricing() {
  const { user, openAuth } = useStore();
  const { data } = useLoad(() => api.plans(), []);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const subscribe = async (plan: string) => {
    if (!user) { openAuth("register"); return; }
    setBusy(plan);
    setError(null);
    try {
      const { url } = await api.checkout(plan);
      window.location.href = url;
      if (url.includes("#")) window.location.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(null);
    }
  };

  return (
    <div className="pricing">
      <div style={{ textAlign: "center", marginBottom: 28 }}>
        <h1 style={{ fontSize: 30, margin: "10px 0 8px" }}>Invest with an edge</h1>
        <p className="muted" style={{ fontSize: 15, margin: 0 }}>
          Institutional-grade factor research, day-trading tools and copy trading. Cancel anytime.
        </p>
      </div>
      {data?.mode === "off" && (
        <div className="banner" style={{ borderRadius: 8, marginBottom: 20, border: "1px solid rgba(250,178,25,.25)" }}>
          <b>Billing is disabled on this server</b>, so every Pro feature is already unlocked. Set <code>STRIPE_SECRET_KEY</code> to start charging.
        </div>
      )}
      {data?.mode === "dev" && (
        <div className="banner" style={{ borderRadius: 8, marginBottom: 20 }}>
          <b>Dev billing mode:</b> checkout activates Pro instantly without payment.
        </div>
      )}
      {error && <div className="error">{error}</div>}
      <div className="plans">
        <div className="plan card">
          <div className="plan-name">Free</div>
          <div className="plan-price">$0</div>
          <div className="hint">forever</div>
          <ul>{FREE.map((f) => <li key={f}>{f}</li>)}</ul>
          <button className="btn" disabled>{user ? "Current plan" : "Included"}</button>
        </div>
        {(data?.plans ?? []).map((p) => (
          <div key={p.id} className={`plan card ${p.badge ? "featured" : ""}`}>
            {p.badge && <div className="plan-badge">{p.badge}</div>}
            <div className="plan-name">Pro {p.interval === "week" ? "Weekly" : "Monthly"}</div>
            <div className="plan-price">{p.price}<span>/{p.interval}</span></div>
            <div className="hint">{p.trial_days ? `${p.trial_days}-day free trial` : "billed " + (p.interval === "week" ? "weekly" : "monthly")}</div>
            <ul>{PRO.map((f) => <li key={f}>{f}</li>)}</ul>
            {user?.is_pro ? (
              <button className="btn" disabled>You're Pro</button>
            ) : (
              <button className={`btn ${p.badge ? "primary" : ""}`} disabled={busy !== null || data?.mode === "off"} onClick={() => subscribe(p.id)}>
                {busy === p.id ? "Redirecting…" : p.trial_days ? "Start free trial" : "Subscribe"}
              </button>
            )}
          </div>
        ))}
      </div>
      <p className="hint" style={{ textAlign: "center", marginTop: 24 }}>
        Payments are processed securely by Stripe. Money provides research tools and simulated trading only, not
        investment advice. Past performance, including of traders on the leaderboard, does not guarantee future results.
      </p>
    </div>
  );
}
