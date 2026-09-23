import { useState, type FormEvent } from "react";
import { api } from "../api";
import { Card } from "../components/bits";
import { go, useStore } from "../store";

export function ResetPassword({ token }: { token: string | null }) {
  const { signedIn, openAuth } = useStore();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (password !== confirm) { setError("Passwords don't match"); return; }
    setBusy(true);
    setError(null);
    try {
      const r = await api.resetPassword(token ?? "", password);
      signedIn(r.token, r.user);
      go("account");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ maxWidth: 420, margin: "24px auto" }}>
      <Card title="Choose a new password">
        {!token ? (
          <div className="hint">This link is missing its token. <a href="#" onClick={(e) => { e.preventDefault(); openAuth("forgot"); }}>Request a new link</a>.</div>
        ) : (
          <form onSubmit={submit}>
            {error && <div className="error">{error}</div>}
            <div className="field"><label>New password (8+ characters)</label>
              <input type="password" autoComplete="new-password" minLength={8} required value={password} onChange={(e) => setPassword(e.target.value)} /></div>
            <div className="field"><label>Confirm new password</label>
              <input type="password" autoComplete="new-password" minLength={8} required value={confirm} onChange={(e) => setConfirm(e.target.value)} /></div>
            <button className="btn primary" style={{ width: "100%" }} disabled={busy}>{busy ? "…" : "Set password and sign in"}</button>
            <p className="hint" style={{ marginTop: 10 }}>This signs you out on every other device.</p>
          </form>
        )}
      </Card>
    </div>
  );
}
