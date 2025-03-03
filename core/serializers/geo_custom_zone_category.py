from core.models.geo_custom_zone_category import GeoCustomZoneCategory
from core.serializers import UuidTimestampedModelSerializerMixin
from rest_framework import serializers


class GeoCustomZoneCategorySerializer(UuidTimestampedModelSerializerMixin):
    class Meta(UuidTimestampedModelSerializerMixin.Meta):
        model = GeoCustomZoneCategory
        fields = UuidTimestampedModelSerializerMixin.Meta.fields + [
            "color",
            "name",
            "name_normalized",
        ]

    name_normalized = serializers.CharField(read_only=True)
