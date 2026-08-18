from __future__ import annotations

FREE_SOURCES: list[dict[str, str]] = [
    {
        "id": "binance_spot",
        "label": "Binance Spot",
        "kind": "websocket",
        "detail": "USDT trades, depth, book ticker, and klines for every enabled coin",
    },
    {
        "id": "binance_futures",
        "label": "Binance USD-M Futures",
        "kind": "websocket",
        "detail": "Perp trades, depth, mark price, liquidations, funding per coin",
    },
    {
        "id": "coinbase",
        "label": "Coinbase Exchange",
        "kind": "websocket",
        "detail": "USD matches, ticker, level2 batch book for enabled coins",
    },
    {
        "id": "kraken",
        "label": "Kraken",
        "kind": "websocket",
        "detail": "USD trades, ticker, 10-level book for enabled coins",
    },
    {
        "id": "bybit",
        "label": "Bybit Linear",
        "kind": "websocket",
        "detail": "USDT perp trades, 50-level book, ticker/funding per coin",
    },
    {
        "id": "okx",
        "label": "OKX",
        "kind": "websocket",
        "detail": "Spot + swap trades, books5, funding rate per coin",
    },
    {
        "id": "bitstamp",
        "label": "Bitstamp",
        "kind": "websocket",
        "detail": "USD live trades and order book for coins Bitstamp lists",
    },
    {
        "id": "deribit",
        "label": "Deribit",
        "kind": "websocket",
        "detail": "BTC/ETH perpetual trades, book, mark (USD)",
    },
    {
        "id": "coincap",
        "label": "CoinCap",
        "kind": "websocket",
        "detail": "Lightweight aggregated USD prices for enabled coins",
    },
    {
        "id": "polymarket_gamma",
        "label": "Polymarket Gamma",
        "kind": "rest",
        "detail": "Discovers BTC/ETH/SOL/XRP 15m Up/Down markets and tokens",
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
        "detail": "Fear & Greed, mempool fees, per-coin Binance OI, 1h/4h klines",
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
