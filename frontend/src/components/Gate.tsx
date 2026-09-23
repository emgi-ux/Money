import type { ReactNode } from "react";
import { ApiError } from "../api";
import { go, useStore } from "../store";

const PRO_FEATURES = [
  "Deep analysis: DCF fair value, F-Score, Altman Z, bull/bear thesis",
  "Day trading desk: VWAP, opening range, pivots, live signals, gap scanner",
  "Strategy backtester and portfolio optimizer",
  "Copy top traders into your paper account",
];

/** Renders children, or a sign-in / upgrade panel when the API says 401 / 402. */
export function Gate({ error, children, feature }: { error: unknown; children?: ReactNode; feature: string }) {
  const { openAuth, user } = useStore();
  if (error instanceof ApiError && (error.status === 401 || error.status === 402)) {
    const needsLogin = error.status === 401 || !user;
    return (
      <div className="paywall card">
        <div className="paywall-badge">PRO</div>
        <h2>{feature} is a Pro feature</h2>
        <p className="muted">{needsLogin ? "Create a free account, then start your Pro trial." : "Upgrade to unlock it, along with:"}</p>
        <ul>{PRO_FEATURES.map((f) => <li key={f}>{f}</li>)}</ul>
        <div className="row" style={{ justifyContent: "center", gap: 10 }}>
          {needsLogin ? (
            <>
              <button className="btn primary" onClick={() => openAuth("register")}>Create account</button>
              <button className="btn" onClick={() => openAuth("login")}>Sign in</button>
            </>
          ) : (
            <button className="btn primary" onClick={() => go("pricing")}>See plans</button>
          )}
        </div>
      </div>
    );
  }
  if (error) return <div className="error">{error instanceof Error ? error.message : String(error)}</div>;
  return <>{children}</>;
}
