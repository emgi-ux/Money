import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import type { Meta } from "./types";

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

interface Store {
  meta: Meta | null;
  metaError: string | null;
  watchlist: string[];
  toggleWatch: (t: string) => void;
  /** Holdings handed from the screener to the portfolio view. */
  draft: Record<string, number>;
  setDraft: (w: Record<string, number>) => void;
}

const Ctx = createContext<Store | null>(null);

export function StoreProvider({ meta, metaError, children }: { meta: Meta | null; metaError: string | null; children: ReactNode }) {
  const [watchlist, setWatchlist] = useState<string[]>(() => load("money.watchlist", []));
  const [draft, setDraft] = useState<Record<string, number>>(() => load("money.portfolio", {}));
  useEffect(() => save("money.watchlist", watchlist), [watchlist]);
  useEffect(() => save("money.portfolio", draft), [draft]);
  const toggleWatch = (t: string) =>
    setWatchlist((w) => (w.includes(t) ? w.filter((x) => x !== t) : [...w, t]));
  return (
    <Ctx.Provider value={{ meta, metaError, watchlist, toggleWatch, draft, setDraft }}>
      {children}
    </Ctx.Provider>
  );
}

export function useStore(): Store {
  const s = useContext(Ctx);
  if (!s) throw new Error("StoreProvider missing");
  return s;
}

// ------------------------------------------------------------ hash routing
export function useRoute(): string[] {
  const parse = () => (window.location.hash.replace(/^#\/?/, "") || "screener").split("/");
  const [route, setRoute] = useState(parse);
  useEffect(() => {
    const on = () => { setRoute(parse()); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

export const go = (path: string) => { window.location.hash = `#/${path}`; };
