"""Intraday analytics for day trading: VWAP, EMAs, opening range, pivots,
signals, and a universe scanner for gappers / unusual volume / breakouts."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from .analytics import series_points
from .data.base import INTRADAY_INTERVALS, DataProvider

OPENING_RANGE_MINUTES = 30


def _ts(t: pd.Timestamp) -> int:
    """Chart timestamp in seconds. Bars are naive exchange-local times, encoded as
    if UTC so charts display the exchange wall clock regardless of viewer timezone."""
    return int(pd.Timestamp(t).value // 10**9)


def _points(s: pd.Series, digits: int = 4) -> list[dict]:
    s = s.dropna()
    return [{"time": _ts(t), "value": round(float(v), digits)} for t, v in s.items()]


def vwap(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Session-anchored VWAP and its volume-weighted standard deviation."""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    day = df.index.normalize()
    pv = (tp * df["volume"]).groupby(day).cumsum()
    vol = df["volume"].groupby(day).cumsum().replace(0, np.nan)
    vw = pv / vol
    var = ((tp**2) * df["volume"]).groupby(day).cumsum() / vol - vw**2
    return vw, np.sqrt(var.clip(lower=0))


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    gain = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + gain / loss.replace(0, np.nan))


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def pivots(high: float, low: float, close: float) -> dict[str, float]:
    p = (high + low + close) / 3
    return {"R3": high + 2 * (p - low), "R2": p + (high - low), "R1": 2 * p - low, "P": p,
            "S1": 2 * p - high, "S2": p - (high - low), "S3": low - 2 * (high - p)}


def _signals(s: pd.DataFrame, or_hi: float, or_lo: float, or_end: pd.Timestamp) -> list[dict]:
    out = []

    def add(t, kind, direction, text):
        out.append({"time": _ts(t), "clock": t.strftime("%H:%M"), "price": float(s.loc[t, "close"]),
                    "kind": kind, "direction": direction, "text": text})

    above = s["close"] > s["vwap"]
    ema_up = s["ema9"] > s["ema21"]
    for i in range(1, len(s)):
        t, prev_t = s.index[i], s.index[i - 1]
        if above.iloc[i] and not above.iloc[i - 1]:
            add(t, "vwap", "long", "Reclaimed VWAP")
        elif not above.iloc[i] and above.iloc[i - 1]:
            add(t, "vwap", "short", "Lost VWAP")
        if ema_up.iloc[i] and not ema_up.iloc[i - 1]:
            add(t, "ema", "long", "EMA 9 crossed above EMA 21")
        elif not ema_up.iloc[i] and ema_up.iloc[i - 1]:
            add(t, "ema", "short", "EMA 9 crossed below EMA 21")
        if t > or_end:
            c, pc = s.loc[t, "close"], s.loc[prev_t, "close"]
            if c > or_hi >= pc:
                add(t, "orb", "long", f"Opening-range breakout above {or_hi:.2f}")
            elif c < or_lo <= pc:
                add(t, "orb", "short", f"Opening-range breakdown below {or_lo:.2f}")
        r, pr = s["rsi"].iloc[i], s["rsi"].iloc[i - 1]
        if r >= 70 > pr:
            add(t, "rsi", "short", f"RSI overbought ({r:.0f})")
        elif r <= 30 < pr:
            add(t, "rsi", "long", f"RSI oversold ({r:.0f})")
    return out[::-1]


def intraday_view(provider: DataProvider, ticker: str, interval: str = "5m", days: int = 5,
                  as_of: date | None = None) -> dict:
    if interval not in INTRADAY_INTERVALS:
        raise ValueError(f"interval must be one of {list(INTRADAY_INTERVALS)}")
    df = provider.intraday(ticker, interval, days)
    if df is None or df.empty:
        raise ValueError(f"no intraday data for {ticker}")
    df = df.sort_index()
    df["vwap"], sd = vwap(df)
    df["vwap_u1"], df["vwap_l1"] = df["vwap"] + sd, df["vwap"] - sd
    df["vwap_u2"], df["vwap_l2"] = df["vwap"] + 2 * sd, df["vwap"] - 2 * sd
    df["ema9"] = df["close"].ewm(span=9, adjust=False).mean()
    df["ema21"] = df["close"].ewm(span=21, adjust=False).mean()
    df["rsi"] = rsi(df["close"])
    df["atr"] = atr(df)

    sessions = sorted(set(df.index.normalize()))
    today = sessions[-1]
    s = df[df.index.normalize() == today]
    minutes = INTRADAY_INTERVALS[interval]
    or_bars = max(1, OPENING_RANGE_MINUTES // minutes)
    or_slice = s.iloc[:or_bars]
    or_hi, or_lo = float(or_slice["high"].max()), float(or_slice["low"].min())
    or_end = or_slice.index[-1]

    # Daily context: previous session, daily ATR and pivots.
    as_of = as_of or date.today()
    daily = provider.prices([ticker], as_of - timedelta(days=60), as_of).get(ticker)
    prev_day = daily[daily.index.normalize() < today].iloc[-1] if daily is not None and len(daily) > 1 else None
    daily_atr = float(atr(daily).iloc[-1]) if daily is not None and len(daily) > 15 else None
    piv = pivots(float(prev_day["high"]), float(prev_day["low"]), float(prev_day["close"])) if prev_day is not None else {}
    prev_close = float(prev_day["close"]) if prev_day is not None else float(s["open"].iloc[0])

    # Relative volume: today's cumulative volume vs prior sessions at the same bar count.
    n = len(s)
    prior = [df[df.index.normalize() == d]["volume"].iloc[:n].sum() for d in sessions[:-1]]
    rvol = float(s["volume"].sum() / np.mean(prior)) if prior and np.mean(prior) > 0 else None

    last = s.iloc[-1]
    price = float(last["close"])
    above_vwap = price > float(last["vwap"])
    ema_bull = float(last["ema9"]) > float(last["ema21"])
    bias = "Bullish" if above_vwap and ema_bull else "Bearish" if not above_vwap and not ema_bull else "Mixed"
    bar_atr = float(last["atr"])

    candles = [{"time": _ts(t), "open": float(r.open), "high": float(r.high), "low": float(r.low),
                "close": float(r.close), "volume": float(r.volume)} for t, r in df.iterrows()]
    return {
        "ticker": ticker,
        "interval": interval,
        "session": today.strftime("%Y-%m-%d"),
        "candles": candles,
        "overlays": {k: _points(df[k]) for k in ("vwap", "vwap_u1", "vwap_l1", "vwap_u2", "vwap_l2",
                                                 "ema9", "ema21", "rsi")},
        "levels": {
            "opening_range_high": or_hi, "opening_range_low": or_lo,
            "prev_close": prev_close,
            "prev_high": float(prev_day["high"]) if prev_day is not None else None,
            "prev_low": float(prev_day["low"]) if prev_day is not None else None,
            "hod": float(s["high"].max()), "lod": float(s["low"].min()),
            "pivots": piv,
        },
        "summary": {
            "price": price,
            "change": price / prev_close - 1,
            "gap": float(s["open"].iloc[0]) / prev_close - 1,
            "vwap": float(last["vwap"]),
            "vs_vwap": price / float(last["vwap"]) - 1,
            "rsi": float(last["rsi"]) if pd.notna(last["rsi"]) else None,
            "rvol": rvol,
            "bar_atr": bar_atr,
            "daily_atr": daily_atr,
            "day_range_used": (float(s["high"].max()) - float(s["low"].min())) / daily_atr if daily_atr else None,
            "bias": bias,
            "long_stop": price - 1.5 * bar_atr,
            "short_stop": price + 1.5 * bar_atr,
        },
        "signals": _signals(s, or_hi, or_lo, or_end),
    }


def scan(provider: DataProvider, tickers: list[str], as_of: date | None = None) -> list[dict]:
    """Daily scanner: gappers, unusual volume, range expansion and 20-day breakouts."""
    as_of = as_of or date.today()
    frames = provider.prices(tickers, as_of - timedelta(days=60), as_of)
    rows = []
    for t, d in frames.items():
        if d is None or len(d) < 22:
            continue
        today, prev = d.iloc[-1], d.iloc[-2]
        hist = d.iloc[:-1]
        a = float(atr(d).iloc[-2])
        avg_vol = float(hist["volume"].tail(20).mean())
        hi20, lo20 = float(hist["high"].tail(20).max()), float(hist["low"].tail(20).min())
        rng = float(today["high"] - today["low"])
        setups = []
        gap = float(today["open"] / prev["close"] - 1)
        rvol = float(today["volume"] / avg_vol) if avg_vol else None
        if abs(gap) >= 0.02 and (rvol or 0) >= 1.5:
            setups.append("Gap & go" if (today["close"] > today["open"]) == (gap > 0) else "Gap fade")
        if today["close"] > hi20:
            setups.append("20-day breakout")
        elif today["close"] < lo20:
            setups.append("20-day breakdown")
        if today["high"] < prev["high"] and today["low"] > prev["low"]:
            setups.append("Inside day")
        if a and rng > 1.5 * a:
            setups.append("Range expansion")
        rows.append({
            "ticker": t,
            "price": float(today["close"]),
            "change": float(today["close"] / prev["close"] - 1),
            "gap": gap,
            "rvol": rvol,
            "volume": float(today["volume"]),
            "atr_pct": a / float(prev["close"]) if a else None,
            "range_vs_atr": rng / a if a else None,
            "close_in_range": float((today["close"] - today["low"]) / rng) if rng > 0 else None,
            "dist_20d_high": float(today["close"] / hi20 - 1),
            "setups": setups,
            "spark": series_points(d["close"].tail(20), 4),
        })
    return rows
