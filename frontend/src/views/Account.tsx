import { useEffect, useState } from "react";
import { api } from "../api";
import { Card, KV } from "../components/bits";
import { go, useStore } from "../store";

export function Account({ query }: { query: URLSearchParams }) {
  const { user, refreshUser, signOut, openAuth } = useStore();
  const [name, setName] = useState(user?.display_name ?? "");
  const [bio, setBio] = useState(user?.bio ?? "");
  const [pub, setPub] = useState(Boolean(user?.is_public));
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { refreshUser(); }, [refreshUser]);
  useEffect(() => {
    if (user) { setName(user.display_name); setBio(user.bio); setPub(Boolean(user.is_public)); }
  }, [user]);

  if (!user) {
    return (
      <Card><div className="empty">
        <p>Sign in to manage your account.</p>
        <button className="btn primary" onClick={() => openAuth("login")}>Sign in</button>
      </div></Card>
    );
  }

  const save = async () => {
    setError(null);
    try {
      await api.updateMe({ display_name: name, bio, is_public: pub });
      await refreshUser();
      setMsg("Saved");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const manage = async () => {
    try {
      const { url } = await api.portal();
      window.location.href = url;
      if (url.includes("#")) { await refreshUser(); }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <>
      <div className="page-head"><h1>Account</h1><span className="sub">{user.email}</span></div>
      {query.get("checkout") === "success" && <div className="success">Welcome to Pro! Your subscription is active.</div>}
      {error && <div className="error">{error}</div>}
      <div className="grid-2">
        <Card title="Subscription">
          <KV rows={[
            ["Plan", user.is_pro ? <b>Pro {user.plan_interval === "week" ? "weekly" : "monthly"}</b> : "Free"],
            ["Status", user.plan_status ?? "–"],
            ["Renews", user.plan_renews_at ? new Date(user.plan_renews_at).toLocaleDateString() : "–"],
          ]} />
          <div className="row" style={{ marginTop: 16 }}>
            {user.is_pro
              ? <button className="btn" onClick={manage}>Manage billing</button>
              : <button className="btn primary" onClick={() => go("pricing")}>Upgrade to Pro</button>}
          </div>
        </Card>
        <Card title="Public profile" sub="how you appear on the leaderboard">
          <div className="field"><label>Display name</label><input type="text" value={name} onChange={(e) => setName(e.target.value)} /></div>
          <div className="field"><label>Bio</label><input type="text" maxLength={280} value={bio} onChange={(e) => setBio(e.target.value)} placeholder="Your strategy in a sentence" /></div>
          <label className="check" style={{ marginBottom: 14 }}>
            <input type="checkbox" checked={pub} onChange={(e) => setPub(e.target.checked)} />
            Show me on the leaderboard and let others copy my paper trades
          </label>
          <div className="row">
            <button className="btn primary" onClick={save}>Save</button>
            {msg && <span className="hint">{msg}</span>}
          </div>
        </Card>
      </div>
      <div style={{ marginTop: 16 }}>
        <button className="btn" onClick={() => { signOut(); go("screener"); }}>Sign out</button>
      </div>
    </>
  );
}
