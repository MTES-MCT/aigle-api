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
from django.db.models import QuerySet
from django.contrib.gis.db.models.aggregates import Union
from django.contrib.gis.db.models.functions import Intersection, Envelope
from django.core.exceptions import BadRequest
from django.core.exceptions import PermissionDenied

if TYPE_CHECKING:
    from django.contrib.gis.geos import GEOSGeometry


class UserPermission(
    BasePermission[User],
):
    def __init__(
        self,
        user: User,
        initial_queryset: Optional[QuerySet[User]] = None,
        scoped_user_group: Optional[UserGroup] = None,
    ):
        self.repository = UserRepository(initial_queryset=initial_queryset)
        self.user = user
        self.scoped_user_group = scoped_user_group

    def _is_unrestricted(self) -> bool:
        return (
            self.user.user_role == UserRole.SUPER_ADMIN
            and self.scoped_user_group is None
        )

    def get_collectivity_filter(
        self,
        communes_uuids: Optional[List[str]] = None,
        departments_uuids: Optional[List[str]] = None,
        regions_uuids: Optional[List[str]] = None,
    ) -> Optional[CollectivityRepoFilter]:
        if self._is_unrestricted() and (
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
        elif self.scoped_user_group:
            geo_zones_accessibles_qs = geo_zones_accessibles_qs.filter(
                user_groups=self.scoped_user_group
            )
        elif not self._is_unrestricted():
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

        if not self._is_unrestricted() and collectivity_filter.is_empty():
            raise BadRequest("User do not have access to any collectivity")

        return collectivity_filter

    def get_accessible_geometry(
        self,
        intersects_geometry: Optional[MultiPolygon] = None,
        bbox: Optional[bool] = False,
    ) -> Optional[MultiPolygon]:
        if self._is_unrestricted():
            return intersects_geometry

        if self.scoped_user_group:
            geo_zones_accessibles = GeoZone.objects.filter(
                user_groups=self.scoped_user_group
            )
        else:
            geo_zones_accessibles = GeoZone.objects.filter(
                user_groups__user_user_groups__user=self.user
            )

        if intersects_geometry:
            agg_expr = Intersection(Union("geometry"), intersects_geometry)
        else:
            agg_expr = Union("geometry")

        if bbox:
            agg_expr = Envelope(agg_expr)

        accessible_geometry = geo_zones_accessibles.aggregate(result=agg_expr).get(
            "result"
        )

        if accessible_geometry is None or accessible_geometry.empty:
            return None

        return accessible_geometry

    def _has_rights(
        self,
        geometry: MultiPolygon,
        user_group_right: UserGroupRight,
        raise_exception: bool = False,
    ):
        if self._is_unrestricted():
            return True

        if self.scoped_user_group:
            geo_zones_editables = GeoZone.objects.filter(
                user_groups=self.scoped_user_group,
            )
        else:
            geo_zones_editables = GeoZone.objects.filter(
                user_groups__user_user_groups__user=self.user,
                user_groups__user_user_groups__user_group_rights__contains=[
                    user_group_right
                ],
            )
        geo_zones_editables = geo_zones_editables.annotate(
            geometry_union=Union("geometry"),
        )
        geo_zones_editables = geo_zones_editables.filter(
            geometry_union__contains=geometry
        )

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
        if self._is_unrestricted():
            object_types = ObjectType.objects.order_by("name").all()
            return [
                (object_type, ObjectTypeCategoryObjectTypeStatus.VISIBLE)
                for object_type in object_types
            ]

        if self.scoped_user_group:
            object_type_categories = list(
                self.scoped_user_group.object_type_categories.prefetch_related(
                    "object_type_category_object_types",
                    "object_type_category_object_types__object_type",
                ).all()
            )
        else:
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
        if self._is_unrestricted():
            return [
                UserGroupRight.WRITE,
                UserGroupRight.ANNOTATE,
                UserGroupRight.READ,
            ]

        if self.scoped_user_group:
            from django.db.models import Q
            from functools import reduce
            from operator import or_

            point_filters = reduce(
                or_,
                [Q(geometry__contains=point) for point in points],
            )
            has_coverage = GeoZone.objects.filter(
                point_filters,
                user_groups=self.scoped_user_group,
            ).exists()

            if has_coverage:
                res = [
                    UserGroupRight.WRITE,
                    UserGroupRight.ANNOTATE,
                    UserGroupRight.READ,
                ]
            else:
                res = []

            if raise_if_has_no_right and raise_if_has_no_right not in res:
                raise PermissionDenied(
                    "Vous n'avez pas les droits pour éditer cette zone"
                )

            return res

        from django.db.models import Q
        from functools import reduce
        from operator import or_

        point_filters = reduce(
            or_,
            [Q(user_group__geo_zones__geometry__contains=point) for point in points],
        )

        matching_groups = (
            self.user.user_user_groups.filter(point_filters)
            .values_list("user_group_rights", flat=True)
            .distinct()
        )

        user_group_rights = set()
        for rights in matching_groups:
            user_group_rights.update(rights)

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
