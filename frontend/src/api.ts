import type {
  AnalysisResponse, BacktestRequest, BacktestResponse, DaytradeResponse, LeaderRow, Meta, PaperResponse,
  PlansResponse, RiskResponse, ScanRow, ScreenRequest, ScreenResponse, StockResponse, TraderProfile, User,
} from "./types";

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

const TOKEN_KEY = "money.token";

export function getToken(): string | null {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch { /* storage unavailable */ }
}

async function call<T>(path: string, body?: unknown, method?: string): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(`/api${path}`, {
    method: method ?? (body === undefined ? "GET" : "POST"),
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail
        : Array.isArray(j.detail) ? j.detail.map((d: { msg: string }) => d.msg).join("; ")
        : JSON.stringify(j.detail);
    } catch { /* non-JSON error body */ }
    throw new ApiError(detail || `HTTP ${res.status}`, res.status);
  }
  return res.json() as Promise<T>;
}

export const api = {
  meta: () => call<Meta>("/meta"),
  screen: (req: ScreenRequest) => call<ScreenResponse>("/screen", req),
  stock: (ticker: string, years = 2) =>
    call<StockResponse>(`/stock/${encodeURIComponent(ticker)}?years=${years}`),
  analysis: (ticker: string) => call<AnalysisResponse>(`/analysis/${encodeURIComponent(ticker)}`),
  daytrade: (ticker: string, interval: string, days: number) =>
    call<DaytradeResponse>(`/daytrade/${encodeURIComponent(ticker)}?interval=${interval}&days=${days}`),
  scanner: () => call<{ rows: ScanRow[] }>("/scanner"),
  backtest: (req: BacktestRequest) => call<BacktestResponse>("/backtest", req),
  analyze: (weights: Record<string, number>, lookback_days = 365) =>
    call<RiskResponse>("/portfolio/analyze", { weights, lookback_days }),
  construct: (body: {
    tickers?: string[]; from_screen?: ScreenRequest; top_n?: number; method: string;
    max_weight: number;
  }) => call<{ method: string; weights: Record<string, number> }>("/portfolio/construct", body),

  // accounts & billing
  register: (email: string, password: string, display_name: string) =>
    call<{ token: string; user: User }>("/auth/register", { email, password, display_name }),
  login: (email: string, password: string) => call<{ token: string; user: User }>("/auth/login", { email, password }),
  logout: () => call<{ ok: boolean }>("/auth/logout", {}),
  me: () => call<{ user: User; billing: PlansResponse }>("/auth/me"),
  updateMe: (patch: { display_name?: string; bio?: string; is_public?: boolean }) =>
    call<{ user: User }>("/auth/me", patch, "PATCH"),
  forgot: (email: string) => call<{ ok: boolean }>("/auth/forgot", { email }),
  resetPassword: (token: string, password: string) =>
    call<{ token: string; user: User }>("/auth/reset", { token, password }),
  deleteMe: (password: string) => call<{ ok: boolean }>("/auth/me", { password }, "DELETE"),
  plans: () => call<PlansResponse>("/billing/plans"),
  checkout: (plan: string) => call<{ url: string }>("/billing/checkout", { plan }),
  portal: () => call<{ url: string }>("/billing/portal", {}),

  // trading
  paper: () => call<PaperResponse>("/paper"),
  order: (ticker: string, side: "buy" | "sell", qty: number) =>
    call<{ id: number; ticker: string; side: string; qty: number; price: number; mirrored_to: number }>(
      "/paper/order", { ticker, side, qty }),
  resetPaper: () => call<{ ok: boolean }>("/paper/reset", {}),
  leaderboard: (sort: string) => call<{ rows: LeaderRow[] }>(`/leaderboard?sort=${sort}`),
  trader: (id: number) => call<TraderProfile>(`/traders/${id}`),
  copy: (id: number, allocation: number) =>
    call<{ positions_opened: number }>(`/traders/${id}/copy`, { allocation }),
  uncopy: (id: number) => call<{ ok: boolean }>(`/traders/${id}/copy`, undefined, "DELETE"),
};
