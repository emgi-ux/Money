# Money: factor terminal for stock pickers

A pro-grade stock selection platform. It combines institutional-style
multi-factor research, deep single-stock analysis, a day-trading desk, and
paper trading with a public leaderboard and copy trading. Access is
monetized through weekly or monthly Stripe subscriptions, and the app
installs on phones and desktops as a PWA.

| Area | What you get |
|---|---|
| **Screener** | Value, Quality, Momentum, Growth and Low-Vol factors built from 17 metrics. Metrics are winsorized and z-scored sector-neutrally, then blended with weights you choose. Includes presets, filters, a watchlist and CSV export. |
| **Deep analysis** (Pro) | Two-stage FCF DCF with bear/base/bull cases, a sensitivity grid and a reverse DCF (the growth rate the price implies). Also Piotroski F-Score, Altman Z, 5-year statement trends, relative valuation, risk profile, seasonality, and a rule-based bull/bear thesis. |
| **Day trading** (Pro) | Intraday candles with session VWAP and ±1σ/2σ bands, EMA 9/21, RSI, opening range, classic pivots, relative volume, and a signal feed (VWAP reclaim/loss, EMA crosses, ORB breakouts, RSI extremes). Also an ATR position-size calculator, plus a scanner for gappers, unusual volume, range expansion and 20-day breakouts. |
| **Backtester** (Pro) | Walk-forward monthly/quarterly rebalancing with next-day execution and turnover costs, compared against an equal-weight universe and a benchmark. Reports Sharpe, Sortino, alpha/beta, information ratio, drawdowns and a monthly heatmap. |
| **Portfolio and risk** (Pro) | Equal, inverse-vol, risk-parity, min-variance and score-weighted construction with position caps (Ledoit-Wolf covariance). Shows VaR/CVaR, beta, risk contributions, sector risk and a correlation matrix. |
| **Top traders** | Every user gets a $100k paper account and can go public. The leaderboard ranks by return, Sharpe and copier count. Strategy bots keep it populated from day one. |
| **Copy trading** (Pro) | One click mirrors a trader's portfolio and every future trade, scaled to the amount you allocate. |
| **Subscriptions** | Stripe Checkout (weekly and monthly, optional free trial), the customer Billing Portal, and a signed, idempotent webhook. Pro features are enforced server-side (HTTP 402). |
| **App** | Installable PWA with offline shell, home-screen icons and a mobile tab bar. Dark and light themes. |

## Quick start

```bash
# Backend (Python 3.10+)
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest                         # 34 tests

# Frontend (Node 20+)
cd ../frontend
npm install
npm run build                  # the API serves frontend/dist

# Run (demo data, everything unlocked)
cd ../backend
money serve                    # http://127.0.0.1:8000
```

Useful variations:

```bash
MONEY_PROVIDER=yahoo money serve       # live Yahoo Finance data (personal use)
MONEY_BILLING=dev money serve          # paywall on, checkout is simulated (no charge)
cd frontend && npm run dev             # hot-reload UI on :5173, proxies /api to :8000
```

CLI:

```bash
money screen --top 20 --weights value=0.4,quality=0.4,momentum=0.2
money backtest --start 2016-01-01 --weighting risk_parity
money risk AAPL=0.3,MSFT=0.3,JNJ=0.4
```

## Going live and charging subscriptions

1. **Stripe.** Create a Product "Money Pro" with two recurring Prices: weekly
   (e.g. $9.99/week) and monthly (e.g. $29.99/month). Put their IDs in
   `STRIPE_PRICE_WEEKLY` and `STRIPE_PRICE_MONTHLY`, and set `STRIPE_SECRET_KEY`.
2. **Webhook.** Add an endpoint at `https://your-domain.com/api/billing/webhook`
   for `checkout.session.completed` and `customer.subscription.created|updated|deleted`.
   Set `STRIPE_WEBHOOK_SECRET` from the signing secret Stripe shows you.
3. **Customer portal.** Enable it in the Stripe dashboard so users can cancel,
   switch weekly/monthly and update cards themselves.
4. **Deploy.** `docker build -t money . && docker run -p 8000:8000 -v money-data:/data --env-file .env money`
   runs on Fly.io, Render, Railway or any VPS. Put it behind HTTPS (required for
   PWA install and Stripe) and set `MONEY_PUBLIC_URL`. See `.env.example` for
   every setting.
5. **App stores (optional).** The PWA already installs from the browser on
   iOS, Android and desktop. To list in the App Store or Google Play, wrap
   `frontend/dist` with [Capacitor](https://capacitorjs.com). Apple and Google
   generally require their in-app purchase systems (15-30% fee) for digital
   subscriptions sold inside the app, so many apps sell on the web through Stripe instead.

## Before you charge money: read this

- **Market data licensing.** Yahoo Finance data (via `yfinance`) is for
  personal use and may not be redistributed commercially. A paid product needs a
  licensed feed such as Polygon.io, Tiingo, Financial Modeling Prep or Intrinio.
  Add a provider by subclassing `DataProvider` in `backend/money/data/`: implement
  `prices`, `fundamentals`, `statements` and `intraday`.
- **Copy trading uses paper money on purpose.** Automatically mirroring trades in
  customers' real brokerage accounts generally requires registration as a
  broker-dealer and/or investment adviser (SEC/FINRA in the US, FCA in the UK,
  and so on). Before moving copy trading to real money, talk to a securities
  lawyer and integrate a licensed broker API (e.g. Alpaca).
- **Research, not advice.** Screener grades, model ratings and DCF values are
  impersonal model outputs, and the UI labels them that way. Keep them general
  and non-personalized, and keep the disclaimers. Consult counsel about the
  publisher's exclusion in your jurisdiction.
- **Leaderboard claims.** Rankings are simulated and labeled as such. Bots are
  clearly marked "strategy bot". Don't market paper returns as real results.

## Architecture

```
backend/money/
  data/           providers: synthetic (deterministic demo market) · yahoo (disk-cached)
  factors.py      metric definitions, price-derived metric panels (no look-ahead)
  scoring.py      winsorize → sector-neutral z-scores → factor scores → composite
  screener.py     filters + ranking            analysis.py  DCF, F-Score, Altman Z, thesis
  backtest.py     walk-forward engine          daytrade.py  VWAP, ORB, pivots, signals, scanner
  portfolio.py    optimizers + shrinkage       risk.py      VaR/CVaR, risk contributions
  auth.py         scrypt passwords, hashed bearer sessions, login throttling
  billing.py      Stripe checkout / portal / webhook, dev + off modes
  trading.py      paper accounts, leaderboard, proportional copy trading, strategy bots
  db.py           SQLite schema                api.py / api_users.py  FastAPI routes
frontend/src/
  views/          Screener, StockView, Analysis, DayTrade, Backtest, Portfolio,
                  Leaders/Trader, Trade (paper), Pricing, Account
  components/     charts (lightweight-charts), paywall gate, auth modal, UI bits
```

**Methodology notes.** The backtester uses only price-derived factors, because
free fundamentals are current snapshots and using them historically would leak
future information. The test universe is today's constituents, so treat absolute
backtest returns as optimistic (survivorship bias) and judge strategies relative
to the equal-weight universe line.
