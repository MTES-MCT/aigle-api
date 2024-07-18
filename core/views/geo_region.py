from common.views.base import BaseViewSetMixin
from django.db.models import Q


from core.models.geo_region import GeoRegion
from core.serializers.geo_region import GeoRegionDetailSerializer, GeoRegionSerializer
from django_filters import FilterSet, CharFilter

from core.utils.permissions import AdminRolePermission

from django.db.models import Case, IntegerField, Value, When
from django.db.models.functions import Length

from core.utils.string import normalize


class GeoRegionFilter(FilterSet):
    q = CharFilter(method="search")

    class Meta:
        model = GeoRegion
        fields = ["q"]

    def search(self, queryset, name, value):
        value_normalized = normalize(value)

        queryset = queryset.annotate(
            match_score=Case(
                When(name_normalized__iexact=value_normalized, then=Value(5)),
                When(insee_code__iexact=value_normalized, then=Value(4)),
                When(name_normalized__istartswith=value_normalized, then=Value(3)),
                When(name_normalized__icontains=value_normalized, then=Value(2)),
                When(insee_code__icontains=value_normalized, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        )

        return queryset.filter(
            Q(name_normalized__icontains=value_normalized)
            | Q(insee_code__icontains=value_normalized)
        ).order_by("-match_score", Length("name"))


class GeoRegionViewSet(BaseViewSetMixin[GeoRegion]):
    filterset_class = GeoRegionFilter
    permission_classes = [AdminRolePermission]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return GeoRegionDetailSerializer

        return GeoRegionSerializer

    def get_queryset(self):
        queryset = GeoRegion.objects.order_by("insee_code")
        return queryset.distinct()
