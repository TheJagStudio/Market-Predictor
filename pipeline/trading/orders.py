from __future__ import annotations

import logging
from typing import Any

from pipeline.models import Prediction, TradeOrder
from pipeline.store import get_setting
from pipeline.trading.markets import current_window_start

logger = logging.getLogger(__name__)


def maybe_place(prediction: dict[str, Any]) -> TradeOrder | None:
    action = prediction.get("action")
    if action not in {"buy_up", "buy_down"}:
        return None
    slug = prediction.get("market_slug") or ""
    max_orders = int(get_setting("max_orders_per_window") or 1)
    existing = TradeOrder.objects.filter(market_slug=slug).count()
    if existing >= max_orders:
        return None
    dry_run = bool(get_setting("dry_run"))
    size = float(get_setting("order_size") or 10)
    outcome = "Up" if action == "buy_up" else "Down"
    from pipeline.models import PolyMarketWindow

    market = PolyMarketWindow.objects.filter(slug=slug).first()
    token_id = ""
    price = 0.5
    if market:
        token_id = market.token_up if outcome == "Up" else market.token_down
        if outcome == "Up" and market.yes_ask:
            price = float(market.yes_ask)
        elif outcome == "Down" and market.no_ask:
            price = float(market.no_ask)
        elif prediction.get("implied_yes"):
            implied = float(prediction["implied_yes"])
            price = implied if outcome == "Up" else 1.0 - implied
    price = min(0.99, max(0.01, round(price, 2)))
    order = TradeOrder(
        dry_run=dry_run,
        market_slug=slug,
        token_id=token_id,
        outcome=outcome,
        side="BUY",
        price=price,
        size=size,
        status="dry_run" if dry_run else "submitting",
        response={"prediction": prediction, "window_start": current_window_start()},
        prediction_id=prediction.get("id"),
    )
    if dry_run:
        order.status = "dry_run"
        order.response["note"] = "Dry-run enabled. No order was sent to Polymarket."
        order.save()
        return order
    try:
        resp = _submit(token_id, price, size)
        order.status = "submitted"
        order.response["clob"] = resp
    except Exception as exc:
        order.status = "error"
        order.response["error"] = str(exc)
        logger.exception("polymarket order failed")
    order.save()
    return order


def _submit(token_id: str, price: float, size: float) -> dict[str, Any]:
    if not token_id:
        raise ValueError("Missing CLOB token id for this market")
    pk = str(get_setting("polymarket_private_key") or "")
    if not pk:
        raise ValueError("Set a Polymarket private key in Setup before live trading")
    try:
        from py_clob_client_v2 import (
            ApiCreds,
            ClobClient,
            OrderArgs,
            OrderType,
            PartialCreateOrderOptions,
            Side,
        )
    except ImportError as exc:
        raise RuntimeError("py-clob-client-v2 is not installed") from exc

    host = "https://clob.polymarket.com"
    chain_id = int(get_setting("polymarket_chain_id") or 137)
    funder = str(get_setting("polymarket_funder") or "") or None
    signature_type = int(get_setting("polymarket_signature_type") or 0)
    kwargs: dict[str, Any] = {"host": host, "chain_id": chain_id, "key": pk, "signature_type": signature_type}
    if funder:
        kwargs["funder"] = funder
    client = ClobClient(**kwargs)
    api_key = str(get_setting("polymarket_api_key") or "")
    api_secret = str(get_setting("polymarket_api_secret") or "")
    api_pass = str(get_setting("polymarket_api_passphrase") or "")
    if api_key and api_secret and api_pass:
        client.set_api_creds(ApiCreds(api_key=api_key, api_secret=api_secret, api_passphrase=api_pass))
    else:
        creds = client.create_or_derive_api_key()
        client.set_api_creds(creds)
    builder = str(get_setting("polymarket_builder_code") or "") or None
    order_kwargs: dict[str, Any] = {
        "token_id": token_id,
        "price": price,
        "side": Side.BUY,
        "size": size,
    }
    if builder:
        order_kwargs["builder_code"] = builder
    resp = client.create_and_post_order(
        order_args=OrderArgs(**order_kwargs),
        options=PartialCreateOrderOptions(tick_size="0.01"),
        order_type=OrderType.GTC,
    )
    if hasattr(resp, "model_dump"):
        return resp.model_dump()
    if isinstance(resp, dict):
        return resp
    return {"raw": str(resp)}
