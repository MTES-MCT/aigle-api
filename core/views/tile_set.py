from common.views.base import BaseViewSetMixin
from django_filters import FilterSet, CharFilter

from django.db.models import Q
from rest_framework import serializers
from django.contrib.gis.geos import Point
from rest_framework.response import Response
from django.db.models import Value

from core.constants.geo import SRID
from core.constants.order_by import TILE_SETS_ORDER_BYS
from core.models.tile_set import TileSet, TileSetScheme, TileSetStatus, TileSetType
from core.permissions.tile_set import TileSetPermission
from core.serializers.tile_set import (
    TileSetDetailSerializer,
    TileSetInputSerializer,
    TileSetMinimalSerializer,
    TileSetSerializer,
)
from rest_framework.decorators import action
from core.utils.filters import ChoiceInFilter
from core.utils.permissions import SuperAdminRoleModifyActionPermission


class GetLastFromCoordinatesParamsSerializer(serializers.Serializer):
    lat = serializers.FloatField(required=True, allow_null=False)
    lng = serializers.FloatField(required=True, allow_null=False)


class TileSetFilter(FilterSet):
    q = CharFilter(method="search")
    statuses = ChoiceInFilter(
        field_name="tile_set_status", choices=TileSetStatus.choices
    )
    schemes = ChoiceInFilter(
        field_name="tile_set_scheme", choices=TileSetScheme.choices
    )
    types = ChoiceInFilter(field_name="tile_set_type", choices=TileSetType.choices)

    class Meta:
        model = TileSet
        fields = ["q"]

    def search(self, queryset, name, value):
        return queryset.filter(Q(name__icontains=value) | Q(url__icontains=value))


class TileSetViewSet(BaseViewSetMixin[TileSet]):
    filterset_class = TileSetFilter
    permission_classes = [SuperAdminRoleModifyActionPermission]

    def get_serializer_class(self):
        if self.action in ["create", "partial_update", "update"]:
            return TileSetInputSerializer

        if self.action == "retrieve":
            return TileSetDetailSerializer

        return TileSetSerializer

    def get_queryset(self):
        queryset = TileSet.objects.order_by(*TILE_SETS_ORDER_BYS)
        queryset = queryset.annotate(detections_count=Value(0))

        return queryset

    @action(methods=["get"], detail=False, url_path="last-from-coordinates")
    def get_from_coordinates(self, request):
        params_serializer = GetLastFromCoordinatesParamsSerializer(data=request.GET)
        params_serializer.is_valid(raise_exception=True)

        point_requested = Point(
            x=params_serializer.data["lng"], y=params_serializer.data["lat"], srid=SRID
        )

        tile_set = (
            TileSetPermission(user=request.user)
            .filter_(
                filter_tile_set_type_in=[TileSetType.PARTIAL, TileSetType.BACKGROUND],
                order_bys=["-date"],
                filter_tile_set_intersects_geometry=point_requested,
            )
            .first()
        )

        if tile_set:
            output_serializer = TileSetMinimalSerializer(tile_set)
            output_data = output_serializer.data
        else:
            output_data = None

        return Response(output_data)
