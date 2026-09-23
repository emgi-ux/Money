"""Command-line interface.

    money screen [--top 25] [--weights value=0.3,momentum=0.4,...] [--no-sector-neutral]
    money backtest [--start 2016-01-01] [--top 20] [--weighting risk_parity]
    money risk AAPL=0.3,MSFT=0.3,JNJ=0.4
    money serve [--port 8000]

Set MONEY_PROVIDER=yahoo for live data (default: synthetic demo data).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from .data import get_provider
from .universe import resolve_universe


def _kv(s: str) -> dict[str, float]:
    out = {}
    for part in s.split(","):
        k, _, v = part.partition("=")
        out[k.strip()] = float(v)
    return out


def _pct(x) -> str:
    return "     -" if x is None else f"{x * 100:6.1f}%"


def _num(x, w: int = 6) -> str:
    return " " * (w - 1) + "-" if x is None else f"{x:{w}.2f}"


def cmd_screen(a) -> None:
    from .scoring import DEFAULT_WEIGHTS, ScoringConfig
    from .screener import run_screen

    weights = _kv(a.weights) if a.weights else DEFAULT_WEIGHTS
    res = run_screen(get_provider(a.provider), resolve_universe(a.universe),
                     ScoringConfig(weights=weights, sector_neutral=not a.no_sector_neutral))
    print(f"As of {res.as_of}  ·  {len(res.table)} stocks  ·  provider={get_provider(a.provider).name}")
    hdr = f"{'#':>3} {'Ticker':<7}{'Sector':<24}{'Score':>6} {'Gr':<3}" \
          f"{'Value':>7}{'Qual':>7}{'Mom':>7}{'Grow':>7}{'LowV':>7}{'P/E':>8}"
    print(hdr)
    print("-" * len(hdr))
    for i, r in enumerate(res.records(a.top), 1):
        print(f"{i:>3} {r['ticker']:<7}{str(r['sector'])[:23]:<24}"
              f"{_num(r.get('score'), 6)} {r['grade']:<3}"
              + "".join(_num(r.get(f), 7) for f in ("value", "quality", "momentum", "growth", "low_vol"))
              + _num(r.get("pe"), 8))


def cmd_backtest(a) -> None:
    from .backtest import BacktestConfig, run_backtest

    cfg = BacktestConfig(
        start=date.fromisoformat(a.start), end=date.fromisoformat(a.end) if a.end else date.today(),
        weights=_kv(a.weights) if a.weights else {"momentum": 0.7, "low_vol": 0.3},
        top_n=a.top, weighting=a.weighting, rebalance=a.rebalance, cost_bps=a.cost_bps,
        max_weight=a.max_weight,
    )
    res = run_backtest(get_provider(a.provider), resolve_universe(a.universe), cfg)
    s = res.summary()
    rows = [("Total return", "total_return", _pct), ("CAGR", "cagr", _pct),
            ("Volatility", "volatility", _pct), ("Sharpe", "sharpe", _num),
            ("Sortino", "sortino", _num), ("Max drawdown", "max_drawdown", _pct),
            ("Calmar", "calmar", _num), ("Beta", "beta", _num), ("Alpha", "alpha", _pct),
            ("Info ratio", "information_ratio", _num),
            ("Annual turnover", "annual_turnover", _pct)]
    print(f"{'':<18}{'Strategy':>10}{'Universe EW':>13}{'Benchmark':>11}")
    for label, key, f in rows:
        print(f"{label:<18}{f(s['strategy'].get(key)):>10}{f(s['universe'].get(key)):>13}"
              f"{f(s['benchmark'].get(key)):>11}")
    last = res.holdings[-1]
    print(f"\nLatest holdings ({last['date']}): "
          + ", ".join(f"{p['ticker']} {p['weight'] * 100:.1f}%" for p in last["positions"]))


def cmd_risk(a) -> None:
    from .risk import analyze_portfolio

    r = analyze_portfolio(get_provider(a.provider), {k.upper(): v for k, v in _kv(a.weights).items()},
                          a.lookback)
    s = r["summary"]
    print(f"Volatility {_pct(s['volatility'])}  Beta {_num(s.get('beta'))}  "
          f"Max DD {_pct(s['max_drawdown'])}  VaR95(1d) {_pct(s['var_95'])}  "
          f"CVaR95(1d) {_pct(s['cvar_95'])}  Effective N {s['effective_n']:.1f}")
    print(f"\n{'Ticker':<8}{'Weight':>8}{'Vol':>8}{'Beta':>7}{'Risk %':>8}")
    for p in r["positions"]:
        print(f"{p['ticker']:<8}{_pct(p['weight']):>8}{_pct(p['volatility']):>8}"
              f"{_num(p['beta'], 7)}{_pct(p['risk_contribution']):>8}")


def cmd_serve(a) -> None:
    import os

    import uvicorn

    if a.provider:
        os.environ["MONEY_PROVIDER"] = a.provider
    uvicorn.run("money.api:app", host=a.host, port=a.port, reload=a.reload)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="money", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", help="synthetic | yahoo (default: $MONEY_PROVIDER or synthetic)")
    ap.add_argument("--universe", help="universe name or comma-separated tickers")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("screen", help="rank stocks by multi-factor score")
    s.add_argument("--top", type=int, default=25)
    s.add_argument("--weights", help="e.g. value=0.3,quality=0.3,momentum=0.4")
    s.add_argument("--no-sector-neutral", action="store_true")
    s.set_defaults(fn=cmd_screen)

    b = sub.add_parser("backtest", help="walk-forward backtest of a price-factor strategy")
    b.add_argument("--start", default="2016-01-01")
    b.add_argument("--end")
    b.add_argument("--top", type=int, default=20)
    b.add_argument("--weights", help="price factors only, e.g. momentum=0.7,low_vol=0.3")
    b.add_argument("--weighting", default="equal")
    b.add_argument("--rebalance", default="monthly", choices=["monthly", "quarterly"])
    b.add_argument("--cost-bps", type=float, default=10.0)
    b.add_argument("--max-weight", type=float, default=0.10)
    b.set_defaults(fn=cmd_backtest)

    r = sub.add_parser("risk", help="risk report for a set of holdings")
    r.add_argument("weights", help="e.g. AAPL=0.3,MSFT=0.3,JNJ=0.4")
    r.add_argument("--lookback", type=int, default=365, help="days of history")
    r.set_defaults(fn=cmd_risk)

    v = sub.add_parser("serve", help="run the API + web UI")
    v.add_argument("--host", default="127.0.0.1")
    v.add_argument("--port", type=int, default=8000)
    v.add_argument("--reload", action="store_true")
    v.set_defaults(fn=cmd_serve)

    a = ap.parse_args(argv)
    try:
        a.fn(a)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
