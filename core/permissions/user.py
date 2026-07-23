import logging
from collections import defaultdict
from typing import List, Optional, Tuple
from core.models.geo_zone import GeoZone, GeoZoneType
from core.models.object_type import ObjectType
from core.models.object_type_category import ObjectTypeCategoryObjectTypeStatus
from core.models.user import User, UserRole
from core.models.user_group import UserGroupRight, UserGroup
from core.permissions.base import BasePermission
from core.repository.base import CollectivityRepoFilter
from core.repository.user import UserRepository
from core.utils.cache import (
    get_or_compute,
    get_user_geo_cache_key,
    USER_GEO_CACHE_TTL,
)

from django.contrib.gis.geos import Point
from django.contrib.gis.geos.collections import MultiPolygon
from django.db.models import Q, QuerySet
from django.contrib.gis.db.models.aggregates import Union
from django.contrib.gis.db.models.functions import Intersection
from django.core.exceptions import BadRequest
from django.core.exceptions import PermissionDenied

logger = logging.getLogger(__name__)


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

    @classmethod
    def from_request(
        cls,
        request,
        initial_queryset: Optional[QuerySet[User]] = None,
    ) -> "UserPermission":
        from core.permissions.scope import resolve_scoped_user_group

        return cls(
            user=request.user,
            initial_queryset=initial_queryset,
            scoped_user_group=resolve_scoped_user_group(request),
        )

    def is_unrestricted(self) -> bool:
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
        if self.is_unrestricted() and (
            communes_uuids is None
            and departments_uuids is None
            and regions_uuids is None
        ):
            return None

        geo_zones_accessibles_qs = GeoZone.objects

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
        elif not self.is_unrestricted():
            geo_zones_accessibles_qs = geo_zones_accessibles_qs.filter(
                user_groups__user_user_groups__user=self.user
            )

        geo_zones_accessibles = geo_zones_accessibles_qs.all()
        collectivity_repo_filter_dict = defaultdict(list)

        for geo_zone in geo_zones_accessibles:
            collectivity_repo_filter_dict[geo_zone.geo_zone_type].append(geo_zone.id)

        # Sort the id lists so the tileset-filter cache hash (which stringifies this
        # filter) is stable regardless of DB row order, keeping the hit rate up.
        commune_ids = collectivity_repo_filter_dict.get(GeoZoneType.COMMUNE)
        department_ids = collectivity_repo_filter_dict.get(GeoZoneType.DEPARTMENT)
        region_ids = collectivity_repo_filter_dict.get(GeoZoneType.REGION)
        collectivity_filter = CollectivityRepoFilter(
            commune_ids=sorted(commune_ids) if commune_ids else commune_ids,
            department_ids=sorted(department_ids) if department_ids else department_ids,
            region_ids=sorted(region_ids) if region_ids else region_ids,
        )

        if not self.is_unrestricted() and collectivity_filter.is_empty():
            raise BadRequest("User do not have access to any collectivity")

        return collectivity_filter

    def accessible_geo_zones(
        self, user_group_right: Optional[UserGroupRight] = None
    ) -> QuerySet[GeoZone]:
        """Geo zones accessible to the user, optionally restricted to those they hold
        the given right on. Impersonation ignores the right: it implies full rights on
        the impersonated group's zones."""
        if self.scoped_user_group:
            return GeoZone.objects.filter(user_groups=self.scoped_user_group)

        if user_group_right is None:
            return GeoZone.objects.filter(user_groups__user_user_groups__user=self.user)

        # Both conditions MUST stay inside a single filter() call: split into chained
        # filters, Django joins the multi-valued relation twice, so a user holding only
        # READ on a group would be granted its zones through ANOTHER user's WRITE
        # membership of that same group.
        return GeoZone.objects.filter(
            user_groups__user_user_groups__user=self.user,
            user_groups__user_user_groups__user_group_rights__contains=[
                user_group_right
            ],
        )

    def _compute_accessible_union(self) -> Optional[MultiPolygon]:
        """Union of the user's accessible geo-zone geometries (the cached value).
        Returns None for an empty/absent union so it is not cached."""
        union = (
            self.accessible_geo_zones()
            .aggregate(result=Union("geometry"))
            .get("result")
        )
        if union is None or union.empty:
            return None
        return union

    def get_accessible_geometry(
        self,
        intersects_geometry: Optional[MultiPolygon] = None,
        bbox: Optional[bool] = False,
    ) -> Optional[MultiPolygon]:
        if self.is_unrestricted():
            return intersects_geometry

        scoped_group_id = self.scoped_user_group.id if self.scoped_user_group else None
        cache_key = get_user_geo_cache_key(self.user.id, scoped_group_id)
        base_union = get_or_compute(
            cache_key, self._compute_accessible_union, USER_GEO_CACHE_TTL
        )
        if base_union is None:
            return None

        result = base_union
        if intersects_geometry:
            try:
                result = result.intersection(intersects_geometry)
            except Exception:
                # GEOS can raise (e.g. TopologyException) on a self-intersecting IGN
                # union. This is the only non-PostGIS geometry op in the map hot path
                # and sits outside the fail-open cache wrappers, so guard it: recompute
                # the intersection in PostGIS (robust), scoped to the SAME accessible
                # zones — no isolation impact, just a slower correct answer.
                logger.exception(
                    "GEOS intersection failed for user %s; falling back to PostGIS",
                    self.user.id,
                )
                result = (
                    self.accessible_geo_zones()
                    .aggregate(
                        result=Intersection(Union("geometry"), intersects_geometry)
                    )
                    .get("result")
                )
                if result is None or result.empty:
                    return None

        if bbox:
            result = result.envelope

        if result.empty:
            return None

        return result

    def get_user_object_types_with_status(
        self,
    ) -> List[Tuple[ObjectType, ObjectTypeCategoryObjectTypeStatus]]:
        if self.is_unrestricted():
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

    def resolve_object_type_uuids(
        self, requested_uuids: Optional[List[str]] = None
    ) -> List[str]:
        """Object type uuids the caller is allowed to query.

        Passing none means "all the granted ones", not "no filter".

        When impersonating, requested uuids are additionally intersected with the
        group's grants so a stale URL cannot show a SUPER_ADMIN object types the
        group does not own. Outside impersonation the requested list is honoured
        as-is: many real groups have no object_type_categories configured, and
        narrowing there would blank their map — a separate, pre-existing gap.
        """
        granted_uuids = [
            object_type.uuid
            for object_type, _ in self.get_user_object_types_with_status()
        ]

        if not requested_uuids:
            return granted_uuids

        if not self.scoped_user_group:
            return requested_uuids

        requested = {str(uuid) for uuid in requested_uuids}
        return [uuid for uuid in granted_uuids if str(uuid) in requested]

    def get_user_group_rights(
        self,
        points: List[Point],
        raise_if_has_no_right: Optional[UserGroupRight] = None,
    ) -> List[UserGroupRight]:
        if self.is_unrestricted():
            return [
                UserGroupRight.WRITE,
                UserGroupRight.ANNOTATE,
                UserGroupRight.READ,
            ]

        if self.scoped_user_group:
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

    def validate_user_group_access(self, user_group_ids: List[str]) -> None:
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
        existing_user_group_ids = [
            str(ug.id) for ug in detection_object.user_groups.all()
        ]
        if existing_user_group_ids:
            self.validate_user_group_access(user_group_ids=existing_user_group_ids)
