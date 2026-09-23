"""Performance statistics for daily return series."""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def equity_curve(returns: pd.Series, start: float = 1.0) -> pd.Series:
    return start * (1 + returns.fillna(0)).cumprod()


def drawdown(returns: pd.Series) -> pd.Series:
    eq = equity_curve(returns)
    return eq / eq.cummax() - 1


def monthly_returns(returns: pd.Series) -> pd.Series:
    return (1 + returns.fillna(0)).resample("ME").prod() - 1


def performance(returns: pd.Series, benchmark: pd.Series | None = None,
                rf: float = 0.0) -> dict[str, float | None]:
    """Summary stats. ``rf`` is the annual risk-free rate."""
    r = returns.dropna()
    if len(r) < 2:
        return {}
    n_years = len(r) / TRADING_DAYS
    total = float((1 + r).prod() - 1)
    cagr = (1 + total) ** (1 / n_years) - 1 if n_years > 0 and total > -1 else None
    vol = float(r.std() * np.sqrt(TRADING_DAYS))
    rf_d = (1 + rf) ** (1 / TRADING_DAYS) - 1
    excess = r - rf_d
    sharpe = float(excess.mean() / r.std() * np.sqrt(TRADING_DAYS)) if r.std() > 0 else None
    downside = np.sqrt((np.minimum(excess, 0) ** 2).mean()) * np.sqrt(TRADING_DAYS)
    sortino = float(excess.mean() * TRADING_DAYS / downside) if downside > 0 else None
    dd = drawdown(r)
    max_dd = float(dd.min())
    monthly = monthly_returns(r)
    out: dict[str, float | None] = {
        "total_return": total,
        "cagr": cagr,
        "volatility": vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_dd,
        "calmar": (cagr / abs(max_dd)) if cagr is not None and max_dd < 0 else None,
        "var_95": float(-np.percentile(r, 5)),
        "cvar_95": float(-r[r <= np.percentile(r, 5)].mean()),
        "best_month": float(monthly.max()) if len(monthly) else None,
        "worst_month": float(monthly.min()) if len(monthly) else None,
        "pct_positive_months": float((monthly > 0).mean()) if len(monthly) else None,
    }
    if benchmark is not None:
        b = benchmark.reindex(r.index).fillna(0)
        var_b = b.var()
        beta = float(r.cov(b) / var_b) if var_b > 0 else None
        active = r - b
        te = float(active.std() * np.sqrt(TRADING_DAYS))
        out["beta"] = beta
        if beta is not None:
            alpha_d = (r.mean() - rf_d) - beta * (b.mean() - rf_d)
            out["alpha"] = float(alpha_d * TRADING_DAYS)
        out["tracking_error"] = te
        out["information_ratio"] = float(active.mean() * TRADING_DAYS / te) if te > 0 else None
        out["correlation"] = float(r.corr(b))
        bm = monthly_returns(b)
        common = monthly.index.intersection(bm.index)
        out["hit_rate_vs_benchmark"] = (
            float((monthly[common] > bm[common]).mean()) if len(common) else None
        )
    return {k: (None if v is None or not np.isfinite(v) else float(v)) for k, v in out.items()}


def series_points(s: pd.Series, digits: int = 6) -> list[dict]:
    """Serialise a date-indexed series for charting."""
    s = s.dropna()
    return [{"time": d.strftime("%Y-%m-%d"), "value": round(float(v), digits)}
            for d, v in s.items()]
