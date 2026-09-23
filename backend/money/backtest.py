"""Walk-forward backtester for price-based factor strategies.

Design choices that keep results honest:
  * Signals at a rebalance date use only prices up to that date's close.
  * Trades execute at the *next* session's close (``execution_lag`` days).
  * Transaction costs are charged on actual turnover (drifted -> target).
  * Only price-derived factors are allowed: free fundamentals feeds are
    current snapshots, so using them historically would leak future data.

Known limitation: the universe is today's constituent list, so the test has
survivorship bias. Results are best read *relative* to the equal-weight
universe benchmark, which shares that bias.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .analytics import drawdown, equity_curve, monthly_returns, performance, series_points
from .data.base import DataProvider
from .factors import PRICE_FACTORS, price_metric_panel, price_metrics_at
from .portfolio import construct
from .scoring import ScoringConfig, score_universe
from .universe import DEFAULT_BENCHMARK

WARMUP_DAYS = 420
REBALANCE_FREQ = {"monthly": "ME", "quarterly": "QE"}


@dataclass
class BacktestConfig:
    start: date
    end: date
    weights: dict[str, float] = field(default_factory=lambda: {"momentum": 0.7, "low_vol": 0.3})
    top_n: int = 20
    rebalance: str = "monthly"
    weighting: str = "equal"
    max_weight: float = 0.10
    cost_bps: float = 10.0
    sector_neutral: bool = False
    execution_lag: int = 1
    rf: float = 0.0
    benchmark: str = DEFAULT_BENCHMARK


@dataclass
class BacktestResult:
    returns: pd.Series
    benchmark_returns: pd.Series
    universe_returns: pd.Series
    holdings: list[dict]
    turnover: pd.Series
    config: BacktestConfig

    def summary(self) -> dict:
        strat = performance(self.returns, self.benchmark_returns, self.config.rf)
        years = len(self.returns) / 252
        strat["avg_turnover"] = float(self.turnover.mean()) if len(self.turnover) else None
        strat["annual_turnover"] = float(self.turnover.sum() / years) if years > 0 else None
        return {
            "strategy": strat,
            "benchmark": performance(self.benchmark_returns, None, self.config.rf),
            "universe": performance(self.universe_returns, self.benchmark_returns, self.config.rf),
        }

    def to_dict(self) -> dict:
        m = monthly_returns(self.returns)
        return {
            "summary": self.summary(),
            "equity": {
                "strategy": series_points(equity_curve(self.returns)),
                "benchmark": series_points(equity_curve(self.benchmark_returns)),
                "universe": series_points(equity_curve(self.universe_returns)),
            },
            "drawdown": {
                "strategy": series_points(drawdown(self.returns)),
                "benchmark": series_points(drawdown(self.benchmark_returns)),
            },
            "monthly": [{"year": d.year, "month": d.month, "ret": float(v)} for d, v in m.items()],
            "holdings": self.holdings,
        }


def _rebalance_dates(index: pd.DatetimeIndex, start: date, end: date, freq: str) -> list[pd.Timestamp]:
    idx = index[(index >= pd.Timestamp(start)) & (index <= pd.Timestamp(end))]
    if idx.empty:
        return []
    s = pd.Series(idx, index=idx)
    return list(s.groupby(pd.Grouper(freq=REBALANCE_FREQ[freq])).last().dropna())


def run_backtest(provider: DataProvider, tickers: list[str], cfg: BacktestConfig) -> BacktestResult:
    bad = [k for k, v in cfg.weights.items() if v > 0 and k not in PRICE_FACTORS]
    if bad:
        raise ValueError(
            f"backtests support price-based factors only ({', '.join(PRICE_FACTORS)}); got {bad}"
        )
    if cfg.rebalance not in REBALANCE_FREQ:
        raise ValueError(f"rebalance must be one of {list(REBALANCE_FREQ)}")

    frames = provider.prices(tickers + [cfg.benchmark],
                             cfg.start - timedelta(days=WARMUP_DAYS), cfg.end)
    bench_df = frames.pop(cfg.benchmark, None)
    closes = pd.DataFrame({t: df["close"] for t, df in frames.items() if not df.empty}).sort_index()
    if closes.empty:
        raise ValueError("no price data for the requested universe")
    bench_close = bench_df["close"].reindex(closes.index).ffill() if bench_df is not None else None

    # Returns: no fill across a stock's absence; held-but-missing days return 0.
    rets = closes.pct_change(fill_method=None)
    panel = price_metric_panel(closes, bench_close)
    sectors = None
    if cfg.sector_neutral:
        sectors = pd.Series({t: f.sector for t, f in provider.fundamentals(list(closes.columns)).items()})

    scoring = ScoringConfig(weights=cfg.weights, sector_neutral=cfg.sector_neutral)
    dates = closes.index
    rebals = _rebalance_dates(dates, cfg.start, cfg.end, cfg.rebalance)
    if not rebals:
        raise ValueError("backtest window contains no rebalance dates")

    # Map each execution day -> target weights.
    targets: dict[pd.Timestamp, pd.Series] = {}
    holdings_log = []
    for d in rebals:
        pos = dates.get_loc(d) + cfg.execution_lag
        if pos >= len(dates):
            break
        px_ok = closes.loc[d].notna()
        metrics = price_metrics_at(panel, d).loc[px_ok[px_ok].index]
        scored = score_universe(metrics, sectors, scoring).dropna(subset=["composite"])
        if scored.empty:
            continue
        picks = list(scored.index[: cfg.top_n])
        hist = rets.loc[:d].iloc[-252:]
        w = construct(picks, cfg.weighting, returns=hist, scores=scored["composite"],
                      max_weight=cfg.max_weight)
        targets[dates[pos]] = w
        holdings_log.append({
            "date": d.strftime("%Y-%m-%d"),
            "positions": [{"ticker": t, "weight": float(wt),
                           "score": float(scored.loc[t, "score"])} for t, wt in w.items()],
        })

    sim_start = min(targets) if targets else None
    if sim_start is None:
        raise ValueError("not enough history to form any portfolio; try a later start date")
    sim_dates = dates[(dates >= sim_start) & (dates <= pd.Timestamp(cfg.end))]

    port_ret = pd.Series(0.0, index=sim_dates)
    turnover = {}
    w = pd.Series(dtype=float)
    cost_rate = cfg.cost_bps / 1e4
    for i, d in enumerate(sim_dates):
        if i > 0:
            r = rets.loc[d].reindex(w.index).fillna(0.0)
            gross = float((w * r).sum())
            port_ret[d] = gross
            # Let weights drift with prices; cash from any loss stays in-portfolio.
            w = w * (1 + r) / (1 + gross) if gross > -1 else w * 0
        if d in targets:
            tgt = targets[d]
            allidx = w.index.union(tgt.index)
            to = float((tgt.reindex(allidx, fill_value=0) - w.reindex(allidx, fill_value=0)).abs().sum())
            turnover[d] = to
            port_ret[d] -= to * cost_rate
            w = tgt.copy()

    universe_ret = rets.loc[sim_dates].mean(axis=1, skipna=True).fillna(0.0)
    universe_ret.iloc[0] = 0.0
    if bench_close is not None:
        bench_ret = bench_close.pct_change().reindex(sim_dates).fillna(0.0)
        bench_ret.iloc[0] = 0.0
    else:
        bench_ret = universe_ret.copy()

    return BacktestResult(
        returns=port_ret,
        benchmark_returns=bench_ret,
        universe_returns=universe_ret,
        holdings=holdings_log,
        turnover=pd.Series(turnover, dtype=float),
        config=cfg,
    )
