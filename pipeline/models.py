from __future__ import annotations

from django.db import models


class AppSetting(models.Model):
    key = models.CharField(max_length=80, unique=True)
    value = models.TextField(blank=True, default="")
    is_secret = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.key


class CollectorSource(models.Model):
    name = models.CharField(max_length=64, unique=True)
    enabled = models.BooleanField(default=True)
    status = models.CharField(max_length=24, default="idle")
    last_message_at = models.DateTimeField(null=True, blank=True)
    message_count = models.BigIntegerField(default=0)
    error = models.TextField(blank=True, default="")
    extra = models.JSONField(default=dict, blank=True)

    def __str__(self) -> str:
        return self.name


class ProcessHeartbeat(models.Model):
    name = models.CharField(max_length=32, unique=True)
    pid = models.IntegerField(null=True, blank=True)
    running = models.BooleanField(default=False)
    started_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    stats = models.JSONField(default=dict, blank=True)
    last_error = models.TextField(blank=True, default="")


class LiveTick(models.Model):
    ts_ms = models.BigIntegerField(db_index=True)
    venue = models.CharField(max_length=32, db_index=True)
    kind = models.CharField(max_length=24, default="trade")
    price = models.FloatField(null=True, blank=True)
    size = models.FloatField(null=True, blank=True)
    is_buyer_maker = models.BooleanField(null=True, blank=True)
    extra = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [models.Index(fields=["venue", "ts_ms"])]


class FeatureBar(models.Model):
    ts = models.BigIntegerField()
    interval_seconds = models.PositiveSmallIntegerField(default=5)
    mid_price = models.FloatField(null=True, blank=True)
    features = models.JSONField(default=dict)
    label_up_15m = models.BooleanField(null=True, blank=True)
    label_poly_up = models.BooleanField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("ts", "interval_seconds")]
        indexes = [
            models.Index(fields=["interval_seconds", "ts"]),
            models.Index(fields=["label_up_15m"]),
        ]


class PolyMarketWindow(models.Model):
    slug = models.CharField(max_length=128, unique=True)
    condition_id = models.CharField(max_length=128, blank=True, default="")
    question = models.TextField(blank=True, default="")
    token_up = models.CharField(max_length=96, blank=True, default="")
    token_down = models.CharField(max_length=96, blank=True, default="")
    start_ts = models.BigIntegerField()
    end_ts = models.BigIntegerField()
    yes_bid = models.FloatField(null=True, blank=True)
    yes_ask = models.FloatField(null=True, blank=True)
    no_bid = models.FloatField(null=True, blank=True)
    no_ask = models.FloatField(null=True, blank=True)
    last_trade_yes = models.FloatField(null=True, blank=True)
    btc_open = models.FloatField(null=True, blank=True)
    btc_last = models.FloatField(null=True, blank=True)
    resolved_up = models.BooleanField(null=True, blank=True)
    extra = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class TrainingJob(models.Model):
    STATUS_CHOICES = [
        ("pending", "pending"),
        ("running", "running"),
        ("completed", "completed"),
        ("failed", "failed"),
    ]
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending")
    config = models.JSONField(default=dict)
    summary = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)


class ModelArtifact(models.Model):
    job = models.ForeignKey(TrainingJob, on_delete=models.CASCADE, related_name="artifacts")
    name = models.CharField(max_length=64)
    family = models.CharField(max_length=32, default="sklearn")
    path = models.CharField(max_length=512)
    metrics = models.JSONField(default=dict)
    selected = models.BooleanField(default=False)
    weight = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["name", "created_at"])]


class EnsembleConfig(models.Model):
    mode = models.CharField(max_length=32, default="auc_weighted")
    min_auc = models.FloatField(default=0.52)
    active_job = models.ForeignKey(TrainingJob, null=True, blank=True, on_delete=models.SET_NULL)
    updated_at = models.DateTimeField(auto_now=True)


class Prediction(models.Model):
    ts = models.BigIntegerField(db_index=True)
    bar = models.ForeignKey(FeatureBar, null=True, blank=True, on_delete=models.SET_NULL)
    market_slug = models.CharField(max_length=128, blank=True, default="")
    p_up = models.FloatField()
    per_model = models.JSONField(default=dict)
    implied_yes = models.FloatField(null=True, blank=True)
    edge = models.FloatField(null=True, blank=True)
    action = models.CharField(max_length=16, default="hold")
    created_at = models.DateTimeField(auto_now_add=True)


class TradeOrder(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    dry_run = models.BooleanField(default=True)
    market_slug = models.CharField(max_length=128)
    token_id = models.CharField(max_length=96, blank=True, default="")
    outcome = models.CharField(max_length=8)
    side = models.CharField(max_length=8, default="BUY")
    price = models.FloatField()
    size = models.FloatField()
    status = models.CharField(max_length=24, default="created")
    response = models.JSONField(default=dict, blank=True)
    prediction = models.ForeignKey(Prediction, null=True, blank=True, on_delete=models.SET_NULL)


class AppLog(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    level = models.CharField(max_length=16, default="info")
    source = models.CharField(max_length=64, default="app")
    message = models.TextField()
    extra = models.JSONField(default=dict, blank=True)
