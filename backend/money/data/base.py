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


STATEMENT_COLUMNS = [
    "revenue", "gross_profit", "operating_income", "net_income", "total_assets",
    "total_liabilities", "current_assets", "current_liabilities", "long_term_debt",
    "total_debt", "cash", "equity", "retained_earnings", "shares",
    "operating_cash_flow", "capex", "free_cash_flow",
]

INTRADAY_INTERVALS = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "60m": 60}


class DataProvider(ABC):
    """Abstract market data source."""

    name: str = "base"

    @abstractmethod
    def prices(self, tickers: list[str], start: date, end: date) -> dict[str, pd.DataFrame]:
        """Return {ticker: OHLCV DataFrame} with columns open/high/low/close/volume."""

    @abstractmethod
    def fundamentals(self, tickers: list[str]) -> dict[str, Fundamentals]:
        """Return {ticker: Fundamentals} for the tickers that have data."""

    def statements(self, ticker: str) -> pd.DataFrame:
        """Annual financial statements, one row per fiscal year (oldest first).

        Columns (any may be missing): revenue, gross_profit, operating_income,
        net_income, total_assets, total_liabilities, current_assets,
        current_liabilities, long_term_debt, total_debt, cash, equity,
        retained_earnings, shares, operating_cash_flow, capex, free_cash_flow.
        """
        return pd.DataFrame()

    def intraday(self, ticker: str, interval: str = "5m", days: int = 5) -> pd.DataFrame:
        """Intraday OHLCV bars (exchange-local timestamps) for the last ``days`` sessions."""
        return pd.DataFrame()

    def close_matrix(self, tickers: list[str], start: date, end: date) -> pd.DataFrame:
        """Adjusted close prices as a (date x ticker) matrix."""
        frames = self.prices(tickers, start, end)
        if not frames:
            return pd.DataFrame()
        closes = {t: df["close"] for t, df in frames.items() if not df.empty}
        return pd.DataFrame(closes).sort_index()
