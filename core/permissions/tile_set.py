from collections import defaultdict
from typing import List, Optional
from core.models.geo_zone import GeoZone, GeoZoneType
from core.models.tile_set import TileSet, TileSetType
from core.models.user import User
from core.permissions.base import BasePermission
from django.db.models import QuerySet
from functools import reduce
from operator import or_
from django.db.models import Q, F
from django.db.models.expressions import Window
from django.db.models.functions import RowNumber

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
        self.filter_(*args, **kwargs)
        return self.repository.list_(
            *args,
            **kwargs,
        )

    def filter_(self, *args, **kwargs):
        geo_zones_accessibles = GeoZone.objects.filter(
            user_groups__user_user_groups__user=self.user
        ).values("id", "geo_zone_type")

        geo_zones_accessibles_map = defaultdict(list)

        for geo_zone in geo_zones_accessibles:
            geo_zones_accessibles_map[geo_zone["geo_zone_type"]].append(geo_zone["id"])

        # we filter initial queryset with the geo zones accessible to the user
        self.repository.initial_queryset = self.repository.filter_(
            queryset=self.repository.initial_queryset,
            filter_collectivities=CollectivityRepoFilter(
                commune_ids=geo_zones_accessibles_map.get(GeoZoneType.COMMUNE),
                department_ids=geo_zones_accessibles_map.get(GeoZoneType.DEPARTMENT),
                region_ids=geo_zones_accessibles_map.get(GeoZoneType.REGION),
            ),
        )

        # here, if filter_collectivities is set, we apply second filter with specified filter_collectivities
        self.repository.initial_queryset = self.repository.filter_(
            queryset=self.repository.initial_queryset, *args, **kwargs
        )

        return self.repository.initial_queryset

    def get_last_detections_filters(self, *args, **kwargs) -> Optional[Q]:
        # TODO: do not use intersection BUT collectivities ids
        queryset = self.filter_(
            *args,
            **kwargs,
            with_intersection=True,
            with_geozone_ids=True,
            order_bys=["-date"],
        )
        # if tilesets have exactly the same geozones, we only retrieve the most recent
        tile_sets = queryset.annotate(
            row_number=Window(
                expression=RowNumber(),
                partition_by=[F("geo_zones")],  # Group by GeoZone
                order_by=F("date").desc(),
            )
        ).filter(row_number=1)

        wheres: List[Q] = []

        for i in range(len(tile_sets)):
            tile_set = tile_sets[i]
            previous_tile_sets = tile_sets[:i]
            where = Q(tile_set__uuid=tile_set.uuid)

            where &= Q(geometry__intersects=tile_set.intersection)

            for previous_tile_set in previous_tile_sets:
                # custom logic here: we want to display the detections on the last tileset
                # if the last tileset for a zone is partial, we also want to display detections for the last BACKGROUND tileset
                if (
                    tile_set.tile_set_type == TileSetType.BACKGROUND
                    and previous_tile_set.tile_set_type == TileSetType.PARTIAL
                ):
                    continue

                where &= ~Q(geometry__intersects=previous_tile_set.intersection)

            wheres.append(where)

        if not wheres:
            return None

        if len(wheres) == 1:
            return wheres[0]

        return reduce(or_, wheres)
