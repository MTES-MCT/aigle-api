from common.views.base import BaseViewSetMixin
from django_filters import FilterSet, CharFilter

from django.db.models import Q

from core.contants.order_by import TILE_SETS_ORDER_BYS
from core.models.tile_set import TileSet, TileSetScheme, TileSetStatus, TileSetType
from core.serializers.tile_set import (
    TileSetDetailSerializer,
    TileSetInputSerializer,
    TileSetSerializer,
)
from core.utils.filters import ChoiceInFilter
from core.utils.permissions import SuperAdminRoleModifyActionPermission


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
        return queryset
