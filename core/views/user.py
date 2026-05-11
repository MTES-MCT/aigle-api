import secrets
from typing import Any, Dict, List, Tuple

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django_filters import CharFilter, FilterSet, OrderingFilter
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from common.views.base import BaseViewSetMixin
from core.models.user import UserRole
from core.models.user_action_log import UserActionLog, UserActionLogAction
from core.models.user_group import UserGroup, UserGroupRight
from core.serializers.user import UserInputSerializer, UserSerializer
from core.services.user import UserService
from core.utils.bulk_csv import (
    LIST_SEP,
    attachment_response,
    bulk_error,
    bulk_import_preview_response,
    join_list,
    parse_csv,
    write_csv,
)
from core.utils.filters import ChoiceInFilter, UuidInFilter
from core.utils.permissions import (
    MODIFY_ACTIONS,
    AdminRolePermission,
    SuperAdminRolePermission,
)

UserModel = get_user_model()


USER_CSV_HEADERS = ["email", "role", "nom du groupe", "droits du groupe"]
USER_RIGHTS_WRITE_LABEL = "Ecriture"
USER_RIGHTS_READ_LABEL = "Lecture"
USER_RIGHTS_WRITE_VALUES = [
    UserGroupRight.READ,
    UserGroupRight.ANNOTATE,
    UserGroupRight.WRITE,
]
USER_RIGHTS_READ_VALUES = [UserGroupRight.READ]


class UserFilter(FilterSet):
    email = CharFilter(lookup_expr="icontains")
    roles = ChoiceInFilter(field_name="user_role", choices=UserRole.choices)
    user_group_uuids = UuidInFilter(
        field_name="user_user_groups__user_group__uuid", distinct=True
    )
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

        if request.user.user_role == UserRole.DEACTIVATED:
            raise PermissionDenied("Votre compte est désactivé")

        user = UserModel.objects.filter(id=request.user.id).first()

        user = UserService.get_user_profile_with_logging(user=user)
        serializer = UserSerializer(user, context={"request": request})
        return Response(serializer.data)

    def get_serializer_class(self):
        if self.action in MODIFY_ACTIONS:
            return UserInputSerializer

        return UserSerializer

    def get_queryset(self):
        queryset = UserModel.objects.order_by("-id")
        queryset = queryset.prefetch_related(
            "user_user_groups",
            "user_user_groups__user_group",
            "user_user_groups__user_group__geo_zones",
        )

        return UserService.get_filtered_users_queryset(
            user=self.request.user, queryset=queryset
        )

    # ------------------------------------------------------------------
    # Bulk CSV: export / preview / import
    # ------------------------------------------------------------------

    @action(
        methods=["get"],
        detail=False,
        url_path="export",
        permission_classes=[SuperAdminRolePermission],
    )
    def export_csv(self, request):
        queryset = self.filter_queryset(self.get_queryset())

        rows = []
        for user in queryset:
            user_user_groups = list(user.user_user_groups.all())
            group_names = [uug.user_group.name for uug in user_user_groups]
            rights_label = USER_RIGHTS_READ_LABEL
            for uug in user_user_groups:
                if UserGroupRight.WRITE in (uug.user_group_rights or []):
                    rights_label = USER_RIGHTS_WRITE_LABEL
                    break
            rows.append(
                {
                    "email": user.email,
                    "role": user.user_role,
                    "nom du groupe": join_list(group_names),
                    "droits du groupe": rights_label if group_names else "",
                }
            )

        response = attachment_response("utilisateurs-export.csv")
        write_csv(response, USER_CSV_HEADERS, rows)
        return response

    @action(
        methods=["post"],
        detail=False,
        url_path="bulk-import-preview",
        permission_classes=[SuperAdminRolePermission],
    )
    def bulk_import_preview(self, request):
        return bulk_import_preview_response(self._validate_user_csv, request)

    @action(
        methods=["post"],
        detail=False,
        url_path="bulk-import",
        permission_classes=[SuperAdminRolePermission],
    )
    def bulk_import(self, request):
        preview, errors, resolved = self._validate_user_csv(request)
        if errors:
            return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)

        created: List[Dict[str, str]] = []
        with transaction.atomic():
            for row, payload in zip(preview, resolved):
                password = secrets.token_urlsafe(16)
                UserService.create_user(
                    email=payload["email"],
                    password=password,
                    user_role=payload["user_role"],
                    requesting_user=request.user,
                    user_user_groups=[
                        {
                            "user_group_uuid": payload["user_group_uuid"],
                            "user_group_rights": payload["user_group_rights"],
                        }
                    ],
                )
                created.append({"email": payload["email"], "password": password})

        UserActionLog.objects.create(
            user=request.user,
            route=request.path,
            action=UserActionLogAction.CUSTOM,
            data={"kind": "bulk_import_user", "count": len(created)},
        )

        return Response(
            {"created_count": len(created), "created": created},
            status=status.HTTP_201_CREATED,
        )

    def _validate_user_csv(
        self, request
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        uploaded = request.FILES.get("file")
        if not uploaded:
            return [], [bulk_error("Aucun fichier fourni")], []

        rows, errors = parse_csv(uploaded)
        if errors:
            return [], errors, []

        valid_roles = {choice for choice, _ in UserRole.choices}
        seen_emails: set[str] = set()
        existing_emails = set(
            UserModel.objects.filter(
                email__in=[r.get("email", "") for r in rows if r.get("email")]
            ).values_list("email", flat=True)
        )

        preview: List[Dict[str, Any]] = []
        resolved: List[Dict[str, Any]] = []

        for index, row in enumerate(rows, start=2):
            email = row.get("email", "")
            role = row.get("role", "")
            group_name = row.get("nom du groupe", "")
            rights_label = row.get("droits du groupe", "")

            if not email:
                errors.append(bulk_error("email manquant", line=index))
                continue
            if email in seen_emails:
                errors.append(
                    bulk_error(f"email en doublon dans le CSV ({email})", line=index)
                )
                continue
            seen_emails.add(email)
            if email in existing_emails:
                errors.append(
                    bulk_error(
                        f"un utilisateur avec l'email {email} existe déjà",
                        line=index,
                    )
                )
                continue

            if role not in valid_roles:
                errors.append(
                    bulk_error(
                        f"rôle invalide '{role}'. Valeurs attendues: "
                        + ", ".join(sorted(valid_roles)),
                        line=index,
                    )
                )
                continue

            if LIST_SEP in group_name:
                errors.append(
                    bulk_error(
                        f"l'import ne supporte qu'un seul groupe par "
                        f"utilisateur (trouvé: '{group_name}')",
                        line=index,
                    )
                )
                continue
            if not group_name:
                errors.append(bulk_error("nom du groupe manquant", line=index))
                continue

            user_group = UserGroup.objects.filter(name=group_name).first()
            if not user_group:
                errors.append(
                    bulk_error(f"groupe introuvable '{group_name}'", line=index)
                )
                continue

            if rights_label == USER_RIGHTS_WRITE_LABEL:
                rights = USER_RIGHTS_WRITE_VALUES
            elif rights_label == USER_RIGHTS_READ_LABEL:
                rights = USER_RIGHTS_READ_VALUES
            else:
                errors.append(
                    bulk_error(
                        f"droits invalides '{rights_label}'. "
                        f"Valeurs attendues: '{USER_RIGHTS_WRITE_LABEL}' ou "
                        f"'{USER_RIGHTS_READ_LABEL}'",
                        line=index,
                    )
                )
                continue

            preview.append(
                {
                    "email": email,
                    "role": role,
                    "nom du groupe": group_name,
                    "droits du groupe": rights_label,
                }
            )
            resolved.append(
                {
                    "email": email,
                    "user_role": role,
                    "user_group_uuid": user_group.uuid,
                    "user_group_rights": rights,
                }
            )

        return preview, errors, resolved
