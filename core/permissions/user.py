from collections import defaultdict
from typing import List, Optional, Tuple, TYPE_CHECKING
from core.models.geo_zone import GeoZone, GeoZoneType
from core.models.object_type import ObjectType
from core.models.object_type_category import ObjectTypeCategoryObjectTypeStatus
from core.models.user import User, UserRole
from core.models.user_group import UserGroupRight, UserGroup
from core.permissions.base import BasePermission
from core.repository.base import CollectivityRepoFilter
from core.repository.user import UserRepository

from django.contrib.gis.geos import Point
from django.contrib.gis.geos.collections import MultiPolygon
from django.db.models import QuerySet, Count, Case, When, F
from django.contrib.gis.db.models.aggregates import Union
from django.contrib.gis.db.models.fields import GeometryField
from django.contrib.gis.db.models.functions import Intersection, Envelope
from django.core.exceptions import BadRequest
from django.core.exceptions import PermissionDenied

if TYPE_CHECKING:
    from django.contrib.gis.geos import GEOSGeometry


class UserPermission(
    BasePermission[User],
):
    def __init__(self, user: User, initial_queryset: Optional[QuerySet[User]] = None):
        self.repository = UserRepository(initial_queryset=initial_queryset)
        self.user = user

    def get_collectivity_filter(
        self,
        communes_uuids: Optional[List[str]] = None,
        departments_uuids: Optional[List[str]] = None,
        regions_uuids: Optional[List[str]] = None,
    ) -> Optional[CollectivityRepoFilter]:
        if self.user.user_role == UserRole.SUPER_ADMIN and (
            communes_uuids is None
            and departments_uuids is None
            and regions_uuids is None
        ):
            return None

        geo_zones_accessibles_qs = GeoZone.objects

        geo_zones_accessibles_qs.values("id", "geo_zone_type")

        # TODO: rework this to make user user has access to uuids
        if (
            communes_uuids is not None
            or departments_uuids is not None
            or regions_uuids is not None
        ):
            geozone_uuids = (
                (communes_uuids or [])
                + (departments_uuids or [])
                + (regions_uuids or [])
            )
            geo_zones_accessibles_qs = geo_zones_accessibles_qs.filter(
                uuid__in=geozone_uuids
            )
        elif self.user.user_role != UserRole.SUPER_ADMIN:
            geo_zones_accessibles_qs = geo_zones_accessibles_qs.filter(
                user_groups__user_user_groups__user=self.user
            )

        geo_zones_accessibles = geo_zones_accessibles_qs.all()
        collectivity_repo_filter_dict = defaultdict(list)

        for geo_zone in geo_zones_accessibles:
            collectivity_repo_filter_dict[geo_zone.geo_zone_type].append(geo_zone.id)

        collectivity_filter = CollectivityRepoFilter(
            commune_ids=collectivity_repo_filter_dict.get(GeoZoneType.COMMUNE),
            department_ids=collectivity_repo_filter_dict.get(GeoZoneType.DEPARTMENT),
            region_ids=collectivity_repo_filter_dict.get(GeoZoneType.REGION),
        )

        if (
            self.user.user_role != UserRole.SUPER_ADMIN
            and collectivity_filter.is_empty()
        ):
            raise BadRequest("User do not have access to any collectivity")

        return collectivity_filter

    def get_accessible_geometry(
        self,
        intersects_geometry: Optional[MultiPolygon] = None,
        bbox: Optional[bool] = False,
    ) -> Optional[MultiPolygon]:
        # super admins have access to all zones
        if self.user.user_role == UserRole.SUPER_ADMIN:
            return intersects_geometry

        geo_zones_accessibles = GeoZone.objects.filter(
            user_groups__user_user_groups__user=self.user
        )

        geo_zones_accessibles = geo_zones_accessibles.annotate(
            geo_zone_count=Count("id"),
            geometry_union=Case(
                When(geo_zone_count=1, then=F("geometry")),
                default=Union("geometry"),
                output_field=GeometryField(),
            ),
        )

        if intersects_geometry:
            geo_zones_accessibles = geo_zones_accessibles.annotate(
                geometry_union_filtered=Intersection(
                    "geometry_union", intersects_geometry
                )
            )
            union_field = "geometry_union_filtered"
        else:
            union_field = "geometry_union"

        # Handle the case where there might be only one zone
        zones = geo_zones_accessibles.values_list(union_field, flat=True)
        zones_list = list(zones)

        if not zones_list:
            accessible_geometry = None
        elif len(zones_list) == 1:
            accessible_geometry = zones_list[0]
            if bbox:
                accessible_geometry = (
                    accessible_geometry.envelope if accessible_geometry else None
                )
        else:
            total_geometry = Union(union_field)
            if bbox:
                total_geometry = Envelope(total_geometry)

            accessible_geometry = geo_zones_accessibles.aggregate(
                total_geo_union=total_geometry
            ).get("total_geo_union")

        return None if accessible_geometry.empty else accessible_geometry

    def _has_rights(
        self,
        geometry: MultiPolygon,
        user_group_right: UserGroupRight,
        raise_exception: bool = False,
    ):
        if self.user.user_role == UserRole.SUPER_ADMIN:
            return True

        geo_zones_editables = GeoZone.objects.filter(
            user_groups__user_user_groups__user=self.user,
            user_groups__user_user_groups__user_group_rights__contains=[
                user_group_right
            ],
        )
        geo_zones_editables = geo_zones_editables.annotate(
            geo_zone_count=Count("id"),
            geometry_union=Case(
                When(geo_zone_count=1, then=F("geometry")),
                default=Union("geometry"),
                output_field=GeometryField(),
            ),
        )
        geo_zones_editables.filter(geometry_union__contains=geometry)

        can_edit = geo_zones_editables.exists()

        if raise_exception and not can_edit:
            raise PermissionDenied(
                "Vous n'avez pas les droits suffisants sur ces détections"
            )

        return can_edit

    def get_user_object_types_with_status(
        self,
    ) -> List[Tuple[ObjectType, ObjectTypeCategoryObjectTypeStatus]]:
        """Get object types accessible by user with their status."""
        if self.user.user_role == UserRole.SUPER_ADMIN:
            object_types = ObjectType.objects.order_by("name").all()
            return [
                (object_type, ObjectTypeCategoryObjectTypeStatus.VISIBLE)
                for object_type in object_types
            ]

        user_user_groups = self.user.user_user_groups.prefetch_related(
            "user_group",
            "user_group__object_type_categories",
            "user_group__object_type_categories__object_type_category_object_types",
            "user_group__object_type_categories__object_type_category_object_types__object_type",
        ).all()

        object_type_categories = []
        for user_user_group in user_user_groups:
            object_type_categories.extend(
                user_user_group.user_group.object_type_categories.all()
            )

        object_type_uuids_statuses_map = {}
        object_type_category_object_type_status_priorities = {
            ObjectTypeCategoryObjectTypeStatus.VISIBLE: 3,
            ObjectTypeCategoryObjectTypeStatus.OTHER_CATEGORY: 2,
            ObjectTypeCategoryObjectTypeStatus.HIDDEN: 1,
        }

        for object_type_category in object_type_categories:
            for (
                object_type_category_object_type
            ) in object_type_category.object_type_category_object_types.all():
                object_type = object_type_category_object_type.object_type
                status = object_type_category_object_type.object_type_category_object_type_status

                if (
                    object_type_uuids_statuses_map.get(object_type.uuid)
                    and object_type_category_object_type_status_priorities[
                        object_type_uuids_statuses_map.get(object_type.uuid)[1]
                    ]
                    >= object_type_category_object_type_status_priorities[status]
                ):
                    continue

                object_type_uuids_statuses_map[object_type.uuid] = (object_type, status)

        object_types_with_status = []
        for object_type, status in object_type_uuids_statuses_map.values():
            object_types_with_status.append((object_type, status))

        return sorted(object_types_with_status, key=lambda x: x[0].name)

    def get_user_group_rights(
        self,
        points: List[Point],
        raise_if_has_no_right: Optional[UserGroupRight] = None,
    ) -> List[UserGroupRight]:
        """Get user group rights for given points."""
        if self.user.user_role == UserRole.SUPER_ADMIN:
            return [
                UserGroupRight.WRITE,
                UserGroupRight.ANNOTATE,
                UserGroupRight.READ,
            ]

        # First, get user groups with geo zones
        user_user_groups = self.user.user_user_groups.annotate(
            geo_zone_count=Count("user_group__geo_zones")
        ).filter(geo_zone_count__gt=0)

        # Handle union differently based on count per user group
        user_user_groups_with_geometry = []
        for user_user_group in user_user_groups:
            geo_zones = user_user_group.user_group.geo_zones.all()
            if len(geo_zones) == 1:
                union_geometry = geo_zones[0].geometry
            elif len(geo_zones) > 1:
                # Use Union aggregate on the related geo zones
                union_result = user_user_group.user_group.geo_zones.aggregate(
                    union_geom=Union("geometry")
                )
                union_geometry = union_result["union_geom"]
            else:
                continue  # Skip if no geo zones

            # Check if any point is contained in the union geometry
            contains_point = False
            for point in points:
                if union_geometry and union_geometry.contains(point):
                    contains_point = True
                    break

            if contains_point:
                user_user_groups_with_geometry.append(user_user_group)

        user_group_rights = set()
        for user_user_group in user_user_groups_with_geometry:
            user_group_rights.update(user_user_group.user_group_rights)

        res = list(user_group_rights)

        if raise_if_has_no_right and raise_if_has_no_right not in res:
            raise PermissionDenied("Vous n'avez pas les droits pour éditer cette zone")

        return res

    def can_edit(
        self,
        geometry: MultiPolygon,
        raise_exception: bool = False,
    ) -> bool:
        return self._has_rights(
            geometry=geometry,
            user_group_right=UserGroupRight.WRITE,
            raise_exception=raise_exception,
        )

    def can_read(
        self,
        geometry: MultiPolygon,
        raise_exception: bool = False,
    ) -> bool:
        return self._has_rights(
            geometry=geometry,
            user_group_right=UserGroupRight.READ,
            raise_exception=raise_exception,
        )

    def validate_geometry_edit_permission(self, geometry: "GEOSGeometry") -> None:
        """Validate user can edit at given geometry location."""
        self.can_edit(geometry=geometry, raise_exception=True)

    def validate_user_group_access(self, user_group_ids: List[str]) -> None:
        """Validate user has access to specified user groups."""
        if not user_group_ids:
            return

        user_accessible_groups = UserGroup.objects.filter(users=self.user).values_list(
            "id", flat=True
        )

        invalid_groups = set(user_group_ids) - set(
            str(gid) for gid in user_accessible_groups
        )
        if invalid_groups:
            raise PermissionError(
                f"User does not have access to user groups: {invalid_groups}"
            )

    def validate_user_group_access_for_detection_object(self, detection_object) -> None:
        """Validate user has access to modify a detection object based on its user groups."""
        existing_user_group_ids = [
            str(ug.id) for ug in detection_object.user_groups.all()
        ]
        if existing_user_group_ids:
            self.validate_user_group_access(user_group_ids=existing_user_group_ids)
