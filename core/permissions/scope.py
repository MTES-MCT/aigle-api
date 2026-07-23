"""SUPER_ADMIN user-group impersonation scope.

A SUPER_ADMIN can pass `X-User-Group-Uuid: <uuid>` on any request to scope the
response as if they only belonged to that user group. The actual scoping is
applied inside the permission layer (`UserPermission`, `GeoCustomZonePermission`,
`TileSetPermission`) — this module is only responsible for resolving the header
into a `UserGroup`, validating it, and caching it on the request.

Views and services should never read the header directly. Instead they should
construct their permission object via `<Permission>.from_request(request)`,
which calls `resolve_scoped_user_group(request)` under the hood.
"""

from typing import Optional

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import PermissionDenied, ValidationError

from core.models.user import UserRole
from core.models.user_group import UserGroup


HEADER_NAME = "HTTP_X_USER_GROUP_UUID"
_REQUEST_CACHE_ATTR = "_scoped_user_group_cache"

# Returned when the header points at a group that no longer exists (deleted while
# a client still had it stored). The frontend keys its recovery on this code, so
# it must not change without updating aigle-frontend/src/utils/api.ts.
UNKNOWN_SCOPED_USER_GROUP_CODE = "UNKNOWN_SCOPED_USER_GROUP"


def resolve_scoped_user_group(request) -> Optional[UserGroup]:
    """Resolve the impersonation header into a `UserGroup`.

    Returns `None` if the header is absent or the request has no authenticated
    user. Raises `PermissionDenied` (403) for non-SUPER_ADMIN users and
    `ValidationError` (400) for unknown UUIDs. The resolved value is cached on
    the request object so repeated lookups within one request are free.
    """
    if request is None:
        return None

    if hasattr(request, _REQUEST_CACHE_ATTR):
        return getattr(request, _REQUEST_CACHE_ATTR)

    user_group_uuid = request.META.get(HEADER_NAME)
    if not user_group_uuid:
        setattr(request, _REQUEST_CACHE_ATTR, None)
        return None

    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        setattr(request, _REQUEST_CACHE_ATTR, None)
        return None

    if user.user_role != UserRole.SUPER_ADMIN:
        raise PermissionDenied(
            "Seuls les utilisateurs SUPER_ADMIN peuvent utiliser le filtrage par groupe"
        )

    try:
        user_group = UserGroup.objects.filter(
            uuid=user_group_uuid, deleted=False
        ).first()
    except DjangoValidationError:
        # A malformed uuid makes the UUIDField lookup raise, which would surface as a
        # 500 on EVERY request. The client persists this value, so it must be a clean
        # 400 it can recognise and recover from.
        user_group = None

    if not user_group:
        raise ValidationError(
            {
                "detail": f"Groupe utilisateur introuvable: {user_group_uuid}",
                "code": UNKNOWN_SCOPED_USER_GROUP_CODE,
            }
        )

    setattr(request, _REQUEST_CACHE_ATTR, user_group)
    return user_group
