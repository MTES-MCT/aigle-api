from typing import Any, Dict, List, Tuple

from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters import CharFilter, FilterSet

from common.views.base import BaseViewSetMixin
from core.models.geo_custom_zone import (
    GeoCustomZone,
    GeoCustomZoneStatus,
    GeoCustomZoneType,
)
from core.models.geo_custom_zone_category import GeoCustomZoneCategory
from core.serializers.geo_custom_zone import (
    GeoCustomZoneGeoFeatureSerializer,
    GeoCustomZoneInputSerializer,
    GeoCustomZoneSerializer,
    GeoCustomZoneWithCollectivitiesSerializer,
)
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
from core.utils.permissions import AdminRolePermission, SuperAdminRolePermission


CUSTOM_ZONE_CSV_HEADERS = [
    "catégorie",
    "nom de la zone",
    "nom court de la zone",
    "régions",
    "départements",
    "communes",
]


class GeometrySerializer(serializers.Serializer):
    neLat = serializers.FloatField()
    neLng = serializers.FloatField()
    swLat = serializers.FloatField()
    swLng = serializers.FloatField()

    uuids = serializers.CharField(required=False, allow_null=True)


class GeoCustomZoneFilter(FilterSet):
    q = CharFilter(method="search")

    class Meta:
        model = GeoCustomZone
        fields = ["q"]

    def search(self, queryset, name, value):
        return queryset.filter(name__icontains=value)


class GeoCustomZoneViewSet(BaseViewSetMixin[GeoCustomZone]):
    filterset_class = GeoCustomZoneFilter
    permission_classes = [AdminRolePermission]

    def get_serializer_class(self):
        if self.action in ["create", "partial_update", "update"]:
            return GeoCustomZoneInputSerializer

        if self.action in ["retrieve"]:
            if self.request.GET.get("geometry"):
                return GeoCustomZoneGeoFeatureSerializer

        if self.request.GET.get("with_collectivities"):
            return GeoCustomZoneWithCollectivitiesSerializer

        return GeoCustomZoneSerializer

    def get_queryset(self):
        from core.services.geo_custom_zone import GeoCustomZoneService

        search_query = self.request.GET.get("q")
        return GeoCustomZoneService.get_filtered_queryset(
            user=self.request.user, search_query=search_query
        )

    @action(methods=["get"], detail=False)
    def get_geometry(self, request):
        from core.services.geo_custom_zone import GeoCustomZoneService

        geometry_serializer = GeometrySerializer(data=request.GET)
        geometry_serializer.is_valid(raise_exception=True)

        # Parse UUIDs if provided
        zone_uuids = None
        if geometry_serializer.data.get("uuids"):
            try:
                zone_uuids = geometry_serializer.data["uuids"].split(",")
            except AttributeError:
                # uuids is not a string
                pass

        # Use service to get zones by geometry
        zones_data = GeoCustomZoneService.get_zones_by_geometry(
            ne_lat=geometry_serializer.data["neLat"],
            ne_lng=geometry_serializer.data["neLng"],
            sw_lat=geometry_serializer.data["swLat"],
            sw_lng=geometry_serializer.data["swLng"],
            zone_uuids=zone_uuids,
        )

        serializer = GeoCustomZoneGeoFeatureSerializer(zones_data, many=True)
        return Response(serializer.data)

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
        queryset = queryset.prefetch_related("geo_zones", "geo_custom_zone_category")

        rows = []
        for zone in queryset:
            zones_by_type = partition_zones_by_type(zone.geo_zones.all())
            rows.append(
                {
                    "catégorie": zone.geo_custom_zone_category.name
                    if zone.geo_custom_zone_category
                    else "",
                    "nom de la zone": zone.name or "",
                    "nom court de la zone": zone.name_short or "",
                    "régions": join_list(zones_by_type[GeoZoneType.REGION]),
                    "départements": join_list(zones_by_type[GeoZoneType.DEPARTMENT]),
                    "communes": join_list(zones_by_type[GeoZoneType.COMMUNE]),
                }
            )

        response = attachment_response("zones-personnalisees-export.csv")
        write_csv(response, CUSTOM_ZONE_CSV_HEADERS, rows)
        return response

    @action(
        methods=["post"],
        detail=False,
        url_path="bulk-import-preview",
        permission_classes=[SuperAdminRolePermission],
    )
    def bulk_import_preview(self, request):
        return bulk_import_preview_response(self._validate_custom_zone_csv, request)

    @action(
        methods=["post"],
        detail=False,
        url_path="bulk-import",
        permission_classes=[SuperAdminRolePermission],
    )
    def bulk_import(self, request):
        return bulk_import_run(
            self._validate_custom_zone_csv,
            request,
            GeoCustomZoneInputSerializer,
            "bulk_import_custom_zone",
        )

    def _validate_custom_zone_csv(
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

        existing_names = set(GeoCustomZone.objects.values_list("name", flat=True))
        existing_short_names = set(
            GeoCustomZone.objects.exclude(name_short__isnull=True).values_list(
                "name_short", flat=True
            )
        )
        seen_names: set[str] = set()
        seen_short_names: set[str] = set()

        for index, row in enumerate(rows, start=2):
            category_name = row.get("catégorie", "")
            name = row.get("nom de la zone", "")
            name_short = row.get("nom court de la zone", "")
            regions_raw = parse_list(row.get("régions", ""))
            departments_raw = parse_list(row.get("départements", ""))
            communes_raw = parse_list(row.get("communes", ""))

            if not name:
                errors.append(f"Ligne {index}: nom de la zone manquant")
                continue
            if name in seen_names:
                errors.append(
                    f"Ligne {index}: nom de zone en doublon dans le CSV ({name})"
                )
                continue
            seen_names.add(name)
            if name in existing_names:
                errors.append(
                    f"Ligne {index}: une zone avec le nom '{name}' existe déjà"
                )
                continue

            if name_short:
                if name_short in seen_short_names:
                    errors.append(
                        f"Ligne {index}: nom court en doublon dans le CSV "
                        f"({name_short})"
                    )
                    continue
                seen_short_names.add(name_short)
                if name_short in existing_short_names:
                    errors.append(
                        f"Ligne {index}: une zone avec le nom court "
                        f"'{name_short}' existe déjà"
                    )
                    continue

            if not category_name:
                errors.append(f"Ligne {index}: catégorie manquante")
                continue

            category = GeoCustomZoneCategory.objects.filter(name=category_name).first()
            if not category:
                errors.append(f"Ligne {index}: catégorie introuvable '{category_name}'")
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
                    "catégorie": category_name,
                    "nom de la zone": name,
                    "nom court de la zone": name_short,
                    "régions": join_list(regions_raw),
                    "départements": join_list(departments_raw),
                    "communes": join_list(communes_raw),
                }
            )
            payloads.append(
                {
                    "name": name,
                    "name_short": name_short or None,
                    "geo_custom_zone_status": GeoCustomZoneStatus.ACTIVE,
                    "geo_custom_zone_type": GeoCustomZoneType.COMMON,
                    "geo_custom_zone_category_uuid": str(category.uuid),
                    "regions_uuids": regions_uuids,
                    "departments_uuids": departments_uuids,
                    "communes_uuids": communes_uuids,
                    "geo_custom_zones_uuids": [],
                }
            )

        return preview, errors, payloads
