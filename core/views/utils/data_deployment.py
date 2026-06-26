from django.core.exceptions import BadRequest
from django.utils.dateparse import parse_date
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from core.constants.geo import LAYER_TYPE_CATEGORY_NAME_MAP
from core.models.detection import Detection
from core.models.geo_commune import GeoCommune
from core.models.geo_custom_zone import GeoCustomZone
from core.models.geo_department import GeoDepartment
from core.models.geo_epci import GeoEpci
from core.models.geo_zone import GeoZone
from core.services.data_deployment import DataDeploymentService, batch_tiles_url_to_xyz
from core.services.detections_schema import DetectionsSchemaService
from core.utils.permissions import SuperAdminRolePermission

URL = "data-deployment/"
RUN_URL = "data-deployment/<int:geozone_id>/run/"


def _department_code_by_geozone(geozone_ids):
    """Department insee_code for each run geozone: itself if it's a department, its
    parent department if it's a commune or EPCI (zae_layer is keyed by department).
    Mirrors DataDeploymentService._resolve_codes so EPCI runs resolve their zae layers."""
    codes = {
        d["id"]: d["insee_code"]
        for d in GeoDepartment.objects.filter(id__in=geozone_ids).values(
            "id", "insee_code"
        )
    }
    codes.update(
        {
            c["id"]: c["department__insee_code"]
            for c in GeoCommune.objects.filter(id__in=geozone_ids).values(
                "id", "department__insee_code"
            )
        }
    )
    codes.update(
        {
            e["id"]: e["department__insee_code"]
            for e in GeoEpci.objects.filter(id__in=geozone_ids).values(
                "id", "department__insee_code"
            )
        }
    )
    return codes


def _deployment_status_by_batch(batch_ids):
    """Deployment status per detections.batch.id, from the public-schema detections
    imported for that batch (core_detection.batch_id is a stringified batch id):
      NOT_DEPLOYED       — no detection imported for the batch
      DEPLOYMENT_RUNNING — detections exist, their tile set import hasn't finished
      DEPLOYED           — detections exist and the tile set import has finished
    """
    statuses = {batch_id: "NOT_DEPLOYED" for batch_id in batch_ids}
    by_str = {str(batch_id): batch_id for batch_id in batch_ids}
    rows = (
        Detection.objects.filter(batch_id__in=by_str.keys())
        .order_by("batch_id", "id")
        .distinct("batch_id")  # first detection per batch
        .values_list("batch_id", "tile_set__last_import_ended_at")
    )
    for batch_id_str, last_import_ended_at in rows:
        statuses[by_str[batch_id_str]] = (
            "DEPLOYED" if last_import_ended_at is not None else "DEPLOYMENT_RUNNING"
        )
    return statuses


def _parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_date_or_none(value):
    """parse_date raises ValueError on a well-formed but calendar-invalid date
    (e.g. "2024-02-31"), not just None on a regex miss — treat both as no filter."""
    try:
        return parse_date(value or "")
    except ValueError:
        return None


@api_view(["GET"])
@permission_classes([SuperAdminRolePermission])
def endpoint(request):
    count, geozones = DetectionsSchemaService.get_run_geozones(
        q=request.GET.get("q") or None,
        batch_created_at_min=_parse_date_or_none(request.GET.get("batchCreatedAtMin")),
        limit=min(max(_parse_int(request.GET.get("limit")) or 20, 1), 200),
        offset=max(_parse_int(request.GET.get("offset")) or 0, 0),
    )

    geozone_ids = [g["geozone_id"] for g in geozones]
    names = dict(GeoZone.objects.filter(id__in=geozone_ids).values_list("id", "name"))
    dept_codes = _department_code_by_geozone(geozone_ids)

    batches = DetectionsSchemaService.get_batches_by_geozone(geozone_ids)
    deployment_by_batch = _deployment_status_by_batch(
        [batch["id"] for batch in batches]
    )
    batches_by_geozone = {}
    for batch in batches:
        batches_by_geozone.setdefault(batch["geozone_id"], []).append(batch)

    zae_by_dept = {}
    for zae in DetectionsSchemaService.get_zae_layers(
        list({code for code in dept_codes.values() if code})
    ):
        zae_by_dept.setdefault(zae["department_code"], []).append(zae)

    # A zae layer is deployed once a GeoCustomZone imported from it exists. Matched on
    # import_layer_name (stable) rather than name (admin-editable).
    zae_names = {zae["layer_name"] for zaes in zae_by_dept.values() for zae in zaes}
    deployed_zae_names = set(
        GeoCustomZone.objects.filter(import_layer_name__in=zae_names).values_list(
            "import_layer_name", flat=True
        )
    )

    results = []
    for geozone in geozones:
        geozone_id = geozone["geozone_id"]
        results.append(
            {
                "uuid": str(geozone_id),
                "geozone_name": names.get(geozone_id),
                "created_at": geozone["created_at"],
                "batches": [
                    {
                        "name": batch["batch_name"],
                        "created_at": batch["created_at"],
                        "tiles_url": batch_tiles_url_to_xyz(batch["batch_tiles_url"]),
                        "deploy_status": deployment_by_batch[batch["id"]],
                    }
                    for batch in batches_by_geozone.get(geozone_id, [])
                ],
                "zae_layers": [
                    {
                        "created_at": zae["created_at"],
                        "name": zae["layer_name"],
                        "type": zae["layer_type"],
                        "type_name": LAYER_TYPE_CATEGORY_NAME_MAP.get(
                            zae["layer_type"], zae["layer_type"]
                        ),
                        "year": zae["layer_year"],
                        "deploy_status": (
                            "DEPLOYED"
                            if zae["layer_name"] in deployed_zae_names
                            else "NOT_DEPLOYED"
                        ),
                    }
                    for zae in zae_by_dept.get(dept_codes.get(geozone_id), [])
                ],
            }
        )

    # Renderer camelizes snake_case keys -> camelCase JSON.
    return Response(
        {"count": count, "next": None, "previous": None, "results": results}
    )


@api_view(["POST"])
@permission_classes([SuperAdminRolePermission])
def run_endpoint(request, geozone_id):
    """Deploy a geozone's detections-schema data: create its per-batch TileSets and
    Cabanisation UserGroup inline, then queue the import commands."""
    try:
        result = DataDeploymentService.run_deployment(geozone_id=geozone_id)
    except (ValueError, BadRequest) as error:
        # ValueError = our validation (geozone/category/conflict); BadRequest = a command
        # param rejected by parse_parameters during enqueue. Both are clean 400s.
        return Response({"detail": str(error)}, status=400)
    return Response(result)
