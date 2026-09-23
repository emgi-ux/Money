"""Paper trading, public trader leaderboard and copy trading.

Every user gets a simulated brokerage account. Traders can make their profile
public; others can *copy* a public trader, which mirrors each of the leader's
trades into the follower's account, scaled by

    follower_qty = leader_qty * allocation / leader_equity

so the follower holds the same portfolio weights on the capital they allocated.
All of this is simulated money - real-money copy trading requires a licensed
broker-dealer / investment adviser and is intentionally out of scope.
"""

from __future__ import annotations

import os
import secrets
import threading
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from .analytics import TRADING_DAYS, series_points
from .data.base import DataProvider
from .db import connect

STARTING_CASH = 100_000.0
MIN_QTY = 1e-4


class TradeError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------ accounts
def ensure_account(user_id: int, created_at: str | None = None, starting_cash: float = STARTING_CASH) -> dict:
    with connect() as c:
        row = c.execute("SELECT * FROM paper_accounts WHERE user_id = ?", (user_id,)).fetchone()
        if row:
            return dict(row)
        created = created_at or _now()
        c.execute("INSERT INTO paper_accounts (user_id, starting_cash, cash, created_at) VALUES (?, ?, ?, ?)",
                  (user_id, starting_cash, starting_cash, created))
        return {"user_id": user_id, "starting_cash": starting_cash, "cash": starting_cash, "created_at": created}


def reset_account(user_id: int) -> None:
    with connect() as c:
        c.execute("DELETE FROM trades WHERE user_id = ?", (user_id,))
        c.execute("DELETE FROM paper_accounts WHERE user_id = ?", (user_id,))
        c.execute("UPDATE copies SET active = 0 WHERE follower_id = ?", (user_id,))
    ensure_account(user_id)


def latest_price(provider: DataProvider, ticker: str, on: date | None = None) -> float:
    on = on or date.today()
    df = provider.prices([ticker], on - timedelta(days=10), on).get(ticker)
    if df is None or df.empty:
        raise TradeError(f"No price available for {ticker}")
    return float(df["close"].iloc[-1])


def _trades(c, user_id: int) -> list[dict]:
    return [dict(r) for r in c.execute("SELECT * FROM trades WHERE user_id = ? ORDER BY ts, id", (user_id,))]


def positions_from_trades(trades: list[dict]) -> tuple[dict[str, dict], float, list[float]]:
    """Average-cost positions, realised P&L and per-sell realised returns."""
    pos: dict[str, dict] = {}
    realized = 0.0
    closed_returns: list[float] = []
    for t in trades:
        p = pos.setdefault(t["ticker"], {"qty": 0.0, "cost": 0.0})
        if t["side"] == "buy":
            p["qty"] += t["qty"]
            p["cost"] += t["qty"] * t["price"]
        else:
            avg = p["cost"] / p["qty"] if p["qty"] > 0 else t["price"]
            realized += (t["price"] - avg) * t["qty"]
            closed_returns.append(t["price"] / avg - 1)
            p["cost"] -= avg * t["qty"]
            p["qty"] -= t["qty"]
    return ({k: v for k, v in pos.items() if v["qty"] > MIN_QTY}, realized, closed_returns)


def _holdings(c, user_id: int) -> dict[str, float]:
    pos, _, _ = positions_from_trades(_trades(c, user_id))
    return {k: v["qty"] for k, v in pos.items()}


def _equity(provider: DataProvider, c, user_id: int) -> float:
    cash = c.execute("SELECT cash FROM paper_accounts WHERE user_id = ?", (user_id,)).fetchone()["cash"]
    return cash + sum(q * latest_price(provider, t) for t, q in _holdings(c, user_id).items())


# -------------------------------------------------------------------- orders
def place_order(provider: DataProvider, user_id: int, ticker: str, side: str, qty: float, *,
                price: float | None = None, ts: str | None = None, source: str = "manual",
                leader_id: int | None = None, leader_trade_id: int | None = None,
                propagate: bool = True) -> dict:
    """Execute a market order at the latest price (or ``price`` for backfills)."""
    ticker = ticker.strip().upper()
    side = side.lower()
    if side not in ("buy", "sell"):
        raise TradeError("Side must be buy or sell")
    if not np.isfinite(qty) or qty <= 0:
        raise TradeError("Quantity must be positive")
    qty = round(float(qty), 4)
    if qty < MIN_QTY:
        raise TradeError("Quantity too small")
    px = price if price is not None else latest_price(provider, ticker)
    ensure_account(user_id)

    with connect() as c:
        cash = c.execute("SELECT cash FROM paper_accounts WHERE user_id = ?", (user_id,)).fetchone()["cash"]
        held = _holdings(c, user_id).get(ticker, 0.0)
        cost = qty * px
        if side == "buy" and cost > cash + 1e-6:
            raise TradeError(f"Insufficient buying power: need ${cost:,.2f}, have ${cash:,.2f}")
        if side == "sell" and qty > held + 1e-6:
            raise TradeError(f"You hold {held:g} shares of {ticker}; short selling is not supported")
        # Leader equity *before* the trade sets the copy-trade scale.
        leader_equity = _equity(provider, c, user_id) if propagate else None
        cur = c.execute(
            """INSERT INTO trades (user_id, ticker, side, qty, price, ts, source, leader_id, leader_trade_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, ticker, side, qty, px, ts or _now(), source, leader_id, leader_trade_id))
        trade_id = cur.lastrowid
        c.execute("UPDATE paper_accounts SET cash = cash + ? WHERE user_id = ?",
                  (-cost if side == "buy" else cost, user_id))
        copiers = [dict(r) for r in c.execute(
            "SELECT follower_id, allocation FROM copies WHERE leader_id = ? AND active = 1", (user_id,))]

    trade = {"id": trade_id, "ticker": ticker, "side": side, "qty": qty, "price": px}
    mirrored = 0
    if propagate and copiers and leader_equity and leader_equity > 0:
        for cp in copiers:
            if _mirror(provider, cp["follower_id"], user_id, trade, cp["allocation"] / leader_equity):
                mirrored += 1
    trade["mirrored_to"] = mirrored
    return trade


def _mirror(provider: DataProvider, follower_id: int, leader_id: int, trade: dict, scale: float) -> bool:
    qty = trade["qty"] * scale
    with connect() as c:
        cash = c.execute("SELECT cash FROM paper_accounts WHERE user_id = ?", (follower_id,)).fetchone()["cash"]
        held = _holdings(c, follower_id).get(trade["ticker"], 0.0)
    if trade["side"] == "buy":
        qty = min(qty, cash / trade["price"])
    else:
        qty = min(qty, held)
    qty = np.floor(qty * 1e4) / 1e4
    if qty < MIN_QTY:
        return False
    try:
        place_order(provider, follower_id, trade["ticker"], trade["side"], qty, price=trade["price"],
                    source="copy", leader_id=leader_id, leader_trade_id=trade["id"], propagate=False)
    except TradeError:
        return False
    return True


# ------------------------------------------------------------------ copying
def start_copy(provider: DataProvider, follower_id: int, leader_id: int, allocation: float) -> dict:
    if follower_id == leader_id:
        raise TradeError("You can't copy yourself")
    ensure_account(follower_id)
    with connect() as c:
        leader = c.execute("SELECT id, is_public, display_name FROM users WHERE id = ?", (leader_id,)).fetchone()
        if not leader or not leader["is_public"]:
            raise TradeError("That trader isn't public")
        cash = c.execute("SELECT cash FROM paper_accounts WHERE user_id = ?", (follower_id,)).fetchone()["cash"]
    if not np.isfinite(allocation) or allocation <= 0:
        raise TradeError("Allocation must be positive")
    if allocation > cash + 1e-6:
        raise TradeError(f"Allocation exceeds your cash (${cash:,.2f})")

    with connect() as c:
        leader_equity = _equity(provider, c, leader_id)
        holdings = _holdings(c, leader_id)
        c.execute("""INSERT INTO copies (follower_id, leader_id, allocation, active) VALUES (?, ?, ?, 1)
                     ON CONFLICT(follower_id, leader_id) DO UPDATE SET allocation = excluded.allocation,
                     active = 1, created_at = datetime('now')""", (follower_id, leader_id, allocation))
    # Establish the leader's current portfolio proportionally.
    bought = 0
    scale = allocation / leader_equity if leader_equity > 0 else 0
    for ticker, qty in holdings.items():
        px = latest_price(provider, ticker)
        if _mirror(provider, follower_id, leader_id, {"id": None, "ticker": ticker, "side": "buy",
                                                      "qty": qty, "price": px}, scale):
            bought += 1
    return {"leader_id": leader_id, "allocation": allocation, "positions_opened": bought}


def stop_copy(follower_id: int, leader_id: int) -> None:
    with connect() as c:
        c.execute("UPDATE copies SET active = 0 WHERE follower_id = ? AND leader_id = ?", (follower_id, leader_id))


def copying(follower_id: int) -> list[dict]:
    with connect() as c:
        return [dict(r) for r in c.execute(
            """SELECT c.leader_id, c.allocation, c.created_at, u.display_name, u.is_bot
               FROM copies c JOIN users u ON u.id = c.leader_id
               WHERE c.follower_id = ? AND c.active = 1""", (follower_id,))]


def follower_count(c, leader_id: int) -> int:
    return c.execute("SELECT COUNT(*) FROM copies WHERE leader_id = ? AND active = 1", (leader_id,)).fetchone()[0]


# --------------------------------------------------------------- analytics
def equity_curve(provider: DataProvider, user_id: int) -> pd.Series:
    with connect() as c:
        acct = c.execute("SELECT * FROM paper_accounts WHERE user_id = ?", (user_id,)).fetchone()
        trades = _trades(c, user_id)
    if not acct:
        return pd.Series(dtype=float)
    start = pd.Timestamp(acct["created_at"][:10])
    today = pd.Timestamp(date.today())
    tickers = sorted({t["ticker"] for t in trades})
    closes = provider.close_matrix(tickers, start.date() - timedelta(days=7), today.date()) if tickers else pd.DataFrame()
    cal = pd.bdate_range(start, today)
    closes = closes.reindex(cal.union(closes.index)).ffill().reindex(cal) if not closes.empty else pd.DataFrame(index=cal)

    cash_delta = pd.Series(0.0, index=cal)
    qty_delta = pd.DataFrame(0.0, index=cal, columns=tickers)
    for t in trades:
        d = pd.Timestamp(t["ts"][:10])
        d = cal[cal.searchsorted(d)] if d <= cal[-1] else cal[-1]
        sign = 1 if t["side"] == "buy" else -1
        qty_delta.loc[d, t["ticker"]] += sign * t["qty"]
        cash_delta.loc[d] -= sign * t["qty"] * t["price"]
    cash = acct["starting_cash"] + cash_delta.cumsum()
    qty = qty_delta.cumsum()
    value = (qty * closes[tickers]).sum(axis=1) if tickers else 0.0
    return (cash + value).rename("equity")


def trader_stats(provider: DataProvider, user_id: int) -> dict:
    eq = equity_curve(provider, user_id)
    with connect() as c:
        acct = c.execute("SELECT * FROM paper_accounts WHERE user_id = ?", (user_id,)).fetchone()
        trades = _trades(c, user_id)
        followers = follower_count(c, user_id)
    if acct is None or eq.empty:
        return {}
    rets = eq.pct_change().dropna()
    _, realized, closed = positions_from_trades(trades)

    def ret_since(days: int):
        cut = eq.index[-1] - pd.Timedelta(days=days)
        base = eq[eq.index <= cut]
        return float(eq.iloc[-1] / base.iloc[-1] - 1) if len(base) else float(eq.iloc[-1] / acct["starting_cash"] - 1)

    sd = rets.std()
    dd = eq / eq.cummax() - 1
    return {
        "equity": float(eq.iloc[-1]),
        "total_return": float(eq.iloc[-1] / acct["starting_cash"] - 1),
        "return_1m": ret_since(30),
        "return_3m": ret_since(91),
        "volatility": float(sd * np.sqrt(TRADING_DAYS)) if len(rets) > 5 else None,
        "sharpe": float(rets.mean() / sd * np.sqrt(TRADING_DAYS)) if len(rets) > 5 and sd > 0 else None,
        "max_drawdown": float(dd.min()),
        "win_rate": float(np.mean([r > 0 for r in closed])) if closed else None,
        "trades": len(trades),
        "realized_pnl": realized,
        "followers": followers,
        "since": acct["created_at"][:10],
    }


def portfolio(provider: DataProvider, user_id: int) -> dict:
    acct = ensure_account(user_id)
    with connect() as c:
        acct = dict(c.execute("SELECT * FROM paper_accounts WHERE user_id = ?", (user_id,)).fetchone())
        trades = _trades(c, user_id)
    pos, realized, _ = positions_from_trades(trades)
    rows = []
    mv = 0.0
    for t, p in pos.items():
        px = latest_price(provider, t)
        value = p["qty"] * px
        mv += value
        rows.append({"ticker": t, "qty": p["qty"], "avg_cost": p["cost"] / p["qty"], "price": px,
                     "value": value, "unrealized": value - p["cost"],
                     "unrealized_pct": value / p["cost"] - 1 if p["cost"] else None})
    equity = acct["cash"] + mv
    for r in rows:
        r["weight"] = r["value"] / equity if equity else 0
    rows.sort(key=lambda r: -r["value"])
    return {
        "cash": acct["cash"], "starting_cash": acct["starting_cash"], "market_value": mv, "equity": equity,
        "total_return": equity / acct["starting_cash"] - 1, "realized_pnl": realized,
        "positions": rows,
        "trades": trades[::-1][:200],
        "equity_curve": series_points(equity_curve(provider, user_id), 2),
        "copying": copying(user_id),
    }


def leaderboard(provider: DataProvider, sort: str = "total_return", limit: int = 50) -> list[dict]:
    with connect() as c:
        users = [dict(r) for r in c.execute(
            """SELECT u.id, u.display_name, u.bio, u.is_bot FROM users u
               JOIN paper_accounts a ON a.user_id = u.id
               WHERE u.is_public = 1 AND EXISTS (SELECT 1 FROM trades t WHERE t.user_id = u.id)""")]
    rows = []
    for u in users:
        s = trader_stats(provider, u["id"])
        if not s:
            continue
        with connect() as c:
            top = sorted(_holdings(c, u["id"]).items(), key=lambda kv: -kv[1] * latest_price(provider, kv[0]))[:5]
        rows.append({**u, **s, "top_holdings": [t for t, _ in top]})
    key = sort if sort in ("total_return", "return_1m", "return_3m", "sharpe", "followers") else "total_return"
    rows.sort(key=lambda r: -(r.get(key) if r.get(key) is not None else -1e9))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows[:limit]


def trader_profile(provider: DataProvider, user_id: int, viewer_id: int | None = None) -> dict:
    with connect() as c:
        u = c.execute("SELECT id, display_name, bio, is_bot, is_public, created_at FROM users WHERE id = ?",
                      (user_id,)).fetchone()
    if not u or (not u["is_public"] and viewer_id != user_id):
        raise TradeError("Trader not found")
    p = portfolio(provider, user_id)
    is_copying = viewer_id is not None and any(cp["leader_id"] == user_id for cp in copying(viewer_id))
    return {
        "trader": dict(u),
        "stats": trader_stats(provider, user_id),
        "positions": [{k: r[k] for k in ("ticker", "weight", "unrealized_pct")} for r in p["positions"]],
        "trades": [{k: t[k] for k in ("ticker", "side", "qty", "price", "ts")} for t in p["trades"][:50]],
        "equity_curve": p["equity_curve"],
        "is_copying": is_copying,
    }


# ------------------------------------------------------------- demo bots
BOTS = [
    ("MomentumMaven", "Strategy bot · top 8 by 12-1 momentum, rebalanced monthly.", {"momentum": 1.0}, 8),
    ("ValueVault", "Strategy bot · deep value tilted to quality, monthly.", {"value": 0.7, "quality": 0.3}, 10),
    ("SteadyCompounder", "Strategy bot · quality + low volatility, monthly.", {"quality": 0.5, "low_vol": 0.5}, 10),
    ("BalancedAlpha", "Strategy bot · balanced five-factor blend, monthly.",
     {"value": 0.25, "quality": 0.25, "momentum": 0.25, "growth": 0.15, "low_vol": 0.10}, 12),
]
_seed_lock = threading.Lock()


def seed_bots(provider: DataProvider, tickers: list[str], months: int = 6) -> int:
    """Create public strategy bots with ~6 months of backfilled trades (idempotent)."""
    if os.environ.get("MONEY_SEED_BOTS", "1") == "0":
        return 0
    from .auth import hash_password
    from .scoring import ScoringConfig
    from .screener import run_screen

    with _seed_lock:
        with connect() as c:
            if c.execute("SELECT value FROM meta WHERE key = 'bots_seeded'").fetchone():
                return 0
        start = date.today() - timedelta(days=30 * months)
        month_starts = pd.bdate_range(start, date.today(), freq="BMS")
        created = 0
        for name, bio, weights, top_n in BOTS:
            with connect() as c:
                if c.execute("SELECT 1 FROM users WHERE display_name = ?", (name,)).fetchone():
                    continue
                cur = c.execute(
                    """INSERT INTO users (email, password_hash, display_name, bio, is_public, is_bot)
                       VALUES (?, ?, ?, ?, 1, 1)""",
                    (f"{name.lower()}@bots.invalid", hash_password(secrets.token_urlsafe(24)), name, bio))
                uid = cur.lastrowid
            ensure_account(uid, created_at=month_starts[0].strftime("%Y-%m-%dT16:00:00+00:00"))
            for d in month_starts:
                res = run_screen(provider, tickers, ScoringConfig(weights=weights), as_of=d.date())
                picks = list(res.table.dropna(subset=["composite"]).index[:top_n])
                ts = d.strftime("%Y-%m-%dT16:00:00+00:00")
                prices = {t: latest_price(provider, t, d.date()) for t in set(picks)}
                with connect() as c:
                    held = _holdings(c, uid)
                for t, q in held.items():
                    if t not in picks:
                        place_order(provider, uid, t, "sell", q, price=latest_price(provider, t, d.date()),
                                    ts=ts, source="bot", propagate=False)
                with connect() as c:
                    equity = _equity_at(provider, c, uid, d.date())
                    held = _holdings(c, uid)
                target = equity / len(picks) if picks else 0
                # Trim overweights first to free cash, then top up.
                for t in picks:
                    diff = target / prices[t] - held.get(t, 0.0)
                    if diff < -MIN_QTY:
                        place_order(provider, uid, t, "sell", -diff, price=prices[t], ts=ts, source="bot",
                                    propagate=False)
                for t in picks:
                    diff = target / prices[t] - held.get(t, 0.0)
                    if diff > MIN_QTY:
                        with connect() as c:
                            cash = c.execute("SELECT cash FROM paper_accounts WHERE user_id = ?", (uid,)).fetchone()["cash"]
                        qty = min(diff, cash / prices[t] * 0.9999)
                        if qty > MIN_QTY:
                            place_order(provider, uid, t, "buy", qty, price=prices[t], ts=ts, source="bot",
                                        propagate=False)
            created += 1
        with connect() as c:
            c.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('bots_seeded', ?)", (_now(),))
        return created


def _equity_at(provider: DataProvider, c, user_id: int, on: date) -> float:
    cash = c.execute("SELECT cash FROM paper_accounts WHERE user_id = ?", (user_id,)).fetchone()["cash"]
    return cash + sum(q * latest_price(provider, t, on) for t, q in _holdings(c, user_id).items())
