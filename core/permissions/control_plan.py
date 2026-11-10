from typing import Optional

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import QuerySet
from django.http import Http404
from rest_framework.exceptions import PermissionDenied

from core.models.control_plan import ControlPlan
from core.models.user import User
from core.models.user_group import (
    FeatureFlag,
    UserGroup,
    UserGroupRight,
    UserUserGroup,
)

CONTROL_PLAN_EDIT_PERMISSION_DENIED_MESSAGE = "Vous devez avoir le droit d'écriture sur le groupe pour modifier son plan de contrôle"


class ControlPlanPermission:
    """Who reaches the control plans, and of which groups.

    A group's plans are open to its members when the group carries the PLAN_DE_CONTROLE
    flag, or to any member flagged internal (is_staff). A SUPER_ADMIN impersonating a
    group (X-User-Group-Uuid) acts as that group only.

    Rights are read from the membership itself: the "as the group" scoping used to
    compute a plan's territory grants every right, so it must never answer this."""

    def __init__(self, user: User, scoped_user_group: Optional[UserGroup] = None):
        self.user = user
        self.scoped_user_group = scoped_user_group

    @classmethod
    def from_request(cls, request) -> "ControlPlanPermission":
        from core.permissions.scope import resolve_scoped_user_group

        return cls(
            user=request.user, scoped_user_group=resolve_scoped_user_group(request)
        )

    def _group_has_feature(self, user_group: UserGroup) -> bool:
        return self.user.is_staff or FeatureFlag.PLAN_DE_CONTROLE in (
            user_group.feature_flags or []
        )

    def accessible_groups(self) -> QuerySet[UserGroup]:
        if self.scoped_user_group is not None:
            if self._group_has_feature(self.scoped_user_group):
                return UserGroup.objects.filter(id=self.scoped_user_group.id)
            return UserGroup.objects.none()

        queryset = UserGroup.objects.filter(
            deleted=False, user_user_groups__user=self.user
        )
        if not self.user.is_staff:
            queryset = queryset.filter(
                feature_flags__contains=[FeatureFlag.PLAN_DE_CONTROLE]
            )

        return queryset.distinct()

    def has_access(self) -> bool:
        return self.accessible_groups().exists()

    def get_group(self, user_group_uuid) -> UserGroup:
        try:
            user_group = self.accessible_groups().filter(uuid=user_group_uuid).first()
        except DjangoValidationError:
            # a malformed uuid
            user_group = None
        if user_group is None:
            raise Http404("Groupe introuvable")
        return user_group

    def can_edit(self, user_group: UserGroup) -> bool:
        if self.scoped_user_group is not None:
            # resolve_scoped_user_group only lets a SUPER_ADMIN impersonate
            return self.scoped_user_group.id == user_group.id

        # One filter() call: chained, the multi-valued relation would be joined twice.
        return UserUserGroup.objects.filter(
            user=self.user,
            user_group=user_group,
            user_group_rights__contains=[UserGroupRight.WRITE],
        ).exists()

    def validate_edit(self, user_group: UserGroup) -> None:
        if not self.can_edit(user_group):
            raise PermissionDenied(CONTROL_PLAN_EDIT_PERMISSION_DENIED_MESSAGE)

    def plans(self) -> QuerySet[ControlPlan]:
        return ControlPlan.objects.filter(
            deleted=False, user_group__in=self.accessible_groups()
        )
