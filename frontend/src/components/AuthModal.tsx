import { useState, type FormEvent } from "react";
import { api } from "../api";
import { useStore } from "../store";

export function AuthModal() {
  const { authMode, openAuth, signedIn } = useStore();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!authMode) return null;
  const register = authMode === "register";

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = register ? await api.register(email, password, name) : await api.login(email, password);
      signedIn(r.token, r.user);
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
          <h2>{register ? "Create your account" : "Sign in"}</h2>
          <div className="right"><button type="button" className="icon-btn" onClick={() => openAuth(null)} aria-label="Close">×</button></div>
        </div>
        <div className="card-body">
          {error && <div className="error">{error}</div>}
          <div className="field"><label>Email</label>
            <input type="text" inputMode="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></div>
          {register && (
            <div className="field"><label>Display name (shown on the leaderboard)</label>
              <input type="text" value={name} onChange={(e) => setName(e.target.value)} required /></div>
          )}
          <div className="field"><label>Password</label>
            <input type="password" autoComplete={register ? "new-password" : "current-password"} value={password}
              onChange={(e) => setPassword(e.target.value)} required minLength={register ? 8 : 1} /></div>
          <button className="btn primary" style={{ width: "100%" }} disabled={busy}>
            {busy ? "…" : register ? "Create account" : "Sign in"}
          </button>
          <p className="hint" style={{ textAlign: "center", marginTop: 12 }}>
            {register ? "Already have an account? " : "New here? "}
            <a href="#" onClick={(e) => { e.preventDefault(); openAuth(register ? "login" : "register"); }}>
              {register ? "Sign in" : "Create an account"}
            </a>
          </p>
        </div>
      </form>
    </div>
  );
}
