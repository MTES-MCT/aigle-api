from typing import List, Optional
from rest_framework.permissions import SAFE_METHODS, BasePermission

from core.models.user import UserRole
from core.models.user_group import UserGroupType


class IsActiveAuthenticated(BasePermission):
    """Default permission: an authenticated, non-deactivated user.

    Used as DEFAULT_PERMISSION_CLASSES so that DEACTIVATED accounts (whose JWT may
    still be valid until it expires) are locked out of every endpoint, not just the
    ones that happen to re-check the role. ``is_active`` is not flipped when a user is
    deactivated, so authentication alone does not block them — this does.
    """

    message = "Vous devez être identifié pour accéder à cette ressource"

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and not user.is_anonymous and user.user_role != UserRole.DEACTIVATED
        )


class CustomRolePermission(BasePermission):
    message = "Vous devez être administrateur pour accéder à cette ressource"

    def __init__(
        self,
        restricted_actions: Optional[List[str]] = None,
        allowed_roles: Optional[List[UserRole]] = None,
    ):
        # ``restricted_actions`` is kept for call-site compatibility but is no longer
        # used to decide write access — see has_permission below.
        self.restricted_actions = restricted_actions or []
        self.allowed_roles = allowed_roles or [UserRole.ADMIN, UserRole.SUPER_ADMIN]

    def has_permission(self, request, view):
        user = request.user

        if not user or user.is_anonymous or user.user_role == UserRole.DEACTIVATED:
            return False

        if user.user_role in self.allowed_roles:
            return True

        # Non-privileged authenticated users get read-only access. Every unsafe method
        # (POST/PUT/PATCH/DELETE) — including custom @action endpoints such as
        # run-command's `run` or tile-set's `bulk_create` — requires a privileged role.
        #
        # The previous implementation gated this on `view.action not in restricted_actions`,
        # an allow-list of the standard CRUD write actions. Custom @action write endpoints
        # were never in that list, so they fell through to "allowed for any authenticated
        # user"; and when restricted_actions was empty (AdminRolePermission) *every* action,
        # including create/update/destroy, was allowed for any authenticated user. That let
        # a REGULAR user reset another user's password and take over their account.
        return request.method in SAFE_METHODS


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


class SuperAdminRolePermission(BasePermission):
    message = "Vous devez être super-administrateur pour accéder à cette ressource"

    def has_permission(self, request, view):
        return (
            request.user
            and not request.user.is_anonymous
            and request.user.user_role == UserRole.SUPER_ADMIN
        )


class DdtmGroupPermission(BasePermission):
    """Members of a DDTM-type user group only — regardless of role (a SUPER_ADMIN
    without a DDTM group is denied too)."""

    message = "Vous devez être membre d'un groupe DDTM pour accéder à cette ressource"

    def has_permission(self, request, view):
        user = request.user
        if not user or user.is_anonymous or user.user_role == UserRole.DEACTIVATED:
            return False
        return user.user_user_groups.filter(
            user_group__user_group_type=UserGroupType.DDTM
        ).exists()
