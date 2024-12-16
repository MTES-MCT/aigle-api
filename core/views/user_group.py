from common.views.base import BaseViewSetMixin
from django_filters import FilterSet, CharFilter


from core.models.user import UserRole
from core.models.user_group import UserGroup
from core.serializers.user_group import (
    UserGroupInputSerializer,
    UserGroupDetailSerializer,
)
from core.utils.permissions import SuperAdminRoleModifyActionPermission


class UserGroupFilter(FilterSet):
    q = CharFilter(method="search")

    class Meta:
        model = UserGroup
        fields = ["q"]

    def search(self, queryset, name, value):
        return queryset.filter(name__icontains=value)


class UserGroupViewSet(BaseViewSetMixin[UserGroup]):
    filterset_class = UserGroupFilter
    permission_classes = [SuperAdminRoleModifyActionPermission]

    def get_serializer_class(self):
        if self.action in ["create", "partial_update", "update"]:
            return UserGroupInputSerializer

        return UserGroupDetailSerializer

    def get_queryset(self):
        queryset = UserGroup.objects.order_by("name")

        if self.request.user.user_role == UserRole.ADMIN:
            user_group_ids = self.request.user.user_user_groups.values_list(
                "user_group__id", flat=True
            )
            queryset = queryset.filter(id__in=user_group_ids)

        return queryset
