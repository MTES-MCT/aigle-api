from common.views.base import BaseViewSetMixin
from django_filters import FilterSet, CharFilter

from core.utils.filters import UuidInFilter
from core.views.utils.collectivity_scope import scope_by_collectivity

from django.db.models import Q

from core.models.geo_commune import GeoCommune
from core.models.geo_zone import GeoZoneType
from core.serializers.geo_commune import (
    GeoCommuneDetailSerializer,
    GeoCommuneSerializer,
)
from django.db.models import Case, IntegerField, Value, When
from django.db.models.functions import Length

from core.utils.string import normalize


class GeoCommuneFilter(FilterSet):
    q = CharFilter(method="search")
    # Exact-match resolution of a comma-separated list (raw mode in the admin forms):
    # codes -> entities, and uuids -> entities (to read back their codes).
    codes = CharFilter(method="filter_codes")
    uuids = UuidInFilter(method="filter_uuids")
    regionsUuids = UuidInFilter(method="filter_regions")
    departmentsUuids = UuidInFilter(method="filter_departments")
    epcisUuids = UuidInFilter(method="filter_epcis")

    class Meta:
        model = GeoCommune
        fields = ["q"]

    def filter_regions(self, queryset, name, value):
        return self._scope_by_collectivity(queryset).filter(
            department__region__uuid__in=value
        )

    def filter_departments(self, queryset, name, value):
        return self._scope_by_collectivity(queryset).filter(department__uuid__in=value)

    def filter_epcis(self, queryset, name, value):
        return self._scope_by_collectivity(queryset).filter(epci__uuid__in=value)

    def filter_uuids(self, queryset, name, value):
        if not value:
            return queryset.none()
        return self._scope_by_collectivity(queryset).filter(uuid__in=value)

    def _scope_by_collectivity(self, queryset):
        return scope_by_collectivity(queryset, self.request, GeoZoneType.COMMUNE)

    def filter_codes(self, queryset, name, value):
        codes = [code.strip() for code in value.split(",") if code.strip()]
        if not codes:
            return queryset.none()
        return self._scope_by_collectivity(queryset).filter(iso_code__in=codes)

    def search(self, queryset, name, value):
        value_normalized = normalize(value)

        queryset = self._scope_by_collectivity(queryset)

        queryset = queryset.annotate(
            match_score=Case(
                When(name_normalized__iexact=value_normalized, then=Value(5)),
                When(iso_code__iexact=value_normalized, then=Value(4)),
                When(name_normalized__istartswith=value_normalized, then=Value(3)),
                When(name_normalized__icontains=value_normalized, then=Value(2)),
                When(iso_code__icontains=value_normalized, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        )

        return (
            queryset.filter(
                Q(name_normalized__icontains=value_normalized)
                | Q(iso_code__icontains=value_normalized)
            )
            .order_by("-match_score", Length("name"))
            .distinct()
        )


class GeoCommuneViewSet(BaseViewSetMixin[GeoCommune]):
    filterset_class = GeoCommuneFilter

    def get_serializer_class(self):
        if self.action == "retrieve":
            return GeoCommuneDetailSerializer

        return GeoCommuneSerializer

    def get_queryset(self):
        queryset = GeoCommune.objects.order_by("iso_code")
        return queryset
