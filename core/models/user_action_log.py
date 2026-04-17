from django.db import models

from common.constants.models import DEFAULT_MAX_LENGTH
from common.models.timestamped import TimestampedModelMixin
from common.models.uuid import UuidModelMixin
from core.models.user import User


class UserActionLogAction(models.TextChoices):
    CREATE = "CREATE", "CREATE"
    UPDATE = "UPDATE", "UPDATE"
    PARTIAL_UPDATE = "PARTIAL_UPDATE", "PARTIAL_UPDATE"
    DESTROY = "DESTROY", "DESTROY"
    CUSTOM = "CUSTOM", "CUSTOM"


class UserActionLog(TimestampedModelMixin, UuidModelMixin):
    user = models.ForeignKey(
        User,
        related_name="user_action_logs",
        on_delete=models.PROTECT,
    )
    route = models.CharField(max_length=DEFAULT_MAX_LENGTH)
    action = models.CharField(
        max_length=DEFAULT_MAX_LENGTH,
        choices=UserActionLogAction.choices,
    )
    data = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["user"]),
            models.Index(fields=["action"]),
            models.Index(fields=["user", "created_at"]),
        ]
