"""Offline tests for live-data providers (no network: payloads are fixtures)."""

import io
import json
import urllib.error
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from money.data import fmp as fmp_mod
from money.data.fmp import FMPError, FMPProvider, fundamentals_from_statements, parse_eod, parse_intraday, parse_statements
from money.data.yahoo import YahooProvider

# ------------------------------------------------------------------ fixtures
INCOME = [
    {"date": "2025-09-27", "revenue": 400e9, "grossProfit": 180e9, "operatingIncome": 120e9,
     "netIncome": 100e9, "ebitda": 135e9, "weightedAverageShsOutDil": 15e9},
    {"date": "2024-09-28", "revenue": 380e9, "grossProfit": 170e9, "operatingIncome": 110e9,
     "netIncome": 90e9, "ebitda": 125e9, "weightedAverageShsOutDil": 15.4e9},
]
BALANCE = [
    {"date": "2025-09-27", "totalAssets": 360e9, "totalLiabilities": 290e9, "totalCurrentAssets": 150e9,
     "totalCurrentLiabilities": 160e9, "longTermDebt": 85e9, "totalDebt": 100e9,
     "cashAndCashEquivalents": 30e9, "totalStockholdersEquity": 70e9, "retainedEarnings": 5e9},
    {"date": "2024-09-28", "totalAssets": 350e9, "totalLiabilities": 290e9, "totalCurrentAssets": 140e9,
     "totalCurrentLiabilities": 150e9, "longTermDebt": 90e9, "totalDebt": 105e9,
     "cashAndCashEquivalents": 29e9, "totalStockholdersEquity": 60e9, "retainedEarnings": -5e9},
]
CASHFLOW = [
    {"date": "2025-09-27", "operatingCashFlow": 115e9, "capitalExpenditure": -10e9, "commonDividendsPaid": -15e9},
    {"date": "2024-09-28", "operatingCashFlow": 110e9, "capitalExpenditure": -9e9, "commonDividendsPaid": -14.5e9},
]
PROFILE = [{"symbol": "AAPL", "companyName": "Apple Inc.", "sector": "Technology", "industry": "Consumer Electronics",
            "marketCap": 3000e9, "beta": 1.2, "price": 200.0, "lastDividend": 1.0}]


def eod_payload(n=320, start=date(2025, 1, 2)):
    days = pd.bdate_range(start, periods=n)
    px = 100 * np.exp(np.cumsum(np.full(n, 0.001)))
    # Newest first, like FMP; adjusted fields present (stable endpoint).
    return [{"symbol": "X", "date": d.strftime("%Y-%m-%d"), "adjOpen": p * 0.999, "adjHigh": p * 1.01,
             "adjLow": p * 0.99, "adjClose": p, "volume": 1e6} for d, p in zip(days, px)][::-1]


def intraday_payload(day="2026-09-22"):
    rows = []
    for m in range(8 * 60, 17 * 60, 5):  # includes pre- and post-market bars
        ts = f"{day} {m // 60:02d}:{m % 60:02d}:00"
        rows.append({"date": ts, "open": 10, "high": 10.2, "low": 9.9, "close": 10.1, "volume": 1000})
    return rows[::-1]


class FakeFMP(FMPProvider):
    """FMPProvider whose HTTP layer serves fixtures and records calls."""

    def __init__(self, tmp_path):
        super().__init__("test-key", tmp_path)
        self.calls = []

    def _get(self, path, **params):
        self.calls.append((path, params))
        return {
            "income-statement": INCOME, "balance-sheet-statement": BALANCE, "cash-flow-statement": CASHFLOW,
            "profile": [{**PROFILE[0], "symbol": params["symbol"]}],
            "historical-price-eod/dividend-adjusted": eod_payload(),
            "historical-chart/5min": intraday_payload("2026-09-21") + intraday_payload("2026-09-22"),
        }[path]


# --------------------------------------------------------------------- FMP
def test_parse_eod_handles_stable_and_legacy_shapes():
    stable = parse_eod(eod_payload(10))
    assert stable.index.is_monotonic_increasing and len(stable) == 10
    assert list(stable.columns) == ["open", "high", "low", "close", "volume"]
    legacy = parse_eod({"symbol": "X", "historical": [
        {"date": "2024-01-03", "open": 100, "high": 110, "low": 90, "close": 100, "adjClose": 50, "volume": 5},
        {"date": "2024-01-02", "open": 98, "high": 99, "low": 97, "close": 98, "adjClose": 49, "volume": 5},
    ]})
    # Raw OHLC is scaled onto the adjusted close (e.g. after a 2:1 split).
    assert legacy.loc["2024-01-03", "close"] == 50 and legacy.loc["2024-01-03", "high"] == 55
    assert parse_eod([]).empty


def test_parse_intraday_keeps_regular_session_sorted():
    df = parse_intraday(intraday_payload())
    assert df.index.is_monotonic_increasing
    assert df.index[0].strftime("%H:%M") == "09:30" and df.index[-1].strftime("%H:%M") == "15:55"
    assert len(df) == 78


def test_fundamentals_derived_from_statements():
    st = parse_statements(INCOME, BALANCE, CASHFLOW)
    assert list(st.index.year) == [2024, 2025]
    assert st["free_cash_flow"].iloc[-1] == pytest.approx(105e9)  # OCF + (negative) capex
    f = fundamentals_from_statements("AAPL", PROFILE[0], st)
    assert f.name == "Apple Inc." and f.sector == "Technology" and f.beta == 1.2
    assert f.pe == pytest.approx(30.0)
    assert f.pb == pytest.approx(3000 / 70)
    assert f.ps == pytest.approx(7.5)
    assert f.ev_ebitda == pytest.approx((3000e9 + 100e9 - 30e9) / 135e9)
    assert f.fcf_yield == pytest.approx(105 / 3000)
    assert f.dividend_yield == pytest.approx(15 / 3000)
    assert f.roe == pytest.approx(100 / 70) and f.roa == pytest.approx(100 / 360)
    assert f.gross_margin == pytest.approx(0.45) and f.operating_margin == pytest.approx(0.3)
    assert f.debt_to_equity == pytest.approx(100 / 70)
    assert f.current_ratio == pytest.approx(150 / 160)
    assert f.revenue_growth == pytest.approx(400 / 380 - 1)
    assert f.earnings_growth == pytest.approx(100 / 90 - 1)


def test_loss_maker_gets_no_pe():
    income = [{**INCOME[0], "netIncome": -5e9}, INCOME[1]]
    f = fundamentals_from_statements("X", PROFILE[0], parse_statements(income, BALANCE, CASHFLOW))
    assert f.pe is None and f.roe < 0
    assert f.earnings_growth == pytest.approx(-5 / 90 - 1)  # profit -> loss is a real, informative drop
    # Growth off a loss base is undefined.
    income = [INCOME[0], {**INCOME[1], "netIncome": -5e9}]
    f = fundamentals_from_statements("X", PROFILE[0], parse_statements(income, BALANCE, CASHFLOW))
    assert f.earnings_growth is None


def test_fmp_provider_end_to_end(tmp_path):
    p = FakeFMP(tmp_path)
    today = date.today()
    prices = p.prices(["AAPL", "MSFT"], date(2025, 1, 1), today)
    assert set(prices) == {"AAPL", "MSFT"} and len(prices["AAPL"]) > 200
    funds = p.fundamentals(["AAPL", "MSFT"])
    assert funds["MSFT"].pe == pytest.approx(30.0)
    st = p.statements("AAPL")
    assert len(st) == 2 and "free_cash_flow" in st
    bars = p.intraday("AAPL", "5m", days=1)
    assert len(bars) == 78 and bars.index[0].strftime("%Y-%m-%d %H:%M") == "2026-09-22 09:30"
    # Second call is served from the disk cache.
    n = len(p.calls)
    p.fundamentals(["AAPL"])
    p.prices(["AAPL"], date(2025, 1, 1), today)
    assert len(p.calls) == n
    assert all(params.get("symbol") for _, params in p.calls)


def test_fmp_screen_runs_on_provider(tmp_path):
    from money.screener import run_screen

    res = run_screen(FakeFMP(tmp_path), ["AAPL", "MSFT", "JPM"], benchmark="SPY")
    assert len(res.table) == 3 and res.table["score"].notna().all()


def test_fmp_http_retries_then_redacts_key(tmp_path, monkeypatch):
    monkeypatch.setattr(fmp_mod.time, "sleep", lambda s: None)
    attempts = []

    def fake_urlopen(url, timeout):
        attempts.append(url)
        if len(attempts) < 3:
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)
        return io.BytesIO(json.dumps([{"ok": 1}]).encode())

    monkeypatch.setattr(fmp_mod.urllib.request, "urlopen", fake_urlopen)
    p = FMPProvider("secret-key-123", tmp_path)
    assert p._get("profile", symbol="AAPL") == [{"ok": 1}] and len(attempts) == 3

    def forbidden(url, timeout):
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)

    monkeypatch.setattr(fmp_mod.urllib.request, "urlopen", forbidden)
    with pytest.raises(FMPError) as e:
        p._get("profile", symbol="AAPL")
    assert "secret-key-123" not in str(e.value) and "403" in str(e.value)


def test_fmp_requires_key(tmp_path):
    with pytest.raises(ValueError):
        FMPProvider("", tmp_path)


# ------------------------------------------------------------------- Yahoo
def test_yahoo_extract_multiindex_and_single():
    idx = pd.date_range("2026-01-02", periods=3, tz="America/New_York")
    cols = pd.MultiIndex.from_product([["AAPL", "MSFT"], ["Open", "High", "Low", "Close", "Volume"]])
    raw = pd.DataFrame(np.arange(30, dtype=float).reshape(3, 10) + 1, index=idx, columns=cols)
    df = YahooProvider._extract(raw, "MSFT", single=False)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.tz is None and df["open"].iloc[0] == 6.0
    assert YahooProvider._extract(raw, "NVDA", single=False) is None
    # Newer yfinance returns (field, ticker) columns for a single ticker.
    single = raw["AAPL"].copy()
    single.columns = pd.MultiIndex.from_product([["Open", "High", "Low", "Close", "Volume"], ["AAPL"]])
    assert YahooProvider._extract(single, "AAPL", single=True)["close"].iloc[0] == 4.0


def test_yahoo_fundamentals_units():
    f = YahooProvider._to_fundamentals("KO", {
        "shortName": "Coca-Cola", "sector": "Consumer Defensive", "marketCap": 3e11, "freeCashflow": 9e9,
        "currentPrice": 60.0, "dividendRate": 1.8, "debtToEquity": 150.0, "trailingPE": float("nan"),
    })
    assert f.debt_to_equity == pytest.approx(1.5)  # Yahoo reports percent
    assert f.dividend_yield == pytest.approx(0.03)
    assert f.fcf_yield == pytest.approx(0.03)
    assert f.pe is None  # NaN is treated as missing
