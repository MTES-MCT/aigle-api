from common.views.base import BaseViewSetMixin


from django_filters import FilterSet, CharFilter

from core.models.object_type_category import ObjectTypeCategory
from core.serializers.object_type_category import (
    ObjectTypeCategoryDetailSerializer,
    ObjectTypeCategoryInputSerializer,
)
from core.utils.filters import UuidInFilter
from core.utils.permissions import SuperAdminRoleModifyActionPermission


class ObjectTypeCategoryFilter(FilterSet):
    q = CharFilter(method="search")
    objectTypesUuids = UuidInFilter(method="search_object_types_uuids")

    class Meta:
        model = ObjectTypeCategory
        fields = ["q"]

    def search(self, queryset, name, value):
        return queryset.filter(name__icontains=value)

    def search_object_types_uuids(self, queryset, name, value):
        if not value:
            return queryset

        return queryset.filter(
            object_type_category_object_types__object_type__uuid__in=value
        )


class ObjectTypeCategoryViewSet(
    BaseViewSetMixin[ObjectTypeCategory],
):
    filterset_class = ObjectTypeCategoryFilter
    permission_classes = [SuperAdminRoleModifyActionPermission]

    def get_serializer_class(self):
        if self.action in ["create", "partial_update", "update"]:
            return ObjectTypeCategoryInputSerializer

        return ObjectTypeCategoryDetailSerializer

    def get_queryset(self):
        queryset = ObjectTypeCategory.objects.order_by("name")
        return queryset
