import json
from rest_framework.views import APIView
from rest_framework.response import Response

from core.contants.order_by import GEO_CUSTOM_ZONES_ORDER_BYS, TILE_SETS_ORDER_BYS
from core.models.geo_custom_zone import GeoCustomZone, GeoCustomZoneStatus
from core.models.tile_set import TileSet, TileSetStatus
from core.models.user import UserRole
from core.permissions.tile_set import TileSetPermission
from core.permissions.user import UserPermission
from core.serializers.geo_custom_zone import GeoCustomZoneMinimalSerializer
from core.serializers.map_settings import (
    MapSettingObjectTypeSerializer,
    MapSettingsGeoCustomZoneCategorySerializer,
    MapSettingsSerializer,
    MapSettingTileSetSerializer,
)
from core.serializers.object_type import ObjectTypeSerializer
from core.serializers.tile_set import TileSetMinimalSerializer
from django.contrib.gis.geos import GEOSGeometry

from django.contrib.gis.db.models.aggregates import Union
from django.contrib.gis.db.models.functions import Envelope

from core.utils.data_permissions import (
    get_user_object_types_with_status,
)


class MapSettingsView(APIView):
    def get(self, request, format=None):
        setting_tile_sets = []
        global_geometry_bbox = None

        # super admin has access to all tile sets and all object types
        if request.user.user_role == UserRole.SUPER_ADMIN:
            tile_sets = TileSet.objects.filter(
                tile_set_status__in=[TileSetStatus.VISIBLE, TileSetStatus.HIDDEN]
            ).order_by(*TILE_SETS_ORDER_BYS)

            tile_sets = tile_sets.annotate(
                bbox=Envelope(Union("geo_zones__geometry"))
            ).all()

            for tile_set in tile_sets:
                setting_tile_set = MapSettingTileSetSerializer(
                    data={
                        "tile_set": TileSetMinimalSerializer(tile_set).data,
                        "geometry_bbox": (
                            json.loads(GEOSGeometry(tile_set.bbox).geojson)
                            if tile_set.bbox
                            else None
                        ),
                    }
                )
                setting_tile_sets.append(setting_tile_set.initial_data)

        if request.user.user_role != UserRole.SUPER_ADMIN:
            tile_sets = TileSetPermission(user=request.user).list_(with_bbox=True)
            global_geometry_bbox = UserPermission(
                user=request.user
            ).get_accessible_geometry(bbox=True)

            for tile_set in tile_sets:
                setting_tile_set = MapSettingTileSetSerializer(
                    data={
                        "tile_set": TileSetMinimalSerializer(tile_set).data,
                        "geometry_bbox": (
                            json.loads(GEOSGeometry(tile_set.bbox).geojson)
                            if tile_set.bbox
                            else None
                        ),
                    }
                )

                setting_tile_sets.append(setting_tile_set.initial_data)

        object_types_with_status = get_user_object_types_with_status(request.user)
        setting_object_types = []

        for object_type, status in object_types_with_status:
            setting_object_type = MapSettingObjectTypeSerializer(
                {
                    "object_type": ObjectTypeSerializer(object_type).data,
                    "object_type_category_object_type_status": status,
                }
            )
            setting_object_types.append(setting_object_type.data)

        geo_custom_zones_data = GeoCustomZone.objects.order_by(
            *GEO_CUSTOM_ZONES_ORDER_BYS
        ).filter(geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE)

        if request.user.user_role != UserRole.SUPER_ADMIN:
            geo_custom_zones_data = geo_custom_zones_data.filter(
                user_groups_custom_geo_zones__user_user_groups__user=request.user
            )

        geo_custom_zones_data = geo_custom_zones_data.select_related(
            "geo_custom_zone_category"
        )

        geo_custom_zones_data = geo_custom_zones_data.all()

        geo_custom_zones_uncategorized = []
        geo_custom_zone_categories_map = {}

        for geo_custom_zone in geo_custom_zones_data:
            if not geo_custom_zone.geo_custom_zone_category:
                geo_custom_zones_uncategorized.append(
                    GeoCustomZoneMinimalSerializer(geo_custom_zone).data
                )
                continue

            if (
                geo_custom_zone_categories_map.get(
                    geo_custom_zone.geo_custom_zone_category.uuid
                )
                is None
            ):
                geo_custom_zone_categories_map[
                    geo_custom_zone.geo_custom_zone_category.uuid
                ] = {
                    "geo_custom_zone_category": geo_custom_zone.geo_custom_zone_category,
                    "geo_custom_zones": [],
                }

            geo_custom_zone_categories_map[
                geo_custom_zone.geo_custom_zone_category.uuid
            ]["geo_custom_zones"].append(
                GeoCustomZoneMinimalSerializer(geo_custom_zone).data
            )

        setting = MapSettingsSerializer(
            data={
                "tile_set_settings": setting_tile_sets,
                "object_type_settings": setting_object_types,
                "global_geometry_bbox": json.loads(
                    GEOSGeometry(global_geometry_bbox).geojson
                )
                if global_geometry_bbox
                else None,
                "geo_custom_zones_uncategorized": geo_custom_zones_uncategorized,
                "geo_custom_zone_categories": [
                    MapSettingsGeoCustomZoneCategorySerializer(
                        geo_custom_zone_category_data
                    ).data
                    for geo_custom_zone_category_data in geo_custom_zone_categories_map.values()
                ],
                "user_last_position": request.user.last_position,
            }
        )

        return Response(setting.initial_data)
