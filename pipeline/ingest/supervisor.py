from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import aiohttp
from asgiref.sync import sync_to_async
from django.utils import timezone as dj_tz

from pipeline.catalog import FREE_SOURCES
from pipeline.ingest.engine import MarketState
from pipeline.ingest.sources import SOURCE_RUNNERS, polymarket_clob
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
from pipeline.universe import (
    TIMEFRAMES,
    asset_from_poly_slug,
    bar_intervals_seconds,
    configured_assets,
    configured_kline_intervals,
    poly_slug,
    set_runtime,
)

logger = logging.getLogger(__name__)


class CollectorRuntime:
    def __init__(self) -> None:
        self.states: dict[str, MarketState] = {}
        self.bus: asyncio.Queue = asyncio.Queue(maxsize=50_000)
        self.tick_buffer: list[LiveTick] = []
        self.stop = asyncio.Event()
        self.messages = 0
        self.bars_written = 0
        self.token_ids: list[str] = []
        self.token_to_asset: dict[str, str] = {}
        self.current_slug = ""
        self.assets: list[str] = ["BTC"]
        self.intervals: list[int] = [60]
        self.vpin_bucket = 50_000.0
        self.vpin_window = 50
        self.tfi_windows: list[int] = [15, 60, 180, 300]

    def state_for(self, asset: str) -> MarketState:
        key = (asset or "BTC").upper()
        if key == "*":
            key = "BTC"
        if key not in self.states:
            state = MarketState()
            state.vpin_bucket = self.vpin_bucket
            state.vpin_window = self.vpin_window
            state.tfi_windows = list(self.tfi_windows)
            self.states[key] = state
        return self.states[key]

    def _load_config(self) -> set[str]:
        self.assets = configured_assets()
        klines = configured_kline_intervals()
        set_runtime(self.assets, klines)
        self.intervals = bar_intervals_seconds()
        usd_bucket = get_setting("vpin_bucket_usd")
        btc_bucket = float(get_setting("vpin_bucket_btc") or 25.0)
        self.vpin_bucket = float(usd_bucket) if usd_bucket else btc_bucket * 100_000.0
        self.vpin_window = int(get_setting("vpin_window_buckets") or 50)
        windows = get_setting("tfi_windows_seconds") or [15, 60, 180, 300]
        self.tfi_windows = [int(w) for w in windows]
        for asset in self.assets:
            self.state_for(asset)
        return set(get_setting("enabled_sources") or [])

    async def run(self) -> None:
        write_pid("collector", os.getpid())
        enabled = await sync_to_async(self._load_config)()
        await _ensure_sources(enabled)

        tasks = [
            asyncio.create_task(self.consume(), name="consume"),
            asyncio.create_task(self.emit_bars(), name="bars"),
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
            tasks.append(asyncio.create_task(self._run_named(sid, lambda r=runner: r(self.bus, self.assets))))

        await _log(
            "info",
            "collector",
            f"collector started pid={os.getpid()} assets={self.assets} intervals={self.intervals} sources={sorted(enabled)}",
        )
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
            asset = str(event.get("asset") or data.get("asset") or "BTC").upper()
            if kind == "fng":
                for state in self.states.values():
                    state.fear_greed = float(data.get("value") or 0)
                    state.message_counts[venue] += 1
                    state.last_event_ts[venue] = ts
            else:
                state = self.state_for("BTC" if asset == "*" else asset)
                state.message_counts[venue] += 1
                state.last_event_ts[venue] = ts
                try:
                    self._apply(state, venue, kind, ts, data, asset)
                except Exception as exc:
                    logger.debug("apply failed %s %s %s: %s", asset, venue, kind, exc)
            if kind == "trade":
                self.tick_buffer.append(
                    LiveTick(
                        ts_ms=int(ts * 1000),
                        venue=venue,
                        asset="BTC" if asset == "*" else asset,
                        kind="trade",
                        price=float(data.get("price") or 0),
                        size=float(data.get("size") or 0),
                        is_buyer_maker=bool(data.get("is_buyer_maker")),
                        extra={},
                    )
                )
            if kind == "kline":
                await self._maybe_write_kline_bar(asset, data, ts)
            source_name = _source_for_venue(venue)
            if self.messages % 200 == 0:
                await _set_source(source_name, status="live", bump=200, error="")

    def _apply(self, state: MarketState, venue: str, kind: str, ts: float, data: dict[str, Any], asset: str) -> None:
        if kind == "trade":
            state.on_trade(venue, float(data["price"]), float(data["size"]), bool(data.get("is_buyer_maker")), ts)
        elif kind == "book":
            book = state.book(venue)
            bids = data.get("bids") or []
            asks = data.get("asks") or []
            if data.get("snapshot", True) or (bids and asks):
                book.apply_snapshot(bids, asks)
            last = state.last_price.get(venue) or book.mid()
            if last:
                state.last_price[venue] = last
        elif kind == "book_delta":
            book = state.book(venue)
            for change in data.get("changes") or []:
                if len(change) >= 3:
                    book.apply_delta(str(change[0]), float(change[1]), float(change[2]))
        elif kind == "ticker":
            price = data.get("price")
            if price:
                state.last_price[venue] = float(price)
            bid, ask = data.get("bid"), data.get("ask")
            if bid and ask:
                book = state.book(venue)
                book.apply_snapshot([[bid, data.get("bid_sz") or 1]], [[ask, data.get("ask_sz") or 1]])
            if data.get("funding") is not None:
                key = "bybit" if venue == "bybit" else venue
                state.funding[key] = float(data["funding"])
            if data.get("oi"):
                state.open_interest = float(data["oi"])
        elif kind == "mark":
            if data.get("funding") is not None:
                state.funding["binance"] = float(data["funding"])
            if data.get("mark"):
                state.last_price["binance_futures"] = float(data["mark"])
        elif kind == "liq":
            state.on_liq(float(data.get("notional") or 0), ts)
        elif kind == "funding":
            state.funding["okx"] = float(data.get("funding") or 0)
        elif kind == "oi":
            state.open_interest = float(data.get("oi") or 0)
        elif kind == "mempool":
            state.mempool_fast = float(data.get("fastestFee") or 0)
        elif kind == "kline":
            _push_kline(state, data)
        elif kind == "mtf":
            interval = data.get("interval")
            closes = [float(x) for x in data.get("closes") or []]
            if interval == "1h":
                state.klines_1h.clear()
                state.klines_1h.extend(closes)
            elif interval == "4h":
                state.klines_4h.clear()
                state.klines_4h.extend(closes)
        elif kind == "clob":
            self._apply_clob(data.get("payload") or {})

    def _apply_clob(self, payload: dict[str, Any]) -> None:
        event = payload.get("event_type") or payload.get("type")
        token = str(payload.get("asset_id") or payload.get("asset") or "")
        asset = self.token_to_asset.get(token, "BTC")
        state = self.state_for(asset)
        token_up = str(state.poly.get("token_up") or "")
        is_yes = token == token_up if token_up else True
        if event == "book" or payload.get("bids") or payload.get("asks"):
            bids = payload.get("bids") or []
            asks = payload.get("asks") or []
            bid, ask, obi = book_top({"bids": bids, "asks": asks})
            prefix = "yes" if is_yes else "no"
            if bid is not None:
                state.poly[f"{prefix}_bid"] = bid
            if ask is not None:
                state.poly[f"{prefix}_ask"] = ask
            if obi is not None:
                state.poly[f"{prefix}_obi"] = obi
        if event == "best_bid_ask":
            prefix = "yes" if is_yes else "no"
            if payload.get("best_bid"):
                state.poly[f"{prefix}_bid"] = float(payload["best_bid"])
            if payload.get("best_ask"):
                state.poly[f"{prefix}_ask"] = float(payload["best_ask"])
        if event == "last_trade_price" and payload.get("price"):
            if is_yes:
                state.poly["last_trade_yes"] = float(payload["price"])

    async def _maybe_write_kline_bar(self, asset: str, data: dict[str, Any], now: float) -> None:
        interval_name = str(data.get("interval") or "")
        interval_sec = TIMEFRAMES.get(interval_name)
        if not interval_sec or interval_sec not in self.intervals:
            return
        open_time = data.get("open_time")
        if not open_time:
            return
        ts = int(open_time) // 1000 if int(open_time) > 10_000_000_000 else int(open_time)
        state = self.state_for(asset)
        feats = state.snapshot(now)
        mid = feats.get("mid") or data.get("close")
        if mid is None:
            return
        await _upsert_bar(asset, ts, interval_sec, float(mid), feats)
        self.bars_written += 1

    async def emit_bars(self) -> None:
        last_ts: dict[tuple[str, int], int] = {}
        while True:
            await asyncio.sleep(1)
            now = time.time()
            intervals = self.intervals or [60]
            for asset, state in list(self.states.items()):
                feats = None
                wrote = False
                for interval in intervals:
                    ts = int(now) - (int(now) % interval)
                    if last_ts.get((asset, interval)) == ts:
                        continue
                    last_ts[(asset, interval)] = ts
                    if feats is None:
                        feats = state.snapshot(now)
                    mid = feats.get("mid")
                    if mid is None:
                        continue
                    await _upsert_bar(asset, ts, interval, mid, feats)
                    self.bars_written += 1
                    wrote = True
                if wrote:
                    state.reset_second_counters()

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
            mids = {asset: state.reference_mid() for asset, state in self.states.items()}
            await _heartbeat(
                "collector",
                {
                    "messages": self.messages,
                    "bars": self.bars_written,
                    "queue": self.bus.qsize(),
                    "mid": mids.get("BTC") or next((v for v in mids.values() if v), None),
                    "mids": mids,
                    "assets": list(self.states),
                    "intervals": self.intervals,
                    "slug": self.current_slug,
                    "venues": {
                        venue: sum(state.message_counts.get(venue, 0) for state in self.states.values())
                        for venue in {v for state in self.states.values() for v in state.message_counts}
                    },
                },
            )
            await asyncio.sleep(2)

    async def poly_loop(self) -> None:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while True:
                try:
                    start = current_window_start()
                    all_tokens: list[str] = []
                    for asset in self.assets:
                        slug = poly_slug(asset, start)
                        if not slug:
                            continue
                        market = await fetch_market(session, start, asset=asset)
                        if not market:
                            continue
                        state = self.state_for(asset)
                        if asset == "BTC":
                            self.current_slug = market["slug"]
                        for token in (market.get("token_up"), market.get("token_down")):
                            if token:
                                all_tokens.append(str(token))
                                self.token_to_asset[str(token)] = asset
                        state.poly.update(
                            {
                                "slug": market["slug"],
                                "token_up": market.get("token_up"),
                                "token_down": market.get("token_down"),
                                "start_ts": market["start_ts"],
                                "end_ts": market["end_ts"],
                                "seconds_left": max(0, market["end_ts"] - time.time()),
                            }
                        )
                        if state.poly.get("btc_open") is None:
                            state.poly["btc_open"] = state.reference_mid()
                        mid = state.reference_mid()
                        if mid:
                            state.poly["btc_last"] = mid
                        if market.get("token_up"):
                            up_book = await fetch_book(session, market["token_up"])
                            bid, ask, obi = book_top(up_book)
                            state.poly["yes_bid"] = bid
                            state.poly["yes_ask"] = ask
                            state.poly["yes_obi"] = obi
                        if market.get("token_down"):
                            down_book = await fetch_book(session, market["token_down"])
                            bid, ask, obi = book_top(down_book)
                            state.poly["no_bid"] = bid
                            state.poly["no_ask"] = ask
                            state.poly["no_obi"] = obi
                        await _upsert_poly(market, state.poly)
                    self.token_ids = all_tokens
                    if all_tokens:
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
    state.last_price["binance_spot"] = close


def _source_for_venue(venue: str) -> str:
    if venue.startswith("okx"):
        return "okx"
    if venue in {"rest_aux"}:
        return "rest_aux"
    if venue == "polymarket_clob":
        return "polymarket_clob"
    return venue


def label_ready_bars(horizon: int = 900, limit: int = 8000) -> int:
    now = int(time.time())
    labeled_15 = _label_horizon(now, horizon, limit)
    labeled_next = _label_next(now, limit)
    _label_poly_windows()
    return labeled_15 + labeled_next


def _future_maps(bars: list[FeatureBar]) -> tuple[dict[tuple[str, int, int], float], dict[tuple[str, int], float]]:
    if not bars:
        return {}, {}
    assets = {bar.asset for bar in bars}
    min_ts = min(bar.ts for bar in bars)
    max_interval = max(bar.interval_seconds for bar in bars)
    max_ts = max(bar.ts for bar in bars) + 900 + max_interval * 2
    same: dict[tuple[str, int, int], float] = {}
    any_tf: dict[tuple[str, int], float] = {}
    for row in FeatureBar.objects.filter(asset__in=assets, ts__gte=min_ts, ts__lte=max_ts).only(
        "asset", "ts", "interval_seconds", "mid_price"
    ):
        if row.mid_price is None:
            continue
        same[(row.asset, row.interval_seconds, row.ts)] = row.mid_price
        key = (row.asset, row.ts)
        if key not in any_tf:
            any_tf[key] = row.mid_price
    return same, any_tf


def _lookup_future(
    asset: str,
    interval: int,
    target: int,
    current_ts: int,
    same: dict[tuple[str, int, int], float],
    any_tf: dict[tuple[str, int], float],
) -> float | None:
    candidates = [target]
    for delta in range(1, interval + 3):
        candidates.append(target + delta)
        back = target - delta
        if back > current_ts:
            candidates.append(back)
    for ts in candidates:
        price = same.get((asset, interval, ts)) or any_tf.get((asset, ts))
        if price is not None:
            return price
    return None


def _label_horizon(now: int, horizon: int, limit: int) -> int:
    qs = list(
        FeatureBar.objects.filter(label_up_15m__isnull=True, ts__lte=now - horizon).order_by("ts")[:limit]
    )
    if not qs:
        return 0
    same, any_tf = _future_maps(qs)
    updated = []
    for bar in qs:
        if bar.mid_price is None:
            continue
        future_px = _lookup_future(bar.asset, bar.interval_seconds, bar.ts + horizon, bar.ts, same, any_tf)
        if future_px is None:
            continue
        bar.label_up_15m = bool(future_px > bar.mid_price)
        updated.append(bar)
    if updated:
        FeatureBar.objects.bulk_update(updated, ["label_up_15m"], batch_size=500)
    return len(updated)


def _label_next(now: int, limit: int) -> int:
    qs = list(FeatureBar.objects.filter(label_up_next__isnull=True).order_by("ts")[: limit * 2])
    ready = [bar for bar in qs if bar.ts + bar.interval_seconds <= now]
    if not ready:
        return 0
    same, any_tf = _future_maps(ready)
    updated = []
    for bar in ready:
        if bar.mid_price is None:
            continue
        future_px = _lookup_future(
            bar.asset, bar.interval_seconds, bar.ts + bar.interval_seconds, bar.ts, same, any_tf
        )
        if future_px is None:
            continue
        bar.label_up_next = bool(future_px > bar.mid_price)
        updated.append(bar)
    if updated:
        FeatureBar.objects.bulk_update(updated, ["label_up_next"], batch_size=500)
    return len(updated)


def _label_poly_windows() -> None:
    now = int(time.time())
    for window in PolyMarketWindow.objects.filter(resolved_up__isnull=True, end_ts__lte=now):
        if window.btc_open and window.btc_last:
            window.resolved_up = window.btc_last > window.btc_open
            window.save(update_fields=["resolved_up"])
            asset = asset_from_poly_slug(window.slug) or "BTC"
            FeatureBar.objects.filter(
                asset=asset,
                ts__gte=window.start_ts,
                ts__lt=window.end_ts,
                label_poly_up__isnull=True,
            ).update(label_poly_up=window.resolved_up)


@sync_to_async
def _upsert_bar(asset: str, ts: int, interval: int, mid: float | None, feats: dict[str, Any]) -> None:
    FeatureBar.objects.update_or_create(
        asset=asset,
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
