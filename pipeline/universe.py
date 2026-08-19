"""Tradable coins and bar timeframes for simultaneous free-data collection."""

from __future__ import annotations

from typing import Any

TIMEFRAMES: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
}

SECONDS_TO_TIMEFRAME: dict[int, str] = {v: k for k, v in TIMEFRAMES.items()}

TIMEFRAME_CHOICES: list[dict[str, Any]] = [
    {"id": "1m", "label": "1 minute", "seconds": 60, "kline": True},
    {"id": "5m", "label": "5 minutes", "seconds": 300, "kline": True},
    {"id": "15m", "label": "15 minutes", "seconds": 900, "kline": True},
    {"id": "1h", "label": "1 hour", "seconds": 3600, "kline": True},
]

# Venue symbols. Missing keys mean that venue is skipped for the coin.
ASSETS: dict[str, dict[str, str]] = {
    "BTC": {
        "label": "Bitcoin",
        "binance": "BTCUSDT",
        "coinbase": "BTC-USD",
        "kraken": "BTC/USD",
        "bybit": "BTCUSDT",
        "okx": "BTC-USDT",
        "okx_swap": "BTC-USDT-SWAP",
        "bitstamp": "btcusd",
        "deribit": "BTC-PERPETUAL",
        "coincap": "bitcoin",
        "poly": "btc",
    },
    "ETH": {
        "label": "Ethereum",
        "binance": "ETHUSDT",
        "coinbase": "ETH-USD",
        "kraken": "ETH/USD",
        "bybit": "ETHUSDT",
        "okx": "ETH-USDT",
        "okx_swap": "ETH-USDT-SWAP",
        "bitstamp": "ethusd",
        "deribit": "ETH-PERPETUAL",
        "coincap": "ethereum",
        "poly": "eth",
    },
    "SOL": {
        "label": "Solana",
        "binance": "SOLUSDT",
        "coinbase": "SOL-USD",
        "kraken": "SOL/USD",
        "bybit": "SOLUSDT",
        "okx": "SOL-USDT",
        "okx_swap": "SOL-USDT-SWAP",
        "bitstamp": "solusd",
        "coincap": "solana",
        "poly": "sol",
    },
    "XRP": {
        "label": "XRP",
        "binance": "XRPUSDT",
        "coinbase": "XRP-USD",
        "kraken": "XRP/USD",
        "bybit": "XRPUSDT",
        "okx": "XRP-USDT",
        "okx_swap": "XRP-USDT-SWAP",
        "bitstamp": "xrpusd",
        "coincap": "ripple",
        "poly": "xrp",
    },
    "DOGE": {
        "label": "Dogecoin",
        "binance": "DOGEUSDT",
        "coinbase": "DOGE-USD",
        "kraken": "DOGE/USD",
        "bybit": "DOGEUSDT",
        "okx": "DOGE-USDT",
        "okx_swap": "DOGE-USDT-SWAP",
        "bitstamp": "dogeusd",
        "coincap": "dogecoin",
    },
    "BNB": {
        "label": "BNB",
        "binance": "BNBUSDT",
        "coinbase": "BNB-USD",
        "bybit": "BNBUSDT",
        "okx": "BNB-USDT",
        "okx_swap": "BNB-USDT-SWAP",
        "coincap": "binance-coin",
    },
    "ADA": {
        "label": "Cardano",
        "binance": "ADAUSDT",
        "coinbase": "ADA-USD",
        "kraken": "ADA/USD",
        "bybit": "ADAUSDT",
        "okx": "ADA-USDT",
        "okx_swap": "ADA-USDT-SWAP",
        "bitstamp": "adausd",
        "coincap": "cardano",
    },
    "AVAX": {
        "label": "Avalanche",
        "binance": "AVAXUSDT",
        "coinbase": "AVAX-USD",
        "kraken": "AVAX/USD",
        "bybit": "AVAXUSDT",
        "okx": "AVAX-USDT",
        "okx_swap": "AVAX-USDT-SWAP",
        "coincap": "avalanche-2",
    },
    "LINK": {
        "label": "Chainlink",
        "binance": "LINKUSDT",
        "coinbase": "LINK-USD",
        "kraken": "LINK/USD",
        "bybit": "LINKUSDT",
        "okx": "LINK-USDT",
        "okx_swap": "LINK-USDT-SWAP",
        "bitstamp": "linkusd",
        "coincap": "chainlink",
    },
    "LTC": {
        "label": "Litecoin",
        "binance": "LTCUSDT",
        "coinbase": "LTC-USD",
        "kraken": "LTC/USD",
        "bybit": "LTCUSDT",
        "okx": "LTC-USDT",
        "okx_swap": "LTC-USDT-SWAP",
        "bitstamp": "ltcusd",
        "coincap": "litecoin",
    },
}

DEFAULT_ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "BNB"]
DEFAULT_TIMEFRAMES = ["1m", "5m", "15m"]

LABEL_MODES: list[dict[str, str]] = [
    {
        "id": "next",
        "label": "Next bar (same timeframe)",
        "field": "label_up_next",
        "detail": "Fast loop: 1m bars label after 1 minute. Best for checking if a starter model works.",
    },
    {
        "id": "horizon_15m",
        "label": "15-minute horizon",
        "field": "label_up_15m",
        "detail": "Matches Polymarket BTC Up/Down. Needs 15 minutes of future price.",
    },
]

_runtime_assets: list[str] | None = None
_runtime_klines: list[str] | None = None


def set_runtime(assets: list[str], klines: list[str]) -> None:
    global _runtime_assets, _runtime_klines
    _runtime_assets = normalize_assets(assets)
    _runtime_klines = normalize_timeframes(klines)


def runtime_assets() -> list[str]:
    if _runtime_assets:
        return list(_runtime_assets)
    return configured_assets()


def runtime_klines() -> list[str]:
    if _runtime_klines:
        return list(_runtime_klines)
    return configured_kline_intervals()


def normalize_assets(raw: Any) -> list[str]:
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.split(",")]
    if not isinstance(raw, (list, tuple)):
        return list(DEFAULT_ASSETS)
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        asset = str(item).strip().upper()
        if asset in ASSETS and asset not in seen:
            seen.add(asset)
            out.append(asset)
    return out or list(DEFAULT_ASSETS)


def normalize_timeframes(raw: Any) -> list[str]:
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.split(",")]
    if not isinstance(raw, (list, tuple)):
        return list(DEFAULT_TIMEFRAMES)
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        tf = str(item).strip().lower()
        if tf in TIMEFRAMES and tf not in seen:
            seen.add(tf)
            out.append(tf)
    return out or list(DEFAULT_TIMEFRAMES)


def configured_assets() -> list[str]:
    from pipeline.store import get_setting

    return normalize_assets(get_setting("enabled_assets") or DEFAULT_ASSETS)


def configured_timeframes() -> list[str]:
    from pipeline.store import get_setting

    return normalize_timeframes(get_setting("bar_timeframes") or DEFAULT_TIMEFRAMES)


def configured_kline_intervals() -> list[str]:
    return [tf for tf in configured_timeframes() if TIMEFRAMES.get(tf)]


def bar_intervals_seconds() -> list[int]:
    from pipeline.store import get_setting

    secs = [TIMEFRAMES[tf] for tf in configured_timeframes()]
    micro = int(get_setting("bar_interval_seconds") or 0)
    if micro > 0 and micro not in secs:
        secs.append(micro)
    return sorted(set(secs))


def venue_symbol(asset: str, venue: str) -> str | None:
    spec = ASSETS.get(asset.upper())
    if not spec:
        return None
    value = spec.get(venue)
    return value or None


def symbols_for(venue: str, assets: list[str] | None = None) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for asset in assets or runtime_assets():
        symbol = venue_symbol(asset, venue)
        if symbol:
            rows.append((asset, symbol))
    return rows


def _index(venue: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for asset, spec in ASSETS.items():
        symbol = spec.get(venue)
        if not symbol:
            continue
        out[symbol] = asset
        out[symbol.upper()] = asset
        out[symbol.lower()] = asset
        compact = symbol.replace("/", "").replace("-", "").upper()
        out[compact] = asset
    return out


_BINANCE = _index("binance")
_COINBASE = _index("coinbase")
_KRAKEN = _index("kraken")
_BYBIT = _index("bybit")
_OKX = {**_index("okx"), **_index("okx_swap")}
_BITSTAMP = _index("bitstamp")
_DERIBIT = _index("deribit")
_COINCAP = _index("coincap")
_POLY = {spec["poly"]: asset for asset, spec in ASSETS.items() if spec.get("poly")}


def asset_from_binance(stream_or_symbol: str) -> str | None:
    token = str(stream_or_symbol or "").split("@")[0].split(":")[-1]
    token = token.replace("/", "").replace("-", "")
    return _BINANCE.get(token) or _BINANCE.get(token.upper()) or _BINANCE.get(token.lower())


def asset_from_coinbase(product_id: str) -> str | None:
    return _COINBASE.get(product_id) or _COINBASE.get(str(product_id).upper())


def asset_from_kraken(symbol: str) -> str | None:
    return _KRAKEN.get(symbol) or _KRAKEN.get(str(symbol).upper())


def asset_from_bybit(symbol: str) -> str | None:
    token = str(symbol or "").split(".")[-1]
    return _BYBIT.get(token) or _BYBIT.get(token.upper())


def asset_from_okx(inst_id: str) -> str | None:
    return _OKX.get(inst_id) or _OKX.get(str(inst_id).upper())


def asset_from_bitstamp(channel: str) -> str | None:
    raw = str(channel or "")
    for prefix in ("live_trades_", "order_book_", "live_orders_"):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
            break
    return _BITSTAMP.get(raw) or _BITSTAMP.get(raw.lower())


def asset_from_deribit(channel: str) -> str | None:
    parts = str(channel or "").split(".")
    instrument = parts[1] if len(parts) > 1 else str(channel)
    return _DERIBIT.get(instrument) or _DERIBIT.get(instrument.upper())


def asset_from_coincap(coin_id: str) -> str | None:
    return _COINCAP.get(coin_id) or _COINCAP.get(str(coin_id).lower())


def asset_from_poly_slug(slug: str) -> str | None:
    prefix = str(slug or "").split("-updown-")[0].lower()
    return _POLY.get(prefix)


def poly_slug(asset: str, start: int) -> str | None:
    prefix = venue_symbol(asset.upper(), "poly")
    if not prefix:
        return None
    return f"{prefix}-updown-15m-{start}"


def universe_payload() -> dict[str, Any]:
    return {
        "assets": [{"id": key, "label": spec["label"]} for key, spec in ASSETS.items()],
        "timeframes": TIMEFRAME_CHOICES,
        "label_modes": LABEL_MODES,
        "default_assets": list(DEFAULT_ASSETS),
        "default_timeframes": list(DEFAULT_TIMEFRAMES),
        "enabled_assets": configured_assets(),
        "enabled_timeframes": configured_timeframes(),
    }
