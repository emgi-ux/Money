"""Portfolio risk analytics on historical returns."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from .analytics import TRADING_DAYS, drawdown, performance, series_points
from .data.base import DataProvider
from .portfolio import shrink_cov
from .universe import DEFAULT_BENCHMARK


def analyze_portfolio(provider: DataProvider, weights: dict[str, float], lookback_days: int = 365,
                      benchmark: str = DEFAULT_BENCHMARK, as_of: date | None = None) -> dict:
    as_of = as_of or date.today()
    tickers = [t for t, w in weights.items() if w]
    if not tickers:
        raise ValueError("portfolio is empty")
    total = sum(weights[t] for t in tickers)
    w = pd.Series({t: weights[t] / total for t in tickers})

    frames = provider.prices(tickers + [benchmark], as_of - timedelta(days=lookback_days), as_of)
    bench_df = frames.pop(benchmark, None)
    closes = pd.DataFrame({t: df["close"] for t, df in frames.items() if not df.empty}).sort_index()
    missing = sorted(set(tickers) - set(closes.columns))
    if missing:
        raise ValueError(f"no price data for: {', '.join(missing)}")
    rets = closes.pct_change(fill_method=None).iloc[1:].fillna(0.0)[w.index]
    bench = (bench_df["close"].pct_change().reindex(rets.index).fillna(0.0)
             if bench_df is not None else None)

    # Static-weight (daily rebalanced) historical simulation.
    port = rets @ w
    cov = shrink_cov(rets.to_numpy()) * TRADING_DAYS
    wv = w.to_numpy()
    port_var = float(wv @ cov @ wv)
    port_vol = np.sqrt(port_var)
    mcr = cov @ wv / port_vol                       # marginal contribution to risk
    rc = wv * mcr / port_vol                        # % risk contribution, sums to 1
    asset_vol = np.sqrt(np.diag(cov))
    div_ratio = float(wv @ asset_vol / port_vol)

    funds = provider.fundamentals(tickers)
    sectors = pd.Series({t: (funds[t].sector if t in funds else "Unknown") for t in w.index})
    sector_w = w.groupby(sectors).sum().sort_values(ascending=False)
    sector_rc = pd.Series(rc, index=w.index).groupby(sectors).sum()

    betas = {}
    if bench is not None and bench.var() > 0:
        for t in w.index:
            betas[t] = float(rets[t].cov(bench) / bench.var())

    corr = rets.corr().round(3)
    weekly = (1 + port).resample("W").prod() - 1

    return {
        "as_of": as_of.isoformat(),
        "observations": int(len(rets)),
        "summary": {
            **performance(port, bench),
            "ex_ante_volatility": port_vol,
            "diversification_ratio": div_ratio,
            "effective_n": float(1 / (w**2).sum()),
            "worst_day": float(port.min()),
            "worst_week": float(weekly.min()) if len(weekly) else None,
            "parametric_var_95_1d": float(1.645 * port_vol / np.sqrt(TRADING_DAYS)),
        },
        "positions": [
            {
                "ticker": t,
                "name": funds[t].name if t in funds else t,
                "sector": sectors[t],
                "weight": float(w[t]),
                "volatility": float(asset_vol[i]),
                "beta": betas.get(t),
                "risk_contribution": float(rc[i]),
                "return": float((1 + rets[t]).prod() - 1),
            }
            for i, t in enumerate(w.index)
        ],
        "sectors": [
            {"sector": s, "weight": float(sector_w[s]), "risk_contribution": float(sector_rc[s])}
            for s in sector_w.index
        ],
        "correlation": {"tickers": list(corr.columns), "matrix": corr.fillna(0).values.tolist()},
        "equity": series_points((1 + port).cumprod()),
        "benchmark_equity": series_points((1 + bench).cumprod()) if bench is not None else [],
        "drawdown": series_points(drawdown(port)),
    }
