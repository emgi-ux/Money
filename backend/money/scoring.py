"""Cross-sectional standardisation and multi-factor composite scoring."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .factors import FACTORS, METRIC_BY_KEY

DEFAULT_WEIGHTS: dict[str, float] = {
    "value": 0.25,
    "quality": 0.25,
    "momentum": 0.25,
    "growth": 0.15,
    "low_vol": 0.10,
}

MIN_SECTOR_SIZE = 4   # smaller sectors fall back to universe-wide statistics
Z_CAP = 3.0


@dataclass
class ScoringConfig:
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    sector_neutral: bool = True
    winsor_pct: float = 0.025

    def normalized_weights(self) -> dict[str, float]:
        w = {k: max(0.0, float(v)) for k, v in self.weights.items() if k in FACTORS}
        total = sum(w.values())
        if total <= 0:
            raise ValueError("at least one factor weight must be positive")
        return {k: v / total for k, v in w.items() if v > 0}


def winsorize(s: pd.Series, pct: float) -> pd.Series:
    if s.count() < 3 or pct <= 0:
        return s
    lo, hi = s.quantile(pct), s.quantile(1 - pct)
    return s.clip(lo, hi)


def _zscore(s: pd.Series) -> pd.Series:
    sd = s.std()
    if s.count() < 2 or not np.isfinite(sd) or sd == 0:
        return s * 0.0
    return (s - s.mean()) / sd


def standardize(metrics: pd.DataFrame, sectors: pd.Series | None, cfg: ScoringConfig
                ) -> pd.DataFrame:
    """Winsorise and z-score each metric; flip sign where lower is better.

    With ``sector_neutral`` each stock is compared with its sector peers, which
    stops structurally cheap sectors (banks, energy) from dominating Value and
    high-margin sectors (software) from dominating Quality.
    """
    out = pd.DataFrame(index=metrics.index)
    for col in metrics.columns:
        meta = METRIC_BY_KEY.get(col)
        if meta is None:
            continue
        s = winsorize(metrics[col].astype(float), cfg.winsor_pct)
        z = _zscore(s)
        if cfg.sector_neutral and sectors is not None:
            sec = sectors.reindex(s.index)
            for _, members in sec.groupby(sec).groups.items():
                grp = s.loc[members]
                if grp.count() >= MIN_SECTOR_SIZE:
                    z.loc[members] = _zscore(grp)
        z = z.clip(-Z_CAP, Z_CAP)
        out[col] = z if meta.higher_is_better else -z
    return out


def factor_scores(z: pd.DataFrame) -> pd.DataFrame:
    """Average available metric z-scores within each factor, then re-standardise."""
    out = pd.DataFrame(index=z.index)
    for factor in FACTORS:
        cols = [c for c in z.columns if METRIC_BY_KEY[c].factor == factor]
        if not cols:
            continue
        out[factor] = _zscore(z[cols].mean(axis=1, skipna=True)).clip(-Z_CAP, Z_CAP)
    return out


def composite(factors: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Weighted blend of factor scores.

    Missing factors for a stock are dropped and remaining weights re-scaled,
    so a stock with no growth data is not penalised as if it had zero growth.
    Stocks with less than half the total weight covered get no score.
    """
    w = pd.Series({k: v for k, v in weights.items() if k in factors.columns}, dtype=float)
    if w.empty:
        return pd.Series(np.nan, index=factors.index)
    f = factors[w.index]
    avail = f.notna().mul(w, axis=1).sum(axis=1)
    score = f.fillna(0).mul(w, axis=1).sum(axis=1) / avail.replace(0, np.nan)
    score[avail < 0.5 * w.sum()] = np.nan
    return score


def percentile(s: pd.Series) -> pd.Series:
    return s.rank(pct=True) * 100


def score_universe(metrics: pd.DataFrame, sectors: pd.Series | None, cfg: ScoringConfig
                   ) -> pd.DataFrame:
    """Full pipeline -> DataFrame with factor scores, composite, percentile and rank."""
    weights = cfg.normalized_weights()
    z = standardize(metrics, sectors, cfg)
    fs = factor_scores(z)
    comp = composite(fs, weights)
    result = fs.copy()
    for f in fs.columns:
        result[f"{f}_pct"] = percentile(fs[f])
    result["composite"] = comp
    result["score"] = percentile(comp)
    result["rank"] = comp.rank(ascending=False, method="min")
    return result.sort_values("composite", ascending=False)


def grade(score_pct: float | None) -> str:
    if score_pct is None or not np.isfinite(score_pct):
        return "-"
    for cut, g in ((90, "A+"), (80, "A"), (70, "B+"), (60, "B"), (45, "C"), (30, "D")):
        if score_pct >= cut:
            return g
    return "F"
