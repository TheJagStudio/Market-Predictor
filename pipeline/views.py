from __future__ import annotations

import sys
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from pipeline.catalog import FREE_SOURCES, MODEL_ARCHES
from pipeline.ingest.backfill import backfill_binance
from pipeline.ingest.engine import training_vector
from pipeline.models import (
    AppLog,
    CollectorSource,
    EnsembleConfig,
    FeatureBar,
    LiveTick,
    ModelArtifact,
    PolyMarketWindow,
    Prediction,
    ProcessHeartbeat,
    TradeOrder,
    TrainingJob,
)
from pipeline.procutil import running_pid, stop_pid, write_pid
from pipeline.store import DEFAULTS, all_settings_public, apply_settings, get_setting, set_setting
from pipeline.trading.markets import btc_15m_slug, current_window_start
from pipeline.trading.orders import maybe_place

import subprocess


def _spawn(command: str, extra: list[str] | None = None) -> int:
    args = [sys.executable, str(settings.BASE_DIR / "manage.py"), command, *(extra or [])]
    proc = subprocess.Popen(
        args,
        cwd=str(settings.BASE_DIR),
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc.pid


def _hb(name: str) -> dict:
    row = ProcessHeartbeat.objects.filter(name=name).first()
    pid = running_pid(name)
    stale = False
    if row and row.heartbeat_at:
        stale = timezone.now() - row.heartbeat_at > timedelta(seconds=20)
    running = bool(pid) and not stale
    return {
        "name": name,
        "running": running,
        "pid": pid or (row.pid if row else None),
        "heartbeat_at": row.heartbeat_at.isoformat() if row and row.heartbeat_at else None,
        "stats": row.stats if row else {},
        "last_error": row.last_error if row else "",
    }


@api_view(["GET"])
def health(request):
    return Response({"ok": True, "app": "btc-15m-pipeline"})


@api_view(["GET"])
def bootstrap(request):
    settings_public = all_settings_public()
    latest_bar = FeatureBar.objects.order_by("-ts").first()
    market = PolyMarketWindow.objects.order_by("-start_ts").first()
    counts = {
        "bars": FeatureBar.objects.count(),
        "labeled": FeatureBar.objects.filter(label_up_15m__isnull=False).count(),
        "ticks": LiveTick.objects.count(),
        "predictions": Prediction.objects.count(),
        "orders": TradeOrder.objects.count(),
        "jobs": TrainingJob.objects.count(),
    }
    sources = []
    db_sources = {s.name: s for s in CollectorSource.objects.all()}
    enabled = set(get_setting("enabled_sources") or [])
    for spec in FREE_SOURCES:
        row = db_sources.get(spec["id"])
        sources.append(
            {
                **spec,
                "enabled": spec["id"] in enabled,
                "status": row.status if row else "idle",
                "message_count": row.message_count if row else 0,
                "last_message_at": row.last_message_at.isoformat() if row and row.last_message_at else None,
                "error": row.error if row else "",
            }
        )
    return Response(
        {
            "setup_complete": bool(settings_public.get("setup_complete")),
            "settings": settings_public,
            "sources_catalog": FREE_SOURCES,
            "sources": sources,
            "architectures": MODEL_ARCHES,
            "collector": _hb("collector"),
            "inference": _hb("inference"),
            "counts": counts,
            "latest_bar": _bar_payload(latest_bar) if latest_bar else None,
            "market": _market_payload(market) if market else {"slug": btc_15m_slug(), "start_ts": current_window_start()},
            "latest_prediction": _pred_payload(Prediction.objects.order_by("-id").first()),
        }
    )


@api_view(["GET", "POST"])
def setup_view(request):
    if request.method == "GET":
        return Response({"settings": all_settings_public(), "defaults": {k: v for k, v in DEFAULTS.items() if k not in {"polymarket_private_key", "polymarket_api_secret", "polymarket_api_passphrase"}}, "sources": FREE_SOURCES})
    data = request.data if isinstance(request.data, dict) else {}
    public = apply_settings(data)
    set_setting("setup_complete", True)
    public["setup_complete"] = True
    return Response({"ok": True, "settings": public})


@api_view(["GET", "POST"])
def settings_view(request):
    if request.method == "GET":
        return Response(all_settings_public())
    return Response(apply_settings(request.data if isinstance(request.data, dict) else {}))


@api_view(["POST"])
def collector_start(request):
    if running_pid("collector"):
        return Response({"ok": True, "already": True, **_hb("collector")})
    pid = _spawn("runcollector")
    write_pid("collector", pid)
    return Response({"ok": True, "pid": pid})


@api_view(["POST"])
def collector_stop(request):
    stop_pid("collector")
    ProcessHeartbeat.objects.filter(name="collector").update(running=False)
    return Response({"ok": True})


@api_view(["POST"])
def inference_start(request):
    if running_pid("inference"):
        return Response({"ok": True, "already": True, **_hb("inference")})
    pid = _spawn("runinference")
    write_pid("inference", pid)
    return Response({"ok": True, "pid": pid})


@api_view(["POST"])
def inference_stop(request):
    stop_pid("inference")
    ProcessHeartbeat.objects.filter(name="inference").update(running=False)
    return Response({"ok": True})


@api_view(["GET"])
def live(request):
    ticks = list(LiveTick.objects.order_by("-ts_ms")[:40])
    bars = list(FeatureBar.objects.order_by("-ts")[:60])
    logs = list(AppLog.objects.order_by("-id")[:30])
    return Response(
        {
            "collector": _hb("collector"),
            "inference": _hb("inference"),
            "ticks": [
                {
                    "ts_ms": t.ts_ms,
                    "venue": t.venue,
                    "price": t.price,
                    "size": t.size,
                    "is_buyer_maker": t.is_buyer_maker,
                }
                for t in ticks
            ],
            "bars": [_bar_payload(b) for b in bars],
            "logs": [
                {"id": l.id, "created_at": l.created_at.isoformat(), "level": l.level, "source": l.source, "message": l.message}
                for l in logs
            ],
        }
    )


@api_view(["POST"])
def backfill(request):
    days = int((request.data or {}).get("days") or 7)
    interval = str((request.data or {}).get("interval") or "1m")
    result = backfill_binance(days=days, interval=interval)
    return Response({"ok": True, **result})


@api_view(["GET"])
def architectures(request):
    return Response({"architectures": MODEL_ARCHES})


@api_view(["GET", "POST"])
def train_view(request):
    if request.method == "GET":
        jobs = TrainingJob.objects.order_by("-id")[:20]
        return Response({"jobs": [_job_payload(j) for j in jobs]})
    data = request.data if isinstance(request.data, dict) else {}
    arches = data.get("architectures") or [a["id"] for a in MODEL_ARCHES]
    job = TrainingJob.objects.create(
        status="pending",
        config={
            "architectures": arches,
            "min_rows": int(data.get("min_rows") or 200),
            "folds": int(data.get("folds") or 5),
            "interval_seconds": data.get("interval_seconds"),
            "min_auc": float(data.get("min_auc") or get_setting("min_auc") or 0.52),
        },
    )
    pid = _spawn("trainjob", [str(job.id)])
    return Response({"ok": True, "job": _job_payload(job), "pid": pid})


@api_view(["GET"])
def train_detail(request, job_id: int):
    job = TrainingJob.objects.filter(pk=job_id).first()
    if not job:
        return Response({"error": "not found"}, status=404)
    artifacts = list(job.artifacts.all())
    return Response({"job": _job_payload(job), "artifacts": [_artifact_payload(a) for a in artifacts]})


@api_view(["GET", "POST"])
def ensemble_view(request):
    from pipeline.ml.ensemble import describe

    cfg, _ = EnsembleConfig.objects.get_or_create(id=1, defaults={"mode": "auc_weighted"})
    if request.method == "POST":
        data = request.data or {}
        if data.get("mode"):
            cfg.mode = str(data["mode"])
        if data.get("min_auc") is not None:
            cfg.min_auc = float(data["min_auc"])
        if data.get("active_job_id"):
            cfg.active_job_id = int(data["active_job_id"])
        cfg.save()
        selected = data.get("selected_ids")
        if isinstance(selected, list) and cfg.active_job_id:
            ModelArtifact.objects.filter(job_id=cfg.active_job_id).update(selected=False)
            ModelArtifact.objects.filter(job_id=cfg.active_job_id, id__in=selected).update(selected=True)
            for art in ModelArtifact.objects.filter(job_id=cfg.active_job_id):
                art.weight = max(float(art.metrics.get("roc_auc") or 0.5) - 0.5, 0.0) if art.selected else 0.0
                art.save(update_fields=["weight"])
    return Response(describe())


@api_view(["GET", "POST"])
def predict_view(request):
    from pipeline.ml.infer import predict_latest

    if request.method == "GET":
        rows = Prediction.objects.order_by("-id")[:50]
        return Response({"predictions": [_pred_payload(p) for p in rows]})
    pred = predict_latest()
    if not pred:
        return Response({"error": "Need a trained model and at least one feature bar."}, status=400)
    order = None
    if (request.data or {}).get("place"):
        order = maybe_place(pred)
    return Response({"prediction": pred, "order": _order_payload(order) if order else None})


@api_view(["GET"])
def orders_view(request):
    rows = TradeOrder.objects.order_by("-id")[:50]
    return Response({"orders": [_order_payload(o) for o in rows]})


@api_view(["GET"])
def market_view(request):
    market = PolyMarketWindow.objects.order_by("-start_ts").first()
    return Response(_market_payload(market) if market else {"slug": btc_15m_slug(), "start_ts": current_window_start()})


def _bar_payload(bar: FeatureBar | None) -> dict | None:
    if not bar:
        return None
    feats = bar.features or {}
    return {
        "ts": bar.ts,
        "interval_seconds": bar.interval_seconds,
        "mid_price": bar.mid_price,
        "label_up_15m": bar.label_up_15m,
        "features": feats,
        "train_features": training_vector(feats),
        "n_features": len(training_vector(feats)),
    }


def _market_payload(market: PolyMarketWindow | None) -> dict | None:
    if not market:
        return None
    yes_mid = None
    if market.yes_bid is not None and market.yes_ask is not None:
        yes_mid = 0.5 * (market.yes_bid + market.yes_ask)
    return {
        "slug": market.slug,
        "question": market.question,
        "condition_id": market.condition_id,
        "token_up": market.token_up,
        "token_down": market.token_down,
        "start_ts": market.start_ts,
        "end_ts": market.end_ts,
        "yes_bid": market.yes_bid,
        "yes_ask": market.yes_ask,
        "no_bid": market.no_bid,
        "no_ask": market.no_ask,
        "yes_mid": yes_mid,
        "btc_open": market.btc_open,
        "btc_last": market.btc_last,
        "resolved_up": market.resolved_up,
        "seconds_left": max(0, market.end_ts - int(timezone.now().timestamp())),
    }


def _pred_payload(pred: Prediction | None) -> dict | None:
    if not pred:
        return None
    return {
        "id": pred.id,
        "ts": pred.ts,
        "p_up": pred.p_up,
        "per_model": pred.per_model,
        "implied_yes": pred.implied_yes,
        "edge": pred.edge,
        "action": pred.action,
        "market_slug": pred.market_slug,
    }


def _order_payload(order: TradeOrder | None) -> dict | None:
    if not order:
        return None
    return {
        "id": order.id,
        "created_at": order.created_at.isoformat(),
        "dry_run": order.dry_run,
        "market_slug": order.market_slug,
        "outcome": order.outcome,
        "price": order.price,
        "size": order.size,
        "status": order.status,
        "response": order.response,
    }


def _job_payload(job: TrainingJob) -> dict:
    return {
        "id": job.id,
        "status": job.status,
        "config": job.config,
        "summary": job.summary,
        "error": job.error,
        "created_at": job.created_at.isoformat(),
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "models": (job.summary or {}).get("models") if job.summary else [],
    }


def _artifact_payload(art: ModelArtifact) -> dict:
    return {
        "id": art.id,
        "name": art.name,
        "path": art.path,
        "metrics": art.metrics,
        "selected": art.selected,
        "weight": art.weight,
    }
