"""Live market data from Yahoo Finance (via ``yfinance``), with a disk cache.

Yahoo's fundamentals are a *current* snapshot, not point-in-time history, so
they are used for today's ranking only. The backtester deliberately restricts
itself to price-derived factors to avoid look-ahead bias.
"""

from __future__ import annotations

import json
import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from ..universe import known_sector
from .base import DataProvider, Fundamentals

log = logging.getLogger(__name__)

PRICE_TTL = 6 * 3600
FUNDAMENTALS_TTL = 24 * 3600


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else v


class YahooProvider(DataProvider):
    name = "yahoo"

    def __init__(self, cache_dir: Path):
        import yfinance  # noqa: F401  (fail fast if missing)

        self.cache_dir = Path(cache_dir)
        (self.cache_dir / "prices").mkdir(parents=True, exist_ok=True)
        (self.cache_dir / "fundamentals").mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ prices
    def _price_path(self, ticker: str) -> Path:
        return self.cache_dir / "prices" / f"{ticker}.pkl"

    def _load_cached(self, ticker: str, start: date) -> pd.DataFrame | None:
        p = self._price_path(ticker)
        if not p.exists() or time.time() - p.stat().st_mtime > PRICE_TTL:
            return None
        df = pd.read_pickle(p)
        # Must cover the requested start (allowing for weekends/holidays).
        if df.empty or df.index[0] > pd.Timestamp(start) + timedelta(days=7):
            return None
        return df

    def prices(self, tickers: list[str], start: date, end: date) -> dict[str, pd.DataFrame]:
        import yfinance as yf

        out: dict[str, pd.DataFrame] = {}
        missing = []
        for t in tickers:
            cached = self._load_cached(t, start)
            if cached is None:
                missing.append(t)
            else:
                out[t] = cached
        if missing:
            raw = yf.download(
                missing, start=start, end=end + timedelta(days=1), auto_adjust=True,
                group_by="ticker", progress=False, threads=True,
            )
            for t in missing:
                df = self._extract(raw, t, single=len(missing) == 1)
                if df is None or df.empty:
                    log.warning("no price data for %s", t)
                    continue
                df.to_pickle(self._price_path(t))
                out[t] = df
        lo, hi = pd.Timestamp(start), pd.Timestamp(end)
        return {t: df.loc[lo:hi] for t, df in out.items()}

    @staticmethod
    def _extract(raw: pd.DataFrame, ticker: str, single: bool) -> pd.DataFrame | None:
        if raw is None or raw.empty:
            return None
        if isinstance(raw.columns, pd.MultiIndex):
            if ticker in raw.columns.get_level_values(0):
                df = raw[ticker]
            elif single:
                df = raw.droplevel(1, axis=1) if raw.columns.nlevels > 1 else raw
            else:
                return None
        else:
            df = raw
        df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
        df = df.dropna(subset=["close"])
        df.index = pd.DatetimeIndex(df.index).tz_localize(None)
        return df.astype(float)

    # ------------------------------------------------------------ fundamentals
    def _fund_path(self, ticker: str) -> Path:
        return self.cache_dir / "fundamentals" / f"{ticker}.json"

    def _fetch_info(self, ticker: str) -> dict | None:
        p = self._fund_path(ticker)
        if p.exists() and time.time() - p.stat().st_mtime < FUNDAMENTALS_TTL:
            return json.loads(p.read_text())
        import yfinance as yf

        try:
            info = yf.Ticker(ticker).info or {}
        except Exception as e:  # network / parsing errors are common
            log.warning("fundamentals failed for %s: %s", ticker, e)
            return None
        p.write_text(json.dumps(info, default=str))
        return info

    @staticmethod
    def _to_fundamentals(ticker: str, info: dict) -> Fundamentals:
        mcap = _num(info.get("marketCap"))
        fcf = _num(info.get("freeCashflow"))
        price = _num(info.get("currentPrice")) or _num(info.get("regularMarketPrice"))
        div_rate = _num(info.get("dividendRate"))
        if div_rate is not None and price:
            dy = div_rate / price
        else:
            dy = _num(info.get("trailingAnnualDividendYield"))
        de = _num(info.get("debtToEquity"))
        return Fundamentals(
            ticker=ticker,
            name=info.get("shortName") or info.get("longName") or ticker,
            sector=info.get("sector") or known_sector(ticker) or "Unknown",
            industry=info.get("industry") or "",
            market_cap=mcap,
            pe=_num(info.get("trailingPE")),
            forward_pe=_num(info.get("forwardPE")),
            pb=_num(info.get("priceToBook")),
            ps=_num(info.get("priceToSalesTrailing12Months")),
            ev_ebitda=_num(info.get("enterpriseToEbitda")),
            fcf_yield=(fcf / mcap) if (fcf is not None and mcap) else None,
            dividend_yield=dy,
            roe=_num(info.get("returnOnEquity")),
            roa=_num(info.get("returnOnAssets")),
            gross_margin=_num(info.get("grossMargins")),
            operating_margin=_num(info.get("operatingMargins")),
            profit_margin=_num(info.get("profitMargins")),
            debt_to_equity=None if de is None else de / 100.0,  # Yahoo reports percent
            current_ratio=_num(info.get("currentRatio")),
            revenue_growth=_num(info.get("revenueGrowth")),
            earnings_growth=_num(info.get("earningsGrowth")),
            beta=_num(info.get("beta")),
        )

    # --------------------------------------------------------------- statements
    _STATEMENT_ROWS = {
        "revenue": ["Total Revenue", "Operating Revenue"],
        "gross_profit": ["Gross Profit"],
        "operating_income": ["Operating Income", "EBIT"],
        "net_income": ["Net Income", "Net Income Common Stockholders"],
        "total_assets": ["Total Assets"],
        "total_liabilities": ["Total Liabilities Net Minority Interest"],
        "current_assets": ["Current Assets"],
        "current_liabilities": ["Current Liabilities"],
        "long_term_debt": ["Long Term Debt"],
        "total_debt": ["Total Debt"],
        "cash": ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"],
        "equity": ["Stockholders Equity", "Common Stock Equity"],
        "retained_earnings": ["Retained Earnings"],
        "shares": ["Ordinary Shares Number", "Share Issued"],
        "operating_cash_flow": ["Operating Cash Flow"],
        "capex": ["Capital Expenditure"],
        "free_cash_flow": ["Free Cash Flow"],
    }

    def statements(self, ticker: str) -> pd.DataFrame:
        p = self.cache_dir / "fundamentals" / f"{ticker}.statements.pkl"
        if p.exists() and time.time() - p.stat().st_mtime < FUNDAMENTALS_TTL:
            return pd.read_pickle(p)
        import yfinance as yf

        try:
            t = yf.Ticker(ticker)
            raw = pd.concat([t.income_stmt, t.balance_sheet, t.cashflow])
        except Exception as e:
            log.warning("statements failed for %s: %s", ticker, e)
            return pd.DataFrame()
        if raw is None or raw.empty:
            return pd.DataFrame()
        raw = raw[~raw.index.duplicated()]
        out = {}
        for col, labels in self._STATEMENT_ROWS.items():
            for label in labels:
                if label in raw.index:
                    out[col] = pd.to_numeric(raw.loc[label], errors="coerce")
                    break
        df = pd.DataFrame(out)
        df.index = pd.DatetimeIndex(df.index, name="fiscal_year_end")
        df = df.sort_index().dropna(how="all")
        df.to_pickle(p)
        return df

    # ----------------------------------------------------------------- intraday
    def intraday(self, ticker: str, interval: str = "5m", days: int = 5) -> pd.DataFrame:
        import yfinance as yf

        # Yahoo limits: 1m bars for ~7 days, other intraday intervals for ~60 days.
        days = min(days, 7 if interval == "1m" else 59)
        raw = yf.download(ticker, period=f"{days}d", interval=interval, auto_adjust=True,
                          progress=False, prepost=False)
        df = self._extract(raw, ticker, single=True)
        if df is None:
            return pd.DataFrame()
        idx = pd.DatetimeIndex(raw.index)
        if idx.tz is not None:
            df.index = idx.tz_convert("America/New_York").tz_localize(None)
        return df

    def fundamentals(self, tickers: list[str]) -> dict[str, Fundamentals]:
        with ThreadPoolExecutor(max_workers=8) as pool:
            infos = list(pool.map(self._fetch_info, tickers))
        return {
            t: self._to_fundamentals(t, info)
            for t, info in zip(tickers, infos)
            if info
        }
