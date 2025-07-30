from django.db import models


from common.constants.models import DEFAULT_MAX_LENGTH
from common.models.deletable import DeletableModelMixin
from common.models.historied import HistoriedModelMixin
from common.models.importable import ImportableModelMixin
from common.models.timestamped import TimestampedModelMixin
from common.models.uuid import UuidModelMixin
from core.models.geo_commune import GeoCommune
from core.models.geo_custom_zone import GeoCustomZone
from core.models.geo_sub_custom_zone import GeoSubCustomZone
from core.models.object_type import ObjectType
from core.models.parcel import Parcel
from simple_history.models import HistoricalRecords

from core.models.tile_set import TileSet


class DetectionObject(
    TimestampedModelMixin, UuidModelMixin, DeletableModelMixin, ImportableModelMixin
):
    address = models.CharField(max_length=DEFAULT_MAX_LENGTH, null=True)
    comment = models.TextField(null=True)
    object_type = models.ForeignKey(
        ObjectType, related_name="detected_objects", on_delete=models.CASCADE
    )
    parcel = models.ForeignKey(
        Parcel,
        related_name="detection_objects",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
    )
    commune = models.ForeignKey(
        GeoCommune,
        related_name="detection_objects",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
    )
    geo_custom_zones = models.ManyToManyField(
        GeoCustomZone, related_name="detection_objects"
    )
    geo_sub_custom_zones = models.ManyToManyField(
        GeoSubCustomZone, related_name="detection_objects"
    )
    tile_sets = models.ManyToManyField(TileSet, through="Detection")
    history = HistoricalRecords(bases=[HistoriedModelMixin])

    class Meta:
        indexes = UuidModelMixin.Meta.indexes + [
            models.Index(fields=["object_type"]),
            models.Index(fields=["object_type", "parcel"]),
        ]
