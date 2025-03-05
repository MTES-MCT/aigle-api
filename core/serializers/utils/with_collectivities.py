from typing import Dict, List
from rest_framework import serializers

from core.models.geo_zone import GeoZone, GeoZoneType
from core.serializers.utils.query import get_objects

from core.models.geo_commune import GeoCommune
from core.models.geo_department import GeoDepartment
from core.models.geo_region import GeoRegion


class WithCollectivitiesSerializerMixin(serializers.ModelSerializer):
    class Meta:
        fields = [
            "communes",
            "departments",
            "regions",
        ]

    communes = serializers.SerializerMethodField()
    departments = serializers.SerializerMethodField()
    regions = serializers.SerializerMethodField()

    def get_communes(self, obj):
        from core.serializers.geo_zone import GeoZoneSerializer

        return GeoZoneSerializer(
            [
                obj
                for obj in obj.geo_zones.all()
                if obj.geo_zone_type == GeoZoneType.COMMUNE
            ],
            many=True,
            read_only=True,
        ).data

    def get_departments(self, obj):
        from core.serializers.geo_zone import GeoZoneSerializer

        return GeoZoneSerializer(
            [
                obj
                for obj in obj.geo_zones.all()
                if obj.geo_zone_type == GeoZoneType.DEPARTMENT
            ],
            many=True,
            read_only=True,
        ).data

    def get_regions(self, obj):
        from core.serializers.geo_zone import GeoZoneSerializer

        return GeoZoneSerializer(
            [
                obj
                for obj in obj.geo_zones.all()
                if obj.geo_zone_type == GeoZoneType.REGION
            ],
            many=True,
            read_only=True,
        ).data


class WithCollectivitiesInputSerializerMixin(serializers.ModelSerializer):
    class Meta:
        fields = [
            "communes_uuids",
            "departments_uuids",
            "regions_uuids",
        ]

    communes_uuids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True, write_only=True
    )
    departments_uuids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True, write_only=True
    )
    regions_uuids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True, write_only=True
    )


def extract_collectivities(validated_data: Dict) -> List[GeoZone]:
    communes_uuids = validated_data.pop("communes_uuids", None)
    communes = get_objects(uuids=communes_uuids, model=GeoCommune) or []

    departments_uuids = validated_data.pop("departments_uuids", None)
    departments = get_objects(uuids=departments_uuids, model=GeoDepartment) or []

    regions_uuids = validated_data.pop("regions_uuids", None)
    regions = get_objects(uuids=regions_uuids, model=GeoRegion) or []

    zones = list(communes) + list(departments) + list(regions)

    return zones
