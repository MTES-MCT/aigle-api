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
from core.utils.permissions import AdminRolePermission, SuperAdminRolePermission


CUSTOM_ZONE_CSV_HEADERS = [
    "catégorie",
    "nom de la zone",
    "nom court de la zone",
    "couleur",
    COL_REGIONS,
    COL_DEPARTMENTS,
    COL_COMMUNES,
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
                    "couleur": zone.color or "",
                    COL_REGIONS: join_list(zones_by_type[GeoZoneType.REGION]),
                    COL_DEPARTMENTS: join_list(zones_by_type[GeoZoneType.DEPARTMENT]),
                    COL_COMMUNES: join_list(zones_by_type[GeoZoneType.COMMUNE]),
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
            color = row.get("couleur", "")
            regions_raw = parse_list(row.get(COL_REGIONS.lower(), ""))
            departments_raw = parse_list(row.get(COL_DEPARTMENTS.lower(), ""))
            communes_raw = parse_list(row.get(COL_COMMUNES.lower(), ""))

            if not name:
                errors.append(bulk_error("nom de la zone manquant", line=index))
                continue
            if name in seen_names:
                errors.append(
                    bulk_error(
                        f"nom de zone en doublon dans le CSV ({name})", line=index
                    )
                )
                continue
            seen_names.add(name)
            if name in existing_names:
                errors.append(
                    bulk_error(f"une zone avec le nom '{name}' existe déjà", line=index)
                )
                continue

            if name_short:
                if name_short in seen_short_names:
                    errors.append(
                        bulk_error(
                            f"nom court en doublon dans le CSV ({name_short})",
                            line=index,
                        )
                    )
                    continue
                seen_short_names.add(name_short)
                if name_short in existing_short_names:
                    errors.append(
                        bulk_error(
                            f"une zone avec le nom court '{name_short}' existe déjà",
                            line=index,
                        )
                    )
                    continue

            category = None
            if category_name:
                category = GeoCustomZoneCategory.objects.filter(
                    name=category_name
                ).first()
                if not category:
                    errors.append(
                        bulk_error(
                            f"catégorie introuvable '{category_name}'", line=index
                        )
                    )
                    continue

            if not category and not color:
                errors.append(
                    bulk_error(
                        "couleur requise lorsqu'aucune catégorie n'est assignée",
                        line=index,
                    )
                )
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
                    "couleur": color,
                    COL_REGIONS: join_list(regions_raw),
                    COL_DEPARTMENTS: join_list(departments_raw),
                    COL_COMMUNES: join_list(communes_raw),
                }
            )

            payload: Dict[str, Any] = {
                "name": name,
                "name_short": name_short or None,
                "geo_custom_zone_status": GeoCustomZoneStatus.ACTIVE,
                "geo_custom_zone_type": GeoCustomZoneType.COMMON,
                "regions_uuids": regions_uuids,
                "departments_uuids": departments_uuids,
                "communes_uuids": communes_uuids,
                "geo_custom_zones_uuids": [],
            }

            if category:
                payload["geo_custom_zone_category_uuid"] = str(category.uuid)
            else:
                payload["color"] = color

            payloads.append(payload)

        return preview, errors, payloads
