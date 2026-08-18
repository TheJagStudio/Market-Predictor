from __future__ import annotations

import json
import math
import time
import urllib.parse
import urllib.request
from typing import Any

from pipeline.ingest.features import bollinger_position, ema, rsi, zscore
from pipeline.models import FeatureBar
from pipeline.universe import (
    TIMEFRAMES,
    configured_assets,
    configured_kline_intervals,
    normalize_assets,
    normalize_timeframes,
    venue_symbol,
)


def fetch_klines(symbol: str = "BTCUSDT", interval: str = "1m", limit: int = 1000, end_ts_ms: int | None = None) -> list[list]:
    params: dict[str, Any] = {"symbol": symbol, "interval": interval, "limit": limit}
    if end_ts_ms:
        params["endTime"] = end_ts_ms
    url = "https://api.binance.com/api/v3/klines?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def backfill_binance(
    days: int = 7,
    interval: str | None = None,
    intervals: list[str] | None = None,
    assets: list[str] | None = None,
) -> dict[str, Any]:
    coins = normalize_assets(assets) if assets else configured_assets()
    if intervals:
        tfs = normalize_timeframes(intervals)
    elif interval and interval not in {"all", "*"}:
        tfs = normalize_timeframes([interval])
    else:
        tfs = configured_kline_intervals()
    per: list[dict[str, Any]] = []
    totals = {"fetched": 0, "created": 0, "updated": 0}
    for asset in coins:
        symbol = venue_symbol(asset, "binance")
        if not symbol:
            continue
        for tf in tfs:
            result = _backfill_symbol(asset, symbol, tf, days)
            per.append({"asset": asset, "interval": tf, **result})
            for key in totals:
                totals[key] += int(result.get(key) or 0)
    return {
        **totals,
        "assets": coins,
        "intervals": tfs,
        "per": per,
    }


def _backfill_symbol(asset: str, symbol: str, interval: str, days: int) -> dict[str, int]:
    interval_sec = TIMEFRAMES.get(interval, 60)
    target_rows = max(int(days * 24 * 3600 / interval_sec), 100)
    rows: list[list] = []
    end_ts = None
    while len(rows) < target_rows:
        batch = fetch_klines(symbol=symbol, interval=interval, limit=1000, end_ts_ms=end_ts)
        if not batch:
            break
        rows = batch + rows
        end_ts = int(batch[0][0]) - 1
        if len(batch) < 1000:
            break
        time.sleep(0.2)
    closes = [float(r[4]) for r in rows]
    volumes = [float(r[5]) for r in rows]
    created = 0
    updated = 0
    objects: list[FeatureBar] = []
    for i, row in enumerate(rows):
        ts = int(row[0]) // 1000
        close = closes[i]
        hist_c = closes[: i + 1]
        hist_v = volumes[: i + 1]
        step_60 = max(1, 60 // interval_sec)
        step_300 = max(1, 300 // interval_sec)
        step_900 = max(1, 900 // interval_sec)
        ret = lambda n: (close - closes[i - n]) / closes[i - n] if i >= n and closes[i - n] else None
        feats: dict[str, Any] = {
            "mid": close,
            "source": "binance_klines",
            "asset": asset,
            "ret_60s": ret(step_60),
            "ret_300s": ret(step_300),
            "ret_900s": ret(step_900),
            "rsi_1m": rsi(hist_c[-50:], 14),
            "ema_cross_1m": None,
            "bb_pos_1h": bollinger_position(hist_c, 20),
            "vol_z_1m": zscore(hist_v, 60),
            "log_return": math.log(close / closes[i - 1]) if i else None,
        }
        e5 = ema(hist_c[-80:], 5)
        e15 = ema(hist_c[-80:], 15)
        if e5 and e15:
            feats["ema_cross_1m"] = (e5 - e15) / e15
            feats["ema5_1m"] = e5
            feats["ema15_1m"] = e15
        horizon_bars = max(1, 900 // interval_sec)
        label_15m = None
        if i + horizon_bars < len(closes):
            label_15m = closes[i + horizon_bars] > close
        label_next = None
        if i + 1 < len(closes):
            label_next = closes[i + 1] > close
        objects.append(
            FeatureBar(
                asset=asset,
                ts=ts,
                interval_seconds=interval_sec,
                mid_price=close,
                features=feats,
                label_up_15m=label_15m,
                label_up_next=label_next,
            )
        )
        if len(objects) >= 500:
            c, u = _upsert_bars(objects)
            created += c
            updated += u
            objects = []
    if objects:
        c, u = _upsert_bars(objects)
        created += c
        updated += u
    return {
        "fetched": len(rows),
        "created": created,
        "updated": updated,
        "interval_seconds": interval_sec,
    }


def _upsert_bars(rows: list[FeatureBar]) -> tuple[int, int]:
    created = 0
    updated = 0
    for bar in rows:
        defaults = {
            "mid_price": bar.mid_price,
            "features": bar.features,
            "label_up_15m": bar.label_up_15m,
            "label_up_next": bar.label_up_next,
        }
        _, was_created = FeatureBar.objects.update_or_create(
            asset=bar.asset,
            ts=bar.ts,
            interval_seconds=bar.interval_seconds,
            defaults=defaults,
        )
        if was_created:
            created += 1
        else:
            updated += 1
    return created, updated
