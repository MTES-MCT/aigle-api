from django.db import models

from common.constants.models import DEFAULT_MAX_LENGTH
from common.models.timestamped import TimestampedModelMixin
from common.models.uuid import UuidModelMixin


class CommandRunStatus(models.TextChoices):
    PENDING = "PENDING", "PENDING"
    RUNNING = "RUNNING", "RUNNING"
    SUCCESS = "SUCCESS", "SUCCESS"
    ERROR = "ERROR", "ERROR"
    CANCELED = "CANCELED", "CANCELED"


class CommandRun(TimestampedModelMixin, UuidModelMixin):
    command_name = models.CharField(max_length=DEFAULT_MAX_LENGTH)
    task_id = models.CharField(max_length=DEFAULT_MAX_LENGTH, unique=True)
    arguments = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=DEFAULT_MAX_LENGTH,
        choices=CommandRunStatus.choices,
        default=CommandRunStatus.PENDING,
    )
    output = models.TextField(blank=True, null=True)
    error = models.TextField(blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=["task_id"]),
            models.Index(fields=["status"]),
            models.Index(fields=["command_name"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["status", "created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.command_name} ({self.task_id}) - {self.status}"

    def is_finished(self):
        return self.status in [
            CommandRunStatus.SUCCESS,
            CommandRunStatus.ERROR,
            CommandRunStatus.CANCELED,
        ]

    def is_running(self):
        return self.status == CommandRunStatus.RUNNING

    def is_pending(self):
        return self.status == CommandRunStatus.PENDING
