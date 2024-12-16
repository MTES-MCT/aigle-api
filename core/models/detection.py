from django.db import models


from common.constants.models import DEFAULT_MAX_LENGTH
from common.models.deletable import DeletableModelMixin
from common.models.historied import HistoriedModelMixin
from common.models.importable import ImportableModelMixin
from common.models.timestamped import TimestampedModelMixin
from common.models.uuid import UuidModelMixin
from core.models.detection_object import DetectionObject
from core.models.detection_data import DetectionData
from django.contrib.gis.db import models as models_gis
from django.core.validators import MinValueValidator, MaxValueValidator

from core.models.tile import Tile
from core.models.tile_set import TileSet
from simple_history.models import HistoricalRecords


class DetectionSource(models.TextChoices):
    INTERFACE_DRAWN = "INTERFACE_DRAWN", "INTERFACE_DRAWN"
    ANALYSIS = "ANALYSIS", "ANALYSIS"


class Detection(
    TimestampedModelMixin, UuidModelMixin, DeletableModelMixin, ImportableModelMixin
):
    geometry = models_gis.GeometryField()
    score = models.FloatField(
        validators=[MinValueValidator(0), MaxValueValidator(1)], default=1
    )
    detection_source = models.CharField(
        max_length=DEFAULT_MAX_LENGTH,
        choices=DetectionSource.choices,
        default=DetectionSource.INTERFACE_DRAWN,
    )
    detection_object = models.ForeignKey(
        DetectionObject, related_name="detections", on_delete=models.CASCADE
    )
    detection_data = models.OneToOneField(
        DetectionData,
        related_name="detection",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    auto_prescribed = models.BooleanField(default=False)

    tile = models.ForeignKey(Tile, related_name="detections", on_delete=models.CASCADE)
    tile_set = models.ForeignKey(
        TileSet, related_name="detections", on_delete=models.CASCADE
    )

    history = HistoricalRecords(bases=[HistoriedModelMixin])

    class Meta:
        indexes = UuidModelMixin.Meta.indexes + [
            models.Index(fields=["score"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["detection_source"]),
            models.Index(fields=["detection_object", "detection_data"]),
            models.Index(fields=["detection_object", "detection_data", "tile_set"]),
        ]
