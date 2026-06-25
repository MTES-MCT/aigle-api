from typing import TYPE_CHECKING, List, Dict, Any, Optional
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from django.contrib.gis.db.models.functions import Centroid
from django.core.exceptions import PermissionDenied
from django.db.models import QuerySet
from django.db import transaction

from core.models.analytic_log import AnalyticLogType
from core.models.user import UserRole
from core.models.user_group import UserGroup, UserUserGroup
from core.utils.analytic_log import create_log
from core.utils.cache import invalidate_caches_for_user

if TYPE_CHECKING:
    from core.models.user import User
else:
    User = get_user_model()


class UserService:
    @staticmethod
    def get_user_profile_with_logging(user: "User") -> "User":
        create_log(
            user=user,
            analytic_log_type=AnalyticLogType.USER_ACCESS,
        )
        return user

    @staticmethod
    def get_filtered_users_queryset(user: "User", queryset: QuerySet) -> QuerySet:
        """Filter users queryset based on current user permissions.

        SUPER_ADMIN sees everyone; ADMIN sees only REGULAR users within their own
        groups; anyone else (REGULAR, DEACTIVATED) sees no one. Returning the full
        queryset for non-admins previously leaked every account (emails, roles) and —
        combined with the broken write permission — enabled account takeover.
        """
        if user.user_role == UserRole.SUPER_ADMIN:
            return queryset

        if user.user_role == UserRole.ADMIN:
            user_group_ids = user.user_user_groups.values_list(
                "user_group__id", flat=True
            )
            return queryset.filter(
                user_role=UserRole.REGULAR,
                user_user_groups__user_group__id__in=user_group_ids,
            )

        return queryset.none()

    @staticmethod
    def update_user_position(user: "User", x: float, y: float) -> None:
        user.last_position = Point(x, y)
        user.save(update_fields=["last_position"])

    @staticmethod
    def create_user(
        email: str,
        password: str,
        user_role: UserRole,
        requesting_user: "User",
        user_user_groups: Optional[List[Dict[str, Any]]] = None,
        is_staff: bool = False,
    ) -> "User":
        UserService._validate_email_unique(email)

        if (
            requesting_user.user_role != UserRole.SUPER_ADMIN
            and user_role != UserRole.REGULAR
        ):
            raise PermissionDenied(
                "Un administrateur peut seulement créer des utilisateurs de rôle normal"
            )

        user = User.objects.create_user(
            email=email,
            password=password,
            user_role=user_role,
            is_staff=is_staff,
        )

        with transaction.atomic():
            if user_user_groups:
                UserService._update_user_groups(
                    user=user,
                    user_user_groups=user_user_groups,
                    requesting_user=requesting_user,
                )

                if not user.last_position:
                    user_group_centroid = UserService._get_user_group_centroid(
                        user_groups=list(
                            UserGroup.objects.filter(
                                uuid__in=[
                                    ug["user_group_uuid"] for ug in user_user_groups
                                ]
                            )
                        )
                    )
                    if user_group_centroid:
                        user.last_position = user_group_centroid
                        user.save(update_fields=["last_position"])

            return user

    @staticmethod
    def update_user(
        user: "User",
        requesting_user: "User",
        email: Optional[str] = None,
        password: Optional[str] = None,
        user_role: Optional[UserRole] = None,
        user_user_groups: Optional[List[Dict[str, Any]]] = None,
        **other_fields,
    ) -> "User":
        with transaction.atomic():
            if email and user.email != email:
                UserService._validate_email_unique(email)
                user.email = email

            if password:
                user.set_password(password)

            if user_role is not None:
                UserService._validate_role_change_permissions(
                    user=user, new_role=user_role, requesting_user=requesting_user
                )
                user.user_role = user_role

            for field, value in other_fields.items():
                setattr(user, field, value)

            if user_user_groups is not None:
                UserService._update_user_groups(
                    user=user,
                    user_user_groups=user_user_groups,
                    requesting_user=requesting_user,
                )

            user.save()
            return user

    @staticmethod
    def _validate_email_unique(
        email: str, exclude_user: Optional["User"] = None
    ) -> None:
        query = User.objects.filter(email=email)
        if exclude_user:
            query = query.exclude(id=exclude_user.id)

        if query.exists():
            from rest_framework import serializers

            raise serializers.ValidationError(
                {"email": ["Un utilisateur avec cet email existe déjà"]}
            )

    @staticmethod
    def _validate_role_change_permissions(
        user: "User", new_role: UserRole, requesting_user: "User"
    ) -> None:
        if (
            requesting_user.user_role != UserRole.SUPER_ADMIN
            and user.id != requesting_user.id
            and new_role != UserRole.REGULAR
        ):
            raise PermissionDenied(
                "Un administrateur ne peut pas donner à un autre utilisateur un rôle autre que normal"
            )

        if (
            requesting_user.user_role != UserRole.SUPER_ADMIN
            and new_role == UserRole.SUPER_ADMIN
        ):
            raise PermissionDenied(
                "Un administrateur ne peut pas donner à un autre utilisateur le rôle de super administrateur"
            )

    @staticmethod
    def _update_user_groups(
        user: "User", user_user_groups: List[Dict[str, Any]], requesting_user: "User"
    ) -> None:
        user_user_groups_map = {ug["user_group_uuid"]: ug for ug in user_user_groups}

        updated_groups = []

        for existing_ug in user.user_user_groups.all():
            if user_user_groups_map.get(existing_ug.user_group.uuid):
                existing_ug.user_group_rights = user_user_groups_map[
                    existing_ug.user_group.uuid
                ]["user_group_rights"]
                updated_groups.append(existing_ug)
                user_user_groups_map.pop(existing_ug.user_group.uuid)
            else:
                existing_ug.delete()

        if updated_groups:
            UserUserGroup.objects.bulk_update(updated_groups, ["user_group_rights"])

        new_groups = UserGroup.objects.filter(
            uuid__in=user_user_groups_map.keys()
        ).all()

        new_user_user_groups = []
        for new_group in new_groups:
            new_user_user_groups.append(
                UserUserGroup(
                    user_group_rights=user_user_groups_map[new_group.uuid][
                        "user_group_rights"
                    ],
                    user=user,
                    user_group=new_group,
                )
            )

        UserUserGroup.objects.bulk_create(new_user_user_groups)

        # bulk_create / bulk_update do not emit post_save, so the membership
        # signals never fire for added/updated rows. Invalidate explicitly,
        # otherwise the user keeps a stale geo-union / tileset-filter cache.
        user_id = user.id
        transaction.on_commit(lambda: invalidate_caches_for_user(user_id))

    @staticmethod
    def _get_user_group_centroid(user_groups: List[UserGroup]) -> Optional[Point]:
        if not user_groups:
            return None

        for user_group in user_groups:
            if user_group.geo_zones:
                for geo_zone in (
                    user_group.geo_zones.all()
                    .annotate(centroid=Centroid("geometry"))
                    .defer("geometry")
                ):
                    if geo_zone.centroid:
                        return geo_zone.centroid

        return None
