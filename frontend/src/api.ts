import type {
  BacktestRequest, BacktestResponse, Meta, RiskResponse, ScreenRequest, ScreenResponse,
  StockResponse,
} from "./types";

async function call<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, body === undefined ? undefined : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch { /* non-JSON error body */ }
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  meta: () => call<Meta>("/meta"),
  screen: (req: ScreenRequest) => call<ScreenResponse>("/screen", req),
  stock: (ticker: string, years = 2) =>
    call<StockResponse>(`/stock/${encodeURIComponent(ticker)}?years=${years}`),
  backtest: (req: BacktestRequest) => call<BacktestResponse>("/backtest", req),
  analyze: (weights: Record<string, number>, lookback_days = 365) =>
    call<RiskResponse>("/portfolio/analyze", { weights, lookback_days }),
  construct: (body: {
    tickers?: string[]; from_screen?: ScreenRequest; top_n?: number; method: string;
    max_weight: number;
  }) => call<{ method: string; weights: Record<string, number> }>("/portfolio/construct", body),
};
