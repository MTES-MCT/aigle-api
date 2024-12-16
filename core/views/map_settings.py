import json
from rest_framework.views import APIView
from rest_framework.response import Response

from core.contants.order_by import GEO_CUSTOM_ZONES_ORDER_BYS, TILE_SETS_ORDER_BYS
from core.models.geo_custom_zone import GeoCustomZone, GeoCustomZoneStatus
from core.models.tile_set import TileSet, TileSetStatus
from core.models.user import UserRole
from core.serializers.geo_custom_zone import GeoCustomZoneSerializer
from core.serializers.map_settings import (
    MapSettingObjectTypeSerializer,
    MapSettingsSerializer,
    MapSettingTileSetSerializer,
)
from core.serializers.object_type import ObjectTypeSerializer
from core.serializers.tile_set import TileSetMinimalSerializer
from django.contrib.gis.geos import GEOSGeometry

from django.contrib.gis.db.models.aggregates import Union

from core.utils.data_permissions import (
    get_user_object_types_with_status,
    get_user_tile_sets,
)


class MapSettingsView(APIView):
    def get(self, request, format=None):
        setting_tile_sets = []
        global_geometry = None

        # super admin has access to all tile sets and all object types
        if request.user.user_role == UserRole.SUPER_ADMIN:
            tile_sets = TileSet.objects.filter(
                tile_set_status__in=[TileSetStatus.VISIBLE, TileSetStatus.HIDDEN]
            ).order_by(*TILE_SETS_ORDER_BYS)

            tile_sets = tile_sets.annotate(
                intersection=Union("geo_zones__geometry")
            ).all()

            for tile_set in tile_sets:
                setting_tile_set = MapSettingTileSetSerializer(
                    data={
                        "tile_set": TileSetMinimalSerializer(tile_set).data,
                        "geometry": (
                            json.loads(GEOSGeometry(tile_set.intersection).geojson)
                            if tile_set.intersection
                            else None
                        ),
                    }
                )
                setting_tile_sets.append(setting_tile_set.initial_data)

        if request.user.user_role != UserRole.SUPER_ADMIN:
            tile_sets, global_geometry = get_user_tile_sets(request.user)

            for tile_set in tile_sets:
                setting_tile_set = MapSettingTileSetSerializer(
                    data={
                        "tile_set": TileSetMinimalSerializer(tile_set).data,
                        "geometry": (
                            json.loads(GEOSGeometry(tile_set.intersection).geojson)
                            if tile_set.intersection
                            else None
                        ),
                    }
                )

                setting_tile_sets.append(setting_tile_set.initial_data)

        object_types_with_status = get_user_object_types_with_status(request.user)
        setting_object_types = []

        for object_type, status in object_types_with_status:
            setting_object_type = MapSettingObjectTypeSerializer(
                data={
                    "object_type": ObjectTypeSerializer(object_type).data,
                    "object_type_category_object_type_status": status,
                }
            )
            setting_object_type.is_valid()
            setting_object_types.append(setting_object_type.data)

        geo_custom_zones_data = GeoCustomZone.objects.order_by(
            *GEO_CUSTOM_ZONES_ORDER_BYS
        ).filter(geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE)

        if request.user.user_role != UserRole.SUPER_ADMIN:
            geo_custom_zones_data = geo_custom_zones_data.filter(
                user_groups_custom_geo_zones__user_user_groups__user=request.user
            )

        geo_custom_zones_data = geo_custom_zones_data.values(
            "uuid", "name", "color", "geo_custom_zone_status"
        )

        geo_custom_zones_data = geo_custom_zones_data.all()

        geo_custom_zones = []

        for geo_custom_zone in geo_custom_zones_data:
            geo_custom_zones.append(GeoCustomZoneSerializer(geo_custom_zone).data)

        setting = MapSettingsSerializer(
            data={
                "tile_set_settings": setting_tile_sets,
                "object_type_settings": setting_object_types,
                "global_geometry": json.loads(GEOSGeometry(global_geometry).geojson)
                if global_geometry
                else None,
                "geo_custom_zones": geo_custom_zones,
                "user_last_position": request.user.last_position,
            }
        )

        return Response(setting.initial_data)
