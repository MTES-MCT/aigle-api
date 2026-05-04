from datetime import datetime
from typing import Any, Dict, List, Tuple

from common.views.base import BaseViewSetMixin
from django_filters import FilterSet, CharFilter

from django.db.models import Q
from rest_framework import serializers
from rest_framework.response import Response
from django.db.models import Value

from core.constants.order_by import TILE_SETS_ORDER_BYS
from core.models.tile_set import TileSet, TileSetScheme, TileSetStatus, TileSetType
from core.services.tile_set import TileSetService
from rest_framework import status

from core.serializers.tile_set import (
    TileSetBulkCreateInputSerializer,
    TileSetDetailSerializer,
    TileSetInputSerializer,
    TileSetMinimalSerializer,
    TileSetSerializer,
)
from rest_framework.decorators import action
from core.utils.bulk_csv import (
    attachment_response,
    bulk_import_preview_response,
    bulk_import_run,
    join_list,
    parse_csv,
    parse_list,
    partition_zones_by_type,
    resolve_collectivity_uuids,
    write_csv,
)
from core.utils.filters import ChoiceInFilter
from core.utils.permissions import (
    SuperAdminRoleModifyActionPermission,
    SuperAdminRolePermission,
)
from core.utils.user_action_log import UserActionLogMixin


TILE_SET_CSV_HEADERS = [
    "année",
    "nom du fond de carte",
    "url",
    "régions",
    "départements",
    "communes",
]


class GetLastFromCoordinatesParamsSerializer(serializers.Serializer):
    lat = serializers.FloatField(required=True, allow_null=False)
    lng = serializers.FloatField(required=True, allow_null=False)


class TileSetFilter(FilterSet):
    q = CharFilter(method="search")
    statuses = ChoiceInFilter(
        field_name="tile_set_status", choices=TileSetStatus.choices
    )
    schemes = ChoiceInFilter(
        field_name="tile_set_scheme", choices=TileSetScheme.choices
    )
    types = ChoiceInFilter(field_name="tile_set_type", choices=TileSetType.choices)

    class Meta:
        model = TileSet
        fields = ["q"]

    def search(self, queryset, name, value):
        return queryset.filter(Q(name__icontains=value) | Q(url__icontains=value))


class TileSetViewSet(UserActionLogMixin, BaseViewSetMixin[TileSet]):
    filterset_class = TileSetFilter
    permission_classes = [SuperAdminRoleModifyActionPermission]

    def get_serializer_class(self):
        if self.action == "bulk_create":
            return TileSetBulkCreateInputSerializer

        if self.action in ["create", "partial_update", "update"]:
            return TileSetInputSerializer

        if self.action == "retrieve":
            return TileSetDetailSerializer

        return TileSetSerializer

    def get_queryset(self):
        queryset = TileSet.objects.order_by(*TILE_SETS_ORDER_BYS)
        queryset = queryset.annotate(detections_count=Value(0))

        return queryset

    @action(methods=["post"], detail=False, url_path="bulk-create")
    def bulk_create(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instances = serializer.save()
        for instance in instances:
            instance.detections_count = 0
        output_serializer = TileSetSerializer(instances, many=True)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)

    @action(methods=["get"], detail=False, url_path="last-from-coordinates")
    def get_from_coordinates(self, request):
        params_serializer = GetLastFromCoordinatesParamsSerializer(data=request.GET)
        params_serializer.is_valid(raise_exception=True)

        x = params_serializer.data["lng"]
        y = params_serializer.data["lat"]

        # Use service to find tile set
        tile_set = TileSetService.find_tile_set_by_coordinates(
            x=x,
            y=y,
            user=request.user,
            tile_set_types=[TileSetType.PARTIAL, TileSetType.BACKGROUND],
        )

        if tile_set:
            output_serializer = TileSetMinimalSerializer(tile_set)
            output_data = output_serializer.data
        else:
            output_data = None

        return Response(output_data)

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
        from core.models.geo_zone import GeoZoneType

        queryset = self.filter_queryset(self.get_queryset())
        queryset = queryset.prefetch_related("geo_zones")

        rows = []
        for tile_set in queryset:
            zones_by_type = partition_zones_by_type(tile_set.geo_zones.all())
            rows.append(
                {
                    "année": str(tile_set.date.year) if tile_set.date else "",
                    "nom du fond de carte": tile_set.name,
                    "url": tile_set.url,
                    "régions": join_list(zones_by_type[GeoZoneType.REGION]),
                    "départements": join_list(zones_by_type[GeoZoneType.DEPARTMENT]),
                    "communes": join_list(zones_by_type[GeoZoneType.COMMUNE]),
                }
            )

        response = attachment_response("fonds-de-carte-export.csv")
        write_csv(response, TILE_SET_CSV_HEADERS, rows)
        return response

    @action(
        methods=["post"],
        detail=False,
        url_path="bulk-import-preview",
        permission_classes=[SuperAdminRolePermission],
    )
    def bulk_import_preview(self, request):
        return bulk_import_preview_response(self._validate_tile_set_csv, request)

    @action(
        methods=["post"],
        detail=False,
        url_path="bulk-import",
        permission_classes=[SuperAdminRolePermission],
    )
    def bulk_import(self, request):
        return bulk_import_run(
            self._validate_tile_set_csv,
            request,
            TileSetInputSerializer,
            "bulk_import_tile_set",
        )

    def _validate_tile_set_csv(
        self, request
    ) -> Tuple[List[Dict[str, Any]], List[str], List[Dict[str, Any]]]:
        uploaded = request.FILES.get("file")
        if not uploaded:
            return [], ["Aucun fichier fourni"], []

        rows, parse_errors = parse_csv(uploaded)
        if parse_errors:
            return [], parse_errors, []

        errors: List[str] = []
        preview: List[Dict[str, Any]] = []
        payloads: List[Dict[str, Any]] = []

        existing_names = set(TileSet.objects.values_list("name", flat=True))
        existing_urls = set(TileSet.objects.values_list("url", flat=True))
        seen_names: set[str] = set()
        seen_urls: set[str] = set()

        for index, row in enumerate(rows, start=2):
            year_raw = row.get("année", "")
            name = row.get("nom du fond de carte", "")
            url = row.get("url", "")
            regions_raw = parse_list(row.get("régions", ""))
            departments_raw = parse_list(row.get("départements", ""))
            communes_raw = parse_list(row.get("communes", ""))

            if not name:
                errors.append(f"Ligne {index}: nom du fond de carte manquant")
                continue
            if name in seen_names:
                errors.append(
                    f"Ligne {index}: nom de fond de carte en doublon ({name})"
                )
                continue
            seen_names.add(name)
            if name in existing_names:
                errors.append(
                    f"Ligne {index}: un fond de carte avec le nom '{name}' "
                    f"existe déjà"
                )
                continue

            if not url:
                errors.append(f"Ligne {index}: URL manquante")
                continue
            if url in seen_urls:
                errors.append(f"Ligne {index}: URL en doublon ({url})")
                continue
            seen_urls.add(url)
            if url in existing_urls:
                errors.append(
                    f"Ligne {index}: un fond de carte avec l'URL '{url}' "
                    f"existe déjà"
                )
                continue

            if not year_raw or not year_raw.isdigit() or len(year_raw) != 4:
                errors.append(
                    f"Ligne {index}: année invalide '{year_raw}'. "
                    f"Format attendu: 'YYYY'"
                )
                continue

            try:
                date = datetime(int(year_raw), 1, 1)
            except ValueError as exc:
                errors.append(f"Ligne {index}: année invalide '{year_raw}': {exc}")
                continue

            (
                regions_uuids,
                departments_uuids,
                communes_uuids,
                row_has_error,
            ) = resolve_collectivity_uuids(
                regions_raw, departments_raw, communes_raw, index, errors
            )

            if row_has_error:
                continue

            preview.append(
                {
                    "année": year_raw,
                    "nom du fond de carte": name,
                    "url": url,
                    "régions": join_list(regions_raw),
                    "départements": join_list(departments_raw),
                    "communes": join_list(communes_raw),
                }
            )
            payloads.append(
                {
                    "name": name,
                    "url": url,
                    "date": date.isoformat(),
                    "tile_set_status": TileSetStatus.VISIBLE,
                    "tile_set_scheme": TileSetScheme.xyz,
                    "tile_set_type": TileSetType.BACKGROUND,
                    "min_zoom": 1,
                    "max_zoom": 22,
                    "monochrome": False,
                    "regions_uuids": regions_uuids,
                    "departments_uuids": departments_uuids,
                    "communes_uuids": communes_uuids,
                }
            )

        return preview, errors, payloads
