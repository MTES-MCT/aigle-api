from core.models.geo_custom_zone_category import GeoCustomZoneCategory
from core.serializers import UuidTimestampedModelSerializerMixin
from rest_framework import serializers


class GeoCustomZoneCategorySerializer(UuidTimestampedModelSerializerMixin):
    class Meta(UuidTimestampedModelSerializerMixin.Meta):
        model = GeoCustomZoneCategory
        fields = UuidTimestampedModelSerializerMixin.Meta.fields + [
            "color",
            "name",
            "name_short",
            "name_normalized",
        ]

    name_normalized = serializers.CharField(read_only=True)


class GeoCustomZoneCategoryDetailSerializer(GeoCustomZoneCategorySerializer):
    from core.serializers.geo_custom_zone import GeoCustomZoneSerializer

    class Meta(GeoCustomZoneCategorySerializer.Meta):
        fields = GeoCustomZoneCategorySerializer.Meta.fields + ["geo_custom_zones"]

    geo_custom_zones = serializers.SerializerMethodField()

    def get_geo_custom_zones(self, obj):
        from core.serializers.geo_custom_zone import GeoCustomZoneSerializer

        return GeoCustomZoneSerializer(obj.geo_custom_zones, many=True).data
