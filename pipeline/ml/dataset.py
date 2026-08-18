from __future__ import annotations

import math
from typing import Any

import numpy as np
from django.conf import settings

from pipeline.ingest.engine import training_vector
from pipeline.models import FeatureBar


def load_dataset(min_rows: int = 200, interval: int | None = None) -> tuple[np.ndarray, np.ndarray, list[str], list[int]]:
    qs = FeatureBar.objects.filter(label_up_15m__isnull=False).order_by("ts")
    if interval:
        qs = qs.filter(interval_seconds=interval)
    rows = list(qs)
    if len(rows) < min_rows:
        raise ValueError(
            f"Need at least {min_rows} labeled bars; have {len(rows)}. "
            "Run collection 24/7 or backfill Binance klines first."
        )
    vectors = [training_vector(row.features or {}) for row in rows]
    keys: set[str] = set()
    for vec in vectors:
        keys.update(vec)
    columns = sorted(keys)
    coverage = {col: sum(1 for vec in vectors if col in vec) / len(vectors) for col in columns}
    columns = [col for col in columns if coverage[col] >= 0.4]
    if not columns:
        raise ValueError("No overlapping features with enough coverage to train.")
    X = np.zeros((len(vectors), len(columns)), dtype=float)
    for i, vec in enumerate(vectors):
        for j, col in enumerate(columns):
            value = vec.get(col)
            X[i, j] = value if value is not None and not math.isnan(value) else np.nan
    y = np.array([1 if row.label_up_15m else 0 for row in rows], dtype=int)
    # median impute per column
    for j in range(X.shape[1]):
        col = X[:, j]
        med = np.nanmedian(col)
        if np.isnan(med):
            med = 0.0
        col[np.isnan(col)] = med
        X[:, j] = col
    timestamps = [row.ts for row in rows]
    return X, y, columns, timestamps


def time_splits(n: int, folds: int = 5, min_train: int = 150) -> list[tuple[np.ndarray, np.ndarray]]:
    folds = max(2, min(folds, 8))
    splits: list[tuple[np.ndarray, np.ndarray]] = []
    if n < min_train + 40:
        cut = max(int(n * 0.7), min_train)
        if cut >= n:
            raise ValueError("Not enough rows for a train/test split.")
        splits.append((np.arange(0, cut), np.arange(cut, n)))
        return splits
    test_size = max(40, n // (folds + 1))
    for i in range(folds):
        test_end = n - (folds - 1 - i) * (test_size // 2)
        test_start = test_end - test_size
        train_end = test_start
        if train_end < min_train:
            continue
        splits.append((np.arange(0, train_end), np.arange(test_start, test_end)))
    if not splits:
        cut = int(n * 0.75)
        splits.append((np.arange(0, cut), np.arange(cut, n)))
    return splits


HORIZON = settings.HORIZON_SECONDS if hasattr(settings, "HORIZON_SECONDS") else 900
