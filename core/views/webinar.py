from django_filters import CharFilter, FilterSet

from common.views.base import BaseViewSetMixin
from core.models.webinar import Webinar
from core.serializers.webinar import WebinarInputSerializer, WebinarSerializer
from core.utils.permissions import SuperAdminRoleModifyActionPermission
from core.utils.user_action_log import UserActionLogMixin


class WebinarFilter(FilterSet):
    q = CharFilter(method="search")

    class Meta:
        model = Webinar
        fields = ["q"]

    def search(self, queryset, name, value):
        return queryset.filter(title__icontains=value)


class WebinarViewSet(UserActionLogMixin, BaseViewSetMixin[Webinar]):
    filterset_class = WebinarFilter
    permission_classes = [SuperAdminRoleModifyActionPermission]
    # A cancelled or mistaken webinar can be removed (soft delete).
    http_method_names = BaseViewSetMixin.http_method_names + ["delete"]

    def get_serializer_class(self):
        if self.action in ["create", "partial_update", "update"]:
            return WebinarInputSerializer

        return WebinarSerializer

    def get_queryset(self):
        return Webinar.objects.filter(deleted=False).order_by(
            "-date", "-start_time", "-created_at"
        )
