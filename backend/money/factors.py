"""Factor metric definitions and raw metric computation.

A *metric* is a single measurable characteristic (e.g. earnings yield).
A *factor* is a family of metrics that capture the same underlying premium
(e.g. Value). Scoring (see ``scoring.py``) standardises metrics
cross-sectionally, averages them into factor scores and blends the factors
into a composite.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .data.base import Fundamentals

TRADING_DAYS = 252


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    factor: str
    higher_is_better: bool
    source: str   # "price" (derived from price history) or "fundamental"
    fmt: str      # "pct", "ratio" or "num" - a display hint for the UI
    description: str


FACTORS: dict[str, str] = {
    "value": "Cheapness relative to earnings, book, sales, EBITDA and cash flow",
    "quality": "Profitability and balance-sheet strength",
    "momentum": "Intermediate-term price trend, skipping the most recent month",
    "growth": "Year-over-year revenue and earnings growth",
    "low_vol": "Low realised volatility and market beta",
}

METRICS: list[Metric] = [
    Metric("earnings_yield", "Earnings yield", "value", True, "fundamental", "pct",
           "Trailing EPS / price (inverse P/E)"),
    Metric("book_yield", "Book yield", "value", True, "fundamental", "pct",
           "Book value / price (inverse P/B)"),
    Metric("sales_yield", "Sales yield", "value", True, "fundamental", "pct",
           "Sales / market cap (inverse P/S)"),
    Metric("ebitda_ev", "EBITDA / EV", "value", True, "fundamental", "pct",
           "Inverse EV/EBITDA; capital-structure neutral"),
    Metric("fcf_yield", "FCF yield", "value", True, "fundamental", "pct",
           "Free cash flow / market cap"),
    Metric("roe", "ROE", "quality", True, "fundamental", "pct", "Return on equity"),
    Metric("roa", "ROA", "quality", True, "fundamental", "pct", "Return on assets"),
    Metric("gross_margin", "Gross margin", "quality", True, "fundamental", "pct",
           "Gross profit / revenue"),
    Metric("operating_margin", "Operating margin", "quality", True, "fundamental", "pct",
           "Operating income / revenue"),
    Metric("debt_to_equity", "Debt / equity", "quality", False, "fundamental", "ratio",
           "Total debt / shareholder equity (lower is better)"),
    Metric("revenue_growth", "Revenue growth", "growth", True, "fundamental", "pct",
           "Year-over-year revenue growth"),
    Metric("earnings_growth", "Earnings growth", "growth", True, "fundamental", "pct",
           "Year-over-year earnings growth"),
    Metric("mom_12_1", "Momentum 12-1", "momentum", True, "price", "pct",
           "Return from 12 months to 1 month ago"),
    Metric("mom_6_1", "Momentum 6-1", "momentum", True, "price", "pct",
           "Return from 6 months to 1 month ago"),
    Metric("pct_52w_high", "% of 52w high", "momentum", True, "price", "pct",
           "Price relative to its 52-week high"),
    Metric("vol_1y", "Volatility 1y", "low_vol", False, "price", "pct",
           "Annualised daily volatility over the past year (lower is better)"),
    Metric("beta_1y", "Beta 1y", "low_vol", False, "price", "num",
           "Beta vs benchmark over the past year (lower is better)"),
]

METRIC_BY_KEY = {m.key: m for m in METRICS}
PRICE_FACTORS = sorted({m.factor for m in METRICS if m.source == "price"})


def _inv(x: float | None, positive_only: bool = True) -> float:
    if x is None or x == 0 or (positive_only and x < 0):
        return np.nan
    return 1.0 / x


def fundamental_metrics(funds: dict[str, Fundamentals]) -> pd.DataFrame:
    rows = {}
    for t, f in funds.items():
        rows[t] = {
            # A negative P/E (losses) carries information: a negative yield.
            "earnings_yield": _inv(f.pe, positive_only=False),
            "book_yield": _inv(f.pb),
            "sales_yield": _inv(f.ps),
            "ebitda_ev": _inv(f.ev_ebitda),
            "fcf_yield": f.fcf_yield,
            "roe": f.roe,
            "roa": f.roa,
            "gross_margin": f.gross_margin,
            "operating_margin": f.operating_margin,
            "debt_to_equity": f.debt_to_equity,
            "revenue_growth": f.revenue_growth,
            "earnings_growth": f.earnings_growth,
        }
    df = pd.DataFrame.from_dict(rows, orient="index", dtype=float)
    return df


def price_metric_panel(closes: pd.DataFrame, benchmark: pd.Series | None = None
                       ) -> dict[str, pd.DataFrame]:
    """Rolling price metrics for every date (value at t uses data up to t only)."""
    closes = closes.sort_index()
    logret = np.log(closes).diff()
    panel = {
        "mom_12_1": closes.shift(21) / closes.shift(252) - 1,
        "mom_6_1": closes.shift(21) / closes.shift(126) - 1,
        "pct_52w_high": closes / closes.rolling(252, min_periods=126).max(),
        "vol_1y": logret.rolling(252, min_periods=126).std() * np.sqrt(TRADING_DAYS),
    }
    if benchmark is not None and not benchmark.empty:
        b = np.log(benchmark.reindex(closes.index).ffill()).diff()
        mean_b = b.rolling(252, min_periods=126).mean()
        var_b = b.rolling(252, min_periods=126).var()
        cov = logret.mul(b, axis=0).rolling(252, min_periods=126).mean().sub(
            logret.rolling(252, min_periods=126).mean().mul(mean_b, axis=0))
        # Sample covariance correction to match var's ddof=1.
        n = logret.rolling(252, min_periods=126).count()
        panel["beta_1y"] = cov.mul(n / (n - 1)).div(var_b, axis=0)
    return panel


def price_metrics_at(panel: dict[str, pd.DataFrame], when: pd.Timestamp) -> pd.DataFrame:
    """Cross-section of price metrics as of the last row on or before ``when``."""
    out = {}
    for key, frame in panel.items():
        sub = frame.loc[:when]
        out[key] = sub.iloc[-1] if len(sub) else pd.Series(dtype=float)
    return pd.DataFrame(out)


def technicals(ohlcv: pd.DataFrame) -> dict[str, pd.Series]:
    """Chart overlays / indicators for a single stock."""
    c = ohlcv["close"]
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    ema12, ema26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    return {
        "sma50": c.rolling(50).mean(),
        "sma200": c.rolling(200).mean(),
        "rsi14": rsi,
        "macd": macd,
        "macd_signal": macd.ewm(span=9, adjust=False).mean(),
    }
