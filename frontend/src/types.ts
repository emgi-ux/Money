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
