from rest_framework.response import Response
from common.views.base import BaseViewSetMixin
from core.models.user import UserRole
from django_filters import FilterSet, CharFilter, OrderingFilter
from django.contrib.auth import get_user_model
from rest_framework.decorators import action
from django.core.exceptions import PermissionDenied

from core.serializers.user import UserInputSerializer, UserSerializer
from core.utils.filters import ChoiceInFilter
from core.utils.permissions import MODIFY_ACTIONS, AdminRolePermission
from core.services.user import UserService

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

        user = UserService.get_user_profile_with_logging(user=request.user)
        serializer = UserSerializer(user, context={"request": request})
        return Response(serializer.data)

    def get_serializer_class(self):
        if self.action in MODIFY_ACTIONS:
            return UserInputSerializer

        return UserSerializer

    def get_queryset(self):
        queryset = UserModel.objects.order_by("-id")
        return UserService.get_filtered_users_queryset(
            user=self.request.user, queryset=queryset
        )
