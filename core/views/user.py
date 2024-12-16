from rest_framework.response import Response
from common.views.base import BaseViewSetMixin
from core.models.analytic_log import AnalyticLogType
from core.models.user import UserRole
from django_filters import FilterSet, CharFilter, OrderingFilter
from django.contrib.auth import get_user_model
from rest_framework.decorators import action
from django.core.exceptions import PermissionDenied

from core.serializers.user import UserInputSerializer, UserSerializer


from core.utils.analytic_log import create_log
from core.utils.filters import ChoiceInFilter
from core.utils.permissions import MODIFY_ACTIONS, AdminRolePermission

UserModel = get_user_model()


class UserFilter(FilterSet):
    email = CharFilter(lookup_expr="icontains")
    roles = ChoiceInFilter(field_name="user_role", choices=UserRole.choices)
    ordering = OrderingFilter(fields=("email", "created_at", "updated_at"))

    class Meta:
        model = UserModel
        fields = ["email"]


class UserViewSet(
    BaseViewSetMixin[UserModel],
):
    lookup_field = "uuid"
    filterset_class = UserFilter
    permission_classes = [AdminRolePermission]

    @action(methods=["get"], detail=False, url_path="me")
    def get_me(self, request):
        if request.user.is_anonymous:
            raise PermissionDenied(
                "Vous devez être identifié pour accéder à cette ressource"
            )

        create_log(
            user=request.user,
            analytic_log_type=AnalyticLogType.USER_ACCESS,
        )
        serializer = UserSerializer(request.user, context={"request": request})
        return Response(serializer.data)

    def get_serializer_class(self):
        if self.action in MODIFY_ACTIONS:
            return UserInputSerializer

        return UserSerializer

    def get_queryset(self):
        queryset = UserModel.objects.order_by("-id")

        if self.request.user.user_role == UserRole.ADMIN:
            queryset = queryset.filter(user_role=UserRole.REGULAR)
            user_group_ids = self.request.user.user_user_groups.values_list(
                "user_group__id", flat=True
            )
            queryset = queryset.filter(
                user_user_groups__user_group__id__in=user_group_ids
            )

        return queryset
