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
    without a DDTM group is denied too).

    A SUPER_ADMIN impersonating a user group (X-User-Group-Uuid) acts *as* that group,
    as everywhere else in the app: the impersonated group's type decides, so
    impersonating a collectivity closes the DDTM-only endpoints even for a super-admin
    who also sits in a DDTM group. Without that, the dashboard the client renders (built
    from the scope-aware summary) and the endpoints it may call would disagree."""

    message = "Vous devez être membre d'un groupe DDTM pour accéder à cette ressource"

    def has_permission(self, request, view):
        from core.permissions.scope import resolve_scoped_user_group

        user = request.user
        if not user or user.is_anonymous or user.user_role == UserRole.DEACTIVATED:
            return False

        scoped_user_group = resolve_scoped_user_group(request)
        if scoped_user_group is not None:
            return scoped_user_group.user_group_type == UserGroupType.DDTM

        return user.user_user_groups.filter(
            user_group__user_group_type=UserGroupType.DDTM
        ).exists()


class SupervisingGroupPermission(BasePermission):
    """Members of a group that SUPERVISES a territory: a DDTM group (its department) or
    a collectivity group scoped to an EPCI (its member communes). Both get the same
    territory-wide overview; a commune-scoped collectivity supervises nothing and is
    denied.

    Same impersonation rule as DdtmGroupPermission: a SUPER_ADMIN passing
    X-User-Group-Uuid acts *as* that group, so the endpoints the client may call and the
    dashboard it renders (built from the scope-aware summary) always agree.

    The per-USER detail of a group stays DdtmGroupPermission — this widens the
    territory-wide aggregates, not the members' identities."""

    message = (
        "Vous devez être membre d'un groupe DDTM ou d'un groupe EPCI "
        "pour accéder à cette ressource"
    )

    @staticmethod
    def _supervises(user_group) -> bool:
        from core.models.geo_zone import GeoZoneType

        if user_group.user_group_type == UserGroupType.DDTM:
            return True
        return user_group.geo_zones.filter(geo_zone_type=GeoZoneType.EPCI).exists()

    def has_permission(self, request, view):
        from core.models.geo_zone import GeoZoneType
        from core.permissions.scope import resolve_scoped_user_group

        user = request.user
        if not user or user.is_anonymous or user.user_role == UserRole.DEACTIVATED:
            return False

        scoped_user_group = resolve_scoped_user_group(request)
        if scoped_user_group is not None:
            return self._supervises(scoped_user_group)

        # Each lookup starts from `user.user_user_groups`, so every row is already a
        # membership OF THIS USER and the group carrying the DDTM type / the EPCI zone
        # is necessarily one of their own — no chained-filter trap here.
        return (
            user.user_user_groups.filter(
                user_group__user_group_type=UserGroupType.DDTM
            ).exists()
            or user.user_user_groups.filter(
                user_group__geo_zones__geo_zone_type=GeoZoneType.EPCI
            ).exists()
        )
