from common.constants.models import DEFAULT_MAX_LENGTH
from common.models.deletable import DeletableModelMixin
from common.models.timestamped import TimestampedModelMixin
from common.models.uuid import UuidModelMixin
from django.db import models

from core.utils.string import normalize


class GeoCustomZoneCategory(TimestampedModelMixin, UuidModelMixin, DeletableModelMixin):
    color = models.CharField(max_length=DEFAULT_MAX_LENGTH, unique=True)
    name_short = models.CharField(max_length=DEFAULT_MAX_LENGTH, unique=True, null=True)
    name = models.CharField(max_length=DEFAULT_MAX_LENGTH, unique=True)
    name_normalized = models.CharField(max_length=DEFAULT_MAX_LENGTH, unique=True)

    def save(self, *args, **kwargs):
        self.name_normalized = normalize(self.name)

        super().save(*args, **kwargs)
