# BTC 15-minute prediction pipeline

Local Django + shadcn/ui app that:

1. Collects **free** real-time microstructure for **many coins at once** (BTC, ETH, SOL, XRP, DOGE, BNB, …) from public exchange WebSockets and REST feeds
2. Writes **multiple timeframes simultaneously** (1m, 5m, 15m, 1h) so you can train a starter model on 1-minute bars, then test the 15-minute Polymarket horizon
3. Engineers TFI, VPIN, order-book imbalance, funding, liquidations, multi-timeframe RSI/Bollinger, and Polymarket 15m implied probabilities
4. Trains **20 model architectures**, compares walk-forward metrics, and builds an ensemble
5. Runs live inference against the current Polymarket `btc-updown-15m-*` Up/Down market
6. Places orders through Polymarket CLOB V2 (**dry-run on by default**)

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

Open http://127.0.0.1:8000 and complete the setup wizard. Pick coins and timeframes there; the collector subscribes to all of them in one process.

### Development (hot reload UI)

Terminal 1: `python manage.py runserver 8000`  
Terminal 2: `cd frontend && npm run dev` (proxies `/api` to Django)

## 24/7 collection

From the UI: **Collect → Start collector**, or:

```bash
python manage.py runcollector
```

The process fans out Binance/Coinbase/Kraken/Bybit/OKX/Bitstamp/Deribit/CoinCap streams across every enabled coin and writes a feature bar for every selected timeframe on aligned timestamps.

Optional history so you can train before microstructure accumulates (all selected coins × timeframes):

```bash
python manage.py backfilldata --days 14 --interval all
python manage.py backfilldata --days 7 --interval 1m --assets BTC,ETH,XRP
```

or **Collect → Run backfill**.

1-minute next-bar labels are available as soon as the following candle exists. That is the fast loop for checking whether a model works before waiting 15 minutes.

## Training & trading

1. Wait until **next-bar labels** &gt; ~200 (backfill labels immediately; live 1m bars label after 1 minute)
2. **Train** with timeframe `1m`, label **Next bar**, and **pool all coins**
3. Review ROC-AUC / accuracy, then retrain on `15m` / **15m horizon** when you have enough 15-minute labels
4. **Trade → Start loop** (still the BTC 15-minute Polymarket market)

Keep **dry-run** enabled until you are comfortable. Live ordering needs a Polygon wallet private key (and `funder` + signature type for proxy/email/Safe wallets). Keys are encrypted in local SQLite.

## Free sources (no paid APIs)

Binance spot + USD-M futures, Coinbase, Kraken, Bybit, OKX, Bitstamp, Deribit, CoinCap, Alternative.me Fear & Greed, mempool.space fees, Polymarket Gamma + public CLOB.

Default coins: BTC, ETH, SOL, XRP, DOGE, BNB. Optional: ADA, AVAX, LINK, LTC. Venues without a pair for a coin are skipped.

## Reality check

A 55–60% directional hit rate on 15-minute BTC is the upper end of published short-horizon results. After Polymarket spread, fees, and slippage, many 0.55–0.60 AUC models still lose money if they trade every window. The app only fires when predicted edge exceeds your **min edge** and **min confidence**. 1-minute next-bar accuracy is a diagnostic, not a trading signal by itself.

## Layout

```
config/                 Django project
pipeline/               API, collectors, features, ML, Polymarket
frontend/               Vite + React + shadcn/ui
data/                   SQLite, artifacts, pids (gitignored)
```
