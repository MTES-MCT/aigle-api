from collections import defaultdict
from django.utils import timezone
from typing import List, Optional, TypedDict
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
from django.contrib.gis.geos.collections import MultiPolygon

from core.repository.base import CollectivityRepoFilter
from core.repository.tile_set import TileSetRepository


class TileSetPreview(TypedDict):
    tile_set: TileSet
    preview: bool


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

    def get_previews(
        self,
        filter_tile_set_intersects_geometry: Optional[MultiPolygon] = None,
        *args,
        **kwargs,
    ) -> List[TileSetPreview]:
        queryset = self.filter_(
            filter_tile_set_type_in=[TileSetType.PARTIAL, TileSetType.BACKGROUND],
            filter_tile_set_intersects_geometry=filter_tile_set_intersects_geometry,
            order_bys=["-date"],
            *args,
            **kwargs,
        )
        tile_sets = list(queryset.all())

        tile_sets_most_recent_map = {}
        tile_set_six_years = (
            get_tile_set_years_ago(tile_sets=tile_sets, relative_years=6)
            or tile_sets[len(tile_sets) - 1]
        )
        tile_sets_most_recent_map[tile_set_six_years.id] = tile_set_six_years

        # append most recent
        tile_sets_most_recent_map[tile_sets[0].id] = tile_sets[0]

        # fill with most recent that are not already included
        for tile_set in tile_sets:
            if not tile_sets_most_recent_map.get(tile_set.id):
                tile_sets_most_recent_map[tile_set.id] = tile_set
                break

        tile_set_previews = []

        for tile_set in sorted(
            tile_sets_most_recent_map.values(), key=lambda t: t.date
        ):
            tile_set_previews.append(
                {
                    "tile_set": tile_set,
                    "preview": True
                    if tile_sets_most_recent_map.get(tile_set.id)
                    else False,
                }
            )

        return sorted(tile_set_previews, key=lambda tpreview: tpreview["tile_set"].date)

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
        intersects_geometry = kwargs.pop("filter_tile_set_intersects_geometry", None)

        queryset = self.filter_(
            *args,
            **kwargs,
            order_bys=["-date"],
        )
        queryset = queryset.prefetch_related("geo_zones")
        # if tilesets have exactly the same geozones, we only retrieve the most recent
        queryset = queryset.annotate(
            row_number=Window(
                expression=RowNumber(),
                partition_by=[F("geo_zones__id")],  # Group by GeoZone
                order_by=F("date").desc(),
            )
        )
        queryset = queryset.only(
            "id", "tile_set_type", "geo_zones__id", "geo_zones__geo_zone_type"
        )

        if intersects_geometry:
            queryset = queryset.filter(
                geo_zones__geometry__intersects=intersects_geometry
            )

        tile_sets = queryset.filter(row_number=1)

        wheres_zones: List[Q] = []
        wheres: List[Q] = []

        for i in range(len(tile_sets)):
            tile_set = tile_sets[i]
            previous_tile_sets = tile_sets[:i]
            where = Q(tile_set__id=tile_set.id)

            if intersects_geometry:
                where &= Q(geometry__intersects=intersects_geometry)

            geo_zones_map = defaultdict(list)
            for geo_zone in tile_set.geo_zones.all():
                geo_zones_map[geo_zone.geo_zone_type].append(geo_zone.id)

            where_zones = Q()
            if geo_zones_map.get(GeoZoneType.COMMUNE):
                where_zones &= Q(
                    detection_object__commune__id__in=geo_zones_map.get(
                        GeoZoneType.COMMUNE
                    )
                )
            if geo_zones_map.get(GeoZoneType.DEPARTMENT):
                where_zones &= Q(
                    detection_object__commune__department__id__in=geo_zones_map.get(
                        GeoZoneType.DEPARTMENT
                    )
                )
            if geo_zones_map.get(GeoZoneType.REGION):
                where_zones &= Q(
                    detection_object__commune__department__region__id__in=geo_zones_map.get(
                        GeoZoneType.REGION
                    )
                )
            wheres_zones.append(where_zones)
            where &= where_zones

            for i_previous in range(len(previous_tile_sets)):
                previous_tile_set = previous_tile_sets[i_previous]

                # custom logic here: we want to display the detections on the last tileset
                # if the last tileset for a zone is partial, we also want to display detections for the last BACKGROUND tileset
                if (
                    tile_set.tile_set_type == TileSetType.BACKGROUND
                    and previous_tile_set.tile_set_type == TileSetType.PARTIAL
                ):
                    continue

                where &= ~wheres_zones[i_previous]

            wheres.append(where)

        if not wheres:
            return None

        if len(wheres) == 1:
            return wheres[0]

        return reduce(or_, wheres)


def get_tile_set_years_ago(
    tile_sets: List[TileSet], relative_years: int
) -> Optional[TileSet]:
    tile_set_years_ago = None
    date_years_ago = timezone.now()
    date_years_ago = date_years_ago.replace(year=date_years_ago.year - relative_years)

    for tile_set in tile_sets:
        if tile_set.date <= date_years_ago:
            tile_set_years_ago = tile_set
            break

    return tile_set_years_ago
