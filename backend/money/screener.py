"""Stock screener: combine fundamentals + price metrics, score, filter, rank."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .data.base import DataProvider
from .factors import METRICS, fundamental_metrics, price_metric_panel, price_metrics_at
from .scoring import ScoringConfig, grade, score_universe
from .universe import DEFAULT_BENCHMARK

HISTORY_DAYS = 400  # calendar days of history needed for 12-month metrics


@dataclass
class Filters:
    min_market_cap: float | None = None
    max_pe: float | None = None
    min_dividend_yield: float | None = None
    max_debt_to_equity: float | None = None
    max_vol: float | None = None
    above_sma200: bool = False
    sectors: list[str] = field(default_factory=list)
    exclude_sectors: list[str] = field(default_factory=list)


@dataclass
class ScreenResult:
    as_of: date
    table: pd.DataFrame           # one row per stock, sorted by composite
    universe_size: int
    missing: list[str]

    def records(self, limit: int | None = None) -> list[dict]:
        df = self.table if limit is None else self.table.head(limit)
        return [_clean(row) for row in df.reset_index().to_dict(orient="records")]


def _clean(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, (float, np.floating)):
            out[k] = None if not np.isfinite(v) else float(v)
        elif isinstance(v, (np.integer,)):
            out[k] = int(v)
        elif isinstance(v, (np.bool_,)):
            out[k] = bool(v)
        else:
            out[k] = v
    return out


def run_screen(provider: DataProvider, tickers: list[str], cfg: ScoringConfig | None = None,
               filters: Filters | None = None, as_of: date | None = None,
               benchmark: str = DEFAULT_BENCHMARK) -> ScreenResult:
    cfg = cfg or ScoringConfig()
    filters = filters or Filters()
    as_of = as_of or date.today()

    funds = provider.fundamentals(tickers)
    frames = provider.prices(tickers + [benchmark], as_of - timedelta(days=HISTORY_DAYS), as_of)
    bench = frames.pop(benchmark, None)
    closes = pd.DataFrame({t: df["close"] for t, df in frames.items() if not df.empty})
    missing = sorted(set(tickers) - set(closes.columns) - set(funds))

    panel = price_metric_panel(closes, None if bench is None else bench["close"])
    pm = price_metrics_at(panel, pd.Timestamp(as_of))
    fm = fundamental_metrics(funds)
    metrics = fm.join(pm, how="outer")
    metrics.index.name = "ticker"

    info = pd.DataFrame(
        {t: {"name": f.name, "sector": f.sector, "industry": f.industry,
             "market_cap": f.market_cap, "pe": f.pe, "forward_pe": f.forward_pe,
             "pb": f.pb, "dividend_yield": f.dividend_yield, "beta": f.beta}
         for t, f in funds.items()}
    ).T.reindex(metrics.index)
    info["price"] = closes.ffill().iloc[-1].reindex(metrics.index) if len(closes) else np.nan
    sma200 = closes.rolling(200).mean().iloc[-1] if len(closes) >= 200 else pd.Series(dtype=float)
    info["sma200_gap"] = (info["price"] / sma200.reindex(metrics.index) - 1).astype(float)
    if len(closes) > 21:
        info["ret_1m"] = (closes.ffill().iloc[-1] / closes.ffill().iloc[-22] - 1).reindex(metrics.index)
    info["sector"] = info["sector"].fillna("Unknown")

    # Filters are applied *before* scoring so percentiles reflect the eligible set.
    keep = _apply_filters(metrics.join(info[["market_cap", "pe", "dividend_yield",
                                             "sector", "sma200_gap"]]), filters)
    metrics, info = metrics.loc[keep], info.loc[keep]

    scored = score_universe(metrics, info["sector"], cfg) if len(metrics) else pd.DataFrame()
    table = info.join(metrics.add_prefix("m_")).join(scored, how="left")
    table = table.sort_values("composite", ascending=False, na_position="last")
    table["grade"] = [grade(s) for s in table.get("score", pd.Series(dtype=float))]
    table.index.name = "ticker"
    return ScreenResult(as_of=as_of, table=table, universe_size=len(tickers), missing=missing)


def _apply_filters(df: pd.DataFrame, f: Filters) -> pd.Index:
    mask = pd.Series(True, index=df.index)

    def num(col: str) -> pd.Series:
        return pd.to_numeric(df[col], errors="coerce")

    if f.min_market_cap is not None:
        mask &= num("market_cap") >= f.min_market_cap
    if f.max_pe is not None:
        pe = num("pe")
        mask &= pe.notna() & (pe > 0) & (pe <= f.max_pe)
    if f.min_dividend_yield is not None:
        mask &= num("dividend_yield").fillna(0) >= f.min_dividend_yield
    if f.max_debt_to_equity is not None:
        mask &= num("debt_to_equity") <= f.max_debt_to_equity
    if f.max_vol is not None:
        mask &= num("vol_1y") <= f.max_vol
    if f.above_sma200:
        mask &= num("sma200_gap") > 0
    if f.sectors:
        mask &= df["sector"].isin(f.sectors)
    if f.exclude_sectors:
        mask &= ~df["sector"].isin(f.exclude_sectors)
    return df.index[mask.fillna(False).astype(bool)]


def metric_catalog() -> list[dict]:
    return [m.__dict__ for m in METRICS]
