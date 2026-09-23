import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { ApiError, api, getToken, setToken } from "./api";
import type { Meta, User } from "./types";

function load<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function save(key: string, value: unknown) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* ignore */ }
}

type AuthMode = "login" | "register" | "forgot" | null;

interface Store {
  meta: Meta | null;
  metaError: string | null;
  watchlist: string[];
  toggleWatch: (t: string) => void;
  /** Holdings handed from the screener to the portfolio view. */
  draft: Record<string, number>;
  setDraft: (w: Record<string, number>) => void;
  user: User | null;
  refreshUser: () => Promise<void>;
  signedIn: (token: string, user: User) => void;
  signOut: () => void;
  authMode: AuthMode;
  openAuth: (mode: AuthMode) => void;
}

const Ctx = createContext<Store | null>(null);

export function StoreProvider({ meta, metaError, children }: { meta: Meta | null; metaError: string | null; children: ReactNode }) {
  const [watchlist, setWatchlist] = useState<string[]>(() => load("money.watchlist", []));
  const [draft, setDraft] = useState<Record<string, number>>(() => load("money.portfolio", {}));
  const [user, setUser] = useState<User | null>(null);
  const [authMode, openAuth] = useState<AuthMode>(null);
  useEffect(() => save("money.watchlist", watchlist), [watchlist]);
  useEffect(() => save("money.portfolio", draft), [draft]);

  const refreshUser = useCallback(async () => {
    if (!getToken()) { setUser(null); return; }
    try {
      setUser((await api.me()).user);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) { setToken(null); setUser(null); }
    }
  }, []);
  useEffect(() => { refreshUser(); }, [refreshUser]);

  const signedIn = (token: string, u: User) => { setToken(token); setUser(u); openAuth(null); };
  const signOut = () => { api.logout().catch(() => {}); setToken(null); setUser(null); };
  const toggleWatch = (t: string) =>
    setWatchlist((w) => (w.includes(t) ? w.filter((x) => x !== t) : [...w, t]));

  return (
    <Ctx.Provider value={{ meta, metaError, watchlist, toggleWatch, draft, setDraft, user, refreshUser,
      signedIn, signOut, authMode, openAuth }}>
      {children}
    </Ctx.Provider>
  );
}

export function useStore(): Store {
  const s = useContext(Ctx);
  if (!s) throw new Error("StoreProvider missing");
  return s;
}

/** Load data with loading/error state; ``deps`` re-trigger the request. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    let live = true;
    setLoading(true);
    fn().then((d) => { if (live) { setData(d); setError(null); } })
      .catch((e) => live && setError(e))
      .finally(() => live && setLoading(false));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);
  return { data, error, loading, reload: () => setNonce((n) => n + 1) };
}

// ------------------------------------------------------------ hash routing
function parseHash(): { parts: string[]; query: URLSearchParams } {
  const raw = window.location.hash.replace(/^#\/?/, "");
  const [path, qs = ""] = raw.split("?");
  return { parts: (path || "screener").split("/"), query: new URLSearchParams(qs) };
}

export function useRoute() {
  const [route, setRoute] = useState(parseHash);
  useEffect(() => {
    const on = () => { setRoute(parseHash()); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

export const go = (path: string) => { window.location.hash = `#/${path}`; };
