# BTC 15-minute prediction pipeline

Local Django + shadcn/ui app that:

1. Collects **free** real-time Bitcoin microstructure from public exchange WebSockets and REST feeds
2. Engineers TFI, VPIN, order-book imbalance, funding, liquidations, multi-timeframe RSI/Bollinger, and Polymarket 15m implied probabilities
3. Trains **20 model architectures**, compares walk-forward metrics, and builds an ensemble
4. Runs live inference against the current Polymarket `btc-updown-15m-*` Up/Down market
5. Places orders through Polymarket CLOB V2 (**dry-run on by default**)

SQLite is the only datastore. Django also serves the built Vite frontend, so one process can host the whole UI.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd frontend
npm install
npm run build
cd ..

python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

Open http://127.0.0.1:8000 and complete the setup wizard.

### Development (hot reload UI)

Terminal 1: `python manage.py runserver 8000`  
Terminal 2: `cd frontend && npm run dev` (proxies `/api` to Django)

## 24/7 collection

From the UI: **Collect → Start collector**, or:

```bash
python manage.py runcollector
```

Optional history so you can train before microstructure accumulates:

```bash
python manage.py backfilldata --days 14 --interval 1m
```

or **Collect → Run backfill**.

## Training & trading

1. Wait until **labeled bars** &gt; ~200 (backfill labels immediately; live bars label after 15 minutes)
2. **Train → Train selected** (all 20 architectures by default)
3. Review ROC-AUC / accuracy, tick models into the ensemble
4. **Trade → Start loop**

Keep **dry-run** enabled until you are comfortable. Live ordering needs a Polygon wallet private key (and `funder` + signature type for proxy/email/Safe wallets). Keys are encrypted in local SQLite.

## Free sources (no paid APIs)

Binance spot + USD-M futures, Coinbase, Kraken, Bybit, OKX, Bitstamp, Deribit, CoinCap, Alternative.me Fear & Greed, mempool.space fees, Polymarket Gamma + public CLOB.

## Reality check

A 55–60% directional hit rate on 15-minute BTC is the upper end of published short-horizon results. After Polymarket spread, fees, and slippage, many 0.55–0.60 AUC models still lose money if they trade every window. The app only fires when predicted edge exceeds your **min edge** and **min confidence**.

## Layout

```
config/                 Django project
pipeline/               API, collectors, features, ML, Polymarket
frontend/               Vite + React + shadcn/ui
data/                   SQLite, artifacts, pids (gitignored)
```
