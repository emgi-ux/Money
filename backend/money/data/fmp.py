"""Financial Modeling Prep (FMP) provider - a commercially licensable data feed.

Set ``MONEY_PROVIDER=fmp`` and ``FMP_API_KEY``. Redistributing market data in a
paid product requires the matching FMP data-display licence; check your plan.

Valuation and quality ratios are *derived here* from the raw annual statements
plus market cap, rather than taken from vendor ratio endpoints, so every
provider scores stocks with the same definitions and vendor field renames only
affect the thin parsing layer below.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from ..universe import known_sector
from .base import INTRADAY_INTERVALS, STATEMENT_COLUMNS, DataProvider, Fundamentals

log = logging.getLogger(__name__)

PRICE_TTL = 6 * 3600
FUNDAMENTALS_TTL = 24 * 3600
INTRADAY_TTL = 60
DEFAULT_BASE = "https://financialmodelingprep.com/stable"


class FMPError(RuntimeError):
    pass


def _f(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if not np.isfinite(v) else v


def _first(d: dict, *keys):
    for k in keys:
        if d.get(k) is not None:
            return d[k]
    return None


# Statement field -> FMP keys (first present wins; covers stable and legacy v3 names).
STATEMENT_FIELDS: dict[str, tuple[str, ...]] = {
    "revenue": ("revenue",),
    "gross_profit": ("grossProfit",),
    "operating_income": ("operatingIncome",),
    "net_income": ("netIncome",),
    "ebitda": ("ebitda",),
    "total_assets": ("totalAssets",),
    "total_liabilities": ("totalLiabilities",),
    "current_assets": ("totalCurrentAssets",),
    "current_liabilities": ("totalCurrentLiabilities",),
    "long_term_debt": ("longTermDebt",),
    "total_debt": ("totalDebt",),
    "cash": ("cashAndCashEquivalents", "cashAndShortTermInvestments"),
    "equity": ("totalStockholdersEquity", "totalEquity"),
    "retained_earnings": ("retainedEarnings",),
    "shares": ("weightedAverageShsOutDil", "weightedAverageShsOut"),
    "operating_cash_flow": ("operatingCashFlow", "netCashProvidedByOperatingActivities"),
    "capex": ("capitalExpenditure", "investmentsInPropertyPlantAndEquipment"),
    "free_cash_flow": ("freeCashFlow",),
    "dividends_paid": ("commonDividendsPaid", "dividendsPaid", "netDividendsPaid"),
}


def parse_statements(income: list[dict], balance: list[dict], cashflow: list[dict]) -> pd.DataFrame:
    """Merge FMP annual statements into one frame indexed by fiscal year end (oldest first)."""
    rows: dict[str, dict] = {}
    for source in (income, balance, cashflow):
        for rec in source or []:
            d = rec.get("date")
            if not d:
                continue
            row = rows.setdefault(d, {})
            for col, keys in STATEMENT_FIELDS.items():
                if row.get(col) is None:
                    v = _f(_first(rec, *keys))
                    if v is not None:
                        row[col] = v
    if not rows:
        return pd.DataFrame(columns=STATEMENT_COLUMNS)
    df = pd.DataFrame.from_dict(rows, orient="index")
    df.index = pd.DatetimeIndex(df.index, name="fiscal_year_end")
    df = df.sort_index()
    if "free_cash_flow" not in df and {"operating_cash_flow", "capex"} <= set(df.columns):
        # FMP reports capex as a negative number.
        df["free_cash_flow"] = df["operating_cash_flow"] + df["capex"]
    return df


def fundamentals_from_statements(ticker: str, profile: dict, st: pd.DataFrame) -> Fundamentals:
    """Build the valuation / quality / growth snapshot from statements + profile."""
    mcap = _f(_first(profile, "marketCap", "mktCap"))
    price = _f(profile.get("price"))
    sector = profile.get("sector") or known_sector(ticker) or "Unknown"
    f = Fundamentals(
        ticker=ticker,
        name=profile.get("companyName") or profile.get("name") or ticker,
        sector=sector,
        industry=profile.get("industry") or "",
        market_cap=mcap,
        beta=_f(profile.get("beta")),
    )
    if st is None or st.empty:
        return f
    cur = st.iloc[-1]
    prev = st.iloc[-2] if len(st) > 1 else None

    def g(row, col):
        return None if row is None else _f(row.get(col))

    def ratio(a, b):
        return a / b if a is not None and b not in (None, 0) else None

    ni, rev, eq = g(cur, "net_income"), g(cur, "revenue"), g(cur, "equity")
    assets, debt, cash = g(cur, "total_assets"), g(cur, "total_debt"), g(cur, "cash")
    if mcap:
        f.pe = ratio(mcap, ni) if ni and ni > 0 else None
        f.pb = ratio(mcap, eq) if eq and eq > 0 else None
        f.ps = ratio(mcap, rev) if rev and rev > 0 else None
        ebitda = g(cur, "ebitda")
        if ebitda and ebitda > 0:
            f.ev_ebitda = (mcap + (debt or 0) - (cash or 0)) / ebitda
        f.fcf_yield = ratio(g(cur, "free_cash_flow"), mcap)
        div = g(cur, "dividends_paid")
        f.dividend_yield = abs(div) / mcap if div is not None else _dividend_from_profile(profile, price)
    f.roe = ratio(ni, eq) if eq and eq > 0 else None
    f.roa = ratio(ni, assets)
    f.gross_margin = ratio(g(cur, "gross_profit"), rev)
    f.operating_margin = ratio(g(cur, "operating_income"), rev)
    f.profit_margin = ratio(ni, rev)
    f.debt_to_equity = ratio(debt, eq) if eq and eq > 0 else None
    f.current_ratio = ratio(g(cur, "current_assets"), g(cur, "current_liabilities"))
    if prev is not None:
        prev_rev, prev_ni = g(prev, "revenue"), g(prev, "net_income")
        f.revenue_growth = rev / prev_rev - 1 if rev and prev_rev and prev_rev > 0 else None
        f.earnings_growth = ni / prev_ni - 1 if ni is not None and prev_ni and prev_ni > 0 else None
    return f


def _dividend_from_profile(profile: dict, price: float | None) -> float | None:
    last = _f(_first(profile, "lastDividend", "lastDiv"))
    return last / price if last is not None and price else None


def parse_eod(payload) -> pd.DataFrame:
    """Daily bars, split/dividend adjusted when the payload carries adjusted fields."""
    recs = payload.get("historical", []) if isinstance(payload, dict) else (payload or [])
    rows = []
    for r in recs:
        close = _f(_first(r, "adjClose", "close"))
        if close is None or not r.get("date"):
            continue
        raw_close = _f(r.get("close")) or close
        k = close / raw_close if raw_close else 1.0  # scale OHLC onto the adjusted close

        def px(adj_key, key):
            v = _f(r.get(adj_key))
            if v is not None:
                return v
            v = _f(r.get(key))
            return None if v is None else v * k

        rows.append({"date": r["date"][:10], "open": px("adjOpen", "open"), "high": px("adjHigh", "high"),
                     "low": px("adjLow", "low"), "close": close, "volume": _f(r.get("volume")) or 0.0})
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame(rows).drop_duplicates("date").set_index("date")
    df.index = pd.DatetimeIndex(df.index)
    df = df.sort_index()
    return df.fillna({"open": df["close"], "high": df["close"], "low": df["close"]}).astype(float)


def parse_intraday(payload) -> pd.DataFrame:
    """Intraday bars (exchange-local, New York time), regular session only."""
    rows = [{"ts": r["date"], "open": _f(r.get("open")), "high": _f(r.get("high")), "low": _f(r.get("low")),
             "close": _f(r.get("close")), "volume": _f(r.get("volume")) or 0.0}
            for r in payload or [] if r.get("date") and _f(r.get("close")) is not None]
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame(rows).drop_duplicates("ts").set_index("ts")
    df.index = pd.DatetimeIndex(df.index)
    df = df.sort_index()
    minutes = df.index.hour * 60 + df.index.minute
    return df[(minutes >= 570) & (minutes < 960)].astype(float)


class FMPProvider(DataProvider):
    name = "fmp"

    def __init__(self, api_key: str, cache_dir: Path, base_url: str | None = None):
        if not api_key:
            raise ValueError("FMP_API_KEY is required for the fmp provider")
        self.api_key = api_key
        self.base = (base_url or os.environ.get("FMP_BASE_URL") or DEFAULT_BASE).rstrip("/")
        self.cache_dir = Path(cache_dir) / "fmp"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ HTTP
    def _get(self, path: str, **params):
        params["apikey"] = self.api_key
        url = f"{self.base}/{path.lstrip('/')}?{urllib.parse.urlencode(params)}"
        delay = 1.0
        for attempt in range(4):
            try:
                with urllib.request.urlopen(url, timeout=20) as resp:
                    data = json.loads(resp.read().decode())
                if isinstance(data, dict) and data.get("Error Message"):
                    raise FMPError(data["Error Message"])
                return data
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                    time.sleep(delay)
                    delay *= 2
                    continue
                # Never leak the API key into logs or error messages.
                raise FMPError(f"FMP {path} failed: HTTP {e.code}") from None
            except urllib.error.URLError as e:
                if attempt < 3:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise FMPError(f"FMP {path} unreachable: {e.reason}") from None
        raise FMPError(f"FMP {path} failed after retries")

    def _cached_json(self, key: str, ttl: int, fetch):
        p = self.cache_dir / f"{key}.json"
        if p.exists() and time.time() - p.stat().st_mtime < ttl:
            return json.loads(p.read_text())
        data = fetch()
        p.write_text(json.dumps(data))
        return data

    # ---------------------------------------------------------------- prices
    def _history(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        p = self.cache_dir / f"eod-{ticker}.pkl"
        if p.exists() and time.time() - p.stat().st_mtime < PRICE_TTL:
            df = pd.read_pickle(p)
            if not df.empty and df.index[0] <= pd.Timestamp(start) + timedelta(days=7):
                return df
        payload = self._get("historical-price-eod/dividend-adjusted", symbol=ticker,
                            **{"from": start.isoformat(), "to": end.isoformat()})
        df = parse_eod(payload)
        df.to_pickle(p)
        return df

    def prices(self, tickers: list[str], start: date, end: date) -> dict[str, pd.DataFrame]:
        def one(t):
            try:
                return t, self._history(t, start, end)
            except FMPError as e:
                log.warning("%s", e)
                return t, None

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(one, tickers))
        lo, hi = pd.Timestamp(start), pd.Timestamp(end)
        return {t: df.loc[lo:hi] for t, df in results if df is not None and not df.empty}

    def intraday(self, ticker: str, interval: str = "5m", days: int = 5) -> pd.DataFrame:
        minutes = INTRADAY_INTERVALS[interval]
        fmp_interval = {1: "1min", 5: "5min", 15: "15min", 30: "30min", 60: "1hour"}[minutes]
        end = date.today()
        start = end - timedelta(days=int(days * 1.6) + 3)  # calendar days covering N sessions
        payload = self._cached_json(f"intraday-{ticker}-{fmp_interval}-{start}", INTRADAY_TTL,
                                    lambda: self._get(f"historical-chart/{fmp_interval}", symbol=ticker,
                                                      **{"from": start.isoformat(), "to": end.isoformat()}))
        df = parse_intraday(payload)
        sessions = sorted(set(df.index.normalize()))[-days:]
        return df[df.index.normalize().isin(sessions)]

    # ---------------------------------------------------------- fundamentals
    def _raw_statements(self, ticker: str) -> pd.DataFrame:
        def fetch(kind):
            return self._cached_json(f"{kind}-{ticker}", FUNDAMENTALS_TTL,
                                     lambda: self._get(kind, symbol=ticker, period="annual", limit=5))

        return parse_statements(fetch("income-statement"), fetch("balance-sheet-statement"),
                                fetch("cash-flow-statement"))

    def statements(self, ticker: str) -> pd.DataFrame:
        try:
            return self._raw_statements(ticker)
        except FMPError as e:
            log.warning("%s", e)
            return pd.DataFrame()

    def _profile(self, ticker: str) -> dict:
        data = self._cached_json(f"profile-{ticker}", FUNDAMENTALS_TTL, lambda: self._get("profile", symbol=ticker))
        return data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else {})

    def fundamentals(self, tickers: list[str]) -> dict[str, Fundamentals]:
        def one(t):
            try:
                return t, fundamentals_from_statements(t, self._profile(t), self._raw_statements(t))
            except FMPError as e:
                log.warning("%s", e)
                return t, None

        with ThreadPoolExecutor(max_workers=8) as pool:
            return {t: f for t, f in pool.map(one, tickers) if f is not None}
