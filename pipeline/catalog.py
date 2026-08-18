from __future__ import annotations

FREE_SOURCES: list[dict[str, str]] = [
    {
        "id": "binance_spot",
        "label": "Binance Spot",
        "kind": "websocket",
        "detail": "BTCUSDT trades, top-20 depth, book ticker, 1m/5m/15m klines",
    },
    {
        "id": "binance_futures",
        "label": "Binance USD-M Futures",
        "kind": "websocket",
        "detail": "Perp trades, depth, mark price, liquidations, funding",
    },
    {
        "id": "coinbase",
        "label": "Coinbase Exchange",
        "kind": "websocket",
        "detail": "BTC-USD matches, ticker, level2 batch book",
    },
    {
        "id": "kraken",
        "label": "Kraken",
        "kind": "websocket",
        "detail": "BTC/USD trades, ticker, 10-level book",
    },
    {
        "id": "bybit",
        "label": "Bybit Linear",
        "kind": "websocket",
        "detail": "BTCUSDT perp trades, 50-level book, ticker/funding",
    },
    {
        "id": "okx",
        "label": "OKX",
        "kind": "websocket",
        "detail": "Spot + swap trades, books5, funding rate",
    },
    {
        "id": "bitstamp",
        "label": "Bitstamp",
        "kind": "websocket",
        "detail": "BTCUSD live trades and order book",
    },
    {
        "id": "deribit",
        "label": "Deribit",
        "kind": "websocket",
        "detail": "BTC-PERPETUAL trades, book, mark (USD)",
    },
    {
        "id": "coincap",
        "label": "CoinCap",
        "kind": "websocket",
        "detail": "Lightweight aggregated BTC price ticks",
    },
    {
        "id": "polymarket_gamma",
        "label": "Polymarket Gamma",
        "kind": "rest",
        "detail": "Discovers the current BTC 15m Up/Down market and tokens",
    },
    {
        "id": "polymarket_clob",
        "label": "Polymarket CLOB",
        "kind": "websocket",
        "detail": "Live yes/no order books and last trades for the 15m market",
    },
    {
        "id": "rest_aux",
        "label": "Auxiliary REST",
        "kind": "rest",
        "detail": "Fear & Greed, mempool fees, Binance OI, 1h/4h klines",
    },
]

MODEL_ARCHES: list[dict[str, str]] = [
    {"id": "logistic_regression", "label": "Logistic Regression", "family": "linear"},
    {"id": "ridge_classifier", "label": "Ridge Classifier", "family": "linear"},
    {"id": "sgd_log", "label": "SGD Logistic", "family": "linear"},
    {"id": "passive_aggressive", "label": "Passive Aggressive", "family": "linear"},
    {"id": "linear_svc", "label": "Linear SVM", "family": "linear"},
    {"id": "gaussian_nb", "label": "Gaussian Naive Bayes", "family": "bayes"},
    {"id": "lda", "label": "Linear Discriminant", "family": "bayes"},
    {"id": "qda", "label": "Quadratic Discriminant", "family": "bayes"},
    {"id": "decision_tree", "label": "Decision Tree", "family": "tree"},
    {"id": "extra_tree", "label": "Extra Tree", "family": "tree"},
    {"id": "random_forest", "label": "Random Forest", "family": "tree"},
    {"id": "extra_trees", "label": "Extra Trees", "family": "tree"},
    {"id": "hist_gbm", "label": "Hist Gradient Boosting", "family": "boosting"},
    {"id": "gradient_boosting", "label": "Gradient Boosting", "family": "boosting"},
    {"id": "adaboost", "label": "AdaBoost", "family": "boosting"},
    {"id": "bagging_trees", "label": "Bagging Trees", "family": "ensemble"},
    {"id": "knn", "label": "k-Nearest Neighbors", "family": "neighbors"},
    {"id": "mlp", "label": "Neural Net (MLP)", "family": "neural"},
    {"id": "xgboost", "label": "XGBoost", "family": "boosting"},
    {"id": "calibrated_logistic", "label": "Calibrated Logistic", "family": "linear"},
]
