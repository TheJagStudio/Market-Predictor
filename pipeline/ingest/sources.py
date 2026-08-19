"""Free public WebSocket + REST collectors. No paid APIs. Multi-coin streams."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import aiohttp

from pipeline.ingest.wsutil import parse_json, run_forever
from pipeline.universe import (
    asset_from_binance,
    asset_from_bitstamp,
    asset_from_bybit,
    asset_from_coinbase,
    asset_from_coincap,
    asset_from_deribit,
    asset_from_kraken,
    asset_from_okx,
    runtime_assets,
    runtime_klines,
    symbols_for,
)

logger = logging.getLogger(__name__)

QUEUE = asyncio.Queue


def _ts() -> float:
    return time.time()


def _assets(assets: list[str] | None) -> list[str]:
    return [a.upper() for a in assets] if assets else runtime_assets()


def _klines() -> list[str]:
    return [tf for tf in runtime_klines() if tf in {"1m", "5m", "15m", "1h"}]


def _chunks(items: list[str], size: int = 40) -> list[list[str]]:
    if not items:
        return []
    return [items[i : i + size] for i in range(0, len(items), size)]


async def emit(
    bus: asyncio.Queue,
    venue: str,
    kind: str,
    data: dict[str, Any],
    ts: float | None = None,
    asset: str = "BTC",
) -> None:
    payload = dict(data)
    payload.setdefault("asset", asset)
    event = {
        "venue": venue,
        "kind": kind,
        "ts": ts if ts is not None else _ts(),
        "asset": asset,
        "data": payload,
    }
    try:
        bus.put_nowait(event)
    except asyncio.QueueFull:
        try:
            bus.get_nowait()
        except asyncio.QueueEmpty:
            pass
        bus.put_nowait(event)


async def binance_spot(bus: asyncio.Queue, assets: list[str] | None = None) -> None:
    coins = _assets(assets)
    klines = _klines() or ["1m", "5m", "15m"]
    streams: list[str] = []
    for asset, symbol in symbols_for("binance", coins):
        sym = symbol.lower()
        depth = "100ms" if asset == "BTC" else "1000ms"
        streams.extend([f"{sym}@trade", f"{sym}@bookTicker", f"{sym}@depth20@{depth}"])
        for interval in klines:
            streams.append(f"{sym}@kline_{interval}")

    async def on_message(_ws: Any, raw: str) -> None:
        msg = parse_json(raw)
        if not msg:
            return
        payload = msg.get("data") or msg
        stream = str(msg.get("stream") or "")
        asset = asset_from_binance(stream) or "BTC"
        if "trade" in stream and "aggTrade" not in stream:
            await emit(
                bus,
                "binance_spot",
                "trade",
                {
                    "price": float(payload["p"]),
                    "size": float(payload["q"]),
                    "is_buyer_maker": bool(payload.get("m")),
                    "id": payload.get("t"),
                },
                ts=float(payload.get("T", time.time() * 1000)) / 1000.0,
                asset=asset,
            )
        elif "depth20" in stream:
            await emit(
                bus,
                "binance_spot",
                "book",
                {"bids": payload.get("bids") or [], "asks": payload.get("asks") or []},
                asset=asset,
            )
        elif "bookTicker" in stream:
            await emit(
                bus,
                "binance_spot",
                "ticker",
                {
                    "bid": float(payload["b"]),
                    "ask": float(payload["a"]),
                    "bid_sz": float(payload["B"]),
                    "ask_sz": float(payload["A"]),
                },
                asset=asset,
            )
        elif "kline" in stream:
            k = payload.get("k") or {}
            if k.get("x"):
                await emit(
                    bus,
                    "binance_spot",
                    "kline",
                    {
                        "interval": k.get("i"),
                        "close": float(k["c"]),
                        "volume": float(k["v"]),
                        "open": float(k["o"]),
                        "high": float(k["h"]),
                        "low": float(k["l"]),
                        "open_time": int(k.get("t") or 0),
                    },
                    asset=asset,
                )

    tasks = [
        run_forever(f"wss://stream.binance.com:9443/stream?streams={'/'.join(chunk)}", on_message=on_message)
        for chunk in _chunks(streams, 45)
    ]
    if not tasks:
        await asyncio.sleep(5)
        return
    await asyncio.gather(*tasks)


async def binance_futures(bus: asyncio.Queue, assets: list[str] | None = None) -> None:
    coins = _assets(assets)
    streams: list[str] = []
    for _asset, symbol in symbols_for("binance", coins):
        sym = symbol.lower()
        streams.extend(
            [
                f"{sym}@aggTrade",
                f"{sym}@depth20@1000ms",
                f"{sym}@markPrice@1s",
                f"{sym}@forceOrder",
                f"{sym}@kline_1m",
            ]
        )

    async def on_message(_ws: Any, raw: str) -> None:
        msg = parse_json(raw)
        if not msg:
            return
        payload = msg.get("data") or msg
        stream = str(msg.get("stream") or "")
        asset = asset_from_binance(stream or str(payload.get("s") or "")) or "BTC"
        if "aggTrade" in stream:
            await emit(
                bus,
                "binance_futures",
                "trade",
                {
                    "price": float(payload["p"]),
                    "size": float(payload["q"]),
                    "is_buyer_maker": bool(payload.get("m")),
                },
                ts=float(payload.get("T", time.time() * 1000)) / 1000.0,
                asset=asset,
            )
        elif "depth20" in stream:
            await emit(
                bus,
                "binance_futures",
                "book",
                {"bids": payload.get("b") or payload.get("bids") or [], "asks": payload.get("a") or payload.get("asks") or []},
                asset=asset,
            )
        elif "markPrice" in stream:
            await emit(
                bus,
                "binance_futures",
                "mark",
                {
                    "mark": float(payload.get("p") or 0),
                    "index": float(payload.get("i") or 0),
                    "funding": float(payload.get("r") or 0),
                },
                asset=asset,
            )
        elif "forceOrder" in stream:
            o = payload.get("o") or payload
            qty = float(o.get("q") or o.get("l") or 0)
            price = float(o.get("p") or o.get("ap") or 0)
            sym = str(o.get("s") or payload.get("s") or "")
            liq_asset = asset_from_binance(sym) or asset
            await emit(bus, "binance_futures", "liq", {"notional": abs(qty * price), "side": o.get("S")}, asset=liq_asset)
        elif "kline" in stream:
            k = payload.get("k") or {}
            if k.get("x"):
                await emit(
                    bus,
                    "binance_futures",
                    "kline",
                    {
                        "interval": k.get("i"),
                        "close": float(k["c"]),
                        "volume": float(k["v"]),
                        "open_time": int(k.get("t") or 0),
                    },
                    asset=asset,
                )

    tasks = [
        run_forever(f"wss://fstream.binance.com/stream?streams={'/'.join(chunk)}", on_message=on_message)
        for chunk in _chunks(streams, 40)
    ]
    if not tasks:
        await asyncio.sleep(5)
        return
    await asyncio.gather(*tasks)


async def coinbase(bus: asyncio.Queue, assets: list[str] | None = None) -> None:
    url = "wss://ws-feed.exchange.coinbase.com"
    products = [symbol for _asset, symbol in symbols_for("coinbase", _assets(assets))]

    async def on_open(ws: Any) -> None:
        if not products:
            return
        await ws.send(
            json.dumps(
                {
                    "type": "subscribe",
                    "product_ids": products,
                    "channels": ["matches", "ticker", "level2_batch"],
                }
            )
        )

    async def on_message(_ws: Any, raw: str) -> None:
        msg = parse_json(raw)
        if not isinstance(msg, dict):
            return
        typ = msg.get("type")
        asset = asset_from_coinbase(str(msg.get("product_id") or "")) or "BTC"
        if typ in {"match", "last_match"}:
            side = str(msg.get("side") or "").lower()
            await emit(
                bus,
                "coinbase",
                "trade",
                {
                    "price": float(msg["price"]),
                    "size": float(msg["size"]),
                    "is_buyer_maker": side == "sell",
                },
                asset=asset,
            )
        elif typ == "ticker":
            await emit(
                bus,
                "coinbase",
                "ticker",
                {
                    "bid": float(msg.get("best_bid") or 0),
                    "ask": float(msg.get("best_ask") or 0),
                    "price": float(msg.get("price") or 0),
                },
                asset=asset,
            )
        elif typ in {"snapshot", "l2update", "level2"}:
            if "bids" in msg or "asks" in msg:
                await emit(
                    bus,
                    "coinbase",
                    "book",
                    {"bids": msg.get("bids") or [], "asks": msg.get("asks") or [], "snapshot": typ == "snapshot"},
                    asset=asset,
                )
            changes = msg.get("changes") or []
            if changes:
                await emit(bus, "coinbase", "book_delta", {"changes": changes}, asset=asset)

    await run_forever(url, on_open=on_open, on_message=on_message)


async def kraken(bus: asyncio.Queue, assets: list[str] | None = None) -> None:
    url = "wss://ws.kraken.com/v2"
    symbols = [symbol for _asset, symbol in symbols_for("kraken", _assets(assets))]

    async def on_open(ws: Any) -> None:
        if not symbols:
            return
        await ws.send(json.dumps({"method": "subscribe", "params": {"channel": "trade", "symbol": symbols}}))
        await ws.send(json.dumps({"method": "subscribe", "params": {"channel": "ticker", "symbol": symbols}}))
        await ws.send(json.dumps({"method": "subscribe", "params": {"channel": "book", "symbol": symbols, "depth": 10}}))

    async def on_message(_ws: Any, raw: str) -> None:
        msg = parse_json(raw)
        if not isinstance(msg, dict):
            return
        channel = msg.get("channel")
        data = msg.get("data") or []
        if channel == "trade":
            for trade in data:
                asset = asset_from_kraken(str(trade.get("symbol") or "")) or "BTC"
                side = str(trade.get("side") or "").lower()
                await emit(
                    bus,
                    "kraken",
                    "trade",
                    {
                        "price": float(trade["price"]),
                        "size": float(trade["qty"]),
                        "is_buyer_maker": side == "sell",
                    },
                    asset=asset,
                )
        elif channel == "ticker" and data:
            t = data[0]
            asset = asset_from_kraken(str(t.get("symbol") or "")) or "BTC"
            await emit(
                bus,
                "kraken",
                "ticker",
                {
                    "bid": float((t.get("bid") or 0)),
                    "ask": float((t.get("ask") or 0)),
                    "price": float(t.get("last") or 0),
                },
                asset=asset,
            )
        elif channel == "book" and data:
            book = data[0]
            asset = asset_from_kraken(str(book.get("symbol") or "")) or "BTC"
            await emit(
                bus,
                "kraken",
                "book",
                {
                    "bids": [[x["price"], x["qty"]] for x in book.get("bids") or []],
                    "asks": [[x["price"], x["qty"]] for x in book.get("asks") or []],
                    "snapshot": msg.get("type") == "snapshot",
                },
                asset=asset,
            )

    await run_forever(url, on_message=on_message, on_open=on_open)


async def bybit(bus: asyncio.Queue, assets: list[str] | None = None) -> None:
    url = "wss://stream.bybit.com/v5/public/linear"
    args: list[str] = []
    for _asset, symbol in symbols_for("bybit", _assets(assets)):
        args.extend([f"publicTrade.{symbol}", f"orderbook.50.{symbol}", f"tickers.{symbol}"])

    async def on_open(ws: Any) -> None:
        for chunk in _chunks(args, 20):
            await ws.send(json.dumps({"op": "subscribe", "args": chunk}))

    async def on_message(_ws: Any, raw: str) -> None:
        msg = parse_json(raw)
        if not isinstance(msg, dict):
            return
        topic = str(msg.get("topic") or "")
        data = msg.get("data")
        asset = asset_from_bybit(topic) or "BTC"
        if topic.startswith("publicTrade") and isinstance(data, list):
            for trade in data:
                await emit(
                    bus,
                    "bybit",
                    "trade",
                    {
                        "price": float(trade["p"]),
                        "size": float(trade["v"]),
                        "is_buyer_maker": str(trade.get("S") or "").lower() == "sell",
                    },
                    asset=asset,
                )
        elif topic.startswith("orderbook") and isinstance(data, dict):
            await emit(
                bus,
                "bybit",
                "book",
                {
                    "bids": data.get("b") or [],
                    "asks": data.get("a") or [],
                    "snapshot": msg.get("type") == "snapshot",
                },
                asset=asset,
            )
        elif topic.startswith("tickers") and isinstance(data, dict):
            funding = data.get("fundingRate")
            await emit(
                bus,
                "bybit",
                "ticker",
                {
                    "bid": float(data.get("bid1Price") or 0),
                    "ask": float(data.get("ask1Price") or 0),
                    "price": float(data.get("lastPrice") or 0),
                    "funding": float(funding) if funding not in (None, "") else None,
                    "oi": float(data["openInterest"]) if data.get("openInterest") else None,
                },
                asset=asset,
            )

    await run_forever(url, on_message=on_message, on_open=on_open)


async def okx(bus: asyncio.Queue, assets: list[str] | None = None) -> None:
    url = "wss://ws.okx.com:8443/ws/v5/public"
    args: list[dict[str, str]] = []
    for _asset, symbol in symbols_for("okx", _assets(assets)):
        args.extend([{"channel": "trades", "instId": symbol}, {"channel": "books5", "instId": symbol}])
    for _asset, symbol in symbols_for("okx_swap", _assets(assets)):
        args.extend(
            [
                {"channel": "trades", "instId": symbol},
                {"channel": "books5", "instId": symbol},
                {"channel": "funding-rate", "instId": symbol},
            ]
        )

    async def on_open(ws: Any) -> None:
        for i in range(0, len(args), 20):
            await ws.send(json.dumps({"op": "subscribe", "args": args[i : i + 20]}))

    async def on_message(_ws: Any, raw: str) -> None:
        msg = parse_json(raw)
        if not isinstance(msg, dict):
            return
        arg = msg.get("arg") or {}
        channel = arg.get("channel")
        inst = arg.get("instId")
        asset = asset_from_okx(str(inst or "")) or "BTC"
        venue = "okx_swap" if inst and "SWAP" in str(inst) else "okx_spot"
        data = msg.get("data") or []
        if channel == "trades":
            for trade in data:
                await emit(
                    bus,
                    venue,
                    "trade",
                    {
                        "price": float(trade["px"]),
                        "size": float(trade["sz"]),
                        "is_buyer_maker": str(trade.get("side") or "").lower() == "sell",
                    },
                    asset=asset,
                )
        elif channel == "books5":
            for book in data:
                await emit(
                    bus,
                    venue,
                    "book",
                    {"bids": book.get("bids") or [], "asks": book.get("asks") or [], "snapshot": True},
                    asset=asset,
                )
        elif channel == "funding-rate" and data:
            await emit(bus, "okx_swap", "funding", {"funding": float(data[0].get("fundingRate") or 0)}, asset=asset)

    await run_forever(url, on_message=on_message, on_open=on_open)


async def bitstamp(bus: asyncio.Queue, assets: list[str] | None = None) -> None:
    url = "wss://ws.bitstamp.net"
    pairs = [symbol for _asset, symbol in symbols_for("bitstamp", _assets(assets))]

    async def on_open(ws: Any) -> None:
        for pair in pairs:
            await ws.send(json.dumps({"event": "bts:subscribe", "data": {"channel": f"live_trades_{pair}"}}))
            await ws.send(json.dumps({"event": "bts:subscribe", "data": {"channel": f"order_book_{pair}"}}))

    async def on_message(_ws: Any, raw: str) -> None:
        msg = parse_json(raw)
        if not isinstance(msg, dict):
            return
        event = msg.get("event")
        data = msg.get("data") or {}
        asset = asset_from_bitstamp(str(msg.get("channel") or "")) or "BTC"
        if event == "trade":
            await emit(
                bus,
                "bitstamp",
                "trade",
                {
                    "price": float(data["price"]),
                    "size": float(data["amount"]),
                    "is_buyer_maker": str(data.get("type")) == "1",
                },
                asset=asset,
            )
        elif event == "data" and (data.get("bids") or data.get("asks")):
            await emit(
                bus,
                "bitstamp",
                "book",
                {"bids": data.get("bids") or [], "asks": data.get("asks") or [], "snapshot": True},
                asset=asset,
            )

    await run_forever(url, on_message=on_message, on_open=on_open)


async def deribit(bus: asyncio.Queue, assets: list[str] | None = None) -> None:
    url = "wss://www.deribit.com/ws/api/v2"
    channels: list[str] = []
    for _asset, instrument in symbols_for("deribit", _assets(assets)):
        channels.extend(
            [
                f"trades.{instrument}.100ms",
                f"book.{instrument}.none.10.100ms",
                f"ticker.{instrument}.100ms",
            ]
        )

    async def on_open(ws: Any) -> None:
        if not channels:
            return
        await ws.send(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "public/subscribe",
                    "params": {"channels": channels},
                }
            )
        )

    async def on_message(_ws: Any, raw: str) -> None:
        msg = parse_json(raw)
        if not isinstance(msg, dict):
            return
        params = msg.get("params") or {}
        channel = str(params.get("channel") or "")
        data = params.get("data")
        asset = asset_from_deribit(channel) or "BTC"
        if channel.startswith("trades") and isinstance(data, list):
            for trade in data:
                await emit(
                    bus,
                    "deribit",
                    "trade",
                    {
                        "price": float(trade["price"]),
                        "size": float(trade.get("amount") or 0) / max(float(trade["price"]), 1.0),
                        "is_buyer_maker": str(trade.get("direction") or "").lower() == "sell",
                    },
                    asset=asset,
                )
        elif channel.startswith("book") and isinstance(data, dict):
            bids = data.get("bids") or []
            asks = data.get("asks") or []
            await emit(
                bus,
                "deribit",
                "book",
                {
                    "bids": [x[-2:] for x in bids] if bids and len(bids[0]) > 2 else bids,
                    "asks": [x[-2:] for x in asks] if asks and len(asks[0]) > 2 else asks,
                    "snapshot": True,
                },
                asset=asset,
            )
        elif channel.startswith("ticker") and isinstance(data, dict):
            await emit(
                bus,
                "deribit",
                "ticker",
                {
                    "bid": float(data.get("best_bid_price") or 0),
                    "ask": float(data.get("best_ask_price") or 0),
                    "price": float(data.get("last_price") or data.get("mark_price") or 0),
                    "funding": float(data["current_funding"]) if data.get("current_funding") is not None else None,
                },
                asset=asset,
            )

    await run_forever(url, on_message=on_message, on_open=on_open)


async def coincap(bus: asyncio.Queue, assets: list[str] | None = None) -> None:
    ids = [symbol for _asset, symbol in symbols_for("coincap", _assets(assets))]
    url = "wss://ws.coincap.io/prices?assets=" + ",".join(ids or ["bitcoin"])

    async def on_message(_ws: Any, raw: str) -> None:
        msg = parse_json(raw)
        if not isinstance(msg, dict):
            return
        for coin_id, price in msg.items():
            asset = asset_from_coincap(str(coin_id))
            if not asset or price is None:
                continue
            await emit(bus, "coincap", "ticker", {"price": float(price)}, asset=asset)

    await run_forever(url, on_message=on_message)


async def polymarket_clob(bus: asyncio.Queue, token_provider) -> None:
    url = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

    async def on_open(ws: Any) -> None:
        tokens = await token_provider()
        if not tokens:
            return
        await ws.send(
            json.dumps(
                {
                    "type": "market",
                    "assets_ids": tokens,
                    "custom_feature_enabled": True,
                }
            )
        )

    async def on_message(ws: Any, raw: str) -> None:
        msg = parse_json(raw)
        payloads = msg if isinstance(msg, list) else [msg]
        for item in payloads:
            if not isinstance(item, dict):
                continue
            event_type = item.get("event_type") or item.get("type")
            await emit(bus, "polymarket_clob", "clob", {"event": event_type, "payload": item})

    async def runner() -> None:
        while True:
            tokens = await token_provider()
            if not tokens:
                await asyncio.sleep(5)
                continue
            await run_forever(
                url,
                on_open=on_open,
                on_message=on_message,
                ping_interval=None,
                ping_timeout=None,
                text_ping="PING",
                text_ping_every=10.0,
            )

    await runner()


async def rest_aux(bus: asyncio.Queue, assets: list[str] | None = None) -> None:
    coins = _assets(assets)
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        while True:
            try:
                await _poll_fng(session, bus)
                await _poll_mempool(session, bus)
                await _poll_oi(session, bus, coins)
                await _poll_mtf(session, bus, coins)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("rest_aux: %s", exc)
            await asyncio.sleep(30)


async def _poll_fng(session: aiohttp.ClientSession, bus: asyncio.Queue) -> None:
    async with session.get("https://api.alternative.me/fng/?limit=1") as resp:
        if resp.status != 200:
            return
        data = await resp.json()
        rows = data.get("data") or []
        if rows:
            await emit(bus, "rest_aux", "fng", {"value": float(rows[0]["value"])}, asset="*")


async def _poll_mempool(session: aiohttp.ClientSession, bus: asyncio.Queue) -> None:
    async with session.get("https://mempool.space/api/v1/fees/recommended") as resp:
        if resp.status != 200:
            return
        data = await resp.json()
        await emit(bus, "rest_aux", "mempool", {"fastestFee": float(data.get("fastestFee") or 0)}, asset="BTC")


async def _poll_oi(session: aiohttp.ClientSession, bus: asyncio.Queue, coins: list[str]) -> None:
    for asset, symbol in symbols_for("binance", coins):
        url = f"https://fapi.binance.com/fapi/v1/openInterest?symbol={symbol}"
        async with session.get(url) as resp:
            if resp.status != 200:
                continue
            data = await resp.json()
            await emit(bus, "binance_futures", "oi", {"oi": float(data.get("openInterest") or 0)}, asset=asset)


async def _poll_mtf(session: aiohttp.ClientSession, bus: asyncio.Queue, coins: list[str]) -> None:
    for asset, symbol in symbols_for("binance", coins):
        for interval in ("1h", "4h"):
            url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=80"
            async with session.get(url) as resp:
                if resp.status != 200:
                    continue
                rows = await resp.json()
                closes = [float(row[4]) for row in rows]
                volumes = [float(row[5]) for row in rows]
                await emit(
                    bus,
                    "binance_spot",
                    "mtf",
                    {"interval": interval, "closes": closes, "volumes": volumes},
                    asset=asset,
                )


SOURCE_RUNNERS = {
    "binance_spot": binance_spot,
    "binance_futures": binance_futures,
    "coinbase": coinbase,
    "kraken": kraken,
    "bybit": bybit,
    "okx": okx,
    "bitstamp": bitstamp,
    "deribit": deribit,
    "coincap": coincap,
    "rest_aux": rest_aux,
}
