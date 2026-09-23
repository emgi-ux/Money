from datetime import date

import numpy as np
import pandas as pd
import pytest

from money.analytics import drawdown, performance
from money.backtest import BacktestConfig, run_backtest
from money.data import SyntheticProvider
from money.portfolio import apply_cap, construct, project_capped_simplex, shrink_cov
from money.risk import analyze_portfolio
from money.scoring import ScoringConfig, composite, score_universe, standardize, winsorize
from money.screener import Filters, run_screen
from money.universe import resolve_universe

AS_OF = date(2026, 6, 30)
UNIVERSE = resolve_universe(None)


@pytest.fixture(scope="module")
def provider():
    return SyntheticProvider(as_of=AS_OF)


# ------------------------------------------------------------------ scoring
def test_winsorize_clips_tails():
    s = pd.Series(list(range(100)) + [10_000.0])
    w = winsorize(s, 0.025)
    assert w.max() < 200 and w.min() >= 0


def test_lower_is_better_metrics_are_flipped():
    m = pd.DataFrame({"debt_to_equity": [0.1, 1.0, 5.0], "roe": [0.3, 0.2, 0.1]},
                     index=["A", "B", "C"])
    z = standardize(m, None, ScoringConfig(sector_neutral=False, winsor_pct=0))
    assert z.loc["A", "debt_to_equity"] > z.loc["C", "debt_to_equity"]
    assert z.loc["A", "roe"] > z.loc["C", "roe"]


def test_sector_neutral_compares_within_sector():
    # Sector X is uniformly cheap; within-sector ranking should still spread it.
    idx = [f"X{i}" for i in range(5)] + [f"Y{i}" for i in range(5)]
    ey = [0.10, 0.11, 0.12, 0.13, 0.14, 0.02, 0.03, 0.04, 0.05, 0.06]
    m = pd.DataFrame({"earnings_yield": ey}, index=idx)
    sectors = pd.Series(["X"] * 5 + ["Y"] * 5, index=idx)
    neutral = standardize(m, sectors, ScoringConfig(sector_neutral=True, winsor_pct=0))
    raw = standardize(m, sectors, ScoringConfig(sector_neutral=False, winsor_pct=0))
    assert raw.loc["X0", "earnings_yield"] > raw.loc["Y4", "earnings_yield"]
    assert neutral.loc["X0", "earnings_yield"] < neutral.loc["Y4", "earnings_yield"]
    assert np.isclose(neutral.loc["X0", "earnings_yield"], neutral.loc["Y0", "earnings_yield"])


def test_composite_rescales_missing_factors():
    f = pd.DataFrame({"value": [1.0, 1.0], "momentum": [1.0, np.nan]}, index=["A", "B"])
    c = composite(f, {"value": 0.5, "momentum": 0.5})
    assert c["A"] == pytest.approx(1.0) and c["B"] == pytest.approx(1.0)
    c2 = composite(f, {"value": 0.2, "momentum": 0.8})
    assert np.isnan(c2["B"])  # less than half the weight covered


def test_score_universe_ranks(provider):
    res = run_screen(provider, UNIVERSE, as_of=AS_OF)
    t = res.table
    assert len(t) == len(UNIVERSE)
    assert t["rank"].iloc[0] == 1
    assert t["composite"].is_monotonic_decreasing
    assert t["score"].between(0, 100).all()


def test_screen_filters(provider):
    res = run_screen(provider, UNIVERSE, filters=Filters(max_pe=20, sectors=["Financials", "Energy"]),
                     as_of=AS_OF)
    assert len(res.table) > 0
    assert set(res.table["sector"]) <= {"Financials", "Energy"}
    assert (res.table["pe"].astype(float) <= 20).all()


def test_invalid_weights_rejected():
    with pytest.raises(ValueError):
        score_universe(pd.DataFrame({"roe": [1, 2]}), None, ScoringConfig(weights={"value": 0}))


# ---------------------------------------------------------------- portfolio
def test_projection_and_cap():
    w = project_capped_simplex(np.array([5.0, 1.0, 0.2, -3.0]), 0.5)
    assert w.sum() == pytest.approx(1) and w.max() <= 0.5 + 1e-9 and w.min() >= 0
    c = apply_cap(np.array([0.7, 0.2, 0.1]), 0.4)
    assert c.sum() == pytest.approx(1) and c.max() <= 0.4 + 1e-9


def test_risk_parity_equalises_risk_contributions():
    rng = np.random.default_rng(0)
    vols = np.array([0.01, 0.02, 0.04])
    rets = pd.DataFrame(rng.standard_normal((1000, 3)) * vols, columns=list("ABC"))
    w = construct(list("ABC"), "risk_parity", returns=rets)
    cov = shrink_cov(rets.to_numpy())
    rc = w.to_numpy() * (cov @ w.to_numpy())
    assert np.allclose(rc / rc.sum(), 1 / 3, atol=1e-3)
    assert w["A"] > w["B"] > w["C"]


def test_min_variance_respects_cap():
    rng = np.random.default_rng(1)
    rets = pd.DataFrame(rng.standard_normal((500, 5)) * [0.005, 0.01, 0.02, 0.02, 0.03],
                        columns=list("ABCDE"))
    w = construct(list("ABCDE"), "min_variance", returns=rets, max_weight=0.3)
    assert w.sum() == pytest.approx(1) and w.max() <= 0.3 + 1e-6
    assert w["A"] == pytest.approx(0.3, abs=1e-4)


# ---------------------------------------------------------------- analytics
def test_performance_on_known_series():
    idx = pd.bdate_range("2020-01-01", periods=252)
    r = pd.Series(0.001, index=idx)
    p = performance(r)
    assert p["total_return"] == pytest.approx(1.001**252 - 1)
    assert p["max_drawdown"] == 0
    dd = drawdown(pd.Series([0.1, -0.5, 0.2], index=idx[:3]))
    assert dd.min() == pytest.approx(-0.5)


# ----------------------------------------------------------------- backtest
class _PerturbedProvider(SyntheticProvider):
    """Same as synthetic but prices after ``cut`` are scrambled."""

    def __init__(self, cut, **kw):
        super().__init__(**kw)
        self.cut = pd.Timestamp(cut)

    def prices(self, tickers, start, end):
        out = super().prices(tickers, start, end)
        for i, (t, df) in enumerate(out.items()):
            df = df.copy()
            df.loc[df.index > self.cut, "close"] *= 1 + 0.5 * np.sin(i)
            out[t] = df
        return out


def test_backtest_has_no_lookahead():
    cfg = BacktestConfig(start=date(2020, 1, 1), end=date(2023, 12, 31), top_n=10)
    base = run_backtest(SyntheticProvider(as_of=AS_OF), UNIVERSE, cfg)
    cut = date(2022, 6, 30)
    pert = run_backtest(_PerturbedProvider(cut, as_of=AS_OF), UNIVERSE, cfg)
    before = [h for h in base.holdings if h["date"] <= cut.isoformat()]
    assert before and before == pert.holdings[: len(before)]


def test_backtest_costs_reduce_returns(provider):
    kw = dict(start=date(2019, 1, 1), end=date(2024, 12, 31), top_n=15)
    free = run_backtest(provider, UNIVERSE, BacktestConfig(cost_bps=0, **kw))
    costly = run_backtest(provider, UNIVERSE, BacktestConfig(cost_bps=50, **kw))
    assert (1 + costly.returns).prod() < (1 + free.returns).prod()
    for h in free.holdings:
        assert len(h["positions"]) == 15
        assert sum(p["weight"] for p in h["positions"]) == pytest.approx(1)


def test_backtest_rejects_fundamental_factors(provider):
    with pytest.raises(ValueError, match="price-based"):
        run_backtest(provider, UNIVERSE, BacktestConfig(
            start=date(2020, 1, 1), end=date(2021, 1, 1), weights={"value": 1.0}))


# --------------------------------------------------------------------- risk
def test_risk_contributions_sum_to_one(provider):
    r = analyze_portfolio(provider, {"AAPL": 0.4, "JPM": 0.3, "XOM": 0.3}, as_of=AS_OF)
    assert sum(p["risk_contribution"] for p in r["positions"]) == pytest.approx(1)
    assert sum(p["weight"] for p in r["positions"]) == pytest.approx(1)
    assert r["summary"]["volatility"] > 0
