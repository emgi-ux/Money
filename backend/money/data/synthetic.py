"""Deterministic synthetic market for demos, offline development and tests.

Returns follow a simple factor structure so that the analytics behave the way
they would on real data:

    r_i,t = alpha_i,t + beta_i * market_t + sector_s,t + eps_i,t

``alpha_i,t`` is a slowly mean-reverting AR(1) process, so trailing momentum
carries a (weak) signal, and it is tilted towards stocks with better
quality/value fundamentals. None of this is real market data; names are
suffixed with "(demo)" to make that obvious in the UI.
"""

from __future__ import annotations

import zlib
from datetime import date
from functools import lru_cache

import numpy as np
import pandas as pd

from ..universe import known_sector
from .base import DataProvider, Fundamentals

_START = pd.Timestamp("2012-01-03")
_END = pd.Timestamp("2030-12-31")
_TRADING_DAYS = 252

SECTORS = [
    "Information Technology", "Communication Services", "Consumer Discretionary",
    "Consumer Staples", "Health Care", "Financials", "Industrials", "Energy",
    "Utilities", "Real Estate", "Materials",
]

# (pe, pb, gross margin, op margin, roe, rev growth, dividend yield, d/e)
_SECTOR_PROFILE: dict[str, tuple[float, ...]] = {
    "Information Technology": (30, 9.0, 0.60, 0.28, 0.30, 0.12, 0.008, 0.6),
    "Communication Services": (22, 4.0, 0.55, 0.22, 0.18, 0.08, 0.012, 0.9),
    "Consumer Discretionary": (25, 7.0, 0.38, 0.12, 0.25, 0.08, 0.010, 1.2),
    "Consumer Staples": (22, 6.0, 0.40, 0.15, 0.28, 0.04, 0.028, 1.1),
    "Health Care": (20, 5.0, 0.62, 0.20, 0.20, 0.07, 0.018, 0.8),
    "Financials": (14, 1.6, 0.55, 0.30, 0.12, 0.06, 0.022, 1.8),
    "Industrials": (21, 5.0, 0.30, 0.14, 0.22, 0.06, 0.017, 1.0),
    "Energy": (11, 2.0, 0.35, 0.16, 0.16, 0.03, 0.035, 0.5),
    "Utilities": (18, 2.2, 0.45, 0.22, 0.10, 0.04, 0.034, 1.6),
    "Real Estate": (35, 2.5, 0.65, 0.30, 0.08, 0.05, 0.035, 1.2),
    "Materials": (17, 3.0, 0.32, 0.15, 0.14, 0.04, 0.022, 0.7),
}


def _seed(*parts: str) -> int:
    return zlib.crc32("|".join(parts).encode())


def _calendar() -> pd.DatetimeIndex:
    return pd.bdate_range(_START, _END)


@lru_cache(maxsize=1)
def _common_factors() -> tuple[pd.Series, pd.DataFrame]:
    """Market and sector daily returns shared by every synthetic stock."""
    idx = _calendar()
    rng = np.random.default_rng(_seed("market"))
    n = len(idx)
    # Market: ~8% drift, ~16% vol, with volatility clustering (GARCH-lite).
    long_run = 0.16 / np.sqrt(_TRADING_DAYS)
    drift = 0.08 / _TRADING_DAYS
    vol = np.empty(n)
    vol[0] = long_run
    shocks = rng.standard_normal(n)
    mkt = np.empty(n)
    for t in range(n):
        if t > 0:
            # GARCH(1,1): omega + alpha * eps^2 + beta * sigma^2, persistence 0.98.
            vol[t] = np.sqrt(0.02 * long_run**2 + 0.08 * (mkt[t - 1] - drift) ** 2
                             + 0.90 * vol[t - 1] ** 2)
        mkt[t] = drift + vol[t] * shocks[t]
    market = pd.Series(mkt, index=idx, name="market")

    sector_rets = {}
    for s in SECTORS:
        r = np.random.default_rng(_seed("sector", s))
        sector_rets[s] = r.normal(0.0, 0.08 / np.sqrt(_TRADING_DAYS), n)
    return market, pd.DataFrame(sector_rets, index=idx)


def _sector_for(ticker: str) -> str:
    return known_sector(ticker) or SECTORS[_seed("sector-of", ticker) % len(SECTORS)]


@lru_cache(maxsize=4096)
def _fundamentals_for(ticker: str) -> Fundamentals:
    sector = _sector_for(ticker)
    pe, pb, gm, om, roe, g, dy, de = _SECTOR_PROFILE[sector]
    r = np.random.default_rng(_seed("fund", ticker))

    def jitter(x: float, spread: float = 0.35) -> float:
        return float(x * np.exp(r.normal(0, spread)))

    market_cap = float(np.exp(r.normal(np.log(150e9), 1.0)))
    trailing_pe = jitter(pe, 0.4)
    if r.random() < 0.05:
        trailing_pe = None  # loss-making
    op_margin = float(np.clip(om + r.normal(0, 0.08), -0.2, 0.6))
    return Fundamentals(
        ticker=ticker,
        name=f"{ticker} (demo)",
        sector=sector,
        industry=sector,
        market_cap=market_cap,
        pe=trailing_pe,
        forward_pe=None if trailing_pe is None else trailing_pe * float(r.uniform(0.75, 1.0)),
        pb=jitter(pb, 0.5),
        ps=jitter(pb * 0.8, 0.5),
        ev_ebitda=jitter(pe * 0.6, 0.35),
        fcf_yield=float(r.normal(1.0 / pe, 0.02)),
        dividend_yield=max(0.0, float(r.normal(dy, dy * 0.6))),
        roe=float(r.normal(roe, 0.08)),
        roa=float(r.normal(roe / 2.5, 0.03)),
        gross_margin=float(np.clip(gm + r.normal(0, 0.1), 0.05, 0.95)),
        operating_margin=op_margin,
        profit_margin=op_margin * float(r.uniform(0.6, 0.85)),
        debt_to_equity=jitter(de, 0.6),
        current_ratio=jitter(1.4, 0.35),
        revenue_growth=float(r.normal(g, 0.08)),
        earnings_growth=float(r.normal(g * 1.2, 0.2)),
        beta=float(np.clip(r.normal(1.0, 0.25), 0.3, 2.0)),
    )


@lru_cache(maxsize=4096)
def _full_history(ticker: str) -> pd.DataFrame:
    idx = _calendar()
    n = len(idx)
    market, sectors = _common_factors()
    f = _fundamentals_for(ticker)
    r = np.random.default_rng(_seed("px", ticker))

    beta = f.beta if f.beta is not None else 1.0
    idio_vol = r.uniform(0.15, 0.40) / np.sqrt(_TRADING_DAYS)

    # Quality/value tilt on long-run alpha (annualised, a few % at most).
    quality = (f.roe or 0) - 0.15 + ((f.operating_margin or 0) - 0.18)
    cheap = (1.0 / f.pe - 0.05) if f.pe else -0.02
    base_alpha = np.clip(0.10 * quality + 0.3 * cheap, -0.04, 0.04) / _TRADING_DAYS

    # Persistent alpha: AR(1) with ~6 month half-life -> momentum is informative.
    phi = 0.5 ** (1 / 126)
    alpha_shock = r.normal(0, 0.10 / _TRADING_DAYS * np.sqrt(1 - phi**2), n)
    alpha = np.empty(n)
    alpha[0] = 0.0
    for t in range(1, n):
        alpha[t] = phi * alpha[t - 1] + alpha_shock[t]

    eps = r.standard_normal(n) * idio_vol
    rets = base_alpha + alpha + beta * market.values + sectors[f.sector].values + eps
    close = 20.0 * np.exp(r.uniform(0, 2.5)) * np.exp(np.cumsum(rets))

    gap = r.normal(0, 0.004, n)
    open_ = np.empty(n)
    open_[0] = close[0]
    open_[1:] = close[:-1] * np.exp(gap[1:])
    wick = np.abs(r.normal(0, 0.008, (2, n)))
    high = np.maximum(open_, close) * (1 + wick[0])
    low = np.minimum(open_, close) * (1 - wick[1])
    volume = np.exp(r.normal(np.log(8e6), 0.4, n)) * (1 + 40 * np.abs(rets))

    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume.round()},
        index=idx,
    )


@lru_cache(maxsize=1)
def _benchmark_history() -> pd.DataFrame:
    market, _ = _common_factors()
    r = np.random.default_rng(_seed("benchmark"))
    rets = market.values + r.normal(0, 0.0005, len(market))
    close = 200.0 * np.exp(np.cumsum(rets))
    return pd.DataFrame(
        {"open": close, "high": close * 1.004, "low": close * 0.996, "close": close,
         "volume": np.full(len(close), 7e7)},
        index=market.index,
    )


class SyntheticProvider(DataProvider):
    name = "synthetic"

    def __init__(self, benchmark: str = "SPY", as_of: date | None = None):
        self.benchmark = benchmark
        self.as_of = pd.Timestamp(as_of or date.today())

    def prices(self, tickers: list[str], start: date, end: date) -> dict[str, pd.DataFrame]:
        lo = pd.Timestamp(start)
        hi = min(pd.Timestamp(end), self.as_of)
        out = {}
        for t in tickers:
            df = _benchmark_history() if t == self.benchmark else _full_history(t)
            out[t] = df.loc[lo:hi].copy()
        return out

    def fundamentals(self, tickers: list[str]) -> dict[str, Fundamentals]:
        return {t: _fundamentals_for(t) for t in tickers if t != self.benchmark}
