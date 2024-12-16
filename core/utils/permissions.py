from typing import List, Optional
from rest_framework.permissions import BasePermission

from core.models.user import UserRole
from rest_framework.request import Request
from rest_framework.views import APIView


class CustomRolePermission(BasePermission):
    message = "Vous devez être administrateur pour accéder à cette ressource"

    def __init__(
        self,
        restricted_actions: Optional[List[str]] = None,
        allowed_roles: Optional[List[UserRole]] = None,
    ):
        self.restricted_actions = restricted_actions or []
        self.allowed_roles = allowed_roles or [UserRole.ADMIN, UserRole.SUPER_ADMIN]

    def has_permission(self, request: Request, view: APIView):
        if (
            request.user
            and not request.user.is_anonymous
            and request.user.user_role in self.allowed_roles
        ):
            return True

        if (
            request.user
            and not request.user.is_anonymous
            and view.action not in self.restricted_actions
        ):
            return True

        return False


# base actions: list, retrieve, create, update, partial_update, destroy
def get_admin_role_permission(
    restricted_actions: Optional[List[str]] = None,
) -> CustomRolePermission:
    class CustomAdminRolePermission(CustomRolePermission):
        def __init__(self):
            super().__init__(
                restricted_actions=restricted_actions,
                allowed_roles=[UserRole.ADMIN, UserRole.SUPER_ADMIN],
            )

    return CustomAdminRolePermission


def get_super_admin_role_permission(
    restricted_actions: Optional[List[str]] = None,
) -> CustomRolePermission:
    class CustomAdminRolePermission(CustomRolePermission):
        def __init__(self):
            super().__init__(
                restricted_actions=restricted_actions,
                allowed_roles=[UserRole.SUPER_ADMIN],
            )

    return CustomAdminRolePermission


BASE_ACTIONS = ["list", "retrieve", "create", "update", "partial_update", "destroy"]
READ_ACTIONS = ["list", "retrieve"]
MODIFY_ACTIONS = list(set(BASE_ACTIONS) - set(READ_ACTIONS))

AdminRoleModifyActionPermission = get_admin_role_permission(MODIFY_ACTIONS)
SuperAdminRoleModifyActionPermission = get_super_admin_role_permission(MODIFY_ACTIONS)
AdminRolePermission = get_admin_role_permission()
