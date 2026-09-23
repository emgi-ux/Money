import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from money import trading
from money.data import SyntheticProvider
from money.universe import resolve_universe


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MONEY_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("MONEY_PROVIDER", "synthetic")
    monkeypatch.setenv("MONEY_SEED_BOTS", "0")
    for k in ("STRIPE_SECRET_KEY", "MONEY_BILLING"):
        monkeypatch.delenv(k, raising=False)
    from money.api import app

    return TestClient(app)


def signup(client, name="alice"):
    r = client.post("/api/auth/register", json={"email": f"{name}@example.com", "password": "hunter22!",
                                                "display_name": name})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()["user"]


def test_register_login_me(client):
    h, user = signup(client)
    assert user["plan"] == "free" and not user["is_pro"]
    assert client.get("/api/auth/me", headers=h).json()["user"]["email"] == "alice@example.com"
    assert client.post("/api/auth/login", json={"email": "alice@example.com", "password": "nope"}).status_code == 401
    ok = client.post("/api/auth/login", json={"email": "ALICE@example.com", "password": "hunter22!"})
    assert ok.status_code == 200 and ok.json()["token"]
    dup = client.post("/api/auth/register", json={"email": "alice@example.com", "password": "hunter22!",
                                                  "display_name": "alice2"})
    assert dup.status_code == 400
    client.post("/api/auth/logout", headers=h)
    assert client.get("/api/auth/me", headers=h).status_code == 401


def test_paper_trading_rules(client):
    h, _ = signup(client)
    buy = client.post("/api/paper/order", headers=h, json={"ticker": "aapl", "side": "buy", "qty": 10})
    assert buy.status_code == 200, buy.text
    p = client.get("/api/paper", headers=h).json()
    assert p["positions"][0]["ticker"] == "AAPL" and p["positions"][0]["qty"] == 10
    assert p["cash"] == pytest.approx(100_000 - 10 * buy.json()["price"])
    assert client.post("/api/paper/order", headers=h, json={"ticker": "AAPL", "side": "sell", "qty": 11}).status_code == 400
    assert client.post("/api/paper/order", headers=h, json={"ticker": "MSFT", "side": "buy", "qty": 1e7}).status_code == 400
    sell = client.post("/api/paper/order", headers=h, json={"ticker": "AAPL", "side": "sell", "qty": 10})
    assert sell.status_code == 200
    p = client.get("/api/paper", headers=h).json()
    assert p["positions"] == [] and p["cash"] == pytest.approx(100_000)


def test_copy_trading_mirrors_proportionally(client):
    lh, leader = signup(client, "leader")
    fh, _ = signup(client, "follower")
    # Private traders can't be copied.
    assert client.post(f"/api/traders/{leader['id']}/copy", headers=fh, json={"allocation": 10_000}).status_code == 400
    client.patch("/api/auth/me", headers=lh, json={"is_public": True})
    r = client.post(f"/api/traders/{leader['id']}/copy", headers=fh, json={"allocation": 10_000})
    assert r.status_code == 200, r.text

    buy = client.post("/api/paper/order", headers=lh, json={"ticker": "MSFT", "side": "buy", "qty": 100}).json()
    assert buy["mirrored_to"] == 1
    fpos = client.get("/api/paper", headers=fh).json()["positions"]
    assert fpos[0]["ticker"] == "MSFT"
    # allocation / leader equity = 10k / 100k -> 10% of the leader's size
    assert fpos[0]["qty"] == pytest.approx(10, abs=1e-3)

    client.post("/api/paper/order", headers=lh, json={"ticker": "MSFT", "side": "sell", "qty": 50})
    fpos = client.get("/api/paper", headers=fh).json()["positions"]
    assert fpos[0]["qty"] == pytest.approx(5, rel=0.02)

    client.delete(f"/api/traders/{leader['id']}/copy", headers=fh)
    client.post("/api/paper/order", headers=lh, json={"ticker": "JPM", "side": "buy", "qty": 10})
    assert {p["ticker"] for p in client.get("/api/paper", headers=fh).json()["positions"]} == {"MSFT"}

    board = client.get("/api/leaderboard").json()["rows"]
    assert [r["display_name"] for r in board] == ["leader"]
    assert board[0]["followers"] == 0


def test_paywall_dev_mode(client, monkeypatch):
    # Billing off: everything open.
    assert client.get("/api/scanner").status_code == 200
    monkeypatch.setenv("MONEY_BILLING", "dev")
    assert client.get("/api/scanner").status_code == 401
    h, _ = signup(client)
    assert client.get("/api/scanner", headers=h).status_code == 402
    r = client.post("/api/billing/checkout", headers=h, json={"plan": "monthly"})
    assert r.status_code == 200 and "checkout=success" in r.json()["url"]
    me = client.get("/api/auth/me", headers=h).json()["user"]
    assert me["is_pro"] and me["plan_interval"] == "month"
    assert client.get("/api/scanner", headers=h).status_code == 200
    client.post("/api/billing/portal", headers=h)  # dev portal = cancel
    assert client.get("/api/scanner", headers=h).status_code == 402


def _signed(payload: dict, secret: str) -> tuple[bytes, str]:
    body = json.dumps(payload).encode()
    t = int(time.time())
    sig = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return body, f"t={t},v1={sig}"


def test_stripe_webhook_activates_subscription(client, monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_dummy")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    h, user = signup(client)
    event = {
        "id": "evt_1", "object": "event", "type": "customer.subscription.updated",
        "data": {"object": {
            "id": "sub_1", "object": "subscription", "customer": "cus_1", "status": "trialing",
            "metadata": {"user_id": str(user["id"])},
            "items": {"data": [{"price": {"recurring": {"interval": "week"}}, "current_period_end": 1900000000}]},
        }},
    }
    body, sig = _signed(event, "whsec_test")
    bad = client.post("/api/billing/webhook", content=body, headers={"Stripe-Signature": "t=1,v1=bad"})
    assert bad.status_code == 400
    ok = client.post("/api/billing/webhook", content=body, headers={"Stripe-Signature": sig})
    assert ok.status_code == 200, ok.text
    me = client.get("/api/auth/me", headers=h).json()["user"]
    assert me["is_pro"] and me["plan_interval"] == "week" and me["plan_status"] == "trialing"
    assert client.get("/api/scanner", headers=h).status_code == 200


def test_bots_seed_and_rank(tmp_path, monkeypatch):
    monkeypatch.setenv("MONEY_DB", str(tmp_path / "bots.db"))
    p = SyntheticProvider()
    assert trading.seed_bots(p, resolve_universe(None), months=2) == len(trading.BOTS)
    assert trading.seed_bots(p, resolve_universe(None), months=2) == 0  # idempotent
    board = trading.leaderboard(p)
    assert len(board) == len(trading.BOTS)
    assert all(r["is_bot"] and r["trades"] > 0 for r in board)
    assert board[0]["total_return"] >= board[-1]["total_return"]
