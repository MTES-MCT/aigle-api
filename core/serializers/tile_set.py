import re
from datetime import datetime
from typing import List, Optional
from core.models.geo_zone import GeoZone
from core.models.object_type_category import ObjectTypeCategory
from core.models.tile_set import TileSet
from core.serializers import UuidTimestampedModelSerializerMixin
from rest_framework_gis.fields import GeometryField

from rest_framework import serializers
from django.db.models import Count, Q

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


TILE_SET_INPUT_FIELDS = [
    "name",
    "url",
    "tile_set_status",
    "tile_set_scheme",
    "tile_set_type",
    "min_zoom",
    "max_zoom",
    "monochrome",
]


class TileSetInputSerializer(TileSetSerializer, WithCollectivitiesInputSerializerMixin):
    class Meta(TileSetSerializer.Meta):
        fields = (
            WithCollectivitiesInputSerializerMixin.Meta.fields
            + TILE_SET_INPUT_FIELDS
            + [
                "date",
            ]
        )

    def create(self, validated_data):
        object_type_categories_uuids = validated_data.pop(
            "object_type_categories_uuids", None
        )
        object_type_categories = get_objects(
            uuids=object_type_categories_uuids, model=ObjectTypeCategory
        )
        collectivities = extract_collectivities(validated_data)

        check_tileset_uniqueness(
            date=validated_data.get("date"), collectivities=collectivities
        )
        check_tileset_url_uniqueness(url=validated_data.get("url"))

        instance = TileSet(**validated_data)
        instance.save()

        if collectivities:
            instance.geo_zones.set(collectivities)

        if object_type_categories:
            instance.object_type_categories.set(object_type_categories)

        instance.save()

        return instance

    def update(self, instance: TileSet, validated_data):
        collectivities = extract_collectivities(validated_data)

        check_tileset_uniqueness(
            date=validated_data.get("date", instance.date),
            collectivities=collectivities,
            exclude_tileset_id=instance.id,
        )
        if "url" in validated_data and validated_data["url"] != instance.url:
            check_tileset_url_uniqueness(url=validated_data["url"])

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


class TileSetBulkCreateInputSerializer(
    TileSetSerializer, WithCollectivitiesInputSerializerMixin
):
    class Meta(TileSetSerializer.Meta):
        fields = (
            WithCollectivitiesInputSerializerMixin.Meta.fields
            + TILE_SET_INPUT_FIELDS
            + [
                "years",
            ]
        )

    years = serializers.CharField(required=True)

    def validate_years(self, value):
        if not re.fullmatch(r"\d{4}(,\d{4})*", value):
            raise serializers.ValidationError(
                "Le format doit être 'yyyy1,yyyy2,yyyy3' (ex: '2023,2024,2025')"
            )
        return value

    def validate(self, attrs):
        name = attrs.get("name", "")
        url = attrs.get("url", "")

        if "{year}" not in name:
            raise serializers.ValidationError(
                {
                    "name": "Le nom doit contenir le placeholder {year} (ex: 'Mon TileSet {year}')"
                }
            )
        if "{year}" not in url:
            raise serializers.ValidationError(
                {
                    "url": "L'URL doit contenir le placeholder {year} (ex: 'https://tiles.example.com/{year}/xyz')"
                }
            )

        return attrs

    def create(self, validated_data):
        object_type_categories_uuids = validated_data.pop(
            "object_type_categories_uuids", None
        )
        object_type_categories = get_objects(
            uuids=object_type_categories_uuids, model=ObjectTypeCategory
        )
        collectivities = extract_collectivities(validated_data)

        years = validated_data.pop("years").split(",")
        name_template = validated_data.pop("name")
        url_template = validated_data.pop("url")

        dates = [datetime(int(year), 1, 1) for year in years]

        for date in dates:
            check_tileset_uniqueness(date=date, collectivities=collectivities)

        for year in years:
            check_tileset_url_uniqueness(url=url_template.replace("{year}", year))

        instances = []
        for year, date in zip(years, dates):
            instance = TileSet(
                **validated_data,
                name=name_template.replace("{year}", year),
                url=url_template.replace("{year}", year),
                date=date,
            )
            instance.save()

            if collectivities:
                instance.geo_zones.set(collectivities)

            if object_type_categories:
                instance.object_type_categories.set(object_type_categories)

            instances.append(instance)

        return instances


# utils


def check_tileset_uniqueness(
    date: datetime,
    collectivities: List[GeoZone],
    exclude_tileset_id: Optional[int] = None,
):
    collectivity_ids = [col.id for col in collectivities]
    collectivity_count = len(collectivity_ids)

    # Find TileSets with same date, exact same count of geo_zones, and all matching geo_zones
    # This is done in a single query by:
    # 1. Filtering by date
    # 2. Filtering only TileSets that have ALL the collectivity_ids
    # 3. Annotating with count to ensure exact match (no extra geo_zones)
    query = Q()
    for geo_zone_id in collectivity_ids:
        query &= Q(geo_zones__id=geo_zone_id)

    queryset = (
        TileSet.objects.filter(date=date)
        .filter(query)
        .annotate(geo_zones_count=Count("geo_zones"))
        .filter(geo_zones_count=collectivity_count)
    )

    if exclude_tileset_id:
        queryset = queryset.exclude(id=exclude_tileset_id)

    if queryset.exists():
        raise serializers.ValidationError(
            {"date": "Un millésime avec ces collectivités et cette date existe déjà"}
        )


def check_tileset_url_uniqueness(url: str):
    if TileSet.objects.filter(url=url).exists():
        raise serializers.ValidationError(
            {"url": f"Un fond de carte avec cette URL existe déjà : {url}"}
        )
