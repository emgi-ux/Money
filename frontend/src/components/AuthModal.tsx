import { useState, type FormEvent } from "react";
import { api } from "../api";
import { useStore } from "../store";

const TITLES = { login: "Sign in", register: "Create your account", forgot: "Reset your password" } as const;

export function AuthModal() {
  const { authMode, openAuth, signedIn } = useStore();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!authMode) return null;
  const register = authMode === "register";
  const forgot = authMode === "forgot";

  const switchTo = (mode: typeof authMode) => { setError(null); setNotice(null); openAuth(mode); };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (forgot) {
        await api.forgot(email);
        setNotice("If an account exists for that email, a reset link is on its way. It expires in 1 hour.");
      } else {
        const r = register ? await api.register(email, password, name) : await api.login(email, password);
        signedIn(r.token, r.user);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={() => openAuth(null)}>
      <form className="modal card" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <div className="card-head">
          <h2>{TITLES[authMode]}</h2>
          <div className="right"><button type="button" className="icon-btn" onClick={() => openAuth(null)} aria-label="Close">×</button></div>
        </div>
        <div className="card-body">
          {error && <div className="error">{error}</div>}
          {notice && <div className="success">{notice}</div>}
          <div className="field"><label>Email</label>
            <input type="text" inputMode="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></div>
          {register && (
            <div className="field"><label>Display name (shown on the leaderboard)</label>
              <input type="text" value={name} onChange={(e) => setName(e.target.value)} required /></div>
          )}
          {!forgot && (
            <div className="field">
              <label className="row" style={{ justifyContent: "space-between" }}>
                <span style={{ flex: "none" }}>Password</span>
                {!register && (
                  <a href="#" style={{ flex: "none", fontSize: 12 }} onClick={(e) => { e.preventDefault(); switchTo("forgot"); }}>
                    Forgot password?
                  </a>
                )}
              </label>
              <input type="password" autoComplete={register ? "new-password" : "current-password"} value={password}
                onChange={(e) => setPassword(e.target.value)} required minLength={register ? 8 : 1} />
            </div>
          )}
          <button className="btn primary" style={{ width: "100%" }} disabled={busy || (forgot && notice !== null)}>
            {busy ? "…" : forgot ? "Email me a reset link" : register ? "Create account" : "Sign in"}
          </button>
          <p className="hint" style={{ textAlign: "center", marginTop: 12 }}>
            {forgot ? "Remembered it? " : register ? "Already have an account? " : "New here? "}
            <a href="#" onClick={(e) => { e.preventDefault(); switchTo(register ? "login" : forgot ? "login" : "register"); }}>
              {register || forgot ? "Sign in" : "Create an account"}
            </a>
          </p>
        </div>
      </form>
    </div>
  );
}
