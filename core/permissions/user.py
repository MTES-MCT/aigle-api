from collections import defaultdict
from typing import List, Optional
from core.models.geo_zone import GeoZone, GeoZoneType
from core.models.user import User, UserRole
from core.models.user_group import UserGroupRight
from core.permissions.base import BasePermission
from core.repository.base import CollectivityRepoFilter
from core.repository.user import UserRepository

from django.contrib.gis.geos.collections import MultiPolygon
from django.db.models import QuerySet
from django.contrib.gis.db.models.aggregates import Union
from django.contrib.gis.db.models.functions import Intersection, Envelope
from django.core.exceptions import BadRequest
from django.core.exceptions import PermissionDenied


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
        geometry_union = Union("geometry")

        if intersects_geometry:
            geometry_union = Intersection(geometry_union, intersects_geometry)

        geo_zones_accessibles = geo_zones_accessibles.annotate(
            geometry_union=geometry_union
        )

        total_geometry = Union("geometry_union")

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
        geometry_union = Union("geometry")
        geo_zones_editables = geo_zones_editables.annotate(
            geometry_union=geometry_union
        )
        geo_zones_editables.filter(geometry_union__contains=geometry)

        can_edit = geo_zones_editables.exists()

        if raise_exception and not can_edit:
            raise PermissionDenied(
                "Vous n'avez pas les droits suffisants sur ces détections"
            )

        return can_edit

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
