from __future__ import annotations

from typing import Any, Callable

from sklearn.calibration import CalibratedClassifierCV
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis, QuadraticDiscriminantAnalysis
from sklearn.ensemble import (
    AdaBoostClassifier,
    BaggingClassifier,
    ExtraTreesClassifier,
    GradientBoostingClassifier,
    HistGradientBoostingClassifier,
    RandomForestClassifier,
)
from sklearn.linear_model import LogisticRegression, PassiveAggressiveClassifier, RidgeClassifier, SGDClassifier
from sklearn.naive_bayes import GaussianNB
from sklearn.neighbors import KNeighborsClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC
from sklearn.tree import DecisionTreeClassifier, ExtraTreeClassifier

Factory = Callable[[], Any]


def _scaled(est: Any) -> Pipeline:
    return Pipeline([("scaler", StandardScaler()), ("model", est)])


def build_estimators() -> dict[str, Factory]:
    factories: dict[str, Factory] = {
        "logistic_regression": lambda: _scaled(LogisticRegression(max_iter=400, C=1.0)),
        "ridge_classifier": lambda: _scaled(RidgeClassifier()),
        "sgd_log": lambda: _scaled(SGDClassifier(loss="log_loss", max_iter=800)),
        "passive_aggressive": lambda: _scaled(PassiveAggressiveClassifier(max_iter=800)),
        "linear_svc": lambda: _scaled(LinearSVC(max_iter=2000)),
        "gaussian_nb": GaussianNB,
        "lda": LinearDiscriminantAnalysis,
        "qda": QuadraticDiscriminantAnalysis,
        "decision_tree": lambda: DecisionTreeClassifier(max_depth=6, min_samples_leaf=20),
        "extra_tree": lambda: ExtraTreeClassifier(max_depth=8, min_samples_leaf=20),
        "random_forest": lambda: RandomForestClassifier(n_estimators=200, max_depth=8, min_samples_leaf=10, n_jobs=-1),
        "extra_trees": lambda: ExtraTreesClassifier(n_estimators=250, max_depth=8, min_samples_leaf=10, n_jobs=-1),
        "hist_gbm": lambda: HistGradientBoostingClassifier(max_depth=6, max_iter=150, learning_rate=0.06),
        "gradient_boosting": lambda: GradientBoostingClassifier(max_depth=3, n_estimators=80, learning_rate=0.08),
        "adaboost": lambda: AdaBoostClassifier(n_estimators=80, learning_rate=0.08),
        "bagging_trees": lambda: BaggingClassifier(
            estimator=DecisionTreeClassifier(max_depth=5, min_samples_leaf=20),
            n_estimators=40,
            n_jobs=-1,
        ),
        "knn": lambda: _scaled(KNeighborsClassifier(n_neighbors=25, weights="distance")),
        "mlp": lambda: _scaled(MLPClassifier(hidden_layer_sizes=(64, 32), max_iter=120, alpha=1e-3)),
        "calibrated_logistic": lambda: CalibratedClassifierCV(
            LogisticRegression(max_iter=300),
            method="sigmoid",
            cv=3,
        ),
    }
    try:
        from xgboost import XGBClassifier

        factories["xgboost"] = lambda: XGBClassifier(
            n_estimators=120,
            max_depth=4,
            learning_rate=0.07,
            subsample=0.9,
            colsample_bytree=0.8,
            eval_metric="logloss",
            n_jobs=-1,
        )
    except Exception:
        pass
    return factories


def predict_proba_up(model: Any, X) -> list[float]:
    if hasattr(model, "predict_proba"):
        proba = model.predict_proba(X)
        classes = list(getattr(model, "classes_", [0, 1]))
        if 1 in classes:
            idx = classes.index(1)
            return proba[:, idx].tolist()
        return proba[:, -1].tolist()
    if hasattr(model, "decision_function"):
        import math

        scores = model.decision_function(X)

        def sig(z: float) -> float:
            if z >= 0:
                ez = math.exp(-z)
                return 1.0 / (1.0 + ez)
            ez = math.exp(z)
            return ez / (1.0 + ez)

        return [sig(float(z)) for z in scores]
    preds = model.predict(X)
    return [float(p) for p in preds]
