from collections import defaultdict
from typing import List, Optional
from core.models.geo_zone import GeoZone, GeoZoneType
from core.models.user import User, UserRole
from core.permissions.base import BasePermission
from core.repository.base import CollectivityRepoFilter
from core.repository.user import UserRepository

from django.contrib.gis.geos.collections import MultiPolygon
from django.db.models import QuerySet
from django.contrib.gis.db.models.aggregates import Union
from django.contrib.gis.db.models.functions import Intersection
from django.core.exceptions import BadRequest


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

        if self.user.user_role != UserRole.SUPER_ADMIN:
            geo_zones_accessibles_qs = geo_zones_accessibles_qs.filter(
                user_groups__user_user_groups__user=self.user
            )

        geo_zones_accessibles_qs.values("id", "geo_zone_type")

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
        self, intersects_geometry: Optional[MultiPolygon] = None
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
        accessible_geometry = geo_zones_accessibles.aggregate(
            total_geo_union=Union("geometry_union")
        ).get("total_geo_union")

        return None if accessible_geometry.empty else accessible_geometry
