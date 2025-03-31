from common.views.base import BaseViewSetMixin

from django.db.models import Q

from core.models.geo_department import GeoDepartment
from core.permissions.user import UserPermission
from core.serializers.geo_department import (
    GeoDepartmentDetailSerializer,
    GeoDepartmentSerializer,
)
from django_filters import FilterSet, CharFilter

from core.utils.permissions import AdminRolePermission
from django.db.models import Case, IntegerField, Value, When
from django.db.models.functions import Length

from core.utils.string import normalize


class GeoDepartmentFilter(FilterSet):
    q = CharFilter(method="search")

    class Meta:
        model = GeoDepartment
        fields = ["q"]

    def search(self, queryset, name, value):
        value_normalized = normalize(value)

        collectivity_filter = UserPermission(
            user=self.request.user
        ).get_collectivity_filter()

        queryset = queryset.filter(
            Q(communes__id__in=collectivity_filter.commune_ids or [])
            | Q(id__in=collectivity_filter.department_ids or [])
            | Q(region__id__in=collectivity_filter.region_ids or [])
        )

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

        return (
            queryset.filter(
                Q(name_normalized__icontains=value_normalized)
                | Q(insee_code__icontains=value_normalized)
            )
            .order_by("-match_score", Length("name"))
            .distinct()
        )


class GeoDepartmentViewSet(BaseViewSetMixin[GeoDepartment]):
    filterset_class = GeoDepartmentFilter
    permission_classes = [AdminRolePermission]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return GeoDepartmentDetailSerializer

        return GeoDepartmentSerializer

    def get_queryset(self):
        queryset = GeoDepartment.objects.order_by("insee_code")
        return queryset
