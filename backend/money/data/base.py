"""Data provider interface.

Every provider returns:
  * prices: a DataFrame of OHLCV per ticker, indexed by trading date, adjusted
    for splits and dividends (so returns are total returns).
  * fundamentals: a point-in-time-ish snapshot of valuation, profitability and
    growth metrics for each ticker (see ``Fundamentals``).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import date

import pandas as pd


@dataclass
class Fundamentals:
    ticker: str
    name: str = ""
    sector: str = "Unknown"
    industry: str = ""
    market_cap: float | None = None
    # Valuation
    pe: float | None = None               # trailing price / earnings
    forward_pe: float | None = None
    pb: float | None = None               # price / book
    ps: float | None = None               # price / sales
    ev_ebitda: float | None = None
    fcf_yield: float | None = None        # free cash flow / market cap
    dividend_yield: float | None = None
    # Profitability / quality
    roe: float | None = None
    roa: float | None = None
    gross_margin: float | None = None
    operating_margin: float | None = None
    profit_margin: float | None = None
    debt_to_equity: float | None = None   # ratio, not percent
    current_ratio: float | None = None
    # Growth
    revenue_growth: float | None = None   # year over year
    earnings_growth: float | None = None
    # Risk
    beta: float | None = None
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("extra", None)
        return d


class DataProvider(ABC):
    """Abstract market data source."""

    name: str = "base"

    @abstractmethod
    def prices(self, tickers: list[str], start: date, end: date) -> dict[str, pd.DataFrame]:
        """Return {ticker: OHLCV DataFrame} with columns open/high/low/close/volume."""

    @abstractmethod
    def fundamentals(self, tickers: list[str]) -> dict[str, Fundamentals]:
        """Return {ticker: Fundamentals} for the tickers that have data."""

    def close_matrix(self, tickers: list[str], start: date, end: date) -> pd.DataFrame:
        """Adjusted close prices as a (date x ticker) matrix."""
        frames = self.prices(tickers, start, end)
        if not frames:
            return pd.DataFrame()
        closes = {t: df["close"] for t, df in frames.items() if not df.empty}
        return pd.DataFrame(closes).sort_index()
