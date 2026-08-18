from __future__ import annotations

from typing import Any

from pipeline.crypto_util import decrypt_value, dumps, encrypt_value, loads
from pipeline.models import AppSetting

SECRET_KEYS = {
    "polymarket_private_key",
    "polymarket_api_key",
    "polymarket_api_secret",
    "polymarket_api_passphrase",
}

DEFAULTS: dict[str, Any] = {
    "setup_complete": False,
    "bar_interval_seconds": 5,
    "tick_retention_hours": 6,
    "vpin_bucket_btc": 25.0,
    "vpin_window_buckets": 50,
    "tfi_windows_seconds": [15, 60, 180, 300],
    "horizon_seconds": 900,
    "enabled_sources": [
        "binance_spot",
        "binance_futures",
        "coinbase",
        "kraken",
        "bybit",
        "okx",
        "bitstamp",
        "deribit",
        "coincap",
        "polymarket_gamma",
        "polymarket_clob",
        "rest_aux",
    ],
    "dry_run": True,
    "min_edge": 0.04,
    "min_confidence": 0.55,
    "order_size": 10.0,
    "max_orders_per_window": 1,
    "ensemble_mode": "auc_weighted",
    "min_auc": 0.52,
    "polymarket_private_key": "",
    "polymarket_funder": "",
    "polymarket_signature_type": 0,
    "polymarket_api_key": "",
    "polymarket_api_secret": "",
    "polymarket_api_passphrase": "",
    "polymarket_builder_code": "",
    "polymarket_chain_id": 137,
}


def get_setting(key: str, default: Any = None) -> Any:
    row = AppSetting.objects.filter(key=key).first()
    if row is None:
        if default is not None:
            return default
        return DEFAULTS.get(key)
    value = decrypt_value(row.value) if row.is_secret else row.value
    if key in DEFAULTS and not isinstance(DEFAULTS[key], str):
        parsed = loads(value, DEFAULTS[key])
        return parsed
    if value in {"true", "false"} and isinstance(DEFAULTS.get(key), bool):
        return value == "true"
    if isinstance(DEFAULTS.get(key), (int, float)) and value != "":
        try:
            return type(DEFAULTS[key])(value)
        except (TypeError, ValueError):
            return DEFAULTS[key]
    return value


def set_setting(key: str, value: Any, secret: bool | None = None) -> None:
    is_secret = key in SECRET_KEYS if secret is None else secret
    if isinstance(value, (dict, list)):
        raw = dumps(value)
    elif isinstance(value, bool):
        raw = "true" if value else "false"
    else:
        raw = "" if value is None else str(value)
    stored = encrypt_value(raw) if is_secret else raw
    AppSetting.objects.update_or_create(
        key=key,
        defaults={"value": stored, "is_secret": is_secret},
    )


def all_settings_public() -> dict[str, Any]:
    data: dict[str, Any] = dict(DEFAULTS)
    for row in AppSetting.objects.all():
        if row.is_secret:
            plain = decrypt_value(row.value)
            data[row.key] = bool(plain)
            data[f"{row.key}_set"] = bool(plain)
            continue
        data[row.key] = get_setting(row.key)
    data["polymarket_private_key"] = bool(get_setting("polymarket_private_key") or "")
    data["polymarket_private_key_set"] = bool(get_setting("polymarket_private_key") or "")
    data["polymarket_api_key_set"] = bool(get_setting("polymarket_api_key") or "")
    return data


def apply_settings(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = set(DEFAULTS) | SECRET_KEYS
    for key, value in payload.items():
        if key not in allowed:
            continue
        if key.endswith("_set"):
            continue
        if key in SECRET_KEYS and value in (True, False, None, ""):
            continue
        set_setting(key, value)
    return all_settings_public()
