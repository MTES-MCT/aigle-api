from common.views.base import BaseViewSetMixin


from django_filters import FilterSet, CharFilter

from core.models.geo_custom_zone_category import GeoCustomZoneCategory
from core.serializers.geo_custom_zone_category import GeoCustomZoneCategorySerializer
from core.utils.permissions import SuperAdminRoleModifyActionPermission


class GeoCustomZoneCategoryFilter(FilterSet):
    q = CharFilter(method="search")

    class Meta:
        model = GeoCustomZoneCategory
        fields = ["q"]

    def search(self, queryset, name, value):
        return queryset.filter(name__icontains=value)


class GeoCustomZoneCategoryViewSet(
    BaseViewSetMixin[GeoCustomZoneCategory],
):
    filterset_class = GeoCustomZoneCategoryFilter
    permission_classes = [SuperAdminRoleModifyActionPermission]

    def get_serializer_class(self):
        return GeoCustomZoneCategorySerializer

    def get_queryset(self):
        queryset = GeoCustomZoneCategory.objects.order_by("name")
        return queryset
