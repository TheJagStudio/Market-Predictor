from __future__ import annotations

import logging
import time
from functools import lru_cache
from typing import Any

import joblib
import numpy as np

from pipeline.ingest.engine import training_vector
from pipeline.ml.catalog import predict_proba_up
from pipeline.ml.ensemble import active_artifacts, combine
from pipeline.models import EnsembleConfig, FeatureBar, ModelArtifact, Prediction
from pipeline.store import get_setting
from pipeline.trading.markets import btc_15m_slug
from pipeline.universe import normalize_assets

logger = logging.getLogger(__name__)


@lru_cache(maxsize=32)
def _load(path: str) -> dict[str, Any]:
    return joblib.load(path)


def clear_model_cache() -> None:
    _load.cache_clear()


def vectorize(features: dict[str, Any], columns: list[str]) -> np.ndarray:
    vec = training_vector(features)
    row = np.zeros((1, len(columns)), dtype=float)
    for i, col in enumerate(columns):
        value = vec.get(col)
        row[0, i] = float(value) if value is not None else 0.0
    return row


def predict_latest() -> dict[str, Any] | None:
    cfg = EnsembleConfig.objects.order_by("id").first()
    job = cfg.active_job if cfg else None
    job_cfg = (job.config if job else None) or {}
    interval = job_cfg.get("interval_seconds")
    assets = job_cfg.get("assets")
    qs = FeatureBar.objects.all()
    if interval:
        qs = qs.filter(interval_seconds=int(interval))
    if assets:
        normalized = normalize_assets(assets)
        if len(normalized) == 1:
            qs = qs.filter(asset=normalized[0])
        else:
            qs = qs.filter(asset="BTC")
    else:
        qs = qs.filter(asset="BTC")
    bar = qs.order_by("-ts").first()
    if bar is None:
        bar = FeatureBar.objects.filter(asset="BTC").order_by("-ts").first() or FeatureBar.objects.order_by("-ts").first()
    if bar is None:
        return None
    artifacts = active_artifacts()
    if not artifacts:
        return None
    per_model: dict[str, float] = {}
    for art in artifacts:
        try:
            payload = _load(art.path)
            X = vectorize(bar.features or {}, payload["columns"])
            p = predict_proba_up(payload["model"], X)[0]
            per_model[art.name] = float(p)
        except Exception as exc:
            logger.warning("infer %s: %s", art.name, exc)
    if not per_model:
        return None
    cfg = EnsembleConfig.objects.order_by("id").first()
    mode = (cfg.mode if cfg else None) or get_setting("ensemble_mode") or "auc_weighted"
    p_up = combine(per_model, artifacts, mode=str(mode))
    yes_bid = None
    yes_ask = None
    implied = None
    from pipeline.models import PolyMarketWindow

    market = PolyMarketWindow.objects.order_by("-start_ts").first()
    slug = market.slug if market else btc_15m_slug()
    if market and market.yes_bid is not None and market.yes_ask is not None:
        yes_bid, yes_ask = market.yes_bid, market.yes_ask
        implied = 0.5 * (yes_bid + yes_ask)
    min_edge = float(get_setting("min_edge") or 0.04)
    min_conf = float(get_setting("min_confidence") or 0.55)
    action = "hold"
    edge = None
    if implied is not None:
        up_edge = p_up - implied
        down_edge = (1.0 - p_up) - (1.0 - implied)
        if p_up >= min_conf and up_edge >= min_edge:
            action = "buy_up"
            edge = up_edge
        elif (1.0 - p_up) >= min_conf and down_edge >= min_edge:
            action = "buy_down"
            edge = down_edge
        else:
            edge = up_edge
    elif p_up >= min_conf:
        action = "buy_up"
        edge = p_up - 0.5
    elif (1.0 - p_up) >= min_conf:
        action = "buy_down"
        edge = (1.0 - p_up) - 0.5
    pred = Prediction.objects.create(
        ts=int(time.time()),
        bar=bar,
        market_slug=slug,
        p_up=p_up,
        per_model=per_model,
        implied_yes=implied,
        edge=edge,
        action=action,
    )
    return {
        "id": pred.id,
        "ts": pred.ts,
        "p_up": p_up,
        "per_model": per_model,
        "implied_yes": implied,
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "edge": edge,
        "action": action,
        "market_slug": slug,
        "bar_ts": bar.ts,
        "mid": bar.mid_price,
    }
