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
    INTERFACE_FORCED_VISIBLE = "INTERFACE_FORCED_VISIBLE", "INTERFACE_FORCED_VISIBLE"
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

    history = HistoricalRecords(
        bases=[HistoriedModelMixin], cascade_delete_history=True
    )

    class Meta:
        indexes = UuidModelMixin.Meta.indexes + [
            models.Index(fields=["score"]),
            models.Index(fields=["detection_object", "score", "detection_source"]),
            models.Index(fields=["detection_object", "detection_data"]),
            models.Index(fields=["detection_object", "detection_data", "tile_set"]),
            models.Index(
                fields=["detection_object", "detection_data", "tile_set", "score"]
            ),
            # Backs the per-import custom-zone association filter on batch_id + tile_set.
            models.Index(
                fields=["batch_id", "tile_set"],
                name="core_detec_batch_tileset_idx",
                condition=models.Q(batch_id__isnull=False),
            ),
        ]
        constraints = [
            # One detection per source row of a batch, so re-deploying a batch can never
            # duplicate its detections. Scoped by batch_id, NOT global: import_id holds
            # ids from two different namespaces (detections.inference.id for real ML
            # batches, another environment's core_detection.id for batches copied by
            # aigle-utils/sql_scripts/import_from_preprod.sql), which do collide across
            # batches. Also backs the import_id lookup import_detections does per batch.
            models.UniqueConstraint(
                fields=["batch_id", "import_id"],
                condition=models.Q(import_id__isnull=False),
                name="detection_batch_import_id_unique",
            ),
        ]
