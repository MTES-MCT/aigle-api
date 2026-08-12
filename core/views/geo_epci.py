from common.views.base import BaseViewSetMixin

from django.db.models import Q

from core.models.geo_epci import GeoEpci
from core.models.geo_zone import GeoZoneType
from core.serializers.geo_epci import GeoEpciDetailSerializer, GeoEpciSerializer
from django_filters import FilterSet, CharFilter

from core.utils.filters import UuidInFilter
from core.utils.permissions import AdminRolePermission
from core.views.utils.collectivity_scope import scope_by_collectivity

from django.db.models import Case, IntegerField, Value, When
from django.db.models.functions import Length

from core.utils.string import normalize


class GeoEpciFilter(FilterSet):
    q = CharFilter(method="search")
    # Exact-match resolution of a comma-separated list (raw mode in the admin forms):
    # codes -> entities, and uuids -> entities (to read back their codes).
    codes = CharFilter(method="filter_codes")
    uuids = UuidInFilter(method="filter_uuids")
    regionsUuids = UuidInFilter(method="filter_regions")
    departmentsUuids = UuidInFilter(method="filter_departments")

    class Meta:
        model = GeoEpci
        fields = ["q"]

    def _scope_by_collectivity(self, queryset):
        return scope_by_collectivity(queryset, self.request, GeoZoneType.EPCI)

    def filter_regions(self, queryset, name, value):
        return self._scope_by_collectivity(queryset).filter(
            department__region__uuid__in=value
        )

    def filter_departments(self, queryset, name, value):
        return self._scope_by_collectivity(queryset).filter(department__uuid__in=value)

    def filter_uuids(self, queryset, name, value):
        if not value:
            return queryset.none()
        return self._scope_by_collectivity(queryset).filter(uuid__in=value)

    def filter_codes(self, queryset, name, value):
        codes = [code.strip() for code in value.split(",") if code.strip()]
        if not codes:
            return queryset.none()
        return self._scope_by_collectivity(queryset).filter(siren_code__in=codes)

    def search(self, queryset, name, value):
        value_normalized = normalize(value)

        queryset = self._scope_by_collectivity(queryset)

        queryset = queryset.annotate(
            match_score=Case(
                When(name_normalized__iexact=value_normalized, then=Value(5)),
                When(siren_code__iexact=value_normalized, then=Value(4)),
                When(name_normalized__istartswith=value_normalized, then=Value(3)),
                When(name_normalized__icontains=value_normalized, then=Value(2)),
                When(siren_code__icontains=value_normalized, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        )

        return (
            queryset.filter(
                Q(name_normalized__icontains=value_normalized)
                | Q(siren_code__icontains=value_normalized)
            )
            .order_by("-match_score", Length("name"))
            .distinct()
        )


class GeoEpciViewSet(BaseViewSetMixin[GeoEpci]):
    filterset_class = GeoEpciFilter
    permission_classes = [AdminRolePermission]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return GeoEpciDetailSerializer

        return GeoEpciSerializer

    def get_queryset(self):
        # Ordered by name, not by code: a SIREN number carries no meaning for a reader.
        return GeoEpci.objects.order_by("name")
