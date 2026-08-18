from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import websockets

logger = logging.getLogger(__name__)

OnMessage = Callable[[Any, str], Awaitable[None]]
OnOpen = Callable[[Any], Awaitable[None]]


async def run_forever(
    url: str,
    *,
    on_open: OnOpen | None = None,
    on_message: OnMessage,
    ping_interval: float | None = 20.0,
    ping_timeout: float | None = 20.0,
    text_ping: str | None = None,
    text_ping_every: float = 10.0,
    extra_headers: dict[str, str] | None = None,
) -> None:
    delay = 1.0
    while True:
        try:
            kwargs: dict[str, Any] = {
                "ping_interval": ping_interval,
                "ping_timeout": ping_timeout,
                "max_size": 2**23,
                "open_timeout": 30,
            }
            if extra_headers:
                kwargs["additional_headers"] = extra_headers
            async with websockets.connect(url, **kwargs) as ws:
                delay = 1.0
                ping_task = None
                if text_ping:
                    ping_task = asyncio.create_task(_text_ping(ws, text_ping, text_ping_every))
                try:
                    if on_open:
                        await on_open(ws)
                    async for raw in ws:
                        if isinstance(raw, bytes):
                            raw = raw.decode("utf-8", "ignore")
                        if raw in {"PONG", "pong", "ping"}:
                            if raw == "ping":
                                await ws.send("pong")
                            continue
                        await on_message(ws, raw)
                finally:
                    if ping_task:
                        ping_task.cancel()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("websocket %s disconnected: %s", url, exc)
            await asyncio.sleep(delay)
            delay = min(delay * 2.0, 60.0)


async def _text_ping(ws: Any, payload: str, every: float) -> None:
    while True:
        await asyncio.sleep(every)
        try:
            await ws.send(payload)
        except Exception:
            return


def parse_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None
