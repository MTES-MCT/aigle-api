from typing import Dict, List
from rest_framework import serializers

from core.constants.collectivity import COLLECTIVITY_LEVELS, model_for_level
from core.models.geo_zone import GeoZone, GeoZoneType
from core.serializers.utils.query import get_objects


# Read/write field name per level, e.g. `communes` / `communes_uuids`.
FIELD_NAME_BY_LEVEL = {
    GeoZoneType.COMMUNE: "communes",
    GeoZoneType.EPCI: "epcis",
    GeoZoneType.DEPARTMENT: "departments",
    GeoZoneType.REGION: "regions",
}


class WithCollectivitiesSerializerMixin(serializers.ModelSerializer):
    class Meta:
        fields = [
            "communes",
            "epcis",
            "departments",
            "regions",
        ]

    communes = serializers.SerializerMethodField()
    epcis = serializers.SerializerMethodField()
    departments = serializers.SerializerMethodField()
    regions = serializers.SerializerMethodField()

    @staticmethod
    def _zones_of_level(obj, level: GeoZoneType):
        from core.serializers.geo_zone import GeoZoneSerializer

        return GeoZoneSerializer(
            [zone for zone in obj.geo_zones.all() if zone.geo_zone_type == level],
            many=True,
            read_only=True,
        ).data

    def get_communes(self, obj):
        return self._zones_of_level(obj, GeoZoneType.COMMUNE)

    def get_epcis(self, obj):
        return self._zones_of_level(obj, GeoZoneType.EPCI)

    def get_departments(self, obj):
        return self._zones_of_level(obj, GeoZoneType.DEPARTMENT)

    def get_regions(self, obj):
        return self._zones_of_level(obj, GeoZoneType.REGION)


def _uuids_field():
    return serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True, write_only=True
    )


class WithCollectivitiesInputSerializerMixin(serializers.ModelSerializer):
    class Meta:
        fields = [
            "communes_uuids",
            "epcis_uuids",
            "departments_uuids",
            "regions_uuids",
        ]

    communes_uuids = _uuids_field()
    epcis_uuids = _uuids_field()
    departments_uuids = _uuids_field()
    regions_uuids = _uuids_field()


def extract_collectivities(validated_data: Dict) -> List[GeoZone]:
    """Pop every `<level>s_uuids` key and resolve it to its GeoZone rows.

    Every writer (user group, tile set, custom zone) does `geo_zones.set(...)` with the
    result, so a level missing here is a level silently WIPED on every update.
    """
    zones = []

    for level in COLLECTIVITY_LEVELS:
        uuids = validated_data.pop(f"{FIELD_NAME_BY_LEVEL[level]}_uuids", None)
        zones.extend(get_objects(uuids=uuids, model=model_for_level(level)) or [])

    return zones
