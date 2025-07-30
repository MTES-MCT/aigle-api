from typing import List, Optional
from django.contrib.gis.geos import Polygon
from django.db.models import QuerySet

from core.constants.geo import SRID
from core.models.tile_set import TileSetType, TileSetStatus
from core.permissions.user import UserPermission
from core.permissions.tile_set import TileSetPermission
from core.repository.detection import (
    DetectionRepository,
    RepoFilterCustomZone,
    RepoFilterInterfaceDrawn,
)


class DetectionGeoFilterService:
    """Service for handling complex geographic detection filtering logic."""

    def __init__(self, user):
        self.user = user

    def apply_filters(self, queryset: QuerySet, filter_params: dict) -> QuerySet:
        """Apply geographic filtering logic to detection queryset."""
        # Filter by object types
        queryset = self._filter_by_object_types(queryset, filter_params)

        # Apply geographic and tile set filtering
        queryset = self._apply_geographic_filtering(queryset, filter_params)

        # Apply custom zone filtering
        return self._apply_custom_zone_filtering(queryset, filter_params)

    def _filter_by_object_types(
        self, queryset: QuerySet, filter_params: dict
    ) -> QuerySet:
        """Filter queryset by object types."""
        object_types_uuids = self._get_object_types_uuids(filter_params)
        return queryset.filter(
            detection_object__object_type__uuid__in=object_types_uuids
        )

    def _get_object_types_uuids(self, filter_params: dict) -> List[str]:
        """Get object type UUIDs from parameters or user permissions."""
        object_types_uuids = (
            filter_params.get("objectTypesUuids").split(",")
            if filter_params.get("objectTypesUuids")
            else []
        )

        if not object_types_uuids:
            user_permission = UserPermission(self.user)
            object_types_with_status = (
                user_permission.get_user_object_types_with_status()
            )
            object_types_uuids = [
                object_type_with_status[0].uuid
                for object_type_with_status in object_types_with_status
            ]

        return object_types_uuids

    def _apply_geographic_filtering(
        self, queryset: QuerySet, filter_params: dict
    ) -> QuerySet:
        """Apply geographic bounding box and tile set filtering."""
        # Get tile set UUIDs
        tile_sets_uuids = (
            filter_params.get("tileSetsUuids").split(",")
            if filter_params.get("tileSetsUuids")
            else []
        )

        # Build polygon from bounding box parameters
        polygon_requested = self._build_polygon_from_bbox(filter_params)

        # Check user permissions for the requested geometry
        geometry_accessible = UserPermission(user=self.user).get_accessible_geometry(
            intersects_geometry=polygon_requested
        )

        if not geometry_accessible:
            return queryset.none()

        # Get detection tile sets filter based on permissions
        detection_tilesets_filter = TileSetPermission(
            user=self.user,
        ).get_last_detections_filters_detections(
            filter_tile_set_type_in=[TileSetType.PARTIAL, TileSetType.BACKGROUND],
            filter_tile_set_status_in=[TileSetStatus.VISIBLE, TileSetStatus.HIDDEN],
            filter_tile_set_intersects_geometry=geometry_accessible,
            filter_tile_set_uuid_in=tile_sets_uuids,
            filter_has_collectivities=True,
        )

        if not detection_tilesets_filter:
            return queryset.none()

        return queryset.filter(detection_tilesets_filter)

    def _build_polygon_from_bbox(self, filter_params: dict) -> Optional[Polygon]:
        """Build polygon from bounding box coordinates."""
        ne_lat = filter_params.get("neLat")
        ne_lng = filter_params.get("neLng")
        sw_lat = filter_params.get("swLat")
        sw_lng = filter_params.get("swLng")

        if not all([ne_lat, ne_lng, sw_lat, sw_lng]):
            return None

        polygon = Polygon.from_bbox((sw_lng, sw_lat, ne_lng, ne_lat))
        polygon.srid = SRID
        return polygon

    def _apply_custom_zone_filtering(
        self, queryset: QuerySet, filter_params: dict
    ) -> QuerySet:
        """Apply custom zone filtering logic."""
        filter_custom_zone = RepoFilterCustomZone(
            custom_zone_uuids=(
                filter_params.get("customZonesUuids").split(",")
                if filter_params.get("customZonesUuids")
                else []
            ),
            interface_drawn=RepoFilterInterfaceDrawn[
                filter_params.get(
                    "interfaceDrawn",
                    RepoFilterInterfaceDrawn.INSIDE_SELECTED_ZONES.value,
                )
            ],
        )

        return DetectionRepository(initial_queryset=queryset).list_(
            filter_custom_zone=filter_custom_zone
        )
