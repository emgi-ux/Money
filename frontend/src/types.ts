export type FactorKey = "value" | "quality" | "momentum" | "growth" | "low_vol";
export type Weights = Partial<Record<FactorKey, number>>;

export interface MetricDef {
  key: string;
  label: string;
  factor: FactorKey;
  higher_is_better: boolean;
  source: "price" | "fundamental";
  fmt: "pct" | "ratio" | "num";
  description: string;
}

export interface Meta {
  version: string;
  provider: string;
  benchmark: string;
  universes: Record<string, number>;
  factors: Record<FactorKey, string>;
  price_factors: FactorKey[];
  default_weights: Weights;
  metrics: MetricDef[];
  weighting_methods: Record<string, string>;
  sectors: string[];
  paywall: boolean;
}

export interface ScreenRow {
  ticker: string;
  name: string;
  sector: string;
  market_cap: number | null;
  price: number | null;
  pe: number | null;
  forward_pe: number | null;
  pb: number | null;
  dividend_yield: number | null;
  beta: number | null;
  sma200_gap: number | null;
  ret_1m: number | null;
  value: number | null;
  quality: number | null;
  momentum: number | null;
  growth: number | null;
  low_vol: number | null;
  composite: number | null;
  score: number | null;
  rank: number | null;
  grade: string;
  [key: string]: unknown;
}

export interface ScreenRequest {
  universe?: string | string[];
  weights: Weights;
  sector_neutral: boolean;
  min_market_cap?: number | null;
  max_pe?: number | null;
  min_dividend_yield?: number | null;
  max_debt_to_equity?: number | null;
  max_vol?: number | null;
  above_sma200?: boolean;
  sectors?: string[];
  exclude_sectors?: string[];
  limit?: number | null;
}

export interface ScreenResponse {
  as_of: string;
  universe_size: number;
  count: number;
  missing: string[];
  rows: ScreenRow[];
}

export interface Point { time: string; value: number }

export interface Candle {
  time: string; open: number; high: number; low: number; close: number; volume: number;
}

export interface StockResponse {
  ticker: string;
  fundamentals: Record<string, number | string | null> | null;
  profile: Partial<ScreenRow>;
  peers: (Partial<ScreenRow> & { is_self: boolean })[];
  returns: Record<string, number | null>;
  candles: Candle[];
  overlays: Record<"sma50" | "sma200" | "rsi14" | "macd" | "macd_signal", Point[]>;
}

export type Stats = Record<string, number | null>;

export interface BacktestRequest {
  universe?: string | string[];
  start: string;
  end: string;
  weights: Weights;
  top_n: number;
  rebalance: "monthly" | "quarterly";
  weighting: string;
  max_weight: number;
  cost_bps: number;
  sector_neutral: boolean;
}

export interface BacktestResponse {
  summary: { strategy: Stats; benchmark: Stats; universe: Stats };
  equity: { strategy: Point[]; benchmark: Point[]; universe: Point[] };
  drawdown: { strategy: Point[]; benchmark: Point[] };
  monthly: { year: number; month: number; ret: number }[];
  holdings: { date: string; positions: { ticker: string; weight: number; score: number }[] }[];
}

export interface RiskResponse {
  as_of: string;
  observations: number;
  summary: Stats;
  positions: {
    ticker: string; name: string; sector: string; weight: number; volatility: number;
    beta: number | null; risk_contribution: number; return: number;
  }[];
  sectors: { sector: string; weight: number; risk_contribution: number }[];
  correlation: { tickers: string[]; matrix: number[][] };
  equity: Point[];
  benchmark_equity: Point[];
  drawdown: Point[];
}

// ------------------------------------------------------------- deep analysis
export interface Scenario { growth: number; discount_rate: number; fair_value: number; upside: number; terminal_share: number }

export interface AnalysisResponse {
  ticker: string; name: string; sector: string; price: number; as_of: string;
  thesis: { rating: string; rating_score: number; bull: string[]; bear: string[] };
  valuation: {
    available: boolean; reason?: string; method: string;
    normalized_fcf?: number; shares?: number; base_growth?: number; historical_revenue_cagr?: number | null;
    discount_rate?: number; terminal_growth?: number; fair_value?: number; upside?: number;
    margin_of_safety?: number; implied_growth?: number | null;
    scenarios?: Record<"bear" | "base" | "bull", Scenario>;
    projected_fcf?: number[];
    sensitivity?: { discount_rates: number[]; terminal_growth: number[]; values: (number | null)[][] };
  };
  piotroski: {
    available: boolean; reason?: string; score?: number; evaluated?: number; label?: string;
    checks?: { name: string; group: string; pass: boolean | null; detail: string }[];
  };
  altman: {
    available: boolean; reason?: string; z?: number; zone?: string;
    components?: { name: string; weight: number; value: number; contribution: number }[];
  };
  trends: { years: number[]; rows: Record<string, (number | null)[]>; cagr?: Record<string, number | null> };
  risk: {
    stats: Stats; drawdown: Point[]; rolling_vol: Point[];
    histogram: { lo: number; hi: number; count: number }[];
    seasonality: { month: number; avg: number; pct_positive: number; n: number }[];
  };
  relative: { metric: string; stock: number | null; sector: number | null; lower_is_better: boolean }[];
}

// ---------------------------------------------------------------- day trading
export interface TimePoint { time: number; value: number }
export interface IntradayCandle { time: number; open: number; high: number; low: number; close: number; volume: number }

export interface DaytradeResponse {
  ticker: string; interval: string; session: string;
  candles: IntradayCandle[];
  overlays: Record<"vwap" | "vwap_u1" | "vwap_l1" | "vwap_u2" | "vwap_l2" | "ema9" | "ema21" | "rsi", TimePoint[]>;
  levels: {
    opening_range_high: number; opening_range_low: number; prev_close: number;
    prev_high: number | null; prev_low: number | null; hod: number; lod: number; pivots: Record<string, number>;
  };
  summary: {
    price: number; change: number; gap: number; vwap: number; vs_vwap: number; rsi: number | null;
    rvol: number | null; bar_atr: number; daily_atr: number | null; day_range_used: number | null;
    bias: string; long_stop: number; short_stop: number;
  };
  signals: { time: number; clock: string; price: number; kind: string; direction: "long" | "short"; text: string }[];
}

export interface ScanRow {
  ticker: string; price: number; change: number; gap: number; rvol: number | null; volume: number;
  atr_pct: number | null; range_vs_atr: number | null; close_in_range: number | null;
  dist_20d_high: number; setups: string[]; spark: Point[];
}

// ----------------------------------------------------------- accounts/billing
export interface User {
  id: number; email: string; display_name: string; bio: string; is_public: number; is_bot: number;
  created_at: string; plan: string; plan_interval: string | null; plan_status: string | null;
  plan_renews_at: string | null; is_pro: boolean;
}

export interface Plan { id: string; interval: string; price: string; trial_days: number; badge?: string }
export interface PlansResponse { mode: "stripe" | "dev" | "off"; plans: Plan[] }

// -------------------------------------------------------------------- trading
export interface Trade {
  id: number; ticker: string; side: "buy" | "sell"; qty: number; price: number; ts: string;
  source: string; leader_id: number | null;
}

export interface PaperResponse {
  cash: number; starting_cash: number; market_value: number; equity: number; total_return: number;
  realized_pnl: number;
  positions: { ticker: string; qty: number; avg_cost: number; price: number; value: number;
    unrealized: number; unrealized_pct: number | null; weight: number }[];
  trades: Trade[];
  equity_curve: Point[];
  copying: { leader_id: number; allocation: number; created_at: string; display_name: string; is_bot: number }[];
}

export interface TraderStats {
  equity: number; total_return: number; return_1m: number; return_3m: number; volatility: number | null;
  sharpe: number | null; max_drawdown: number; win_rate: number | null; trades: number;
  realized_pnl: number; followers: number; since: string;
}

export interface LeaderRow extends TraderStats {
  id: number; rank: number; display_name: string; bio: string; is_bot: number; top_holdings: string[];
}

export interface TraderProfile {
  trader: { id: number; display_name: string; bio: string; is_bot: number; is_public: number; created_at: string };
  stats: TraderStats;
  positions: { ticker: string; weight: number; unrealized_pct: number | null }[];
  trades: { ticker: string; side: string; qty: number; price: number; ts: string }[];
  equity_curve: Point[];
  is_copying: boolean;
}
