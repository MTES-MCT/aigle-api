from typing import Optional, List, Dict, Any, TYPE_CHECKING
from django.db import transaction
from django.contrib.gis.geos import GEOSGeometry, Polygon
from django.contrib.gis.db.models.functions import Intersection

from core.constants.geo import SRID
from core.models.geo_custom_zone import (
    GeoCustomZone,
    GeoCustomZoneCategory,
    GeoCustomZoneStatus,
)
from core.models.user_group import UserGroup

if TYPE_CHECKING:
    from core.models.user import User


class GeoCustomZoneService:
    """Service for handling GeoCustomZone business logic."""

    @staticmethod
    def create_custom_zone(
        name: str,
        category: GeoCustomZoneCategory,
        geometry: GEOSGeometry,
        user_group_ids: List[str],
        user,
        color: Optional[str] = None,
        description: Optional[str] = None,
        parent_id: Optional[str] = None,
    ) -> GeoCustomZone:
        """Create a new GeoCustomZone with business logic validation."""
        with transaction.atomic():
            # Validate user permissions for the category
            GeoCustomZoneService._validate_user_permissions(
                user=user, user_group_ids=user_group_ids
            )

            # Create the zone
            custom_zone = GeoCustomZone.objects.create(
                name=name,
                category=category,
                geometry=geometry,
                color=color,
                description=description,
                parent_id=parent_id,
            )

            # Assign user groups
            custom_zone.user_groups.set(user_group_ids)

            return custom_zone

    @staticmethod
    def update_custom_zone(
        custom_zone: GeoCustomZone,
        user,
        name: Optional[str] = None,
        geometry: Optional[GEOSGeometry] = None,
        color: Optional[str] = None,
        description: Optional[str] = None,
        user_group_ids: Optional[List[str]] = None,
    ) -> GeoCustomZone:
        """Update GeoCustomZone with business logic validation."""
        with transaction.atomic():
            # Always validate user has permission to edit existing zone
            existing_user_group_ids = [
                str(ug.id) for ug in custom_zone.user_groups.all()
            ]
            GeoCustomZoneService._validate_user_permissions(
                user=user, user_group_ids=existing_user_group_ids
            )

            # Validate user permissions for new user groups if provided
            if user_group_ids is not None:
                GeoCustomZoneService._validate_user_permissions(
                    user=user, user_group_ids=user_group_ids
                )

            # Update fields
            if name is not None:
                custom_zone.name = name
            if geometry is not None:
                custom_zone.geometry = geometry
            if color is not None:
                custom_zone.color = color
            if description is not None:
                custom_zone.description = description

            custom_zone.save()

            # Update user groups if provided
            if user_group_ids is not None:
                custom_zone.user_groups.set(user_group_ids)

            return custom_zone

    @staticmethod
    def process_geometry_intersections(
        geometry: GEOSGeometry, user_group_ids: List[str]
    ) -> Dict[str, Any]:
        """Process geometry intersections with detection objects."""
        from core.models.detection_object import DetectionObject

        # Find intersecting detection objects using direct model query
        intersecting_objects = DetectionObject.objects.filter(
            location__intersects=geometry, user_groups__id__in=user_group_ids
        ).distinct()

        return {
            "intersecting_count": intersecting_objects.count(),
            "intersecting_objects": list(
                intersecting_objects.values_list("id", flat=True)
            ),
        }

    @staticmethod
    def _validate_user_permissions(user, user_group_ids: List[str]):
        """Validate that user has permission to create/update zones with given user groups."""
        # Check if user has access to all specified user groups
        user_accessible_groups = UserGroup.objects.filter(users=user).values_list(
            "id", flat=True
        )

        invalid_groups = set(user_group_ids) - set(
            str(gid) for gid in user_accessible_groups
        )
        if invalid_groups:
            raise PermissionError(
                f"User does not have access to user groups: {invalid_groups}"
            )

    @staticmethod
    def delete_custom_zone(custom_zone: GeoCustomZone, user: "User") -> bool:
        """Delete custom zone with business logic validation."""
        # Validate user permissions
        user_groups = custom_zone.user_groups.all()
        user_group_ids = [str(ug.id) for ug in user_groups]

        GeoCustomZoneService._validate_user_permissions(
            user=user, user_group_ids=user_group_ids
        )

        with transaction.atomic():
            custom_zone.delete()
            return True

    @staticmethod
    def get_zones_by_geometry(
        ne_lat: float,
        ne_lng: float,
        sw_lat: float,
        sw_lng: float,
        zone_uuids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Get custom zones intersecting with given bounding box geometry."""
        # Create polygon from bounding box
        polygon = Polygon.from_bbox((sw_lng, sw_lat, ne_lng, ne_lat))
        polygon.srid = SRID

        # Build queryset
        queryset = GeoCustomZone.objects.prefetch_related("geo_zones").select_related(
            "geo_custom_zone_category"
        )

        # Filter by specific UUIDs if provided
        if zone_uuids:
            try:
                queryset = queryset.filter(uuid__in=zone_uuids)
            except (ValueError, TypeError):
                # Ignore invalid UUID formats
                pass

        # Filter by active status and intersection
        queryset = queryset.filter(
            geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE,
            geometry__intersects=polygon,
        )

        # Get values and add intersection geometry
        queryset = queryset.values(
            "uuid",
            "name",
            "color",
            "geo_custom_zone_status",
        ).annotate(geometry=Intersection("geometry", polygon))

        return list(queryset.all())

    @staticmethod
    def get_filtered_queryset(user: "User", search_query: Optional[str] = None):
        """Get filtered queryset for geo custom zones."""
        from core.constants.order_by import GEO_CUSTOM_ZONES_ORDER_BYS

        queryset = GeoCustomZone.objects.order_by(*GEO_CUSTOM_ZONES_ORDER_BYS)
        queryset = queryset.prefetch_related("geo_zones")
        queryset = queryset.select_related("geo_custom_zone_category")

        if search_query:
            queryset = queryset.filter(name__icontains=search_query)

        return queryset
