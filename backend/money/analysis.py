"""Deep single-stock analysis: intrinsic value, financial health, risk and thesis.

Everything here is a *model output* built from public data, not investment
advice. The UI labels it accordingly.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from .analytics import TRADING_DAYS, drawdown, performance, series_points
from .data.base import DataProvider, Fundamentals
from .universe import DEFAULT_BENCHMARK

RISK_FREE = 0.0425
EQUITY_RISK_PREMIUM = 0.055
TERMINAL_GROWTH = 0.025


# --------------------------------------------------------------------- DCF
def discount_rate(beta: float | None) -> float:
    """Cost of equity via CAPM, clamped to a sane range."""
    b = 1.0 if beta is None or not np.isfinite(beta) else float(np.clip(beta, 0.5, 2.0))
    return float(np.clip(RISK_FREE + b * EQUITY_RISK_PREMIUM, 0.06, 0.14))


def dcf_value(fcf0: float, growth: float, rate: float, terminal: float = TERMINAL_GROWTH,
              years: int = 10, high_growth_years: int = 5) -> dict:
    """Two-stage DCF of free cash flow to equity.

    Growth is held at ``growth`` for ``high_growth_years`` and then fades
    linearly to ``terminal`` by year ``years``; a Gordon terminal value follows.
    Returns the equity value and its components.
    """
    if rate <= terminal:
        raise ValueError("discount rate must exceed terminal growth")
    flows, pvs = [], []
    fcf = fcf0
    for y in range(1, years + 1):
        if y <= high_growth_years:
            g = growth
        else:
            frac = (y - high_growth_years) / (years - high_growth_years)
            g = growth + (terminal - growth) * frac
        fcf *= 1 + g
        flows.append(fcf)
        pvs.append(fcf / (1 + rate) ** y)
    tv = flows[-1] * (1 + terminal) / (rate - terminal)
    pv_tv = tv / (1 + rate) ** years
    return {
        "equity_value": float(sum(pvs) + pv_tv),
        "pv_cash_flows": float(sum(pvs)),
        "pv_terminal": float(pv_tv),
        "terminal_share": float(pv_tv / (sum(pvs) + pv_tv)),
        "projected_fcf": [float(x) for x in flows],
    }


def _cagr(first: float, last: float, years: float) -> float | None:
    if years <= 0 or first is None or last is None or first <= 0 or last <= 0:
        return None
    return float((last / first) ** (1 / years) - 1)


def valuation(st: pd.DataFrame, f: Fundamentals, price: float) -> dict:
    out: dict = {"method": "Two-stage free-cash-flow DCF", "available": False}
    if st.empty or "free_cash_flow" not in st or "shares" not in st:
        out["reason"] = "Financial statements unavailable"
        return out
    fcf_hist = st["free_cash_flow"].dropna()
    shares = st["shares"].dropna()
    if fcf_hist.empty or shares.empty:
        out["reason"] = "Free cash flow or share count unavailable"
        return out
    # Normalise FCF: average of the last three years dampens one-off swings.
    fcf0 = float(fcf_hist.tail(3).mean())
    if fcf0 <= 0:
        out["reason"] = "Negative normalised free cash flow - DCF not meaningful"
        return out
    n_shares = float(shares.iloc[-1])

    rev = st["revenue"].dropna() if "revenue" in st else pd.Series(dtype=float)
    hist_g = _cagr(rev.iloc[0], rev.iloc[-1], len(rev) - 1) if len(rev) >= 2 else None
    candidates = [g for g in (hist_g, f.revenue_growth) if g is not None and np.isfinite(g)]
    base_g = float(np.clip(np.mean(candidates) if candidates else 0.04, -0.05, 0.20))
    rate = discount_rate(f.beta)

    scenarios = {}
    for name, dg, dr in (("bear", -0.05, 0.01), ("base", 0.0, 0.0), ("bull", 0.05, -0.01)):
        g = float(np.clip(base_g + dg, -0.10, 0.30))
        r = rate + dr
        v = dcf_value(fcf0, g, r)
        scenarios[name] = {
            "growth": g, "discount_rate": r,
            "fair_value": v["equity_value"] / n_shares,
            "upside": v["equity_value"] / n_shares / price - 1,
            "terminal_share": v["terminal_share"],
        }
    base = dcf_value(fcf0, base_g, rate)

    rates = [rate - 0.02, rate - 0.01, rate, rate + 0.01, rate + 0.02]
    terms = [0.015, 0.02, 0.025, 0.03, 0.035]
    grid = [[dcf_value(fcf0, base_g, r, t)["equity_value"] / n_shares if r > t + 0.005 else None
             for t in terms] for r in rates]

    # Reverse DCF: growth the market price implies at the base discount rate.
    lo, hi = -0.2, 0.5
    target = price * n_shares
    for _ in range(60):
        mid = (lo + hi) / 2
        if dcf_value(fcf0, mid, rate)["equity_value"] < target:
            lo = mid
        else:
            hi = mid
    implied = (lo + hi) / 2

    out.update({
        "available": True,
        "normalized_fcf": fcf0,
        "shares": n_shares,
        "price": price,
        "base_growth": base_g,
        "historical_revenue_cagr": hist_g,
        "discount_rate": rate,
        "terminal_growth": TERMINAL_GROWTH,
        "fair_value": scenarios["base"]["fair_value"],
        "upside": scenarios["base"]["upside"],
        "margin_of_safety": 1 - price / scenarios["base"]["fair_value"],
        "implied_growth": implied if -0.19 < implied < 0.49 else None,
        "scenarios": scenarios,
        "projected_fcf": base["projected_fcf"],
        "sensitivity": {"discount_rates": rates, "terminal_growth": terms, "values": grid},
    })
    return out


# --------------------------------------------------------- financial health
def piotroski(st: pd.DataFrame) -> dict:
    """Piotroski F-score (0-9) from the two most recent fiscal years."""
    need = ["net_income", "total_assets", "operating_cash_flow", "revenue"]
    if len(st) < 2 or any(c not in st for c in need):
        return {"available": False, "reason": "Needs two years of statements"}
    cur, prev = st.iloc[-1], st.iloc[-2]

    def ratio(row, a, b):
        try:
            return float(row[a]) / float(row[b]) if row[b] else np.nan
        except (KeyError, TypeError):
            return np.nan

    roa, roa_prev = ratio(cur, "net_income", "total_assets"), ratio(prev, "net_income", "total_assets")
    lev, lev_prev = ratio(cur, "long_term_debt", "total_assets"), ratio(prev, "long_term_debt", "total_assets")
    cr, cr_prev = ratio(cur, "current_assets", "current_liabilities"), ratio(prev, "current_assets", "current_liabilities")
    gm, gm_prev = ratio(cur, "gross_profit", "revenue"), ratio(prev, "gross_profit", "revenue")
    at, at_prev = ratio(cur, "revenue", "total_assets"), ratio(prev, "revenue", "total_assets")
    cfo = float(cur["operating_cash_flow"])

    def check(name, group, passed, detail):
        return {"name": name, "group": group,
                "pass": None if passed is None or (isinstance(passed, float) and np.isnan(passed)) else bool(passed),
                "detail": detail}

    def cmp(a, b, better="higher"):
        if np.isnan(a) or np.isnan(b):
            return None
        return a > b if better == "higher" else a < b

    shares_ok = None
    if "shares" in st and pd.notna(cur.get("shares")) and pd.notna(prev.get("shares")):
        shares_ok = float(cur["shares"]) <= float(prev["shares"]) * 1.005
    checks = [
        check("Positive ROA", "Profitability", roa > 0, f"ROA {roa:.1%}"),
        check("Positive operating cash flow", "Profitability", cfo > 0, f"CFO {cfo / 1e9:,.2f}B"),
        check("Improving ROA", "Profitability", cmp(roa, roa_prev), f"{roa_prev:.1%} → {roa:.1%}"),
        check("Cash flow exceeds net income", "Profitability",
              cfo > float(cur["net_income"]), "Low accruals = higher earnings quality"),
        check("Lower leverage", "Leverage & liquidity", cmp(lev, lev_prev, "lower"),
              f"LT debt/assets {lev_prev:.1%} → {lev:.1%}" if not np.isnan(lev) else "n/a"),
        check("Higher current ratio", "Leverage & liquidity", cmp(cr, cr_prev),
              f"{cr_prev:.2f} → {cr:.2f}" if not np.isnan(cr) else "n/a"),
        check("No share dilution", "Leverage & liquidity", shares_ok, "Shares outstanding flat or down"),
        check("Higher gross margin", "Operating efficiency", cmp(gm, gm_prev),
              f"{gm_prev:.1%} → {gm:.1%}" if not np.isnan(gm) else "n/a"),
        check("Higher asset turnover", "Operating efficiency", cmp(at, at_prev), f"{at_prev:.2f} → {at:.2f}"),
    ]
    score = sum(1 for c in checks if c["pass"])
    evaluated = sum(1 for c in checks if c["pass"] is not None)
    label = "Strong" if score >= 7 else "Average" if score >= 4 else "Weak"
    return {"available": True, "score": score, "evaluated": evaluated, "label": label, "checks": checks}


def altman_z(st: pd.DataFrame, market_cap: float | None, sector: str) -> dict:
    """Altman Z-score (original public-manufacturer model)."""
    if sector in ("Financials", "Real Estate"):
        return {"available": False, "reason": f"Not meaningful for {sector.lower()} (balance-sheet driven business models)"}
    need = ["total_assets", "total_liabilities", "current_assets", "current_liabilities",
            "retained_earnings", "operating_income", "revenue"]
    if st.empty or any(c not in st for c in need) or not market_cap:
        return {"available": False, "reason": "Insufficient balance-sheet data"}
    r = st.iloc[-1]
    ta, tl = float(r["total_assets"]), float(r["total_liabilities"])
    if ta <= 0 or tl <= 0:
        return {"available": False, "reason": "Invalid balance-sheet values"}
    parts = {
        "working_capital / assets": (1.2, (float(r["current_assets"]) - float(r["current_liabilities"])) / ta),
        "retained_earnings / assets": (1.4, float(r["retained_earnings"]) / ta),
        "EBIT / assets": (3.3, float(r["operating_income"]) / ta),
        "market_cap / liabilities": (0.6, market_cap / tl),
        "sales / assets": (1.0, float(r["revenue"]) / ta),
    }
    z = sum(w * v for w, v in parts.values())
    zone = "Safe" if z > 2.99 else "Grey" if z > 1.81 else "Distress"
    return {"available": True, "z": float(z), "zone": zone,
            "components": [{"name": k, "weight": w, "value": float(v), "contribution": float(w * v)}
                           for k, (w, v) in parts.items()]}


def financial_trends(st: pd.DataFrame) -> dict:
    if st.empty:
        return {"years": [], "rows": {}}
    years = [d.year for d in st.index]

    def col(name):
        return [None if pd.isna(v) else float(v) for v in st[name]] if name in st else [None] * len(st)

    def margin(num, den="revenue"):
        if num not in st or den not in st:
            return [None] * len(st)
        m = st[num] / st[den].replace(0, np.nan)
        return [None if pd.isna(v) else float(v) for v in m]

    rows = {
        "revenue": col("revenue"), "gross_profit": col("gross_profit"),
        "operating_income": col("operating_income"), "net_income": col("net_income"),
        "free_cash_flow": col("free_cash_flow"), "operating_cash_flow": col("operating_cash_flow"),
        "total_debt": col("total_debt"), "cash": col("cash"), "equity": col("equity"),
        "shares": col("shares"),
        "gross_margin": margin("gross_profit"), "operating_margin": margin("operating_income"),
        "net_margin": margin("net_income"), "fcf_margin": margin("free_cash_flow"),
    }
    n = len(st) - 1
    cagr = {}
    for k in ("revenue", "net_income", "free_cash_flow", "shares"):
        v = rows[k]
        cagr[k] = _cagr(v[0], v[-1], n) if n > 0 and v[0] is not None and v[-1] is not None else None
    return {"years": years, "rows": rows, "cagr": cagr}


# -------------------------------------------------------------------- risk
def risk_profile(px: pd.DataFrame, bench: pd.Series | None) -> dict:
    close = px["close"]
    rets = close.pct_change().dropna()
    b = bench.pct_change().reindex(rets.index).fillna(0) if bench is not None else None
    perf = performance(rets, b)
    monthly = (1 + rets).resample("ME").prod() - 1
    bins = np.linspace(-0.25, 0.25, 21)
    hist, edges = np.histogram(monthly.clip(-0.25, 0.25), bins=bins)
    by_month = monthly.groupby(monthly.index.month)
    season = [{"month": int(m), "avg": float(g.mean()), "pct_positive": float((g > 0).mean()), "n": int(len(g))}
              for m, g in by_month]
    ann_vol = rets.rolling(63).std() * np.sqrt(TRADING_DAYS)
    return {
        "stats": perf,
        "drawdown": series_points(drawdown(rets)),
        "rolling_vol": series_points(ann_vol.iloc[::5]),
        "histogram": [{"lo": float(edges[i]), "hi": float(edges[i + 1]), "count": int(hist[i])}
                      for i in range(len(hist))],
        "seasonality": season,
    }


# ------------------------------------------------------------------ thesis
def build_thesis(profile: dict, val: dict, pio: dict, alt: dict, f: Fundamentals,
                 sector_medians: dict, trend_gap: float | None) -> dict:
    bull, bear = [], []

    def pctile(k):
        v = profile.get(f"{k}_pct")
        return None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)

    names = {"value": "valuation", "quality": "quality", "momentum": "price momentum",
             "growth": "growth", "low_vol": "low volatility"}
    for k, label in names.items():
        p = pctile(k)
        if p is None:
            continue
        if p >= 75:
            bull.append(f"Top-quartile {label} (percentile {p:.0f} vs universe).")
        elif p <= 25:
            bear.append(f"Bottom-quartile {label} (percentile {p:.0f} vs universe).")

    if val.get("available"):
        up = val["upside"]
        if up > 0.15:
            bull.append(f"Base-case DCF fair value implies {up:.0%} upside.")
        elif up < -0.15:
            bear.append(f"Trades {-up:.0%} above base-case DCF fair value.")
        ig = val.get("implied_growth")
        if ig is not None and ig > val["base_growth"] + 0.05:
            bear.append(f"Price implies {ig:.0%} FCF growth - above the {val['base_growth']:.0%} base case.")
        elif ig is not None and ig < val["base_growth"] - 0.05:
            bull.append(f"Price implies only {ig:.0%} FCF growth vs a {val['base_growth']:.0%} base case.")
    if pio.get("available"):
        if pio["score"] >= 7:
            bull.append(f"Strong Piotroski F-score of {pio['score']}/9: improving fundamentals.")
        elif pio["score"] <= 3:
            bear.append(f"Weak Piotroski F-score of {pio['score']}/9: deteriorating fundamentals.")
    if alt.get("available"):
        if alt["zone"] == "Distress":
            bear.append(f"Altman Z of {alt['z']:.2f} is in the distress zone.")
        elif alt["zone"] == "Safe":
            bull.append(f"Altman Z of {alt['z']:.2f} indicates low bankruptcy risk.")
    pe, med = f.pe, sector_medians.get("pe")
    if pe and med and pe > 0:
        if pe < med * 0.8:
            bull.append(f"P/E of {pe:.1f} is below the sector median of {med:.1f}.")
        elif pe > med * 1.3:
            bear.append(f"P/E of {pe:.1f} is well above the sector median of {med:.1f}.")
    if trend_gap is not None:
        if trend_gap > 0.05:
            bull.append(f"Uptrend: price {trend_gap:.0%} above its 200-day average.")
        elif trend_gap < -0.05:
            bear.append(f"Downtrend: price {-trend_gap:.0%} below its 200-day average.")
    if f.debt_to_equity is not None and f.debt_to_equity > 2 and f.sector not in ("Financials", "Utilities", "Real Estate"):
        bear.append(f"High leverage: debt/equity of {f.debt_to_equity:.1f}x.")

    # Model rating: composite percentile, nudged by valuation and health.
    score = profile.get("score")
    s = 50.0 if score is None or (isinstance(score, float) and np.isnan(score)) else float(score)
    if val.get("available"):
        s += float(np.clip(val["upside"], -0.5, 0.5)) * 30
    if pio.get("available"):
        s += (pio["score"] - 4.5) * 2
    if alt.get("available") and alt["zone"] == "Distress":
        s -= 15
    s = float(np.clip(s, 0, 100))
    rating = ("Strong" if s >= 75 else "Favorable" if s >= 60 else "Neutral" if s >= 40
              else "Unfavorable" if s >= 25 else "Weak")
    return {"rating": rating, "rating_score": s, "bull": bull, "bear": bear}


# -------------------------------------------------------------------- main
def deep_analysis(provider: DataProvider, ticker: str, profile: dict, sector_table: pd.DataFrame,
                  benchmark: str = DEFAULT_BENCHMARK, as_of: date | None = None) -> dict:
    as_of = as_of or date.today()
    frames = provider.prices([ticker, benchmark], as_of - timedelta(days=365 * 5 + 10), as_of)
    px = frames.get(ticker)
    if px is None or px.empty:
        raise ValueError(f"no price data for {ticker}")
    bench = frames.get(benchmark)
    f = provider.fundamentals([ticker]).get(ticker) or Fundamentals(ticker=ticker)
    st = provider.statements(ticker)
    price = float(px["close"].iloc[-1])
    sma200 = px["close"].rolling(200).mean().iloc[-1]
    trend_gap = float(price / sma200 - 1) if np.isfinite(sma200) else None

    medians = {}
    for col in ("pe", "pb", "dividend_yield"):
        if col in sector_table:
            v = pd.to_numeric(sector_table[col], errors="coerce")
            v = v[v > 0] if col == "pe" else v
            medians[col] = float(v.median()) if v.notna().any() else None
    for col in ("m_ebitda_ev", "m_roe", "m_operating_margin", "m_revenue_growth"):
        if col in sector_table:
            v = pd.to_numeric(sector_table[col], errors="coerce")
            medians[col[2:]] = float(v.median()) if v.notna().any() else None

    val = valuation(st, f, price)
    pio = piotroski(st)
    alt = altman_z(st, f.market_cap, f.sector)
    thesis = build_thesis(profile, val, pio, alt, f, medians, trend_gap)
    ev_ebitda = f.ev_ebitda
    return {
        "ticker": ticker,
        "name": f.name,
        "sector": f.sector,
        "price": price,
        "as_of": as_of.isoformat(),
        "thesis": thesis,
        "valuation": val,
        "piotroski": pio,
        "altman": alt,
        "trends": financial_trends(st),
        "risk": risk_profile(px, bench["close"] if bench is not None else None),
        "relative": [
            {"metric": "P/E", "stock": f.pe, "sector": medians.get("pe"), "lower_is_better": True},
            {"metric": "P/B", "stock": f.pb, "sector": medians.get("pb"), "lower_is_better": True},
            {"metric": "EV/EBITDA", "stock": ev_ebitda,
             "sector": (1 / medians["ebitda_ev"]) if medians.get("ebitda_ev") else None, "lower_is_better": True},
            {"metric": "ROE", "stock": f.roe, "sector": medians.get("roe"), "lower_is_better": False},
            {"metric": "Operating margin", "stock": f.operating_margin, "sector": medians.get("operating_margin"),
             "lower_is_better": False},
            {"metric": "Revenue growth", "stock": f.revenue_growth, "sector": medians.get("revenue_growth"),
             "lower_is_better": False},
            {"metric": "Dividend yield", "stock": f.dividend_yield, "sector": medians.get("dividend_yield"),
             "lower_is_better": False},
        ],
    }
