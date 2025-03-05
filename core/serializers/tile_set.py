from core.models.object_type_category import ObjectTypeCategory
from core.models.tile_set import TileSet
from core.models.user_group import UserGroup
from core.serializers import UuidTimestampedModelSerializerMixin
from rest_framework_gis.fields import GeometryField

from rest_framework import serializers

from core.serializers.utils.query import get_objects
from core.serializers.utils.with_collectivities import (
    WithCollectivitiesInputSerializerMixin,
    WithCollectivitiesSerializerMixin,
    extract_collectivities,
)


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


class TileSetSerializer(TileSetMinimalSerializer, WithCollectivitiesSerializerMixin):
    class Meta(TileSetMinimalSerializer.Meta):
        model = TileSet
        fields = (
            TileSetMinimalSerializer.Meta.fields
            + WithCollectivitiesSerializerMixin.Meta.fields
            + [
                "id",
                "last_import_started_at",
                "last_import_ended_at",
                "detections_count",
            ]
        )

    detections_count = serializers.IntegerField()


class TileSetDetailSerializer(TileSetSerializer):
    class Meta(TileSetSerializer.Meta):
        fields = TileSetSerializer.Meta.fields + ["geometry"]

    geometry = GeometryField(read_only=True)


class TileSetInputSerializer(TileSetSerializer, WithCollectivitiesInputSerializerMixin):
    class Meta(TileSetSerializer.Meta):
        fields = WithCollectivitiesInputSerializerMixin.Meta.fields + [
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

    def create(self, validated_data):
        object_type_categories_uuids = validated_data.pop(
            "object_type_categories_uuids", None
        )
        object_type_categories = get_objects(
            uuids=object_type_categories_uuids, model=ObjectTypeCategory
        )
        collectivities = extract_collectivities(validated_data)

        instance = TileSet(
            **validated_data,
        )
        instance.save()

        if collectivities:
            instance.geo_zones.set(collectivities)

        if object_type_categories:
            instance.object_type_categories.set(object_type_categories)

        instance.save()

        return instance

    def update(self, instance: UserGroup, validated_data):
        collectivities = extract_collectivities(validated_data)

        object_type_categories_uuids = validated_data.pop(
            "object_type_categories_uuids", None
        )
        object_type_categories = get_objects(
            uuids=object_type_categories_uuids, model=ObjectTypeCategory
        )

        instance.geo_zones.set(collectivities)

        if object_type_categories is not None:
            instance.object_type_categories.set(object_type_categories)

        for key, value in validated_data.items():
            setattr(instance, key, value)

        instance.save()

        return instance
