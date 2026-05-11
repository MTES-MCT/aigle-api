from typing import Any, Dict, List, Tuple

from django_filters import CharFilter, FilterSet
from rest_framework.decorators import action

from common.views.base import BaseViewSetMixin
from core.models.geo_zone import GeoZoneType
from core.models.object_type_category import ObjectTypeCategory
from core.models.user import UserRole
from core.models.user_group import UserGroup, UserGroupType
from core.serializers.user_group import (
    UserGroupDetailSerializer,
    UserGroupInputSerializer,
)
from core.utils.bulk_csv import (
    COL_COMMUNES,
    COL_DEPARTMENTS,
    COL_REGIONS,
    attachment_response,
    bulk_error,
    bulk_import_preview_response,
    bulk_import_run,
    join_list,
    parse_csv,
    parse_list,
    partition_zones_by_type,
    resolve_collectivity_uuids,
    write_csv,
)
from core.utils.permissions import (
    SuperAdminRoleModifyActionPermission,
    SuperAdminRolePermission,
)
from core.utils.string import normalize
from core.utils.user_action_log import UserActionLogMixin


USER_GROUP_CSV_HEADERS = [
    "nom du groupe",
    "type",
    "thématiques",
    COL_REGIONS,
    COL_DEPARTMENTS,
    COL_COMMUNES,
]
USER_GROUP_TYPE_LABELS = {
    UserGroupType.COLLECTIVITY: "Collectivité",
    UserGroupType.DDTM: "DDTM",
}
USER_GROUP_TYPE_REVERSE = {
    "collectivite": UserGroupType.COLLECTIVITY,
    "ddtm": UserGroupType.DDTM,
}


class UserGroupFilter(FilterSet):
    q = CharFilter(method="search")

    class Meta:
        model = UserGroup
        fields = ["q"]

    def search(self, queryset, name, value):
        return queryset.filter(name__icontains=value)


class UserGroupViewSet(UserActionLogMixin, BaseViewSetMixin[UserGroup]):
    filterset_class = UserGroupFilter
    permission_classes = [SuperAdminRoleModifyActionPermission]

    def get_serializer_class(self):
        if self.action in ["create", "partial_update", "update"]:
            return UserGroupInputSerializer

        return UserGroupDetailSerializer

    def get_queryset(self):
        queryset = UserGroup.objects.order_by("name")
        queryset = queryset.prefetch_related(
            "geo_zones",
            "object_type_categories",
            "geo_custom_zones",
            "geo_custom_zones__geo_custom_zone_category",
        )

        if self.request.user.user_role == UserRole.ADMIN:
            user_group_ids = self.request.user.user_user_groups.values_list(
                "user_group__id", flat=True
            )
            queryset = queryset.filter(id__in=user_group_ids)

        return queryset

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
        for group in queryset:
            zones_by_type = partition_zones_by_type(group.geo_zones.all())
            thematics = [c.name for c in group.object_type_categories.all()]

            rows.append(
                {
                    "nom du groupe": group.name,
                    "type": USER_GROUP_TYPE_LABELS.get(
                        group.user_group_type, group.user_group_type
                    ),
                    "thématiques": join_list(thematics),
                    COL_REGIONS: join_list(zones_by_type[GeoZoneType.REGION]),
                    COL_DEPARTMENTS: join_list(zones_by_type[GeoZoneType.DEPARTMENT]),
                    COL_COMMUNES: join_list(zones_by_type[GeoZoneType.COMMUNE]),
                }
            )

        response = attachment_response("groupes-export.csv")
        write_csv(response, USER_GROUP_CSV_HEADERS, rows)
        return response

    @action(
        methods=["post"],
        detail=False,
        url_path="bulk-import-preview",
        permission_classes=[SuperAdminRolePermission],
    )
    def bulk_import_preview(self, request):
        return bulk_import_preview_response(self._validate_user_group_csv, request)

    @action(
        methods=["post"],
        detail=False,
        url_path="bulk-import",
        permission_classes=[SuperAdminRolePermission],
    )
    def bulk_import(self, request):
        return bulk_import_run(
            self._validate_user_group_csv,
            request,
            UserGroupInputSerializer,
            "bulk_import_user_group",
        )

    def _validate_user_group_csv(
        self, request
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        uploaded = request.FILES.get("file")
        if not uploaded:
            return [], [bulk_error("Aucun fichier fourni")], []

        rows, parse_errors = parse_csv(uploaded)
        if parse_errors:
            return [], parse_errors, []

        errors: List[Dict[str, Any]] = []
        preview: List[Dict[str, Any]] = []
        payloads: List[Dict[str, Any]] = []

        existing_names = set(UserGroup.objects.values_list("name", flat=True))
        seen_names: set[str] = set()

        for index, row in enumerate(rows, start=2):
            name = row.get("nom du groupe", "")
            type_label = row.get("type", "")
            thematics_raw = parse_list(row.get("thématiques", ""))
            regions_raw = parse_list(row.get(COL_REGIONS.lower(), ""))
            departments_raw = parse_list(row.get(COL_DEPARTMENTS.lower(), ""))
            communes_raw = parse_list(row.get(COL_COMMUNES.lower(), ""))

            if not name:
                errors.append(bulk_error("nom du groupe manquant", line=index))
                continue
            if name in seen_names:
                errors.append(
                    bulk_error(f"nom de groupe en doublon ({name})", line=index)
                )
                continue
            seen_names.add(name)
            if name in existing_names:
                errors.append(
                    bulk_error(
                        f"un groupe avec le nom '{name}' existe déjà", line=index
                    )
                )
                continue

            type_normalized = normalize(type_label)
            user_group_type = USER_GROUP_TYPE_REVERSE.get(type_normalized)
            if not user_group_type:
                errors.append(
                    bulk_error(
                        f"type invalide '{type_label}'. "
                        f"Valeurs attendues: 'Collectivité' ou 'DDTM'",
                        line=index,
                    )
                )
                continue

            thematics_uuids: List[str] = []
            row_has_error = False
            for raw in thematics_raw:
                cat = ObjectTypeCategory.objects.filter(name=raw).first()
                if not cat:
                    errors.append(
                        bulk_error(f"thématique introuvable '{raw}'", line=index)
                    )
                    row_has_error = True
                    continue
                thematics_uuids.append(str(cat.uuid))
            if not thematics_uuids and not row_has_error:
                errors.append(
                    bulk_error("au moins une thématique est requise", line=index)
                )
                row_has_error = True

            (
                regions_uuids,
                departments_uuids,
                communes_uuids,
                geo_has_error,
            ) = resolve_collectivity_uuids(
                regions_raw, departments_raw, communes_raw, index, errors
            )
            if geo_has_error:
                row_has_error = True

            if (
                not (regions_uuids or departments_uuids or communes_uuids)
                and not row_has_error
            ):
                errors.append(
                    bulk_error(
                        "au moins une collectivité (région, département "
                        "ou commune) est requise",
                        line=index,
                    )
                )
                row_has_error = True

            if row_has_error:
                continue

            preview.append(
                {
                    "nom du groupe": name,
                    "type": USER_GROUP_TYPE_LABELS[user_group_type],
                    "thématiques": join_list(thematics_raw),
                    COL_REGIONS: join_list(regions_raw),
                    COL_DEPARTMENTS: join_list(departments_raw),
                    COL_COMMUNES: join_list(communes_raw),
                }
            )
            payloads.append(
                {
                    "name": name,
                    "user_group_type": user_group_type,
                    "object_type_categories_uuids": thematics_uuids,
                    "regions_uuids": regions_uuids,
                    "departments_uuids": departments_uuids,
                    "communes_uuids": communes_uuids,
                    "geo_custom_zones_uuids": [],
                }
            )

        return preview, errors, payloads
