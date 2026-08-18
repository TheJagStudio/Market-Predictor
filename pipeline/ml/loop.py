from __future__ import annotations

import logging
import os
import time

from django.utils import timezone as dj_tz

from pipeline.ml.infer import clear_model_cache, predict_latest
from pipeline.models import ProcessHeartbeat
from pipeline.procutil import write_pid
from pipeline.trading.orders import maybe_place

logger = logging.getLogger(__name__)


def run_inference_loop(interval: float = 5.0) -> None:
    write_pid("inference", os.getpid())
    clear_model_cache()
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            pred = predict_latest()
            order = None
            if pred:
                order = maybe_place(pred)
            _heartbeat(
                {
                    "last_p_up": pred.get("p_up") if pred else None,
                    "action": pred.get("action") if pred else "hold",
                    "order_id": order.id if order else None,
                    "slug": pred.get("market_slug") if pred else None,
                }
            )
        except Exception as exc:
            logger.exception("inference loop")
            _heartbeat_error(str(exc))
        time.sleep(interval)


def _heartbeat(stats: dict) -> None:
    row, created = ProcessHeartbeat.objects.get_or_create(name="inference")
    now = dj_tz.now()
    row.pid = os.getpid()
    row.running = True
    row.heartbeat_at = now
    if created or not row.started_at:
        row.started_at = now
    row.stats = stats
    row.last_error = ""
    row.save()


def _heartbeat_error(message: str) -> None:
    row, _ = ProcessHeartbeat.objects.get_or_create(name="inference")
    row.last_error = message[:500]
    row.heartbeat_at = dj_tz.now()
    row.save(update_fields=["last_error", "heartbeat_at"])
