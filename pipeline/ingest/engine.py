from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from pipeline.ingest.features import (
    OrderBook,
    RealTimeTradeImbalance,
    RealTimeVPIN,
    bollinger_position,
    ema,
    rsi,
    zscore,
)

VENUE_KEYS = (
    "binance_spot",
    "binance_futures",
    "coinbase",
    "kraken",
    "bybit",
    "okx_spot",
    "okx_swap",
    "bitstamp",
    "deribit",
    "coincap",
)


@dataclass
class MarketState:
    last_price: dict[str, float] = field(default_factory=dict)
    last_size: dict[str, float] = field(default_factory=dict)
    books: dict[str, OrderBook] = field(default_factory=dict)
    tfi: dict[str, dict[int, RealTimeTradeImbalance]] = field(default_factory=dict)
    vpin: dict[str, RealTimeVPIN] = field(default_factory=dict)
    buy_vol: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    sell_vol: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    trade_count: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    intensity: dict[str, deque[float]] = field(default_factory=dict)
    vwap_num: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    vwap_den: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    liq_notional_5m: deque[tuple[float, float]] = field(default_factory=deque)
    funding: dict[str, float] = field(default_factory=dict)
    open_interest: float | None = None
    fear_greed: float | None = None
    mempool_fast: float | None = None
    klines_1m: deque[float] = field(default_factory=lambda: deque(maxlen=400))
    klines_5m: deque[float] = field(default_factory=lambda: deque(maxlen=400))
    klines_15m: deque[float] = field(default_factory=lambda: deque(maxlen=400))
    klines_1h: deque[float] = field(default_factory=lambda: deque(maxlen=300))
    klines_4h: deque[float] = field(default_factory=lambda: deque(maxlen=200))
    volumes_1m: deque[float] = field(default_factory=lambda: deque(maxlen=400))
    poly: dict[str, Any] = field(default_factory=dict)
    message_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    last_event_ts: dict[str, float] = field(default_factory=dict)
    mid_history: deque[tuple[float, float]] = field(default_factory=lambda: deque(maxlen=4000))
    vpin_bucket: float = 25.0
    vpin_window: int = 50
    tfi_windows: list[int] = field(default_factory=lambda: [15, 60, 180, 300])

    def book(self, venue: str) -> OrderBook:
        if venue not in self.books:
            self.books[venue] = OrderBook()
        return self.books[venue]

    def ensure_venue(self, venue: str) -> None:
        if venue not in self.tfi:
            self.tfi[venue] = {w: RealTimeTradeImbalance(w) for w in self.tfi_windows}
        if venue not in self.vpin:
            self.vpin[venue] = RealTimeVPIN(self.vpin_bucket, self.vpin_window)
        if venue not in self.intensity:
            self.intensity[venue] = deque(maxlen=300)

    def on_trade(self, venue: str, price: float, size: float, is_buyer_maker: bool, ts: float) -> None:
        self.ensure_venue(venue)
        self.last_price[venue] = price
        self.last_size[venue] = size
        signed = -size if is_buyer_maker else size
        if is_buyer_maker:
            self.sell_vol[venue] += size
        else:
            self.buy_vol[venue] += size
        self.trade_count[venue] += 1
        self.vwap_num[venue] += price * size
        self.vwap_den[venue] += size
        self.intensity[venue].append(ts)
        for window, meter in self.tfi[venue].items():
            meter.process_tick(size, is_buyer_maker, ts)
        self.vpin[venue].process_tick(size, is_buyer_maker)
        _ = signed

    def on_liq(self, notional: float, ts: float) -> None:
        self.liq_notional_5m.append((ts, abs(notional)))
        cutoff = ts - 300
        while self.liq_notional_5m and self.liq_notional_5m[0][0] < cutoff:
            self.liq_notional_5m.popleft()

    def reset_second_counters(self) -> None:
        self.buy_vol.clear()
        self.sell_vol.clear()
        self.trade_count.clear()

    def reference_mid(self) -> float | None:
        for venue in ("binance_spot", "coinbase", "binance_futures", "bybit", "kraken"):
            book = self.books.get(venue)
            if book:
                mid = book.mid()
                if mid:
                    return mid
            price = self.last_price.get(venue)
            if price:
                return price
        if self.last_price:
            return next(iter(self.last_price.values()))
        return None

    def snapshot(self, now: float) -> dict[str, float | None]:
        mid = self.reference_mid()
        if mid:
            self.mid_history.append((now, mid))
        feats: dict[str, float | None] = {
            "mid": mid,
            "log_mid": math.log(mid) if mid else None,
        }
        for horizon in (5, 15, 30, 60, 180, 300):
            feats[f"ret_{horizon}s"] = self._return(now, horizon)
        feats["basis_perp_spot"] = self._basis()
        feats["cross_binance_coinbase"] = self._cross("binance_spot", "coinbase")
        feats["cross_binance_kraken"] = self._cross("binance_spot", "kraken")
        feats["cross_binance_bybit"] = self._cross("binance_spot", "bybit")
        feats["funding_binance"] = self.funding.get("binance")
        feats["funding_bybit"] = self.funding.get("bybit")
        feats["funding_okx"] = self.funding.get("okx")
        feats["open_interest"] = self.open_interest
        feats["oi_z"] = None
        feats["fear_greed"] = self.fear_greed
        feats["mempool_fast"] = self.mempool_fast
        feats["liq_5m"] = sum(v for _, v in self.liq_notional_5m) if self.liq_notional_5m else 0.0

        for venue in VENUE_KEYS:
            self.ensure_venue(venue)
            book = self.books.get(venue)
            last = self.last_price.get(venue)
            feats[f"{venue}_last"] = last
            feats[f"{venue}_spread_bps"] = book.spread_bps() if book else None
            feats[f"{venue}_obi1"] = book.imbalance(1) if book else None
            feats[f"{venue}_obi5"] = book.imbalance(5) if book else None
            feats[f"{venue}_obi10"] = book.imbalance(10) if book else None
            wmp = book.weighted_mid() if book else None
            book_mid = book.mid() if book else None
            feats[f"{venue}_wmp_minus_mid"] = (wmp - book_mid) / book_mid if wmp and book_mid else None
            feats[f"{venue}_depth_bid_10bps"] = book.depth_notional("bid", 0.001, book_mid) if book else None
            feats[f"{venue}_depth_ask_10bps"] = book.depth_notional("ask", 0.001, book_mid) if book else None
            feats[f"{venue}_depth_bid_50bps"] = book.depth_notional("bid", 0.005, book_mid) if book else None
            feats[f"{venue}_depth_ask_50bps"] = book.depth_notional("ask", 0.005, book_mid) if book else None
            for window, meter in self.tfi[venue].items():
                den = last or 1.0
                feats[f"{venue}_tfi_{window}"] = meter.current_imbalance / den if den else meter.current_imbalance
            vpin_val = None
            buckets = self.vpin[venue].bucket_imbalances
            if len(buckets) == self.vpin[venue].n:
                vpin_val = sum(buckets) / (self.vpin[venue].n * self.vpin[venue].V)
            feats[f"{venue}_vpin"] = vpin_val
            buy = self.buy_vol.get(venue, 0.0)
            sell = self.sell_vol.get(venue, 0.0)
            tot = buy + sell
            feats[f"{venue}_buy_ratio"] = buy / tot if tot else None
            feats[f"{venue}_trades"] = float(self.trade_count.get(venue, 0))
            intensity = self.intensity.get(venue, deque())
            cutoff = now - 1.0
            feats[f"{venue}_intensity_1s"] = float(sum(1 for t in intensity if t >= cutoff))
            vden = self.vwap_den.get(venue, 0.0)
            vwap = self.vwap_num[venue] / vden if vden else None
            feats[f"{venue}_vwap_dev"] = (last - vwap) / vwap if last and vwap else None

        closes_1m = list(self.klines_1m)
        if mid:
            closes_1m = closes_1m + [mid]
        feats["rsi_1m"] = rsi(closes_1m, 14)
        feats["rsi_5m"] = rsi(list(self.klines_5m), 14)
        feats["rsi_15m"] = rsi(list(self.klines_15m), 14)
        feats["rsi_1h"] = rsi(list(self.klines_1h), 14)
        feats["rsi_4h"] = rsi(list(self.klines_4h), 14)
        feats["bb_pos_1h"] = bollinger_position(list(self.klines_1h), 20)
        feats["bb_pos_4h"] = bollinger_position(list(self.klines_4h), 20)
        feats["ema5_1m"] = ema(closes_1m[-80:], 5) if closes_1m else None
        feats["ema15_1m"] = ema(closes_1m[-80:], 15) if closes_1m else None
        if feats["ema5_1m"] and feats["ema15_1m"]:
            feats["ema_cross_1m"] = (feats["ema5_1m"] - feats["ema15_1m"]) / feats["ema15_1m"]
        else:
            feats["ema_cross_1m"] = None
        feats["vol_z_1m"] = zscore(list(self.volumes_1m), 60) if self.volumes_1m else None

        yes_bid = _f(self.poly.get("yes_bid"))
        yes_ask = _f(self.poly.get("yes_ask"))
        no_bid = _f(self.poly.get("no_bid"))
        no_ask = _f(self.poly.get("no_ask"))
        yes_mid = _mid(yes_bid, yes_ask)
        feats["poly_yes_mid"] = yes_mid
        feats["poly_yes_spread"] = (yes_ask - yes_bid) if yes_ask and yes_bid else None
        feats["poly_no_mid"] = _mid(no_bid, no_ask)
        feats["poly_yes_obi"] = _f(self.poly.get("yes_obi"))
        feats["poly_seconds_left"] = _f(self.poly.get("seconds_left"))
        if feats["poly_seconds_left"] is not None:
            feats["poly_time_frac"] = max(0.0, min(1.0, feats["poly_seconds_left"] / 900.0))
        else:
            feats["poly_time_frac"] = None
        open_px = _f(self.poly.get("btc_open"))
        feats["poly_vs_open"] = (mid - open_px) / open_px if mid and open_px else None
        if yes_mid is not None and feats["poly_vs_open"] is not None:
            feats["poly_edge_vs_spot"] = yes_mid - (1.0 if feats["poly_vs_open"] > 0 else 0.0)
        else:
            feats["poly_edge_vs_spot"] = None
        return feats

    def _return(self, now: float, horizon: int) -> float | None:
        target = now - horizon
        past = None
        for ts, price in self.mid_history:
            if ts <= target:
                past = price
            else:
                break
        current = self.reference_mid()
        if past and current:
            return (current - past) / past
        return None

    def _basis(self) -> float | None:
        spot = self.last_price.get("binance_spot") or (self.books.get("binance_spot").mid() if self.books.get("binance_spot") else None)
        perp = self.last_price.get("binance_futures") or (self.books.get("binance_futures").mid() if self.books.get("binance_futures") else None)
        if spot and perp:
            return (perp - spot) / spot
        return None

    def _cross(self, a: str, b: str) -> float | None:
        pa = self.last_price.get(a) or (self.books[a].mid() if a in self.books else None)
        pb = self.last_price.get(b) or (self.books[b].mid() if b in self.books else None)
        if pa and pb:
            return (pa - pb) / pb
        return None


def _f(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mid(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None:
        return None
    return 0.5 * (bid + ask)


def training_vector(features: dict[str, Any]) -> dict[str, float]:
    """Drop raw price levels; keep returns, ratios, z-scores, probabilities."""
    skip_exact = {"mid", "log_mid"}
    skip_suffixes = ("_last",)
    out: dict[str, float] = {}
    for key, value in features.items():
        if key in skip_exact or key.endswith(skip_suffixes):
            continue
        if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
            continue
        try:
            out[key] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def now_ts() -> float:
    return time.time()
