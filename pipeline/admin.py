from django.contrib import admin

from pipeline.models import (
    AppLog,
    AppSetting,
    CollectorSource,
    EnsembleConfig,
    FeatureBar,
    ModelArtifact,
    PolyMarketWindow,
    Prediction,
    ProcessHeartbeat,
    TradeOrder,
    TrainingJob,
)


@admin.register(AppSetting)
class AppSettingAdmin(admin.ModelAdmin):
    list_display = ("key", "is_secret", "updated_at")


admin.site.register(CollectorSource)
admin.site.register(ProcessHeartbeat)
admin.site.register(PolyMarketWindow)
admin.site.register(TrainingJob)
admin.site.register(ModelArtifact)
admin.site.register(EnsembleConfig)
admin.site.register(Prediction)
admin.site.register(TradeOrder)
admin.site.register(AppLog)


@admin.register(FeatureBar)
class FeatureBarAdmin(admin.ModelAdmin):
    list_display = ("asset", "ts", "interval_seconds", "mid_price", "label_up_next", "label_up_15m")
