from typing import Callable, Iterable, Optional, List, Dict, Any, TYPE_CHECKING
from django.db import connection, transaction
from django.contrib.gis.geos import GEOSGeometry, Polygon
from django.contrib.gis.db.models.functions import Intersection

from core.constants.geo import SRID
from core.models.geo_custom_zone import (
    GeoCustomZone,
    GeoCustomZoneCategory,
    GeoCustomZoneStatus,
)
from core.models.user import UserRole
from core.models.user_group import UserGroup

if TYPE_CHECKING:
    from core.models.user import User


def _noop_log(info: str) -> None:  # noqa: ARG001
    pass


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
    def associate_detections_to_custom_zones(
        custom_zone_ids: Iterable[int],
        batch_ids: Optional[List[str]] = None,
        tile_set_uuids: Optional[List[str]] = None,
        log_event: Callable[[str], None] = _noop_log,
    ) -> None:
        """Populate the DetectionObject ↔ GeoCustomZone (and ↔ GeoSubCustomZone)
        M2M tables for the given custom zones, based on spatial intersection
        between each zone geometry and its detections' geometry.

        Filters detections by `batch_ids` (Detection.batch_id values) and
        `tile_set_uuids` (TileSet.uuid values). Either, when omitted, defaults to
        the full population: all distinct batches / all non-INDICATIVE-DEACTIVATED
        tile sets.

        Writes the M2M directly via raw SQL (bypasses the m2m_changed signal), so
        this helper also schedules a count-cache invalidation on commit — the
        caller must not invalidate counts itself.
        """
        from core.models.detection import Detection
        from core.models.tile_set import TileSet, TileSetStatus, TileSetType
        from core.utils.cache import invalidate_count_caches

        custom_zone_id_list = list(custom_zone_ids)
        if not custom_zone_id_list:
            log_event("No custom zones to associate")
            return

        zones = list(
            GeoCustomZone.objects.filter(
                id__in=custom_zone_id_list, geometry__isnull=False
            )
            .prefetch_related("sub_custom_zones")
            .defer("geometry", "sub_custom_zones__geometry")
        )
        if not zones:
            log_event("No custom zones to associate (none have a geometry)")
            return

        if batch_ids is None:
            batch_ids = list(
                Detection.objects.exclude(batch_id=None)
                .values_list("batch_id", flat=True)
                .distinct()
            )

        # Detection.tile_set_id is the FK integer column, but callers identify
        # tile sets by their UUID — resolve to ids here so ANY(%s) gets the
        # correct type.
        if tile_set_uuids is None:
            tile_set_ids = list(
                TileSet.objects.exclude(
                    tile_set_type=TileSetType.INDICATIVE,
                    tile_set_status=TileSetStatus.DEACTIVATED,
                ).values_list("id", flat=True)
            )
        else:
            tile_set_ids = list(
                TileSet.objects.filter(uuid__in=tile_set_uuids).values_list(
                    "id", flat=True
                )
            )

        for zone in zones:
            log_event(f"Associating detections to custom zone: {zone.name}")
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO core_detectionobject_geo_custom_zones (
                        detectionobject_id, geocustomzone_id
                    )
                    SELECT DISTINCT dobj.id, %s
                    FROM core_detectionobject dobj
                    JOIN core_detection detec
                        ON detec.detection_object_id = dobj.id
                    WHERE
                        detec.batch_id = ANY(%s)
                        AND detec.tile_set_id = ANY(%s)
                        AND ST_Intersects(
                            detec.geometry,
                            (SELECT geometry FROM core_geozone WHERE id = %s)
                        )
                    ON CONFLICT DO NOTHING
                    """,
                    [zone.id, batch_ids, tile_set_ids, zone.id],
                )

        sub_zones = [
            sub_zone for zone in zones for sub_zone in zone.sub_custom_zones.all()
        ]
        for sub_zone in sub_zones:
            log_event(f"Associating detections to sub-custom zone: {sub_zone.name}")
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO core_detectionobject_geo_sub_custom_zones (
                        detectionobject_id, geosubcustomzone_id
                    )
                    SELECT DISTINCT dobj.id, %s
                    FROM core_detectionobject dobj
                    JOIN core_detection detec
                        ON detec.detection_object_id = dobj.id
                    WHERE
                        detec.batch_id = ANY(%s)
                        AND detec.tile_set_id = ANY(%s)
                        AND ST_Intersects(
                            detec.geometry,
                            (SELECT geometry FROM core_geozone WHERE id = %s)
                        )
                    ON CONFLICT DO NOTHING
                    """,
                    [sub_zone.id, batch_ids, tile_set_ids, sub_zone.id],
                )

        # Raw-SQL M2M writes bypass m2m_changed; bump the count cache once for
        # the whole operation. on_commit defers under an open atomic block and
        # runs synchronously outside one, so it's safe in both contexts.
        transaction.on_commit(invalidate_count_caches)

    @staticmethod
    def get_filtered_queryset(
        user: "User",
        search_query: Optional[str] = None,
        scoped_user_group: Optional[UserGroup] = None,
    ):
        """Get filtered queryset for geo custom zones."""
        from core.constants.order_by import GEO_CUSTOM_ZONES_ORDER_BYS

        queryset = GeoCustomZone.objects.order_by(*GEO_CUSTOM_ZONES_ORDER_BYS)
        queryset = queryset.prefetch_related("geo_zones")
        queryset = queryset.select_related("geo_custom_zone_category")

        if scoped_user_group is not None:
            queryset = queryset.filter(user_groups_custom_geo_zones=scoped_user_group)
        elif user.user_role == UserRole.ADMIN:
            queryset = queryset.filter(
                id__in=user.user_user_groups.values_list(
                    "user_group__geo_custom_zones__id", flat=True
                )
            )

        if search_query:
            queryset = queryset.filter(name__icontains=search_query)

        return queryset
