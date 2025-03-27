from typing import List, Optional
from django.db.models import QuerySet

from core.contants.order_by import TILE_SETS_ORDER_BYS
from core.models.geo_commune import GeoCommune
from core.models.geo_department import GeoDepartment
from core.models.geo_region import GeoRegion
from core.models.geo_zone import GeoZoneType
from core.models.tile_set import TileSet, TileSetStatus, TileSetType
from core.repository.base import (
    BaseRepository,
    CollectivityRepoFilter,
    DateRepoFilter,
    TimestampedBaseRepositoryMixin,
    UuidBaseRepositoryMixin,
)
from django.db.models import Q, Subquery
from django.contrib.gis.geos import Polygon, Point, MultiPolygon
from django.contrib.gis.db.models.functions import Intersection
from django.db.models import F
from django.contrib.gis.db.models import Union
from django.db.models import Count


DEFAULT_VALUES = {
    "filter_tile_set_status_in": [TileSetStatus.VISIBLE, TileSetStatus.HIDDEN],
    "filter_tile_set_type_in": [
        TileSetType.INDICATIVE,
        TileSetType.PARTIAL,
        TileSetType.BACKGROUND,
    ],
    "order_bys": TILE_SETS_ORDER_BYS,
}


class TileSetRepository(
    BaseRepository[TileSet],
    TimestampedBaseRepositoryMixin[TileSet],
    UuidBaseRepositoryMixin[TileSet],
):
    def __init__(self, initial_queryset: Optional[QuerySet[TileSet]] = None):
        self.model = TileSet
        super().__init__(initial_queryset=initial_queryset)

    def _filter(
        self,
        queryset: QuerySet[TileSet],
        filter_created_at: Optional[DateRepoFilter] = None,
        filter_updated_at: Optional[DateRepoFilter] = None,
        filter_uuid_in: Optional[List[str]] = None,
        filter_uuid_notin: Optional[List[str]] = None,
        filter_tile_set_status_in: Optional[List[TileSetStatus]] = None,
        filter_tile_set_type_in: Optional[List[TileSetType]] = None,
        filter_tile_set_contains_point: Optional[Point] = None,
        filter_tile_set_intersects_geometry: Optional[MultiPolygon] = None,
        filter_collectivities: Optional[CollectivityRepoFilter] = None,
        with_intersection: bool = False,
        order_bys: Optional[List[str]] = None,
        *args,
        **kwargs,
    ) -> QuerySet[TileSet]:
        if filter_tile_set_status_in is None:
            filter_tile_set_status_in = DEFAULT_VALUES["filter_tile_set_status_in"]

        if filter_tile_set_type_in is None:
            filter_tile_set_type_in = DEFAULT_VALUES["filter_tile_set_type_in"]

        if order_bys is None:
            order_bys = DEFAULT_VALUES["order_bys"]

        # mixin filters

        queryset = self._filter_timestamped(
            queryset=queryset,
            filter_created_at=filter_created_at,
            filter_updated_at=filter_updated_at,
        )
        queryset = self._filter_uuid(
            queryset=queryset,
            filter_uuid_in=filter_uuid_in,
            filter_uuid_notin=filter_uuid_notin,
        )

        # custom filters

        queryset = self._filter_tile_set_status_in(
            queryset=queryset,
            filter_tile_set_status_in=filter_tile_set_status_in,
        )

        queryset = self._filter_tile_set_type_in(
            queryset=queryset,
            filter_tile_set_type_in=filter_tile_set_type_in,
        )

        queryset = self._filter_tile_set_contains_point(
            queryset=queryset,
            filter_tile_set_contains_point=filter_tile_set_contains_point,
        )

        queryset = self._filter_tile_set_intersects_geometry(
            queryset=queryset,
            filter_tile_set_intersects_geometry=filter_tile_set_intersects_geometry,
        )

        queryset = self._filter_collectivities(
            queryset=queryset,
            filter_collectivities=filter_collectivities,
        )

        queryset = self._annotate_intersection(
            queryset=queryset,
            with_intersection=with_intersection,
            filter_tile_set_intersects_geometry=filter_tile_set_intersects_geometry,
        )
        queryset = self._order_by(queryset=queryset, order_bys=order_bys)

        return queryset

    @staticmethod
    def _annotate_intersection(
        queryset: QuerySet[TileSet],
        with_intersection: bool = False,
        filter_tile_set_intersects_geometry: Optional[Polygon] = None,
    ):
        if not with_intersection:
            return queryset

        intersection = Union(F("geo_zones__geometry"))

        if filter_tile_set_intersects_geometry:
            intersection = Intersection(
                intersection, filter_tile_set_intersects_geometry
            )

        queryset = queryset.annotate(intersection=intersection)

        return queryset

    @staticmethod
    def _filter_tile_set_status_in(
        queryset: QuerySet[TileSet],
        filter_tile_set_status_in: Optional[List[TileSetStatus]] = None,
    ) -> QuerySet[TileSet]:
        if filter_tile_set_status_in is not None:
            q = Q(tile_set_status__in=filter_tile_set_status_in)
            queryset = queryset.filter(q)

        return queryset

    @staticmethod
    def _filter_tile_set_type_in(
        queryset: QuerySet[TileSet],
        filter_tile_set_type_in: Optional[List[TileSetType]] = None,
    ) -> QuerySet[TileSet]:
        if filter_tile_set_type_in is not None:
            q = Q(tile_set_type__in=filter_tile_set_type_in)
            queryset = queryset.filter(q)

        return queryset

    @staticmethod
    def _filter_tile_set_contains_point(
        queryset: QuerySet[TileSet],
        filter_tile_set_contains_point: Optional[Point] = None,
    ) -> QuerySet[TileSet]:
        if filter_tile_set_contains_point is not None:
            q = Q(geo_zones__geometry__contains=filter_tile_set_contains_point)
            queryset = queryset.filter(q)

        return queryset

    @staticmethod
    def _filter_tile_set_intersects_geometry(
        queryset: QuerySet[TileSet],
        filter_tile_set_intersects_geometry: Optional[Polygon] = None,
    ) -> QuerySet[TileSet]:
        if filter_tile_set_intersects_geometry is not None:
            q = Q(geo_zones__geometry__intersects=filter_tile_set_intersects_geometry)
            queryset = queryset.filter(q)

        return queryset

    @staticmethod
    def _filter_collectivities(
        queryset: QuerySet[TileSet],
        filter_collectivities: Optional[CollectivityRepoFilter] = None,
    ) -> QuerySet[TileSet]:
        if filter_collectivities is not None:
            q = Q()
            queryset = queryset.annotate(geo_zones_count=Count("geo_zones"))
            q = q | Q(geo_zones_count=0)

            if filter_collectivities.commune_ids:
                q = q | (
                    (
                        Q(geo_zones__geo_zone_type=GeoZoneType.COMMUNE)
                        & Q(geo_zones__id__in=filter_collectivities.commune_ids)
                    )
                    | (
                        Q(geo_zones__geo_zone_type=GeoZoneType.DEPARTMENT)
                        & Q(
                            geo_zones__id__in=Subquery(
                                GeoCommune.objects.filter(
                                    id__in=filter_collectivities.commune_ids
                                ).values("department__id")
                            )
                        )
                    )
                    | (
                        Q(geo_zones__geo_zone_type=GeoZoneType.REGION)
                        & Q(
                            geo_zones__id__in=Subquery(
                                GeoCommune.objects.filter(
                                    id__in=filter_collectivities.commune_ids
                                ).values("department__region__id")
                            )
                        )
                    )
                )

            if filter_collectivities.department_ids:
                q = q | (
                    (
                        Q(geo_zones__geo_zone_type=GeoZoneType.COMMUNE)
                        & Q(
                            geo_zones__id__in=Subquery(
                                GeoDepartment.objects.filter(
                                    id__in=filter_collectivities.department_ids
                                ).values("communes__id")
                            )
                        )
                    )
                    | (
                        Q(geo_zones__geo_zone_type=GeoZoneType.DEPARTMENT)
                        & Q(geo_zones__id__in=filter_collectivities.department_ids)
                    )
                    | (
                        Q(geo_zones__geo_zone_type=GeoZoneType.REGION)
                        & Q(
                            geo_zones__id__in=Subquery(
                                GeoDepartment.objects.filter(
                                    id__in=filter_collectivities.department_ids
                                ).values("region__id")
                            )
                        )
                    )
                )

            if filter_collectivities.region_ids:
                q = q | (
                    (
                        Q(geo_zones__geo_zone_type=GeoZoneType.COMMUNE)
                        & Q(
                            geo_zones__id__in=Subquery(
                                GeoRegion.objects.filter(
                                    id__in=filter_collectivities.region_ids
                                ).values("departments__communes__id")
                            )
                        )
                    )
                    | (
                        Q(geo_zones__geo_zone_type=GeoZoneType.DEPARTMENT)
                        & Q(
                            geo_zones__id__in=Subquery(
                                GeoRegion.objects.filter(
                                    id__in=filter_collectivities.commune_ids
                                ).values("departments__id")
                            )
                        )
                    )
                    | (
                        Q(geo_zones__geo_zone_type=GeoZoneType.REGION)
                        & Q(geo_zones__id__in=filter_collectivities.region_ids)
                    )
                )

            queryset = queryset.filter(q)

        return queryset
