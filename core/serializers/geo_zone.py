from django.db.models import Case, CharField, F, When
from django.db.models.manager import BaseManager
from rest_framework import serializers

from core.models.geo_zone import GeoZone, GeoZoneType
from core.serializers import UuidTimestampedModelSerializerMixin


def geo_zones_with_code():
    # The geozone table has no code column: read it from the collectivity subclass.
    return GeoZone.objects.annotate(
        code=Case(
            When(
                geo_zone_type=GeoZoneType.COMMUNE,
                then=F("geocommune__iso_code"),
            ),
            When(
                geo_zone_type=GeoZoneType.DEPARTMENT,
                then=F("geodepartment__insee_code"),
            ),
            When(
                geo_zone_type=GeoZoneType.REGION,
                then=F("georegion__insee_code"),
            ),
            When(
                geo_zone_type=GeoZoneType.EPCI,
                then=F("geoepci__siren_code"),
            ),
            output_field=CharField(),
        )
    )


def fill_geo_zone_codes(geo_zones) -> None:
    # Zones loaded through geo_zones_with_code() already carry `code`, even a None one.
    missing = [zone for zone in geo_zones if not hasattr(zone, "code")]
    if not missing:
        return

    codes = dict(
        geo_zones_with_code()
        .filter(id__in=[zone.id for zone in missing])
        .values_list("id", "code")
    )
    for zone in missing:
        zone.code = codes.get(zone.id)


class GeoZoneListSerializer(serializers.ListSerializer):
    def to_representation(self, data):
        geo_zones = list(data.all() if isinstance(data, BaseManager) else data)
        fill_geo_zone_codes(geo_zones)
        return super().to_representation(geo_zones)


class GeoZoneSerializer(UuidTimestampedModelSerializerMixin):
    code = serializers.SerializerMethodField()

    class Meta(UuidTimestampedModelSerializerMixin.Meta):
        model = GeoZone
        fields = UuidTimestampedModelSerializerMixin.Meta.fields + [
            "name",
            "geo_zone_type",
            "code",
        ]
        list_serializer_class = GeoZoneListSerializer

    def get_code(self, obj):
        fill_geo_zone_codes([obj])
        return obj.code


class GeoZoneDetailSerializer(GeoZoneSerializer):
    class Meta(GeoZoneSerializer.Meta):
        fields = GeoZoneSerializer.Meta.fields + ["geometry"]
