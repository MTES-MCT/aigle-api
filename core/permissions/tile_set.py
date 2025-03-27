from collections import defaultdict
from typing import Optional
from core.models.geo_zone import GeoZone, GeoZoneType
from core.models.tile_set import TileSet
from core.models.user import User
from core.permissions.base import BasePermission
from django.db.models import QuerySet

from core.repository.base import CollectivityRepoFilter
from core.repository.tile_set import TileSetRepository


class TileSetPermission(
    BasePermission[TileSet],
):
    def __init__(
        self, user: User, initial_queryset: Optional[QuerySet[TileSet]] = None
    ):
        self.repository = TileSetRepository(initial_queryset=initial_queryset)
        self.user = user

    def list_(self, *args, **kwargs):
        geo_zones_accessibles = (
            GeoZone.objects.filter(user_groups__user_user_groups__user=self.user)
            .values("id", "geo_zone_type")
            .all()
        )
        geo_zones_accessibles_map = defaultdict(list)

        for geo_zone in geo_zones_accessibles:
            geo_zones_accessibles_map[geo_zone["geo_zone_type"]].append(geo_zone["id"])

        if not kwargs.get("filter_collectivities"):
            kwargs["filter_collectivities"] = CollectivityRepoFilter(
                commune_ids=geo_zones_accessibles_map.get(GeoZoneType.COMMUNE),
                department_ids=geo_zones_accessibles_map.get(GeoZoneType.DEPARTMENT),
                region_ids=geo_zones_accessibles_map.get(GeoZoneType.REGION),
            )
        else:
            if kwargs["filter_collectivities"].commune_ids is not None:
                kwargs["filter_collectivities"].commune_ids = list(
                    set(geo_zones_accessibles_map.get(GeoZoneType.COMMUNE))
                    & set(kwargs["filter_collectivities"].commune_ids)
                )

            if kwargs["filter_collectivities"].department_ids is not None:
                kwargs["filter_collectivities"].department_ids = list(
                    set(geo_zones_accessibles_map.get(GeoZoneType.DEPARTMENT))
                    & set(kwargs["filter_collectivities"].department_ids)
                )

            if kwargs["filter_collectivities"].region_ids is not None:
                kwargs["filter_collectivities"].region_ids = list(
                    set(geo_zones_accessibles_map.get(GeoZoneType.REGION))
                    & set(kwargs["filter_collectivities"].region_ids)
                )

        return self.repository.list_(*args, **kwargs)
