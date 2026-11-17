from django.db import models

from common.models.timestamped import TimestampedModelMixin
from common.models.uuid import UuidModelMixin
from core.models.geo_zone import GeoZone
from core.models.object_type import ObjectType
from core.models.tile_set import TileSet


# Written by compute_detection_type_overlaps: detections of the zone's latest year that
# overlap a detection of another object type. One per zone, a re-run replaces it, hence
# no soft delete. The "outside zones à enjeux" figures are all minus custom_zones.
class DetectionTypeOverlapReport(TimestampedModelMixin, UuidModelMixin):
    geo_zone = models.OneToOneField(
        GeoZone,
        related_name="detection_type_overlap_report",
        on_delete=models.CASCADE,
    )
    report_date = models.DateTimeField()
    tile_sets = models.ManyToManyField(
        TileSet, related_name="detection_type_overlap_reports"
    )

    detections_count = models.IntegerField()
    overlapping_count = models.IntegerField()
    overlapping_prescribable_count = models.IntegerField()
    custom_zones_detections_count = models.IntegerField()
    custom_zones_overlapping_count = models.IntegerField()
    custom_zones_overlapping_prescribable_count = models.IntegerField()

    class Meta:
        indexes = UuidModelMixin.Meta.indexes + [
            models.Index(fields=["report_date"]),
        ]


# One per object type prescribable when the report was computed.
class DetectionTypeOverlapReportObjectType(models.Model):
    report = models.ForeignKey(
        DetectionTypeOverlapReport,
        related_name="object_types",
        on_delete=models.CASCADE,
    )
    object_type = models.ForeignKey(
        ObjectType,
        related_name="detection_type_overlap_reports",
        on_delete=models.CASCADE,
    )
    overlapping_count = models.IntegerField()
    custom_zones_overlapping_count = models.IntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["report", "object_type"],
                name="detection_type_overlap_report_object_type_unique",
            ),
        ]
