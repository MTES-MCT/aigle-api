from rest_framework import serializers

from core.models.object_type_category import ObjectTypeCategoryObjectTypeStatus
from core.serializers.geo_custom_zone import GeoCustomZoneSerializer
from core.serializers.object_type import ObjectTypeSerializer
from core.serializers.tile_set import TileSetMinimalSerializer
from django.contrib.gis.db import models as models_gis


class MapSettingTileSetSerializer(serializers.Serializer):
    tile_set = TileSetMinimalSerializer()
    geometry = models_gis.GeometryField()


class MapSettingObjectTypeSerializer(serializers.Serializer):
    object_type = ObjectTypeSerializer()
    object_type_category_object_type_status = serializers.ChoiceField(
        choices=ObjectTypeCategoryObjectTypeStatus.choices,
    )


class MapSettingsSerializer(serializers.Serializer):
    tile_set_settings = MapSettingTileSetSerializer(many=True)
    object_type_settings = MapSettingObjectTypeSerializer(many=True)
    global_geometry = models_gis.GeometryField(null=True)
    geo_custom_zones = GeoCustomZoneSerializer(many=True)
    user_last_position = models_gis.PointField(null=True)
