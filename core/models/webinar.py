from django.db import models
from django.db.models import F, Q

from common.constants.models import DEFAULT_MAX_LENGTH
from common.models.deletable import DeletableModelMixin
from common.models.timestamped import TimestampedModelMixin
from common.models.uuid import UuidModelMixin


class Webinar(TimestampedModelMixin, UuidModelMixin, DeletableModelMixin):
    title = models.CharField(max_length=DEFAULT_MAX_LENGTH)
    # Sanitized HTML from the admin rich text editor.
    description = models.TextField(blank=True, default="")
    # Paris wall-clock values: a webinar is announced in Paris time, whatever the viewer's timezone.
    date = models.DateField()
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    replay_url = models.URLField(max_length=1024, null=True, blank=True)
    registration_url = models.URLField(max_length=1024, null=True, blank=True)
    visio_url = models.URLField(max_length=1024, null=True, blank=True)

    class Meta:
        indexes = UuidModelMixin.Meta.indexes + []
        constraints = [
            models.CheckConstraint(
                check=Q(start_time__isnull=True, end_time__isnull=True)
                | Q(start_time__isnull=False, end_time__gt=F("start_time")),
                name="webinar_time_slot_valid",
            ),
        ]
