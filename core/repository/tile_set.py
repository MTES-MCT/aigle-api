from typing import List, Optional
from django.db.models import QuerySet

from core.constants.order_by import TILE_SETS_ORDER_BYS
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
from django.db.models import Q, Subquery, OuterRef
from django.contrib.gis.geos import Polygon, Point, MultiPolygon
from django.contrib.postgres.aggregates import ArrayAgg
from django.contrib.gis.db.models.functions import Intersection, Envelope
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
        self.initial_queryset = (
            initial_queryset if initial_queryset is not None else self.model.objects
        )

    def filter_(
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
        filter_has_collectivities: bool = False,
        filter_detection_object_id_in: Optional[List[int]] = None,
        filter_detection_id_in: Optional[List[int]] = None,
        with_intersection: bool = False,
        with_bbox: bool = False,
        with_geozone_ids: bool = False,
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

        # annotations
        queryset = self._annotate_intersection(
            queryset=queryset,
            with_intersection=with_intersection,
            filter_tile_set_intersects_geometry=filter_tile_set_intersects_geometry,
        )
        queryset = self._annotate_bbox(
            queryset=queryset,
            with_bbox=with_bbox,
        )
        queryset = self._annotate_geozone_ids(
            queryset=queryset,
            with_geozone_ids=with_geozone_ids,
        )
        queryset = self._annotate_collectivities_count(
            queryset=queryset,
            filter_has_collectivities=filter_has_collectivities,
            filter_collectivities=filter_collectivities,
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

        queryset = self._filter_detection_object_id_in(
            queryset=queryset,
            filter_detection_object_id_in=filter_detection_object_id_in,
        )

        queryset = self._filter_detection_id_in(
            queryset=queryset, filter_detection_id_in=filter_detection_id_in
        )

        queryset = self.order_by(queryset=queryset, order_bys=order_bys)

        return queryset

    @staticmethod
    def _annotate_intersection(
        queryset: QuerySet[TileSet],
        with_intersection: bool = False,
        filter_tile_set_intersects_geometry: Optional[MultiPolygon] = None,
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
    def _annotate_bbox(queryset: QuerySet[TileSet], with_bbox: bool = False):
        if not with_bbox:
            return queryset

        # Use a subquery to avoid duplicates from the many-to-many relationship
        bbox_subquery = (
            TileSet.objects.filter(id=OuterRef("id"))
            .annotate(bbox_calc=Envelope(Union(F("geo_zones__geometry"))))
            .values("bbox_calc")[:1]
        )

        queryset = queryset.annotate(bbox=Subquery(bbox_subquery))

        return queryset

    @staticmethod
    def _annotate_geozone_ids(
        queryset: QuerySet[TileSet],
        with_geozone_ids: bool = False,
    ):
        if not with_geozone_ids:
            return queryset

        queryset = queryset.annotate(geo_zone_ids=ArrayAgg("geo_zones__id"))

        return queryset

    @staticmethod
    def _annotate_collectivities_count(
        queryset: QuerySet[TileSet],
        filter_collectivities: Optional[CollectivityRepoFilter] = None,
        filter_has_collectivities: Optional[bool] = None,
    ):
        if (
            filter_collectivities is not None and not filter_collectivities.is_empty()
        ) or filter_has_collectivities:
            queryset = queryset.annotate(geo_zones_count=Count("geo_zones"))

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
    def _filter_has_collectivities(
        queryset: QuerySet[TileSet],
        filter_has_collectivities: Optional[bool] = None,
    ) -> QuerySet[TileSet]:
        if filter_has_collectivities is not None:
            q = Q(geo_zones_count__gt=0)
            queryset = queryset.filter(q)

        return queryset

    @staticmethod
    def _filter_collectivities(
        queryset: QuerySet[TileSet],
        filter_collectivities: Optional[CollectivityRepoFilter] = None,
    ) -> QuerySet[TileSet]:
        if filter_collectivities is not None and not filter_collectivities.is_empty():
            q = Q()
            queryset = queryset.annotate(geo_zones_count=Count("geo_zones"))
            q |= Q(geo_zones_count=0)

            if filter_collectivities.commune_ids:
                q |= (
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
                q |= (
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
                q |= (
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
                                    id__in=filter_collectivities.region_ids
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

    @staticmethod
    def _filter_detection_object_id_in(
        queryset: QuerySet[TileSet],
        filter_detection_object_id_in: Optional[List[int]] = None,
    ) -> QuerySet[TileSet]:
        if filter_detection_object_id_in is not None:
            q = Q(detections__detection_object__id__in=filter_detection_object_id_in)
            queryset = queryset.filter(q)

        return queryset

    @staticmethod
    def _filter_detection_id_in(
        queryset: QuerySet[TileSet],
        filter_detection_id_in: Optional[List[int]] = None,
    ) -> QuerySet[TileSet]:
        if filter_detection_id_in is not None:
            q = Q(detections__id__in=filter_detection_id_in)
            queryset = queryset.filter(q)

        return queryset
