"""Long-only portfolio construction with position caps."""

from __future__ import annotations

import numpy as np
import pandas as pd

METHODS = {
    "equal": "Equal weight",
    "inverse_vol": "Inverse volatility",
    "risk_parity": "Equal risk contribution",
    "min_variance": "Minimum variance",
    "score": "Score weighted (tilts toward higher composite scores)",
}


def project_capped_simplex(v: np.ndarray, cap: float) -> np.ndarray:
    """Euclidean projection onto {w : 0 <= w_i <= cap, sum w = 1}."""
    n = len(v)
    cap = max(cap, 1.0 / n)  # infeasible caps are relaxed to equal weight
    lo, hi = v.min() - cap, v.max()
    for _ in range(100):
        tau = (lo + hi) / 2
        s = np.clip(v - tau, 0, cap).sum()
        if s > 1:
            lo = tau
        else:
            hi = tau
    w = np.clip(v - (lo + hi) / 2, 0, cap)
    return w / w.sum()


def apply_cap(w: np.ndarray, cap: float) -> np.ndarray:
    """Cap weights, redistributing excess pro rata to uncapped names."""
    n = len(w)
    cap = max(cap, 1.0 / n)
    w = w / w.sum()
    for _ in range(n):
        over = w > cap + 1e-12
        if not over.any():
            break
        excess = (w[over] - cap).sum()
        w[over] = cap
        free = ~over & (w < cap)
        if not free.any():
            break
        w[free] += excess * w[free] / w[free].sum()
    return w / w.sum()


def _risk_parity(cov: np.ndarray, iters: int = 500) -> np.ndarray:
    n = cov.shape[0]
    w = np.full(n, 1.0 / n)
    for _ in range(iters):
        rc = w * (cov @ w)
        target = rc.sum() / n
        w_new = w * np.sqrt(target / np.maximum(rc, 1e-18))
        w_new /= w_new.sum()
        if np.abs(w_new - w).max() < 1e-10:
            w = w_new
            break
        w = w_new
    return w


def _min_variance(cov: np.ndarray, cap: float, iters: int = 2000) -> np.ndarray:
    n = cov.shape[0]
    w = np.full(n, 1.0 / n)
    step = 1.0 / (2 * np.linalg.eigvalsh(cov).max() + 1e-12)
    for _ in range(iters):
        w_new = project_capped_simplex(w - step * 2 * cov @ w, cap)
        if np.abs(w_new - w).max() < 1e-10:
            return w_new
        w = w_new
    return w


def construct(tickers: list[str], method: str = "equal", returns: pd.DataFrame | None = None,
              scores: pd.Series | None = None, max_weight: float = 1.0) -> pd.Series:
    """Return weights (summing to 1) for ``tickers``.

    ``returns`` (daily, date x ticker) is required for the risk-based methods;
    ``scores`` (any scale, higher is better) is required for ``score``.
    """
    n = len(tickers)
    if n == 0:
        return pd.Series(dtype=float)
    if method not in METHODS:
        raise ValueError(f"unknown weighting method {method!r}")

    if method == "equal":
        w = np.full(n, 1.0 / n)
    elif method == "score":
        if scores is None:
            raise ValueError("score weighting needs scores")
        s = scores.reindex(tickers).astype(float)
        s = s.fillna(s.min() if s.notna().any() else 0.0)
        # Shift so the weakest selected name still gets a positive weight.
        s = s - s.min() + (s.std() if s.std() > 0 else 1.0) * 0.5
        w = (s / s.sum()).to_numpy()
    else:
        if returns is None:
            raise ValueError(f"{method} weighting needs return history")
        r = returns.reindex(columns=tickers).dropna(how="all").fillna(0.0)
        cov = shrink_cov(r.to_numpy())
        if method == "inverse_vol":
            vol = np.sqrt(np.diag(cov))
            w = 1.0 / np.maximum(vol, 1e-8)
            w /= w.sum()
        elif method == "risk_parity":
            w = _risk_parity(cov)
        else:
            w = _min_variance(cov, max_weight)
    return pd.Series(apply_cap(np.asarray(w, dtype=float), max_weight), index=tickers)


def shrink_cov(x: np.ndarray, shrink: float | None = None) -> np.ndarray:
    """Ledoit-Wolf style shrinkage of the sample covariance toward a scaled identity.

    Sample covariances of many stocks over short windows are noisy; shrinkage
    makes optimisers (min-variance, risk parity) far more stable.
    """
    t, n = x.shape
    if t < 2:
        return np.eye(n) * 1e-4
    xc = x - x.mean(axis=0)
    s = xc.T @ xc / t
    mu = np.trace(s) / n
    target = mu * np.eye(n)
    if shrink is None:
        d2 = ((s - target) ** 2).sum()
        b2 = sum(((np.outer(row, row) - s) ** 2).sum() for row in xc) / t**2
        shrink = float(np.clip(b2 / d2, 0, 1)) if d2 > 0 else 1.0
    return shrink * target + (1 - shrink) * s
