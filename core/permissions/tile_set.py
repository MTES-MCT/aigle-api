from collections import defaultdict
from django.utils import timezone
from typing import List, Optional, TypedDict, Tuple
from core.constants.order_by import TILE_SETS_ORDER_BYS
from core.models.geo_zone import GeoZone, GeoZoneType
from core.models.tile_set import TileSet, TileSetType, TileSetStatus
from core.models.user import User, UserRole
from core.models.user_group import UserUserGroup
from core.permissions.base import BasePermission
from core.utils.postgis import GeometryType, GetGeometryType
from django.db.models import QuerySet, Count, Case, When, F, FloatField
from functools import reduce
from operator import or_
from django.db.models import Q
from django.db.models.expressions import Window
from django.db.models.functions import RowNumber, Cast
from django.contrib.gis.geos import Point
from django.contrib.gis.geos.collections import MultiPolygon
from django.contrib.gis.db.models.functions import Area, Intersection, Union
from django.contrib.gis.db.models.fields import GeometryField

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

        if not tile_sets:
            return []

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

    def get_last_detections_filters_parcels(self, *args, **kwargs):
        return self._get_last_detections_filters(
            detection_object_prefix="detection_objects__",
            detection_prefix="detection_objects__detections__",
            *args,
            **kwargs,
        )

    def get_last_detections_filters_detections(self, *args, **kwargs):
        return self._get_last_detections_filters(
            detection_object_prefix="detection_object__",
            detection_prefix="",
            *args,
            **kwargs,
        )

    def _get_last_detections_filters(
        self, detection_object_prefix: str, detection_prefix: str, *args, **kwargs
    ) -> Optional[Q]:
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
            where = Q(**{f"{detection_prefix}tile_set__id": tile_set.id})

            if intersects_geometry:
                where &= Q(
                    **{f"{detection_prefix}geometry__intersects": intersects_geometry}
                )

            geo_zones_map = defaultdict(list)
            for geo_zone in tile_set.geo_zones.all():
                geo_zones_map[geo_zone.geo_zone_type].append(geo_zone.id)

            where_zones = Q()
            if geo_zones_map.get(GeoZoneType.COMMUNE):
                where_zones &= Q(
                    **{
                        f"{detection_object_prefix}commune__id__in": geo_zones_map.get(
                            GeoZoneType.COMMUNE
                        )
                    }
                )
            if geo_zones_map.get(GeoZoneType.DEPARTMENT):
                where_zones &= Q(
                    **{
                        f"{detection_object_prefix}commune__department__id__in": geo_zones_map.get(
                            GeoZoneType.DEPARTMENT
                        )
                    }
                )
            if geo_zones_map.get(GeoZoneType.REGION):
                where_zones &= Q(
                    **{
                        f"{detection_object_prefix}commune__department__region__id__in": geo_zones_map.get(
                            GeoZoneType.REGION
                        )
                    }
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

    def get_user_tile_sets(
        self,
        filter_tile_set_status__in: Optional[List[TileSetStatus]] = None,
        filter_tile_set_type__in: Optional[List[TileSetType]] = None,
        filter_tile_set_contains_point: Optional[Point] = None,
        filter_tile_set_intersects_geometry: Optional[MultiPolygon] = None,
        filter_tile_set_uuid__in: Optional[List[str]] = None,
        order_bys: Optional[List[str]] = None,
    ) -> Tuple[QuerySet[TileSet], Optional[MultiPolygon]]:
        """Get tile sets accessible by user with optional filters."""
        if filter_tile_set_status__in is None:
            filter_tile_set_status__in = [TileSetStatus.VISIBLE, TileSetStatus.HIDDEN]

        if filter_tile_set_type__in is None:
            filter_tile_set_type__in = [
                TileSetType.INDICATIVE,
                TileSetType.PARTIAL,
                TileSetType.BACKGROUND,
            ]

        if order_bys is None:
            order_bys = TILE_SETS_ORDER_BYS

        if self.user.user_role != UserRole.SUPER_ADMIN:
            final_union = self._get_user_geo_union(filter_tile_set_intersects_geometry)
            intersection = Intersection("union_geometry", final_union)
        else:
            final_union = None
            # We'll handle the intersection in the annotation below
            intersection = None

        tile_sets = TileSet.objects.filter(
            tile_set_status__in=filter_tile_set_status__in,
            tile_set_type__in=filter_tile_set_type__in,
        ).order_by(*order_bys)

        if intersection is not None:
            # User has restricted access
            tile_sets = tile_sets.annotate(
                geo_zone_count=Count("geo_zones"),
                union_geometry=Case(
                    When(geo_zone_count=1, then=F("geo_zones__geometry")),
                    default=Union("geo_zones__geometry"),
                    output_field=GeometryField(),
                ),
                intersection=intersection,
                intersection_type=GetGeometryType("intersection"),
                intersection_area=Cast(Area("intersection"), FloatField()),
            )
        else:
            # No user restriction, handle geometry union and optional intersection
            if filter_tile_set_intersects_geometry:
                tile_sets = tile_sets.annotate(
                    geo_zone_count=Count("geo_zones"),
                    union_geometry=Case(
                        When(geo_zone_count=1, then=F("geo_zones__geometry")),
                        default=Union("geo_zones__geometry"),
                        output_field=GeometryField(),
                    ),
                    intersection=Case(
                        When(
                            geo_zone_count=1,
                            then=Intersection(
                                F("geo_zones__geometry"),
                                filter_tile_set_intersects_geometry,
                            ),
                        ),
                        default=Intersection(
                            Union("geo_zones__geometry"),
                            filter_tile_set_intersects_geometry,
                        ),
                        output_field=GeometryField(),
                    ),
                    intersection_type=GetGeometryType("intersection"),
                    intersection_area=Cast(Area("intersection"), FloatField()),
                )
            else:
                tile_sets = tile_sets.annotate(
                    geo_zone_count=Count("geo_zones"),
                    union_geometry=Case(
                        When(geo_zone_count=1, then=F("geo_zones__geometry")),
                        default=Union("geo_zones__geometry"),
                        output_field=GeometryField(),
                    ),
                    intersection=Case(
                        When(geo_zone_count=1, then=F("geo_zones__geometry")),
                        default=Union("geo_zones__geometry"),
                        output_field=GeometryField(),
                    ),
                    intersection_type=GetGeometryType("intersection"),
                    intersection_area=Cast(Area("intersection"), FloatField()),
                )

        tile_sets = tile_sets.filter(
            (
                Q(geo_zone_count=0)
                | (
                    Q(intersection__isnull=False)
                    & Q(
                        intersection_type__in=[
                            GeometryType.POLYGON,
                            GeometryType.MULTIPOLYGON,
                        ]
                    )
                    & Q(intersection_area__gt=0)
                )
            )
        )

        if filter_tile_set_contains_point:
            tile_sets = tile_sets.filter(
                Q(intersection__contains=filter_tile_set_contains_point)
            )

        if filter_tile_set_intersects_geometry:
            tile_sets = tile_sets.filter(
                Q(intersection__intersects=filter_tile_set_intersects_geometry)
            )

        if filter_tile_set_uuid__in:
            tile_sets = tile_sets.filter(uuid__in=filter_tile_set_uuid__in)

        return tile_sets, final_union

    def _get_user_geo_union(
        self, filter_tile_set_intersects_geometry: Optional[MultiPolygon] = None
    ) -> Optional[MultiPolygon]:
        """Get union of user's accessible geo zones."""
        user_user_groups_with_geo_union = UserUserGroup.objects.filter(
            user=self.user
        ).prefetch_related("user_group__object_type_categories__object_types")

        user_user_groups_with_geo_union = user_user_groups_with_geo_union.annotate(
            geo_zone_count=Count("user_group__geo_zones")
        ).filter(geo_zone_count__gt=0)

        # Collect all geometries from user groups
        all_geometries = []
        for user_user_group in user_user_groups_with_geo_union:
            geo_zones = user_user_group.user_group.geo_zones.all()
            if len(geo_zones) == 1:
                geometry = geo_zones[0].geometry
            elif len(geo_zones) > 1:
                # Use Union aggregate on the related geo zones
                union_result = user_user_group.user_group.geo_zones.aggregate(
                    union_geom=Union("geometry")
                )
                geometry = union_result["union_geom"]
            else:
                continue  # Skip if no geo zones

            if filter_tile_set_intersects_geometry and geometry:
                geometry = geometry.intersection(filter_tile_set_intersects_geometry)

            if geometry:
                all_geometries.append(geometry)

        # Final union of all collected geometries
        if not all_geometries:
            return None
        elif len(all_geometries) == 1:
            return all_geometries[0]
        else:
            # Manually union all geometries
            result = all_geometries[0]
            for geom in all_geometries[1:]:
                result = result.union(geom)
            return result


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
