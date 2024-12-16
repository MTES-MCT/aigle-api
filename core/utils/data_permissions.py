from typing import List, Optional, Tuple
from core.contants.order_by import TILE_SETS_ORDER_BYS
from core.models.object_type import ObjectType
from core.models.object_type_category import ObjectTypeCategoryObjectTypeStatus
from core.models.tile_set import TileSet, TileSetStatus, TileSetType
from core.models.user import UserRole
from core.models.user_group import UserGroupRight, UserUserGroup
from django.contrib.gis.db.models.functions import Intersection
from django.db.models import Q
from django.db.models import Count
from django.contrib.gis.geos.collections import MultiPolygon

from django.core.exceptions import PermissionDenied
from django.contrib.gis.db.models.aggregates import Union

from core.utils.postgis import GeometryType, GetGeometryType
from django.contrib.gis.geos import Point


def get_user_tile_sets(
    user,
    filter_tile_set_status__in=None,
    filter_tile_set_type__in=None,
    filter_tile_set_contains_point=None,
    filter_tile_set_intersects_geometry=None,
    filter_tile_set_uuid__in=None,
    order_bys=None,
) -> Tuple[List[TileSet], Optional[MultiPolygon]]:
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

    if user.user_role != UserRole.SUPER_ADMIN:
        user_user_groups_with_geo_union = UserUserGroup.objects.filter(
            user=user
        ).prefetch_related("user_group__object_type_categories__object_types")

        geo_union = Union("user_group__geo_zones__geometry")

        if filter_tile_set_intersects_geometry:
            geo_union = Intersection(geo_union, filter_tile_set_intersects_geometry)

        user_user_groups_with_geo_union = user_user_groups_with_geo_union.annotate(
            geo_union=geo_union
        )

        final_union = user_user_groups_with_geo_union.aggregate(
            total_geo_union=Union("geo_union")
        )["total_geo_union"]
        intersection = Intersection("union_geometry", final_union)
    else:
        final_union = None
        intersection = Union("geo_zones__geometry")

    tile_sets = TileSet.objects.filter(
        tile_set_status__in=filter_tile_set_status__in,
        tile_set_type__in=filter_tile_set_type__in,
    ).order_by(*order_bys)

    union_geometry = Union("geo_zones__geometry")

    tile_sets = tile_sets.annotate(
        union_geometry=union_geometry,
        intersection=intersection,
        geo_zones_count=Count("geo_zones"),
        intersection_type=GetGeometryType("intersection"),
    )

    tile_sets = tile_sets.filter(
        (
            Q(intersection__isnull=False)
            & Q(
                intersection_type__in=[
                    GeometryType.POLYGON,
                    GeometryType.MULTIPOLYGON,
                ]
            )
        )
        | Q(geo_zones_count=0)
    )

    if filter_tile_set_contains_point:
        tile_sets = tile_sets.filter(
            Q(intersection__contains=filter_tile_set_contains_point)
            | Q(geo_zones_count=0)
        )

    if filter_tile_set_intersects_geometry:
        tile_sets = tile_sets.filter(
            Q(intersection__intersects=filter_tile_set_intersects_geometry)
            | Q(geo_zones_count=0)
        )

    if filter_tile_set_uuid__in:
        tile_sets = tile_sets.filter(uuid__in=filter_tile_set_uuid__in)

    return tile_sets, final_union


def get_user_object_types_with_status(
    user,
) -> List[Tuple[ObjectType, ObjectTypeCategoryObjectTypeStatus]]:
    if user.user_role == UserRole.SUPER_ADMIN:
        object_types = ObjectType.objects.order_by("name").all()

        return [
            (object_type, ObjectTypeCategoryObjectTypeStatus.VISIBLE)
            for object_type in object_types
        ]

    user_user_groups = user.user_user_groups.prefetch_related(
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

    for object_type_category in object_type_categories:
        for (
            object_type_category_object_type
        ) in object_type_category.object_type_category_object_types.all():
            object_type = object_type_category_object_type.object_type
            status = (
                object_type_category_object_type.object_type_category_object_type_status
            )

            if (
                object_type_uuids_statuses_map.get(object_type.uuid)
                and object_type_uuids_statuses_map.get(object_type.uuid)[1]
                == ObjectTypeCategoryObjectTypeStatus.VISIBLE
            ):
                continue

            object_type_uuids_statuses_map[object_type.uuid] = (object_type, status)

    object_types_with_status = []

    for object_type, status in object_type_uuids_statuses_map.values():
        object_types_with_status.append((object_type, status))

    object_types_with_status = sorted(object_types_with_status, key=lambda x: x[0].name)

    return object_types_with_status


def get_user_group_rights(
    user, points: List[Point], raise_if_has_no_right: Optional[UserGroupRight] = None
) -> List[UserGroupRight]:
    if user.user_role == UserRole.SUPER_ADMIN:
        return [
            UserGroupRight.WRITE,
            UserGroupRight.ANNOTATE,
            UserGroupRight.READ,
        ]

    user_user_groups = user.user_user_groups.annotate(
        union_geometry=Union("user_group__geo_zones__geometry")
    )
    for point in points:
        user_user_groups = user_user_groups.filter(union_geometry__contains=point)

    user_group_rights = set()

    for user_user_group in user_user_groups:
        user_group_rights.update(user_user_group.user_group_rights)

    res = list(user_group_rights)

    if raise_if_has_no_right and raise_if_has_no_right not in res:
        raise PermissionDenied("Vous n'avez pas les droits pour éditer cette zone")

    return res
