import os

import pytest

os.environ["MONEY_PROVIDER"] = "synthetic"

from fastapi.testclient import TestClient  # noqa: E402

from money.api import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_meta(client):
    r = client.get("/api/meta")
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "synthetic"
    assert "momentum" in body["factors"]


def test_screen(client):
    r = client.post("/api/screen", json={"limit": 10, "weights": {"quality": 1}})
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert len(rows) == 10
    assert rows[0]["rank"] == 1
    assert rows[0]["score"] >= rows[-1]["score"]


def test_stock(client):
    r = client.get("/api/stock/AAPL?years=1")
    assert r.status_code == 200
    body = r.json()
    assert body["candles"] and body["profile"]["grade"]
    assert any(p["is_self"] for p in body["peers"])


def test_backtest(client):
    r = client.post("/api/backtest", json={"start": "2021-01-01", "end": "2024-01-01", "top_n": 10})
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["strategy"]["sharpe"] is not None
    # Day one pays the entry cost: 100% turnover x 10 bps.
    assert body["equity"]["strategy"][0]["value"] == pytest.approx(0.999)


def test_backtest_bad_factor(client):
    r = client.post("/api/backtest", json={"weights": {"value": 1}})
    assert r.status_code == 400


def test_portfolio(client):
    c = client.post("/api/portfolio/construct", json={"top_n": 8, "method": "risk_parity",
                                                      "max_weight": 0.25})
    assert c.status_code == 200
    weights = c.json()["weights"]
    assert len(weights) == 8
    a = client.post("/api/portfolio/analyze", json={"weights": weights})
    assert a.status_code == 200
    assert len(a.json()["positions"]) == 8


def test_unknown_ticker_risk(client):
    r = client.post("/api/portfolio/analyze", json={"weights": {}})
    assert r.status_code == 400
