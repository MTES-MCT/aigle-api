from common.views.base import BaseViewSetMixin
from django.db.models import Q


from core.models.object_type import ObjectType
from django_filters import FilterSet, CharFilter

from core.serializers.object_type import (
    ObjectTypeDetailSerializer,
    ObjectTypeInputSerializer,
)
from core.utils.filters import UuidInFilter
from core.utils.permissions import SuperAdminRoleModifyActionPermission


class ObjectTypeFilter(FilterSet):
    q = CharFilter(method="search")
    objectTypeCategoriesUuids = UuidInFilter(
        method="search_object_type_categories_uuids"
    )

    class Meta:
        model = ObjectType
        fields = ["q"]

    def search(self, queryset, name, value):
        return queryset.filter(Q(name__icontains=value))

    def search_object_type_categories_uuids(self, queryset, name, value):
        if not value:
            return queryset

        return queryset.filter(
            Q(object_type_category_object_types__object_type_category__uuid__in=value)
        )


class ObjectTypeViewSet(BaseViewSetMixin[ObjectType]):
    filterset_class = ObjectTypeFilter
    permission_classes = [SuperAdminRoleModifyActionPermission]

    def get_serializer_class(self):
        if self.action in ["create", "partial_update", "update"]:
            return ObjectTypeInputSerializer

        return ObjectTypeDetailSerializer

    def get_queryset(self):
        queryset = ObjectType.objects.order_by("name")
        return queryset
