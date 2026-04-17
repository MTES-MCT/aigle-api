from django_filters import FilterSet, CharFilter, DateTimeFilter, UUIDFilter
from rest_framework.viewsets import ReadOnlyModelViewSet

from core.models.user_action_log import UserActionLog, UserActionLogAction
from core.serializers.user_action_log import UserActionLogSerializer
from core.utils.filters import ChoiceInFilter
from core.utils.permissions import SuperAdminRolePermission


class UserActionLogFilter(FilterSet):
    route = CharFilter(lookup_expr="icontains")
    actions = ChoiceInFilter(field_name="action", choices=UserActionLogAction.choices)
    userUuid = UUIDFilter(field_name="user__uuid")
    createdAfter = DateTimeFilter(field_name="created_at", lookup_expr="gte")
    createdBefore = DateTimeFilter(field_name="created_at", lookup_expr="lte")

    class Meta:
        model = UserActionLog
        fields = ["route", "actions", "userUuid", "createdAfter", "createdBefore"]


class UserActionLogViewSet(ReadOnlyModelViewSet):
    lookup_field = "uuid"
    filterset_class = UserActionLogFilter
    permission_classes = [SuperAdminRolePermission]
    serializer_class = UserActionLogSerializer

    def get_serializer_context(self):
        return {"request": self.request}

    queryset = UserActionLog.objects.select_related("user").order_by("-created_at")
