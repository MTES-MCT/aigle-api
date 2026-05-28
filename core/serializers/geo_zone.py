from rest_framework import serializers

from core.models.geo_zone import GeoZone
from core.serializers import UuidTimestampedModelSerializerMixin


class GeoZoneSerializer(UuidTimestampedModelSerializerMixin):
    code = serializers.SerializerMethodField()

    class Meta(UuidTimestampedModelSerializerMixin.Meta):
        model = GeoZone
        fields = UuidTimestampedModelSerializerMixin.Meta.fields + [
            "name",
            "geo_zone_type",
            "code",
        ]

    def get_code(self, obj):
        return getattr(obj, "code", None)


class GeoZoneDetailSerializer(GeoZoneSerializer):
    class Meta(GeoZoneSerializer.Meta):
        fields = GeoZoneSerializer.Meta.fields + ["geometry"]
