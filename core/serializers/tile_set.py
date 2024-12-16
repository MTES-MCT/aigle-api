from core.models.geo_commune import GeoCommune
from core.models.geo_department import GeoDepartment
from core.models.geo_region import GeoRegion
from core.models.geo_zone import GeoZoneType
from core.models.object_type_category import ObjectTypeCategory
from core.models.tile_set import TileSet
from core.models.user_group import UserGroup
from core.serializers import UuidTimestampedModelSerializerMixin
from rest_framework_gis.fields import GeometryField

from rest_framework import serializers

from core.serializers.geo_zone import GeoZoneSerializer
from core.serializers.utils.query import get_objects


class TileSetMinimalSerializer(UuidTimestampedModelSerializerMixin):
    class Meta(UuidTimestampedModelSerializerMixin.Meta):
        model = TileSet
        fields = UuidTimestampedModelSerializerMixin.Meta.fields + [
            "name",
            "url",
            "tile_set_status",
            "tile_set_scheme",
            "tile_set_type",
            "date",
            "min_zoom",
            "max_zoom",
            "monochrome",
        ]


class TileSetWithGeometrySerializer(TileSetMinimalSerializer):
    class Meta(TileSetMinimalSerializer.Meta):
        fields = TileSetMinimalSerializer.Meta.fields + ["geometry"]

    geometry = GeometryField(read_only=True)


class TileSetSerializer(TileSetMinimalSerializer):
    class Meta(TileSetMinimalSerializer.Meta):
        model = TileSet
        fields = TileSetMinimalSerializer.Meta.fields + [
            "id",
            "communes",
            "departments",
            "regions",
            "last_import_started_at",
            "last_import_ended_at",
        ]

    communes = serializers.SerializerMethodField()
    departments = serializers.SerializerMethodField()
    regions = serializers.SerializerMethodField()

    def get_communes(self, obj):
        return GeoZoneSerializer(
            obj.geo_zones.filter(geo_zone_type=GeoZoneType.COMMUNE),
            many=True,
            read_only=True,
        ).data

    def get_departments(self, obj):
        return GeoZoneSerializer(
            obj.geo_zones.filter(geo_zone_type=GeoZoneType.DEPARTMENT),
            many=True,
            read_only=True,
        ).data

    def get_regions(self, obj):
        return GeoZoneSerializer(
            obj.geo_zones.filter(geo_zone_type=GeoZoneType.REGION),
            many=True,
            read_only=True,
        ).data


class TileSetDetailSerializer(TileSetSerializer):
    class Meta(TileSetSerializer.Meta):
        fields = TileSetSerializer.Meta.fields + ["geometry"]

    geometry = GeometryField(read_only=True)


class TileSetInputSerializer(TileSetSerializer):
    class Meta(TileSetSerializer.Meta):
        fields = [
            "name",
            "url",
            "tile_set_status",
            "tile_set_scheme",
            "tile_set_type",
            "date",
            "communes_uuids",
            "departments_uuids",
            "regions_uuids",
            "min_zoom",
            "max_zoom",
            "monochrome",
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

    def create(self, validated_data):
        communes_uuids = validated_data.pop("communes_uuids", None)
        communes = get_objects(uuids=communes_uuids, model=GeoCommune) or []

        departments_uuids = validated_data.pop("departments_uuids", None)
        departments = get_objects(uuids=departments_uuids, model=GeoDepartment) or []

        regions_uuids = validated_data.pop("regions_uuids", None)
        regions = get_objects(uuids=regions_uuids, model=GeoRegion) or []

        object_type_categories_uuids = validated_data.pop(
            "object_type_categories_uuids", None
        )
        object_type_categories = get_objects(
            uuids=object_type_categories_uuids, model=ObjectTypeCategory
        )

        instance = TileSet(
            **validated_data,
        )

        instance.save()

        zones = list(communes) + list(departments) + list(regions)

        if zones:
            instance.geo_zones.set(zones)

        if object_type_categories:
            instance.object_type_categories.set(object_type_categories)

        instance.save()

        return instance

    def update(self, instance: UserGroup, validated_data):
        communes_uuids = validated_data.pop("communes_uuids", None)
        communes = get_objects(uuids=communes_uuids, model=GeoCommune) or []

        departments_uuids = validated_data.pop("departments_uuids", None)
        departments = get_objects(uuids=departments_uuids, model=GeoDepartment) or []

        regions_uuids = validated_data.pop("regions_uuids", None)
        regions = get_objects(uuids=regions_uuids, model=GeoRegion) or []

        zones = list(communes) + list(departments) + list(regions)

        object_type_categories_uuids = validated_data.pop(
            "object_type_categories_uuids", None
        )
        object_type_categories = get_objects(
            uuids=object_type_categories_uuids, model=ObjectTypeCategory
        )

        instance.geo_zones.set(zones)

        if object_type_categories is not None:
            instance.object_type_categories.set(object_type_categories)

        for key, value in validated_data.items():
            setattr(instance, key, value)

        instance.save()

        return instance
