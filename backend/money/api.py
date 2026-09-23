"""HTTP API (FastAPI). Run with: ``uvicorn money.api:app --reload``."""

from __future__ import annotations

import math
import os
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .analysis import deep_analysis
from .analytics import series_points
from .api_users import require_pro, router as users_router
from .billing import paywall_enabled
from .backtest import BacktestConfig, run_backtest
from .data import get_provider
from .daytrade import intraday_view, scan
from .factors import FACTORS, PRICE_FACTORS, technicals
from .portfolio import METHODS, construct
from .risk import analyze_portfolio
from .screener import Filters, metric_catalog, run_screen
from .scoring import DEFAULT_WEIGHTS, ScoringConfig
from .universe import DEFAULT_BENCHMARK, UNIVERSES, resolve_universe

app = FastAPI(title="Money", version=__version__)
_origins = [o for o in os.environ.get("MONEY_CORS_ORIGINS", "").split(",") if o] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["*"], allow_headers=["*"])
app.include_router(users_router)
PRO = [Depends(require_pro)]


def clean(obj: Any) -> Any:
    """Make numpy / NaN-laden structures JSON-safe."""
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, (pd.Timestamp, date)):
        return obj.isoformat()[:10]
    return obj


def provider():
    return get_provider()


# ---------------------------------------------------------------- small cache
_cache: dict[str, tuple[float, Any]] = {}
CACHE_TTL = 600


def cached(key: str, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    val = fn()
    _cache[key] = (time.time(), val)
    return val


# --------------------------------------------------------------------- models
class ScreenRequest(BaseModel):
    universe: str | list[str] | None = None
    weights: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    sector_neutral: bool = True
    min_market_cap: float | None = None
    max_pe: float | None = None
    min_dividend_yield: float | None = None
    max_debt_to_equity: float | None = None
    max_vol: float | None = None
    above_sma200: bool = False
    sectors: list[str] = Field(default_factory=list)
    exclude_sectors: list[str] = Field(default_factory=list)
    limit: int | None = None


class BacktestRequest(BaseModel):
    universe: str | list[str] | None = None
    start: date = Field(default_factory=lambda: date.today() - timedelta(days=365 * 10))
    end: date = Field(default_factory=date.today)
    weights: dict[str, float] = Field(default_factory=lambda: {"momentum": 0.7, "low_vol": 0.3})
    top_n: int = Field(20, ge=1, le=500)
    rebalance: str = "monthly"
    weighting: str = "equal"
    max_weight: float = Field(0.10, gt=0, le=1)
    cost_bps: float = Field(10.0, ge=0, le=500)
    sector_neutral: bool = False
    rf: float = 0.0


class Holdings(BaseModel):
    weights: dict[str, float]
    lookback_days: int = Field(365, ge=60, le=365 * 10)


class ConstructRequest(BaseModel):
    tickers: list[str] | None = None
    from_screen: ScreenRequest | None = None
    top_n: int = Field(15, ge=1, le=200)
    method: str = "risk_parity"
    max_weight: float = Field(0.10, gt=0, le=1)
    lookback_days: int = Field(365, ge=60, le=365 * 10)


# ------------------------------------------------------------------ endpoints
@app.get("/api/meta")
def meta():
    p = provider()
    return {
        "version": __version__,
        "provider": p.name,
        "benchmark": DEFAULT_BENCHMARK,
        "universes": {k: len(v) for k, v in UNIVERSES.items()},
        "factors": FACTORS,
        "price_factors": PRICE_FACTORS,
        "default_weights": DEFAULT_WEIGHTS,
        "metrics": metric_catalog(),
        "weighting_methods": METHODS,
        "sectors": sorted(set(UNIVERSES["us_large_cap"].values())),
        "paywall": paywall_enabled(),
    }


def _screen(req: ScreenRequest):
    tickers = resolve_universe(req.universe)
    cfg = ScoringConfig(weights=req.weights, sector_neutral=req.sector_neutral)
    filters = Filters(
        min_market_cap=req.min_market_cap, max_pe=req.max_pe,
        min_dividend_yield=req.min_dividend_yield, max_debt_to_equity=req.max_debt_to_equity,
        max_vol=req.max_vol, above_sma200=req.above_sma200,
        sectors=req.sectors, exclude_sectors=req.exclude_sectors,
    )
    key = "screen:" + req.model_dump_json(exclude={"limit"})
    try:
        return cached(key, lambda: run_screen(provider(), tickers, cfg, filters))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/screen")
def screen(req: ScreenRequest):
    res = _screen(req)
    return clean({
        "as_of": res.as_of,
        "universe_size": res.universe_size,
        "count": len(res.table),
        "missing": res.missing,
        "rows": res.records(req.limit),
    })


@app.get("/api/stock/{ticker}")
def stock(ticker: str, years: float = Query(2.0, gt=0, le=20)):
    ticker = ticker.upper()
    p = provider()
    today = date.today()
    start = today - timedelta(days=int(365 * years) + 300)  # extra for SMA200 warm-up
    frames = p.prices([ticker], start, today)
    df = frames.get(ticker)
    if df is None or df.empty:
        raise HTTPException(404, f"no price data for {ticker}")
    funds = p.fundamentals([ticker]).get(ticker)
    tech = technicals(df)
    cut = pd.Timestamp(today - timedelta(days=int(365 * years)))
    view = df.loc[cut:]

    # Factor profile relative to the default universe (ticker added if absent).
    universe = resolve_universe(None)
    if ticker not in universe:
        universe = universe + [ticker]
    req = ScreenRequest(universe=universe)
    table = _screen(req).table
    row = table.loc[ticker].to_dict() if ticker in table.index else {}

    closes = df["close"]

    def ret(days: int):
        return float(closes.iloc[-1] / closes.iloc[-days - 1] - 1) if len(closes) > days else None

    return clean({
        "ticker": ticker,
        "fundamentals": funds.to_dict() if funds else None,
        "profile": row,
        "peers": _peers(table, row.get("sector"), ticker),
        "returns": {"1w": ret(5), "1m": ret(21), "3m": ret(63), "6m": ret(126), "1y": ret(252)},
        "candles": [
            {"time": d.strftime("%Y-%m-%d"), "open": r.open, "high": r.high, "low": r.low,
             "close": r.close, "volume": r.volume}
            for d, r in view.iterrows()
        ],
        "overlays": {k: series_points(v.loc[cut:], 4) for k, v in tech.items()},
    })


@app.get("/api/analysis/{ticker}", dependencies=PRO)
def analysis(ticker: str):
    ticker = ticker.upper()
    universe = resolve_universe(None)
    if ticker not in universe:
        universe = universe + [ticker]
    table = _screen(ScreenRequest(universe=universe)).table
    profile = table.loc[ticker].to_dict() if ticker in table.index else {}
    sector = profile.get("sector")
    peers = table[table["sector"] == sector] if sector else table.iloc[0:0]
    try:
        return clean(cached(f"analysis:{ticker}",
                            lambda: deep_analysis(provider(), ticker, profile, peers)))
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@app.get("/api/daytrade/{ticker}", dependencies=PRO)
def daytrade(ticker: str, interval: str = "5m", days: int = Query(5, ge=1, le=30)):
    try:
        return clean(intraday_view(provider(), ticker.upper(), interval, days))
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@app.get("/api/scanner", dependencies=PRO)
def scanner(universe: str | None = None):
    rows = cached(f"scan:{universe}", lambda: scan(provider(), resolve_universe(universe)))
    return clean({"rows": rows})


def _peers(table: pd.DataFrame, sector: str | None, ticker: str) -> list[dict]:
    if not sector:
        return []
    peers = table[table["sector"] == sector].head(12)
    cols = ["name", "score", "grade", "value", "quality", "momentum", "growth", "low_vol", "pe"]
    return [{"ticker": t, **{c: peers.loc[t, c] for c in cols if c in peers.columns},
             "is_self": t == ticker} for t in peers.index]


@app.post("/api/backtest", dependencies=PRO)
def backtest(req: BacktestRequest):
    cfg = BacktestConfig(
        start=req.start, end=req.end, weights=req.weights, top_n=req.top_n,
        rebalance=req.rebalance, weighting=req.weighting, max_weight=req.max_weight,
        cost_bps=req.cost_bps, sector_neutral=req.sector_neutral, rf=req.rf,
    )
    try:
        res = cached("bt:" + req.model_dump_json(),
                     lambda: run_backtest(provider(), resolve_universe(req.universe), cfg))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return clean(res.to_dict())


@app.post("/api/portfolio/analyze", dependencies=PRO)
def portfolio_analyze(req: Holdings):
    weights = {k.upper(): v for k, v in req.weights.items()}
    try:
        return clean(analyze_portfolio(provider(), weights, req.lookback_days))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/portfolio/construct", dependencies=PRO)
def portfolio_construct(req: ConstructRequest):
    p = provider()
    scores = None
    if req.tickers:
        tickers = [t.upper() for t in req.tickers]
    else:
        table = _screen(req.from_screen or ScreenRequest()).table.dropna(subset=["composite"])
        tickers = list(table.index[: req.top_n])
        scores = table["composite"]
    today = date.today()
    frames = p.prices(tickers, today - timedelta(days=req.lookback_days), today)
    rets = pd.DataFrame({t: d["close"] for t, d in frames.items()}).pct_change(fill_method=None)
    try:
        w = construct(tickers, req.method, returns=rets.iloc[1:], scores=scores,
                      max_weight=req.max_weight)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return clean({"method": req.method, "weights": w.round(6).to_dict()})


# ------------------------------------------------- serve the built frontend
_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = _dist / path
        return FileResponse(f if path and f.is_file() else _dist / "index.html")
