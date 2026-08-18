from django.urls import path

from pipeline import views

urlpatterns = [
    path("health", views.health),
    path("bootstrap", views.bootstrap),
    path("setup", views.setup_view),
    path("settings", views.settings_view),
    path("collector/start", views.collector_start),
    path("collector/stop", views.collector_stop),
    path("inference/start", views.inference_start),
    path("inference/stop", views.inference_stop),
    path("live", views.live),
    path("backfill", views.backfill),
    path("architectures", views.architectures),
    path("train", views.train_view),
    path("train/<int:job_id>", views.train_detail),
    path("ensemble", views.ensemble_view),
    path("predict", views.predict_view),
    path("orders", views.orders_view),
    path("market", views.market_view),
]
