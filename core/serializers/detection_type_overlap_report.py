from django.db.models.manager import BaseManager
from rest_framework import serializers

from core.models.detection_type_overlap_report import (
    DetectionTypeOverlapReport,
    DetectionTypeOverlapReportObjectType,
)
from core.serializers import UuidTimestampedModelSerializerMixin
from core.serializers.geo_zone import GeoZoneSerializer, fill_geo_zone_codes
from core.serializers.object_type import ObjectTypeSerializer
from core.serializers.tile_set import TileSetMinimalSerializer


class DetectionTypeOverlapReportListSerializer(serializers.ListSerializer):
    def to_representation(self, data):
        reports = list(data.all() if isinstance(data, BaseManager) else data)
        # one query for the page's zone codes instead of one per row
        fill_geo_zone_codes([report.geo_zone for report in reports])
        return super().to_representation(reports)


class DetectionTypeOverlapReportObjectTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = DetectionTypeOverlapReportObjectType
        fields = [
            "object_type",
            "overlapping_count",
            "custom_zones_overlapping_count",
        ]

    object_type = ObjectTypeSerializer(read_only=True)


class DetectionTypeOverlapReportSerializer(UuidTimestampedModelSerializerMixin):
    class Meta(UuidTimestampedModelSerializerMixin.Meta):
        model = DetectionTypeOverlapReport
        fields = UuidTimestampedModelSerializerMixin.Meta.fields + [
            "geo_zone",
            "report_date",
            "tile_sets",
            "detections_count",
            "overlapping_count",
            "overlapping_prescribable_count",
            "custom_zones_detections_count",
            "custom_zones_overlapping_count",
            "custom_zones_overlapping_prescribable_count",
            "object_types",
        ]
        list_serializer_class = DetectionTypeOverlapReportListSerializer

    geo_zone = GeoZoneSerializer(read_only=True)
    tile_sets = TileSetMinimalSerializer(many=True, read_only=True)
    object_types = DetectionTypeOverlapReportObjectTypeSerializer(
        many=True, read_only=True
    )
