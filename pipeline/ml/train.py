from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from django.conf import settings
from django.utils import timezone
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)

from pipeline.ml.catalog import build_estimators, predict_proba_up
from pipeline.ml.dataset import load_dataset, time_splits
from pipeline.models import EnsembleConfig, ModelArtifact, TrainingJob


def run_training_job(job_id: int) -> None:
    job = TrainingJob.objects.get(pk=job_id)
    job.status = "running"
    job.save(update_fields=["status"])
    try:
        summary = train(job)
        job.status = "completed"
        job.summary = summary
        job.finished_at = timezone.now()
        job.error = ""
        job.save()
        _activate_ensemble(job)
    except Exception as exc:
        job.status = "failed"
        job.error = str(exc)
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error", "finished_at"])
        raise


def train(job: TrainingJob) -> dict[str, Any]:
    cfg = job.config or {}
    names: list[str] = cfg.get("architectures") or list(build_estimators())
    min_rows = int(cfg.get("min_rows") or 200)
    folds = int(cfg.get("folds") or 5)
    interval = cfg.get("interval_seconds")
    assets = cfg.get("assets")
    label = cfg.get("label")
    label_field = cfg.get("label_field")
    X, y, columns, timestamps = load_dataset(
        min_rows=min_rows,
        interval=interval,
        assets=assets,
        label=label,
        label_field=label_field,
    )
    splits = time_splits(len(y), folds=folds)
    factories = build_estimators()
    artifacts_dir: Path = Path(settings.ARTIFACTS_DIR) / f"job-{job.id}"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    for name in names:
        factory = factories.get(name)
        if factory is None:
            results.append({"name": name, "error": "unknown architecture"})
            continue
        fold_metrics: list[dict[str, float]] = []
        last_model = None
        try:
            for train_idx, test_idx in splits:
                model = factory()
                model.fit(X[train_idx], y[train_idx])
                last_model = model
                p = np.array(predict_proba_up(model, X[test_idx]))
                pred = (p >= 0.5).astype(int)
                yt = y[test_idx]
                fold_metrics.append(_metrics(yt, pred, p))
            if last_model is None:
                raise ValueError("no splits")
            last_model.fit(X, y)
            path = artifacts_dir / f"{name}.joblib"
            joblib.dump({"model": last_model, "columns": columns, "name": name}, path)
            avg = _avg(fold_metrics)
            selected = avg.get("roc_auc", 0) >= float(cfg.get("min_auc") or 0.52)
            weight = max(avg.get("roc_auc", 0.5) - 0.5, 0.0)
            ModelArtifact.objects.create(
                job=job,
                name=name,
                family=name.split("_")[0],
                path=str(path),
                metrics={**avg, "folds": fold_metrics, "n": int(len(y)), "features": len(columns)},
                selected=selected,
                weight=weight,
            )
            results.append({"name": name, **avg, "selected": selected, "weight": weight})
        except Exception as exc:
            results.append({"name": name, "error": str(exc)})

    ranked = sorted([r for r in results if "roc_auc" in r], key=lambda r: r["roc_auc"], reverse=True)
    return {
        "rows": int(len(y)),
        "features": columns,
        "n_features": len(columns),
        "label_field": cfg.get("label_field") or ("label_up_next" if cfg.get("label") == "next" else "label_up_15m"),
        "interval_seconds": interval,
        "assets": assets,
        "span": {"start": timestamps[0], "end": timestamps[-1]} if timestamps else {},
        "models": results,
        "best": ranked[0] if ranked else None,
        "trained_at": int(time.time()),
    }


def _metrics(y_true, y_pred, proba) -> dict[str, float]:
    out = {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
    }
    try:
        out["roc_auc"] = float(roc_auc_score(y_true, proba))
    except ValueError:
        out["roc_auc"] = 0.5
    try:
        p = np.clip(proba, 1e-6, 1 - 1e-6)
        out["log_loss"] = float(log_loss(y_true, p))
        out["brier"] = float(brier_score_loss(y_true, p))
    except Exception:
        out["log_loss"] = 0.0
        out["brier"] = 0.0
    return out


def _avg(rows: list[dict[str, float]]) -> dict[str, float]:
    if not rows:
        return {}
    keys = rows[0].keys()
    return {k: float(sum(r[k] for r in rows) / len(rows)) for k in keys}


def _activate_ensemble(job: TrainingJob) -> None:
    cfg, _ = EnsembleConfig.objects.get_or_create(id=1, defaults={"mode": "auc_weighted"})
    cfg.active_job = job
    cfg.save(update_fields=["active_job", "updated_at"])
