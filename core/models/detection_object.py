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
    history = HistoricalRecords(
        bases=[HistoriedModelMixin], cascade_delete_history=True
    )

    class Meta:
        indexes = UuidModelMixin.Meta.indexes + [
            models.Index(fields=["object_type"]),
            models.Index(fields=["object_type", "parcel"]),
            # Covering index for the Detection->DetectionObject join in full-dataset
            # per-commune aggregates (DeployedDataService): serves the join side as
            # an index-only scan instead of a ~1GB heap scan.
            models.Index(
                fields=["id", "commune"],
                condition=models.Q(commune__isnull=False),
                name="detobj_id_commune_idx",
            ),
            # commune-LEADING covering index for the per-department deployed-data detail,
            # which seeks objects by `commune_id IN (<populated communes>)`. The (id,
            # commune) index above leads with id and so can't seek by commune; this one
            # lets those scoped lookups (and the detection-join object side) run as
            # index-only seeks instead of scanning the whole table. See DeployedDataService.
            models.Index(
                fields=["commune", "id"],
                condition=models.Q(commune__isnull=False),
                name="detobj_commune_id_idx",
            ),
        ]
