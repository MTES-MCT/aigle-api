from typing import Optional
from core.models.geo_zone import GeoZone
from core.models.user import User
from core.permissions.base import BasePermission
from core.repository.user import UserRepository

from django.contrib.gis.geos.collections import MultiPolygon
from django.db.models import QuerySet
from django.contrib.gis.db.models.aggregates import Union
from django.contrib.gis.db.models.functions import Intersection


class UserPermission(
    BasePermission[User],
):
    def __init__(self, user: User, initial_queryset: Optional[QuerySet[User]] = None):
        self.repository = UserRepository(initial_queryset=initial_queryset)
        self.user = user

    def get_accessible_geometry(
        self, intersects_geometry: Optional[MultiPolygon] = None
    ) -> MultiPolygon:
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
        return accessible_geometry
