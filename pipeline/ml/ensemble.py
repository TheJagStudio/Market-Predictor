from __future__ import annotations

from typing import Any

from pipeline.models import EnsembleConfig, ModelArtifact, TrainingJob


def active_artifacts() -> list[ModelArtifact]:
    cfg = EnsembleConfig.objects.order_by("id").first()
    job: TrainingJob | None = cfg.active_job if cfg else None
    if job is None:
        job = TrainingJob.objects.filter(status="completed").order_by("-id").first()
    if job is None:
        return []
    qs = list(ModelArtifact.objects.filter(job=job))
    selected = [row for row in qs if row.selected]
    if selected:
        return selected
    return [row for row in qs if "error" not in (row.metrics or {})]


def combine(per_model: dict[str, float], artifacts: list[ModelArtifact], mode: str = "auc_weighted") -> float:
    if not per_model:
        return 0.5
    if mode == "equal":
        return sum(per_model.values()) / len(per_model)
    if mode == "best":
        best = max(artifacts, key=lambda a: float(a.metrics.get("roc_auc") or 0), default=None)
        if best and best.name in per_model:
            return per_model[best.name]
        return next(iter(per_model.values()))
    weights = {a.name: max(float(a.weight or 0), 0.0) for a in artifacts if a.name in per_model}
    if not any(weights.values()):
        return sum(per_model.values()) / len(per_model)
    num = sum(per_model[name] * w for name, w in weights.items())
    den = sum(weights.values())
    return num / den if den else 0.5


def describe() -> dict[str, Any]:
    cfg = EnsembleConfig.objects.order_by("id").first()
    arts = active_artifacts()
    return {
        "mode": cfg.mode if cfg else "auc_weighted",
        "min_auc": cfg.min_auc if cfg else 0.52,
        "active_job_id": cfg.active_job_id if cfg else None,
        "members": [
            {
                "id": a.id,
                "name": a.name,
                "selected": a.selected,
                "weight": a.weight,
                "metrics": {k: a.metrics.get(k) for k in ("accuracy", "roc_auc", "f1", "precision", "recall", "brier")},
            }
            for a in arts
        ],
    }
