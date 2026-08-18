"""Free public WebSocket + REST collectors. No paid APIs."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import aiohttp

from pipeline.ingest.wsutil import parse_json, run_forever

logger = logging.getLogger(__name__)

QUEUE = asyncio.Queue


def _ts() -> float:
    return time.time()


async def emit(bus: asyncio.Queue, venue: str, kind: str, data: dict[str, Any], ts: float | None = None) -> None:
    event = {"venue": venue, "kind": kind, "ts": ts if ts is not None else _ts(), "data": data}
    try:
        bus.put_nowait(event)
    except asyncio.QueueFull:
        try:
            bus.get_nowait()
        except asyncio.QueueEmpty:
            pass
        bus.put_nowait(event)


async def binance_spot(bus: asyncio.Queue) -> None:
    streams = "/".join(
        [
            "btcusdt@trade",
            "btcusdt@depth20@100ms",
            "btcusdt@bookTicker",
            "btcusdt@kline_1m",
            "btcusdt@kline_5m",
            "btcusdt@kline_15m",
        ]
    )
    url = f"wss://stream.binance.com:9443/stream?streams={streams}"

    async def on_message(_ws: Any, raw: str) -> None:
        msg = parse_json(raw)
        if not msg:
            return
        payload = msg.get("data") or msg
        stream = str(msg.get("stream") or "")
        if "trade" in stream:
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
            )
        elif "depth20" in stream:
            await emit(bus, "binance_spot", "book", {"bids": payload.get("bids") or [], "asks": payload.get("asks") or []})
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
            )
        elif "kline" in stream:
            k = payload.get("k") or {}
            if k.get("x"):
                interval = k.get("i")
                await emit(
                    bus,
                    "binance_spot",
                    "kline",
                    {
                        "interval": interval,
                        "close": float(k["c"]),
                        "volume": float(k["v"]),
                        "open": float(k["o"]),
                        "high": float(k["h"]),
                        "low": float(k["l"]),
                    },
                )

    await run_forever(url, on_message=on_message)


async def binance_futures(bus: asyncio.Queue) -> None:
    streams = "/".join(
        [
            "btcusdt@aggTrade",
            "btcusdt@depth20@100ms",
            "btcusdt@markPrice@1s",
            "btcusdt@forceOrder",
            "btcusdt@kline_1m",
        ]
    )
    url = f"wss://fstream.binance.com/stream?streams={streams}"

    async def on_message(_ws: Any, raw: str) -> None:
        msg = parse_json(raw)
        if not msg:
            return
        payload = msg.get("data") or msg
        stream = str(msg.get("stream") or "")
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
            )
        elif "depth20" in stream:
            await emit(bus, "binance_futures", "book", {"bids": payload.get("b") or payload.get("bids") or [], "asks": payload.get("a") or payload.get("asks") or []})
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
            )
        elif "forceOrder" in stream:
            o = payload.get("o") or payload
            qty = float(o.get("q") or o.get("l") or 0)
            price = float(o.get("p") or o.get("ap") or 0)
            await emit(bus, "binance_futures", "liq", {"notional": abs(qty * price), "side": o.get("S")})
        elif "kline" in stream:
            k = payload.get("k") or {}
            if k.get("x"):
                await emit(bus, "binance_futures", "kline", {"interval": k.get("i"), "close": float(k["c"]), "volume": float(k["v"])})

    await run_forever(url, on_message=on_message)


async def coinbase(bus: asyncio.Queue) -> None:
    url = "wss://ws-feed.exchange.coinbase.com"

    async def on_open(ws: Any) -> None:
        await ws.send(
            json.dumps(
                {
                    "type": "subscribe",
                    "product_ids": ["BTC-USD"],
                    "channels": ["matches", "ticker", "level2_batch"],
                }
            )
        )

    async def on_message(_ws: Any, raw: str) -> None:
        msg = parse_json(raw)
        if not isinstance(msg, dict):
            return
        typ = msg.get("type")
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
            )
        elif typ in {"snapshot", "l2update", "level2"}:
            if "bids" in msg or "asks" in msg:
                await emit(bus, "coinbase", "book", {"bids": msg.get("bids") or [], "asks": msg.get("asks") or [], "snapshot": typ == "snapshot"})
            changes = msg.get("changes") or []
            if changes:
                await emit(bus, "coinbase", "book_delta", {"changes": changes})

    await run_forever(url, on_open=on_open, on_message=on_message)


async def kraken(bus: asyncio.Queue) -> None:
    url = "wss://ws.kraken.com/v2"

    async def on_open(ws: Any) -> None:
        await ws.send(json.dumps({"method": "subscribe", "params": {"channel": "trade", "symbol": ["BTC/USD"]}}))
        await ws.send(json.dumps({"method": "subscribe", "params": {"channel": "ticker", "symbol": ["BTC/USD"]}}))
        await ws.send(json.dumps({"method": "subscribe", "params": {"channel": "book", "symbol": ["BTC/USD"], "depth": 10}}))

    async def on_message(_ws: Any, raw: str) -> None:
        msg = parse_json(raw)
        if not isinstance(msg, dict):
            return
        channel = msg.get("channel")
        data = msg.get("data") or []
        if channel == "trade":
            for trade in data:
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
                )
        elif channel == "ticker" and data:
            t = data[0]
            await emit(
                bus,
                "kraken",
                "ticker",
                {
                    "bid": float((t.get("bid") or 0)),
                    "ask": float((t.get("ask") or 0)),
                    "price": float(t.get("last") or 0),
                },
            )
        elif channel == "book" and data:
            book = data[0]
            await emit(
                bus,
                "kraken",
                "book",
                {
                    "bids": [[x["price"], x["qty"]] for x in book.get("bids") or []],
                    "asks": [[x["price"], x["qty"]] for x in book.get("asks") or []],
                    "snapshot": msg.get("type") == "snapshot",
                },
            )

    await run_forever(url, on_message=on_message, on_open=on_open)


async def bybit(bus: asyncio.Queue) -> None:
    url = "wss://stream.bybit.com/v5/public/linear"

    async def on_open(ws: Any) -> None:
        await ws.send(
            json.dumps(
                {
                    "op": "subscribe",
                    "args": ["publicTrade.BTCUSDT", "orderbook.50.BTCUSDT", "tickers.BTCUSDT"],
                }
            )
        )

    async def on_message(_ws: Any, raw: str) -> None:
        msg = parse_json(raw)
        if not isinstance(msg, dict):
            return
        topic = str(msg.get("topic") or "")
        data = msg.get("data")
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
            )

    await run_forever(url, on_message=on_message, on_open=on_open)


async def okx(bus: asyncio.Queue) -> None:
    url = "wss://ws.okx.com:8443/ws/v5/public"

    async def on_open(ws: Any) -> None:
        args = [
            {"channel": "trades", "instId": "BTC-USDT"},
            {"channel": "books5", "instId": "BTC-USDT"},
            {"channel": "trades", "instId": "BTC-USDT-SWAP"},
            {"channel": "books5", "instId": "BTC-USDT-SWAP"},
            {"channel": "funding-rate", "instId": "BTC-USDT-SWAP"},
        ]
        await ws.send(json.dumps({"op": "subscribe", "args": args}))

    async def on_message(_ws: Any, raw: str) -> None:
        msg = parse_json(raw)
        if not isinstance(msg, dict):
            return
        arg = msg.get("arg") or {}
        channel = arg.get("channel")
        inst = arg.get("instId")
        venue = "okx_swap" if inst and "SWAP" in inst else "okx_spot"
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
                )
        elif channel == "books5":
            for book in data:
                await emit(
                    bus,
                    venue,
                    "book",
                    {"bids": book.get("bids") or [], "asks": book.get("asks") or [], "snapshot": True},
                )
        elif channel == "funding-rate" and data:
            await emit(bus, "okx_swap", "funding", {"funding": float(data[0].get("fundingRate") or 0)})

    await run_forever(url, on_message=on_message, on_open=on_open)


async def bitstamp(bus: asyncio.Queue) -> None:
    url = "wss://ws.bitstamp.net"

    async def on_open(ws: Any) -> None:
        await ws.send(json.dumps({"event": "bts:subscribe", "data": {"channel": "live_trades_btcusd"}}))
        await ws.send(json.dumps({"event": "bts:subscribe", "data": {"channel": "order_book_btcusd"}}))

    async def on_message(_ws: Any, raw: str) -> None:
        msg = parse_json(raw)
        if not isinstance(msg, dict):
            return
        event = msg.get("event")
        data = msg.get("data") or {}
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
            )
        elif event == "data" and (data.get("bids") or data.get("asks")):
            await emit(bus, "bitstamp", "book", {"bids": data.get("bids") or [], "asks": data.get("asks") or [], "snapshot": True})

    await run_forever(url, on_message=on_message, on_open=on_open)


async def deribit(bus: asyncio.Queue) -> None:
    url = "wss://www.deribit.com/ws/api/v2"

    async def on_open(ws: Any) -> None:
        await ws.send(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "public/subscribe",
                    "params": {
                        "channels": [
                            "trades.BTC-PERPETUAL.100ms",
                            "book.BTC-PERPETUAL.none.10.100ms",
                            "ticker.BTC-PERPETUAL.100ms",
                        ]
                    },
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
                )
        elif channel.startswith("book") and isinstance(data, dict):
            bids = data.get("bids") or []
            asks = data.get("asks") or []
            await emit(bus, "deribit", "book", {"bids": [x[-2:] for x in bids] if bids and len(bids[0]) > 2 else bids, "asks": [x[-2:] for x in asks] if asks and len(asks[0]) > 2 else asks, "snapshot": True})
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
            )

    await run_forever(url, on_message=on_message, on_open=on_open)


async def coincap(bus: asyncio.Queue) -> None:
    url = "wss://ws.coincap.io/prices?assets=bitcoin"

    async def on_message(_ws: Any, raw: str) -> None:
        msg = parse_json(raw)
        if not isinstance(msg, dict):
            return
        price = msg.get("bitcoin")
        if price is None:
            return
        await emit(bus, "coincap", "ticker", {"price": float(price)})

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


async def rest_aux(bus: asyncio.Queue) -> None:
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        while True:
            try:
                await _poll_fng(session, bus)
                await _poll_mempool(session, bus)
                await _poll_oi(session, bus)
                await _poll_mtf(session, bus)
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
            await emit(bus, "rest_aux", "fng", {"value": float(rows[0]["value"])})


async def _poll_mempool(session: aiohttp.ClientSession, bus: asyncio.Queue) -> None:
    async with session.get("https://mempool.space/api/v1/fees/recommended") as resp:
        if resp.status != 200:
            return
        data = await resp.json()
        await emit(bus, "rest_aux", "mempool", {"fastestFee": float(data.get("fastestFee") or 0)})


async def _poll_oi(session: aiohttp.ClientSession, bus: asyncio.Queue) -> None:
    async with session.get("https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT") as resp:
        if resp.status != 200:
            return
        data = await resp.json()
        await emit(bus, "binance_futures", "oi", {"oi": float(data.get("openInterest") or 0)})


async def _poll_mtf(session: aiohttp.ClientSession, bus: asyncio.Queue) -> None:
    for interval in ("1h", "4h"):
        url = f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval={interval}&limit=80"
        async with session.get(url) as resp:
            if resp.status != 200:
                continue
            rows = await resp.json()
            closes = [float(row[4]) for row in rows]
            volumes = [float(row[5]) for row in rows]
            await emit(bus, "binance_spot", "mtf", {"interval": interval, "closes": closes, "volumes": volumes})


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
