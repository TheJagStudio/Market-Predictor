from __future__ import annotations

import json
import math
import time
import urllib.parse
import urllib.request
from typing import Any

from pipeline.ingest.features import bollinger_position, ema, rsi, zscore
from pipeline.models import FeatureBar


def fetch_klines(symbol: str = "BTCUSDT", interval: str = "1m", limit: int = 1000, end_ts_ms: int | None = None) -> list[list]:
    params: dict[str, Any] = {"symbol": symbol, "interval": interval, "limit": limit}
    if end_ts_ms:
        params["endTime"] = end_ts_ms
    url = "https://api.binance.com/api/v3/klines?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def backfill_binance(days: int = 7, interval: str = "1m") -> dict[str, int]:
    interval_sec = {"1m": 60, "5m": 300, "15m": 900}.get(interval, 60)
    target_rows = max(int(days * 24 * 3600 / interval_sec), 100)
    rows: list[list] = []
    end_ts = None
    while len(rows) < target_rows:
        batch = fetch_klines(interval=interval, limit=1000, end_ts_ms=end_ts)
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
        ret = lambda n: (close - closes[i - n]) / closes[i - n] if i >= n and closes[i - n] else None
        feats: dict[str, Any] = {
            "mid": close,
            "source": "binance_klines",
            "ret_60s": ret(1) if interval_sec == 60 else ret(max(1, 60 // interval_sec)),
            "ret_300s": ret(max(1, 300 // interval_sec)),
            "ret_900s": ret(max(1, 900 // interval_sec)),
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
        horizon = 900 // interval_sec
        label = None
        if i + horizon < len(closes):
            label = closes[i + horizon] > close
        objects.append(
            FeatureBar(
                ts=ts,
                interval_seconds=interval_sec,
                mid_price=close,
                features=feats,
                label_up_15m=label,
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
    return {"fetched": len(rows), "created": created, "updated": updated, "interval_seconds": interval_sec}


def _upsert_bars(rows: list[FeatureBar]) -> tuple[int, int]:
    created = 0
    updated = 0
    for bar in rows:
        _, was_created = FeatureBar.objects.update_or_create(
            ts=bar.ts,
            interval_seconds=bar.interval_seconds,
            defaults={
                "mid_price": bar.mid_price,
                "features": bar.features,
                "label_up_15m": bar.label_up_15m,
            },
        )
        if was_created:
            created += 1
        else:
            updated += 1
    return created, updated
