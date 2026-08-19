from __future__ import annotations

import json
import logging
import time
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
WINDOW = 900


def current_window_start(now: float | None = None) -> int:
    ts = int(now if now is not None else time.time())
    return (ts // WINDOW) * WINDOW


def btc_15m_slug(start: int | None = None) -> str:
    return f"btc-updown-15m-{start if start is not None else current_window_start()}"


def updown_slug(asset: str = "BTC", start: int | None = None) -> str:
    from pipeline.universe import poly_slug

    ts = start if start is not None else current_window_start()
    return poly_slug(asset, ts) or f"{asset.lower()}-updown-15m-{ts}"


def _parse_json_field(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


async def fetch_json(session: aiohttp.ClientSession, url: str) -> Any | None:
    try:
        async with session.get(url) as resp:
            if resp.status == 404:
                return None
            if resp.status != 200:
                logger.warning("GET %s -> %s", url, resp.status)
                return None
            return await resp.json()
    except Exception as exc:
        logger.warning("GET %s failed: %s", url, exc)
        return None


async def fetch_market(session: aiohttp.ClientSession, start: int | None = None, asset: str = "BTC") -> dict[str, Any] | None:
    slug = updown_slug(asset, start)
    event = await fetch_json(session, f"{GAMMA}/events/slug/{slug}")
    market = await fetch_json(session, f"{GAMMA}/markets/slug/{slug}")
    if not market:
        # fallback search
        search = await fetch_json(
            session,
            f"{GAMMA}/markets?closed=false&limit=20&slug={slug}",
        )
        if isinstance(search, list) and search:
            market = search[0]
        elif isinstance(search, dict) and search.get("id"):
            market = search
    if not market:
        return None
    tokens = _parse_json_field(market.get("clobTokenIds") or market.get("clob_token_ids") or [])
    outcomes = _parse_json_field(market.get("outcomes") or ["Up", "Down"])
    prices = _parse_json_field(market.get("outcomePrices") or [])
    token_up = ""
    token_down = ""
    if isinstance(tokens, list) and len(tokens) >= 2:
        token_up, token_down = str(tokens[0]), str(tokens[1])
        if isinstance(outcomes, list) and len(outcomes) >= 2:
            mapped = {str(name).lower(): str(tid) for name, tid in zip(outcomes, tokens)}
            token_up = mapped.get("up", token_up)
            token_down = mapped.get("down", token_down)
    start_ts = start if start is not None else current_window_start()
    end_iso = market.get("endDate") or market.get("end_date_iso")
    end_ts = start_ts + WINDOW
    return {
        "slug": slug,
        "condition_id": market.get("conditionId") or market.get("condition_id") or "",
        "question": market.get("question") or (event or {}).get("title") or "",
        "token_up": token_up,
        "token_down": token_down,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "end_iso": end_iso,
        "active": (event or {}).get("active", True),
        "closed": (event or {}).get("closed", False) or market.get("closed"),
        "outcome_prices": prices,
        "raw": {"market": {k: market.get(k) for k in ("id", "question", "liquidityNum") if k in market}},
    }


async def fetch_book(session: aiohttp.ClientSession, token_id: str) -> dict[str, Any] | None:
    if not token_id:
        return None
    return await fetch_json(session, f"{CLOB}/book?token_id={token_id}")


def book_top(book: dict[str, Any] | None) -> tuple[float | None, float | None, float | None]:
    if not book:
        return None, None, None
    bids = book.get("bids") or []
    asks = book.get("asks") or []

    def px_sz(levels: list) -> tuple[float | None, float]:
        if not levels:
            return None, 0.0
        top = levels[0]
        if isinstance(top, dict):
            return float(top.get("price") or 0), float(top.get("size") or 0)
        return float(top[0]), float(top[1])

    bid, bid_sz = px_sz(bids)
    ask, ask_sz = px_sz(asks)
    tot = bid_sz + ask_sz
    obi = (bid_sz - ask_sz) / tot if tot else None
    return bid, ask, obi
