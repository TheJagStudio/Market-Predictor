from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import aiohttp
from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils import timezone as dj_tz

from pipeline.catalog import FREE_SOURCES
from pipeline.ingest.engine import MarketState
from pipeline.ingest.sources import SOURCE_RUNNERS, emit, polymarket_clob
from pipeline.models import (
    AppLog,
    CollectorSource,
    FeatureBar,
    LiveTick,
    PolyMarketWindow,
    ProcessHeartbeat,
)
from pipeline.procutil import write_pid
from pipeline.store import get_setting
from pipeline.trading.markets import book_top, current_window_start, fetch_book, fetch_market

logger = logging.getLogger(__name__)


class CollectorRuntime:
    def __init__(self) -> None:
        self.state = MarketState()
        self.bus: asyncio.Queue = asyncio.Queue(maxsize=50_000)
        self.tick_buffer: list[LiveTick] = []
        self.stop = asyncio.Event()
        self.messages = 0
        self.bars_written = 0
        self.token_ids: list[str] = []
        self.current_slug = ""

    async def run(self) -> None:
        write_pid("collector", os.getpid())
        interval = int(get_setting("bar_interval_seconds") or settings.DEFAULT_BAR_SECONDS)
        self.state.vpin_bucket = float(get_setting("vpin_bucket_btc") or 25.0)
        self.state.vpin_window = int(get_setting("vpin_window_buckets") or 50)
        windows = get_setting("tfi_windows_seconds") or [15, 60, 180, 300]
        self.state.tfi_windows = [int(w) for w in windows]
        enabled = set(get_setting("enabled_sources") or [])
        await _ensure_sources(enabled)

        tasks = [
            asyncio.create_task(self.consume(), name="consume"),
            asyncio.create_task(self.emit_bars(interval), name="bars"),
            asyncio.create_task(self.flush_loop(), name="flush"),
            asyncio.create_task(self.heartbeat_loop(), name="hb"),
            asyncio.create_task(self.poly_loop(), name="poly"),
            asyncio.create_task(self.label_loop(), name="labels"),
            asyncio.create_task(self.prune_loop(), name="prune"),
        ]
        for source in FREE_SOURCES:
            sid = source["id"]
            if sid not in enabled:
                await _set_source(sid, status="disabled")
                continue
            if sid == "polymarket_gamma":
                continue
            if sid == "polymarket_clob":
                tasks.append(asyncio.create_task(self._run_named(sid, lambda: polymarket_clob(self.bus, self._tokens))))
                continue
            runner = SOURCE_RUNNERS.get(sid)
            if not runner:
                continue
            tasks.append(asyncio.create_task(self._run_named(sid, lambda r=runner: r(self.bus))))

        await _log("info", "collector", f"collector started pid={os.getpid()} sources={sorted(enabled)}")
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            raise
        finally:
            await self.flush(force=True)

    async def _tokens(self) -> list[str]:
        return list(self.token_ids)

    async def _run_named(self, name: str, factory) -> None:
        await _set_source(name, status="connecting", error="")
        while not self.stop.is_set():
            try:
                await factory()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await _set_source(name, status="error", error=str(exc)[:500])
                await asyncio.sleep(3)

    async def consume(self) -> None:
        while True:
            event = await self.bus.get()
            self.messages += 1
            venue = event["venue"]
            kind = event["kind"]
            ts = float(event["ts"])
            data = event["data"]
            self.state.message_counts[venue] += 1
            self.state.last_event_ts[venue] = ts
            try:
                self._apply(venue, kind, ts, data)
            except Exception as exc:
                logger.debug("apply failed %s %s: %s", venue, kind, exc)
            if kind == "trade":
                self.tick_buffer.append(
                    LiveTick(
                        ts_ms=int(ts * 1000),
                        venue=venue,
                        kind="trade",
                        price=float(data.get("price") or 0),
                        size=float(data.get("size") or 0),
                        is_buyer_maker=bool(data.get("is_buyer_maker")),
                        extra={},
                    )
                )
            source_name = _source_for_venue(venue)
            if self.messages % 200 == 0:
                await _set_source(source_name, status="live", bump=200, error="")

    def _apply(self, venue: str, kind: str, ts: float, data: dict[str, Any]) -> None:
        if kind == "trade":
            self.state.on_trade(venue, float(data["price"]), float(data["size"]), bool(data.get("is_buyer_maker")), ts)
        elif kind == "book":
            book = self.state.book(venue)
            bids = data.get("bids") or []
            asks = data.get("asks") or []
            if data.get("snapshot", True) or (bids and asks):
                book.apply_snapshot(bids, asks)
            last = self.state.last_price.get(venue) or book.mid()
            if last:
                self.state.last_price[venue] = last
        elif kind == "book_delta":
            book = self.state.book(venue)
            for change in data.get("changes") or []:
                if len(change) >= 3:
                    book.apply_delta(str(change[0]), float(change[1]), float(change[2]))
        elif kind == "ticker":
            price = data.get("price")
            if price:
                self.state.last_price[venue] = float(price)
            bid, ask = data.get("bid"), data.get("ask")
            if bid and ask:
                book = self.state.book(venue)
                book.apply_snapshot([[bid, data.get("bid_sz") or 1]], [[ask, data.get("ask_sz") or 1]])
            if data.get("funding") is not None:
                key = "bybit" if venue == "bybit" else venue
                self.state.funding[key] = float(data["funding"])
            if data.get("oi"):
                self.state.open_interest = float(data["oi"])
        elif kind == "mark":
            if data.get("funding") is not None:
                self.state.funding["binance"] = float(data["funding"])
            if data.get("mark"):
                self.state.last_price["binance_futures"] = float(data["mark"])
        elif kind == "liq":
            self.state.on_liq(float(data.get("notional") or 0), ts)
        elif kind == "funding":
            self.state.funding["okx"] = float(data.get("funding") or 0)
        elif kind == "oi":
            self.state.open_interest = float(data.get("oi") or 0)
        elif kind == "fng":
            self.state.fear_greed = float(data.get("value") or 0)
        elif kind == "mempool":
            self.state.mempool_fast = float(data.get("fastestFee") or 0)
        elif kind == "kline":
            _push_kline(self.state, data)
        elif kind == "mtf":
            interval = data.get("interval")
            closes = [float(x) for x in data.get("closes") or []]
            if interval == "1h":
                self.state.klines_1h.clear()
                self.state.klines_1h.extend(closes)
            elif interval == "4h":
                self.state.klines_4h.clear()
                self.state.klines_4h.extend(closes)
        elif kind == "clob":
            self._apply_clob(data.get("payload") or {})

    def _apply_clob(self, payload: dict[str, Any]) -> None:
        event = payload.get("event_type") or payload.get("type")
        asset = str(payload.get("asset_id") or payload.get("asset") or "")
        token_up = str(self.state.poly.get("token_up") or "")
        is_yes = asset == token_up if token_up else True
        if event == "book" or payload.get("bids") or payload.get("asks"):
            bids = payload.get("bids") or []
            asks = payload.get("asks") or []
            bid, ask, obi = book_top({"bids": bids, "asks": asks})
            prefix = "yes" if is_yes else "no"
            if bid is not None:
                self.state.poly[f"{prefix}_bid"] = bid
            if ask is not None:
                self.state.poly[f"{prefix}_ask"] = ask
            if obi is not None:
                self.state.poly[f"{prefix}_obi"] = obi
        if event == "best_bid_ask":
            prefix = "yes" if is_yes else "no"
            if payload.get("best_bid"):
                self.state.poly[f"{prefix}_bid"] = float(payload["best_bid"])
            if payload.get("best_ask"):
                self.state.poly[f"{prefix}_ask"] = float(payload["best_ask"])
        if event == "last_trade_price" and payload.get("price"):
            if is_yes:
                self.state.poly["last_trade_yes"] = float(payload["price"])

    async def emit_bars(self, interval: int) -> None:
        while True:
            await asyncio.sleep(interval)
            now = time.time()
            ts = int(now) - (int(now) % interval)
            feats = self.state.snapshot(now)
            mid = feats.get("mid")
            await _upsert_bar(ts, interval, mid, feats)
            self.bars_written += 1
            self.state.reset_second_counters()

    async def flush_loop(self) -> None:
        while True:
            await asyncio.sleep(2)
            await self.flush()

    async def flush(self, force: bool = False) -> None:
        if not self.tick_buffer:
            return
        if not force and len(self.tick_buffer) < 50:
            return
        batch = self.tick_buffer
        self.tick_buffer = []
        await sync_to_async(LiveTick.objects.bulk_create)(batch, batch_size=500)

    async def heartbeat_loop(self) -> None:
        while True:
            await _heartbeat(
                "collector",
                {
                    "messages": self.messages,
                    "bars": self.bars_written,
                    "queue": self.bus.qsize(),
                    "mid": self.state.reference_mid(),
                    "slug": self.current_slug,
                    "venues": dict(self.state.message_counts),
                },
            )
            await asyncio.sleep(2)

    async def poly_loop(self) -> None:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while True:
                try:
                    start = current_window_start()
                    market = await fetch_market(session, start)
                    if market:
                        self.current_slug = market["slug"]
                        self.token_ids = [t for t in (market.get("token_up"), market.get("token_down")) if t]
                        self.state.poly.update(
                            {
                                "slug": market["slug"],
                                "token_up": market.get("token_up"),
                                "token_down": market.get("token_down"),
                                "start_ts": market["start_ts"],
                                "end_ts": market["end_ts"],
                                "seconds_left": max(0, market["end_ts"] - time.time()),
                            }
                        )
                        if self.state.poly.get("btc_open") is None:
                            self.state.poly["btc_open"] = self.state.reference_mid()
                        mid = self.state.reference_mid()
                        if mid:
                            self.state.poly["btc_last"] = mid
                        if market.get("token_up"):
                            up_book = await fetch_book(session, market["token_up"])
                            bid, ask, obi = book_top(up_book)
                            self.state.poly["yes_bid"] = bid
                            self.state.poly["yes_ask"] = ask
                            self.state.poly["yes_obi"] = obi
                        if market.get("token_down"):
                            down_book = await fetch_book(session, market["token_down"])
                            bid, ask, obi = book_top(down_book)
                            self.state.poly["no_bid"] = bid
                            self.state.poly["no_ask"] = ask
                            self.state.poly["no_obi"] = obi
                        await _upsert_poly(market, self.state.poly)
                        await _set_source("polymarket_gamma", status="live", bump=1, error="")
                        await _set_source("polymarket_clob", status="live", error="")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    await _set_source("polymarket_gamma", status="error", error=str(exc)[:400])
                await asyncio.sleep(2)

    async def label_loop(self) -> None:
        while True:
            await asyncio.sleep(15)
            try:
                n = await sync_to_async(label_ready_bars)()
                if n:
                    await _log("info", "labeler", f"labeled {n} bars")
            except Exception as exc:
                logger.warning("label: %s", exc)

    async def prune_loop(self) -> None:
        while True:
            await asyncio.sleep(120)
            hours = float(get_setting("tick_retention_hours") or 6)
            cutoff = int((time.time() - hours * 3600) * 1000)
            deleted, _ = await sync_to_async(lambda: LiveTick.objects.filter(ts_ms__lt=cutoff).delete())()
            if deleted:
                await _log("info", "prune", f"dropped {deleted} old ticks")


def _push_kline(state: MarketState, data: dict[str, Any]) -> None:
    interval = data.get("interval")
    close = float(data.get("close") or 0)
    volume = float(data.get("volume") or 0)
    if not close:
        return
    mapping = {
        "1m": state.klines_1m,
        "5m": state.klines_5m,
        "15m": state.klines_15m,
        "1h": state.klines_1h,
        "4h": state.klines_4h,
    }
    buf = mapping.get(str(interval))
    if buf is not None:
        buf.append(close)
    if interval == "1m":
        state.volumes_1m.append(volume)


def _source_for_venue(venue: str) -> str:
    if venue.startswith("okx"):
        return "okx"
    if venue in {"rest_aux"}:
        return "rest_aux"
    if venue == "polymarket_clob":
        return "polymarket_clob"
    return venue


def label_ready_bars(horizon: int = 900, limit: int = 4000) -> int:
    now = int(time.time())
    qs = list(
        FeatureBar.objects.filter(label_up_15m__isnull=True, ts__lte=now - horizon).order_by("ts")[:limit]
    )
    if not qs:
        return 0
    interval = qs[0].interval_seconds
    min_ts = qs[0].ts
    max_ts = qs[-1].ts + horizon + interval * 2
    futures = {
        row.ts: row.mid_price
        for row in FeatureBar.objects.filter(interval_seconds=interval, ts__gte=min_ts, ts__lte=max_ts)
    }
    updated = []
    for bar in qs:
        target = bar.ts + horizon
        future_px = futures.get(target)
        if future_px is None:
            for delta in range(1, interval + 3):
                future_px = futures.get(target + delta) or futures.get(target - delta)
                if future_px is not None:
                    break
        if future_px is None or bar.mid_price is None:
            continue
        bar.label_up_15m = bool(future_px > bar.mid_price)
        updated.append(bar)
    if updated:
        FeatureBar.objects.bulk_update(updated, ["label_up_15m"], batch_size=500)
    _label_poly_windows()
    return len(updated)


def _label_poly_windows() -> None:
    now = int(time.time())
    for window in PolyMarketWindow.objects.filter(resolved_up__isnull=True, end_ts__lte=now):
        if window.btc_open and window.btc_last:
            window.resolved_up = window.btc_last > window.btc_open
            window.save(update_fields=["resolved_up"])
            FeatureBar.objects.filter(ts__gte=window.start_ts, ts__lt=window.end_ts, label_poly_up__isnull=True).update(
                label_poly_up=window.resolved_up
            )


@sync_to_async
def _upsert_bar(ts: int, interval: int, mid: float | None, feats: dict[str, Any]) -> None:
    FeatureBar.objects.update_or_create(
        ts=ts,
        interval_seconds=interval,
        defaults={"mid_price": mid, "features": feats},
    )


@sync_to_async
def _upsert_poly(market: dict[str, Any], poly: dict[str, Any]) -> None:
    PolyMarketWindow.objects.update_or_create(
        slug=market["slug"],
        defaults={
            "condition_id": market.get("condition_id") or "",
            "question": market.get("question") or "",
            "token_up": market.get("token_up") or "",
            "token_down": market.get("token_down") or "",
            "start_ts": market["start_ts"],
            "end_ts": market["end_ts"],
            "yes_bid": poly.get("yes_bid"),
            "yes_ask": poly.get("yes_ask"),
            "no_bid": poly.get("no_bid"),
            "no_ask": poly.get("no_ask"),
            "last_trade_yes": poly.get("last_trade_yes"),
            "btc_open": poly.get("btc_open"),
            "btc_last": poly.get("btc_last"),
            "extra": market.get("raw") or {},
        },
    )


@sync_to_async
def _ensure_sources(enabled: set[str]) -> None:
    for source in FREE_SOURCES:
        CollectorSource.objects.get_or_create(
            name=source["id"],
            defaults={"enabled": source["id"] in enabled, "status": "idle"},
        )


@sync_to_async
def _set_source(name: str, status: str | None = None, error: str | None = None, bump: int = 0) -> None:
    row, _ = CollectorSource.objects.get_or_create(name=name, defaults={"enabled": True})
    fields = []
    if status:
        row.status = status
        fields.append("status")
    if error is not None:
        row.error = error
        fields.append("error")
    if bump:
        row.message_count += bump
        row.last_message_at = dj_tz.now()
        fields.extend(["message_count", "last_message_at"])
    if fields:
        row.save(update_fields=list(set(fields)))


@sync_to_async
def _heartbeat(name: str, stats: dict[str, Any]) -> None:
    row, created = ProcessHeartbeat.objects.get_or_create(name=name)
    now = dj_tz.now()
    row.pid = os.getpid()
    row.running = True
    row.heartbeat_at = now
    if created or not row.started_at:
        row.started_at = now
    row.stats = stats
    row.last_error = ""
    row.save()


@sync_to_async
def _log(level: str, source: str, message: str, extra: dict | None = None) -> None:
    AppLog.objects.create(level=level, source=source, message=message, extra=extra or {})
    if AppLog.objects.count() > 5000:
        cutoff = list(AppLog.objects.order_by("-id").values_list("id", flat=True)[:4000])[-1]
        AppLog.objects.filter(id__lt=cutoff).delete()


def run_collector() -> None:
    logging.basicConfig(level=logging.INFO)
    runtime = CollectorRuntime()
    asyncio.run(runtime.run())
