from django.db import models


from common.constants.models import DEFAULT_MAX_LENGTH


from core.models.user import User


class AnalyticLogType(models.TextChoices):
    REPORT_DOWNLOAD = "REPORT_DOWNLOAD", "REPORT_DOWNLOAD"
    USER_ACCESS = "USER_ACCESS", "USER_ACCESS"


class AnalyticLog(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    analytic_log_type = models.CharField(
        max_length=DEFAULT_MAX_LENGTH,
        choices=AnalyticLogType.choices,
    )
    user = models.ForeignKey(
        User,
        related_name="analytic_logs",
        on_delete=models.PROTECT,
    )
    data = models.JSONField(null=True)

    class Meta:
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["analytic_log_type"]),
            models.Index(fields=["created_at", "analytic_log_type"]),
            models.Index(fields=["user"]),
        ]
