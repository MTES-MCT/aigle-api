from common.views.base import BaseViewSetMixin
from django_filters import FilterSet, CharFilter

from django.db.models import Q

from core.models.geo_commune import GeoCommune
from core.permissions.user import UserPermission
from core.serializers.geo_commune import (
    GeoCommuneDetailSerializer,
    GeoCommuneSerializer,
)
from django.db.models import Case, IntegerField, Value, When
from django.db.models.functions import Length

from core.utils.string import normalize


class GeoCommuneFilter(FilterSet):
    q = CharFilter(method="search")

    class Meta:
        model = GeoCommune
        fields = ["q"]

    def search(self, queryset, name, value):
        value_normalized = normalize(value)

        collectivity_filter = UserPermission(
            user=self.request.user
        ).get_collectivity_filter()

        if collectivity_filter:
            queryset = queryset.filter(
                Q(id__in=collectivity_filter.commune_ids or [])
                | Q(department__id__in=collectivity_filter.department_ids or [])
                | Q(department__region__id__in=collectivity_filter.region_ids or [])
            )

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
