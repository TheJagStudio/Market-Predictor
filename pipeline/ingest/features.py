"""Pure-Python microstructure metrics (no Django). Used by the live engine and tests."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


class RealTimeTradeImbalance:
    """Rolling signed trade flow imbalance over a time window (seconds)."""

    def __init__(self, window_seconds: float = 60.0) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.window_seconds = float(window_seconds)
        self.trades: deque[tuple[float, float]] = deque()
        self.current_imbalance = 0.0

    def process_tick(self, size: float, is_buyer_maker: bool, now: float) -> float:
        if size < 0:
            raise ValueError("size must be non-negative")
        trade_flow = -size if is_buyer_maker else size
        self.trades.append((now, trade_flow))
        self.current_imbalance += trade_flow
        cutoff = now - self.window_seconds
        while self.trades and self.trades[0][0] < cutoff:
            _old_time, old_flow = self.trades.popleft()
            self.current_imbalance -= old_flow
        return self.current_imbalance


class RealTimeVPIN:
    """Volume-synchronized probability of informed trading (Easley et al.)."""

    def __init__(self, bucket_volume: float = 25.0, window_size: int = 50) -> None:
        if bucket_volume <= 0:
            raise ValueError("bucket_volume must be positive")
        if window_size <= 0:
            raise ValueError("window_size must be positive")
        self.V = float(bucket_volume)
        self.n = int(window_size)
        self.current_buy_vol = 0.0
        self.current_sell_vol = 0.0
        self.bucket_imbalances: deque[float] = deque(maxlen=self.n)

    def process_tick(self, size: float, is_buyer_maker: bool) -> float | None:
        if size < 0:
            raise ValueError("size must be non-negative")
        remaining = float(size)
        last: float | None = None
        while remaining > 1e-12:
            filled = self.current_buy_vol + self.current_sell_vol
            space = self.V - filled
            take = remaining if remaining < space else space
            if is_buyer_maker:
                self.current_sell_vol += take
            else:
                self.current_buy_vol += take
            remaining -= take
            if self.current_buy_vol + self.current_sell_vol >= self.V - 1e-9:
                imbalance = abs(self.current_buy_vol - self.current_sell_vol)
                self.bucket_imbalances.append(imbalance)
                self.current_buy_vol = 0.0
                self.current_sell_vol = 0.0
                if len(self.bucket_imbalances) == self.n:
                    last = sum(self.bucket_imbalances) / (self.n * self.V)
        return last


@dataclass
class OrderBook:
    bids: dict[float, float] = field(default_factory=dict)
    asks: dict[float, float] = field(default_factory=dict)

    def apply_snapshot(self, bids: list, asks: list) -> None:
        self.bids = {}
        self.asks = {}
        for row in bids:
            price, size = _level(row)
            if size > 0:
                self.bids[price] = size
        for row in asks:
            price, size = _level(row)
            if size > 0:
                self.asks[price] = size

    def apply_delta(self, side: str, price: float, size: float) -> None:
        book = self.bids if side in {"bid", "buy", "bids"} else self.asks
        if size <= 0:
            book.pop(float(price), None)
        else:
            book[float(price)] = float(size)

    def best_bid(self) -> float | None:
        return max(self.bids) if self.bids else None

    def best_ask(self) -> float | None:
        return min(self.asks) if self.asks else None

    def mid(self) -> float | None:
        bid = self.best_bid()
        ask = self.best_ask()
        if bid is None or ask is None:
            return None
        return 0.5 * (bid + ask)

    def spread_bps(self) -> float | None:
        bid = self.best_bid()
        ask = self.best_ask()
        mid = self.mid()
        if bid is None or ask is None or not mid:
            return None
        return (ask - bid) / mid * 10_000.0

    def imbalance(self, levels: int = 5) -> float | None:
        bid_vol = sum(size for _, size in sorted(self.bids.items(), reverse=True)[:levels])
        ask_vol = sum(size for _, size in sorted(self.asks.items())[:levels])
        total = bid_vol + ask_vol
        if total <= 0:
            return None
        return (bid_vol - ask_vol) / total

    def weighted_mid(self) -> float | None:
        bid = self.best_bid()
        ask = self.best_ask()
        if bid is None or ask is None:
            return None
        bid_sz = self.bids.get(bid, 0.0)
        ask_sz = self.asks.get(ask, 0.0)
        denom = bid_sz + ask_sz
        if denom <= 0:
            return 0.5 * (bid + ask)
        return (ask * bid_sz + bid * ask_sz) / denom

    def depth_notional(self, side: str, pct: float, mid: float | None = None) -> float:
        ref = mid or self.mid()
        if not ref:
            return 0.0
        total = 0.0
        if side == "bid":
            lo = ref * (1.0 - pct)
            for price, size in self.bids.items():
                if price >= lo:
                    total += price * size
        else:
            hi = ref * (1.0 + pct)
            for price, size in self.asks.items():
                if price <= hi:
                    total += price * size
        return total


def _level(row: object) -> tuple[float, float]:
    if isinstance(row, dict):
        price = float(row.get("price") or row.get("px") or 0)
        size = float(row.get("size") or row.get("qty") or row.get("sz") or 0)
        return price, size
    if isinstance(row, (list, tuple)) and len(row) >= 2:
        return float(row[0]), float(row[1])
    raise ValueError("invalid book level")


def ema(values: list[float], span: int) -> float | None:
    if not values or span <= 0:
        return None
    alpha = 2.0 / (span + 1.0)
    acc = values[0]
    for value in values[1:]:
        acc = alpha * value + (1.0 - alpha) * acc
    return acc


def rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    window = closes[-(period + 1) :]
    for i in range(1, len(window)):
        delta = window[i] - window[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def bollinger_position(closes: list[float], period: int = 20, k: float = 2.0) -> float | None:
    if len(closes) < period:
        return None
    window = closes[-period:]
    mean = sum(window) / period
    var = sum((x - mean) ** 2 for x in window) / period
    std = var ** 0.5
    if std == 0:
        return 0.5
    lower = mean - k * std
    upper = mean + k * std
    width = upper - lower
    if width == 0:
        return 0.5
    pos = (closes[-1] - lower) / width
    return max(0.0, min(1.0, pos))


def zscore(values: list[float], period: int = 100) -> float | None:
    if len(values) < 5:
        return None
    window = values[-period:]
    mean = sum(window) / len(window)
    var = sum((x - mean) ** 2 for x in window) / len(window)
    std = var ** 0.5
    if std == 0:
        return 0.0
    return (values[-1] - mean) / std
