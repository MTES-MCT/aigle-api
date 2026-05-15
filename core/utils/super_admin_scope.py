from typing import Optional

from rest_framework.exceptions import PermissionDenied, ValidationError

from core.models.user import UserRole
from core.models.user_group import UserGroup


HEADER_NAME = "HTTP_X_USER_GROUP_UUID"


def get_super_admin_scoped_user_group(request) -> Optional[UserGroup]:
    user_group_uuid = request.META.get(HEADER_NAME)

    if not user_group_uuid:
        return None

    if request.user.user_role != UserRole.SUPER_ADMIN:
        raise PermissionDenied(
            "Seuls les utilisateurs SUPER_ADMIN peuvent utiliser le filtrage par groupe"
        )

    user_group = UserGroup.objects.filter(uuid=user_group_uuid, deleted=False).first()

    if not user_group:
        raise ValidationError(
            {"detail": f"Groupe utilisateur introuvable: {user_group_uuid}"}
        )

    return user_group
