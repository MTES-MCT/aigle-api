import json
from typing import Dict, List, Any, Optional
from django.contrib.gis.db.models.functions import Envelope
from django.contrib.gis.db.models.aggregates import Union
from django.contrib.gis.geos import GEOSGeometry

from core.constants.order_by import GEO_CUSTOM_ZONES_ORDER_BYS, TILE_SETS_ORDER_BYS
from core.models.geo_custom_zone import GeoCustomZone, GeoCustomZoneStatus
from core.models.tile_set import TileSet, TileSetStatus
from core.models.user import UserRole
from core.permissions.user import UserPermission
from core.permissions.tile_set import TileSetPermission
from core.serializers.geo_custom_zone import GeoCustomZoneMinimalSerializer
from core.serializers.map_settings import (
    MapSettingObjectTypeSerializer,
    MapSettingsGeoCustomZoneCategorySerializer,
    MapSettingsSerializer,
    MapSettingTileSetSerializer,
)
from core.serializers.object_type import ObjectTypeSerializer
from core.serializers.tile_set import TileSetMinimalSerializer


class MapSettingsService:
    """Service for assembling map configuration and settings data."""

    def __init__(self, user):
        self.user = user
        self.user_permission = UserPermission(user)

    def build_settings(self) -> Dict[str, Any]:
        """Build complete map settings configuration."""
        # Get tile sets and global geometry based on user role
        setting_tile_sets, global_geometry_bbox = self._get_tile_sets_data()

        # Get object types with permissions
        setting_object_types = self._get_object_types_data()

        # Get custom zones data
        geo_custom_zones_uncategorized, geo_custom_zone_categories = (
            self._get_custom_zones_data()
        )

        # Build final settings
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
                    for geo_custom_zone_category_data in geo_custom_zone_categories.values()
                ],
                "user_last_position": self.user.last_position,
            }
        )

        return setting.initial_data

    def _get_tile_sets_data(self) -> tuple[List[Dict], Optional[Any]]:
        """Get tile sets data based on user role and permissions."""
        if self.user.user_role == UserRole.SUPER_ADMIN:
            return self._get_super_admin_tile_sets(), None
        else:
            return self._get_regular_user_tile_sets()

    def _get_super_admin_tile_sets(self) -> List[Dict]:
        """Get tile sets for super admin users."""
        tile_sets = TileSet.objects.filter(
            tile_set_status__in=[TileSetStatus.VISIBLE, TileSetStatus.HIDDEN]
        ).order_by(*TILE_SETS_ORDER_BYS)

        tile_sets = tile_sets.annotate(
            bbox=Envelope(Union("geo_zones__geometry"))
        ).all()

        setting_tile_sets = []
        for tile_set in tile_sets:
            setting_tile_set = MapSettingTileSetSerializer(
                data={
                    "tile_set": TileSetMinimalSerializer(tile_set).data,
                    "geometry_bbox": self._serialize_geometry_bbox(tile_set.bbox),
                }
            )
            setting_tile_sets.append(setting_tile_set.initial_data)

        return setting_tile_sets

    def _get_regular_user_tile_sets(self) -> tuple[List[Dict], Optional[Any]]:
        """Get tile sets for regular users with permission filtering."""
        tile_sets = TileSetPermission(user=self.user).list_(with_bbox=True)
        global_geometry_bbox = self.user_permission.get_accessible_geometry(bbox=True)

        setting_tile_sets = []
        for tile_set in tile_sets:
            setting_tile_set = MapSettingTileSetSerializer(
                data={
                    "tile_set": TileSetMinimalSerializer(tile_set).data,
                    "geometry_bbox": self._serialize_geometry_bbox(tile_set.bbox),
                }
            )
            setting_tile_sets.append(setting_tile_set.initial_data)

        return setting_tile_sets, global_geometry_bbox

    def _serialize_geometry_bbox(self, bbox) -> Optional[Dict]:
        """Serialize geometry bounding box to GeoJSON."""
        if not bbox:
            return None
        return json.loads(GEOSGeometry(bbox).geojson)

    def _get_object_types_data(self) -> List[Dict]:
        """Get object types data with status information."""
        object_types_with_status = (
            self.user_permission.get_user_object_types_with_status()
        )
        setting_object_types = []

        for object_type, status in object_types_with_status:
            setting_object_type = MapSettingObjectTypeSerializer(
                {
                    "object_type": ObjectTypeSerializer(object_type).data,
                    "object_type_category_object_type_status": status,
                }
            )
            setting_object_types.append(setting_object_type.data)

        return setting_object_types

    def _get_custom_zones_data(self) -> tuple[List[Dict], Dict]:
        """Get organized custom zones data with permissions."""
        geo_custom_zones_data = GeoCustomZone.objects.order_by(
            *GEO_CUSTOM_ZONES_ORDER_BYS
        ).filter(geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE)

        if self.user.user_role != UserRole.SUPER_ADMIN:
            geo_custom_zones_data = geo_custom_zones_data.filter(
                user_groups_custom_geo_zones__user_user_groups__user=self.user
            )

        geo_custom_zones_data = geo_custom_zones_data.select_related(
            "geo_custom_zone_category"
        ).all()

        geo_custom_zones_uncategorized = []
        geo_custom_zone_categories_map = {}

        for geo_custom_zone in geo_custom_zones_data:
            if not geo_custom_zone.geo_custom_zone_category:
                geo_custom_zones_uncategorized.append(
                    GeoCustomZoneMinimalSerializer(geo_custom_zone).data
                )
                continue

            category_uuid = geo_custom_zone.geo_custom_zone_category.uuid
            if geo_custom_zone_categories_map.get(category_uuid) is None:
                geo_custom_zone_categories_map[category_uuid] = {
                    "geo_custom_zone_category": geo_custom_zone.geo_custom_zone_category,
                    "geo_custom_zones": [],
                }

            geo_custom_zone_categories_map[category_uuid]["geo_custom_zones"].append(
                GeoCustomZoneMinimalSerializer(geo_custom_zone).data
            )

        return geo_custom_zones_uncategorized, geo_custom_zone_categories_map
