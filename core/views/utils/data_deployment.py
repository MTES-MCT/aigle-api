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
BATCHES_URL = "data-deployment/batches/"
ZAE_URL = "data-deployment/zae/"
RUN_URL = "data-deployment/<int:geozone_id>/run/"
BATCH_RUN_URL = "data-deployment/<int:geozone_id>/batch/<int:batch_id>/run/"
ZAE_RUN_URL = "data-deployment/<int:geozone_id>/zae/<int:zae_id>/run/"


def _department_code_by_geozone(geozone_ids):
    """Department insee_code for each run geozone: itself if it's a department, its
    parent department if it's a commune or EPCI (zae_layer is keyed by department).
    Mirrors DataDeploymentService._resolve_codes so EPCI runs resolve their zae layers.
    Geozone ids are disjoint across types, so update order doesn't matter."""
    codes = {}
    for model, field in (
        (GeoDepartment, "insee_code"),
        (GeoCommune, "department__insee_code"),
        (GeoEpci, "department__insee_code"),
    ):
        codes.update(
            {
                row["id"]: row[field]
                for row in model.objects.filter(id__in=geozone_ids).values("id", field)
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


def _parse_id_list(value):
    """Absent / non-list -> None = deploy all. A JSON list -> its parseable ints (an
    empty list stays [] = deploy none). The parser camelizes, so the body's `batchIds`
    reaches here as request.data["batch_ids"]."""
    if not isinstance(value, (list, tuple)):
        return None
    return [parsed for parsed in map(_parse_int, value) if parsed is not None]


def _parse_bool(value):
    """Body flags arrive as real JSON booleans from the admin UI; be lenient about the
    string forms a hand-rolled call can send. Anything else is False."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def _parse_date_or_none(value):
    """parse_date raises ValueError on a well-formed but calendar-invalid date
    (e.g. "2024-02-31"), not just None on a regex miss — treat both as no filter."""
    try:
        return parse_date(value or "")
    except ValueError:
        return None


def _pagination(request):
    return (
        min(max(_parse_int(request.GET.get("limit")) or 20, 1), 200),
        max(_parse_int(request.GET.get("offset")) or 0, 0),
    )


def _paginated(count, results):
    # Renderer camelizes snake_case keys -> camelCase JSON.
    return Response(
        {"count": count, "next": None, "previous": None, "results": results}
    )


def _serialize_batch(batch, deploy_status):
    return {
        "id": batch["id"],
        "name": batch["batch_name"],
        "created_at": batch["created_at"],
        "tiles_url": batch_tiles_url_to_xyz(batch["batch_tiles_url"]),
        "deploy_status": deploy_status,
    }


def _deployed_zae_layers(zaes):
    """The (department code, layer name) pairs already imported as a GeoCustomZone.

    Matched on import_layer_name (stable) rather than name (admin-editable), and paired
    with the department the zone is attached to: layer names repeat across departments
    ("ZFEE"), so an unscoped name match reports a layer deployed in one department as
    deployed in every other one. Soft-deleted zones don't count either — the import
    ignores them, so there would be nothing there to redeploy over.

    This status is what the admin UI offers the override option from, so a false
    positive costs an operator a confusing (destructive-sounding) extra click.
    """
    return set(
        GeoCustomZone.objects.filter(
            deleted=False,
            import_layer_name__in={zae["layer_name"] for zae in zaes},
        ).values_list("geo_zones__geodepartment__insee_code", "import_layer_name")
    )


def _serialize_zae(zae, deployed_zae_layers):
    return {
        "id": zae["id"],
        "created_at": zae["created_at"],
        "name": zae["layer_name"],
        "type": zae["layer_type"],
        "type_name": LAYER_TYPE_CATEGORY_NAME_MAP.get(
            zae["layer_type"], zae["layer_type"]
        ),
        "year": zae["layer_year"],
        "deploy_status": (
            "DEPLOYED"
            if (zae["department_code"], zae["layer_name"]) in deployed_zae_layers
            else "NOT_DEPLOYED"
        ),
    }


@api_view(["GET"])
@permission_classes([SuperAdminRolePermission])
def endpoint(request):
    limit, offset = _pagination(request)
    count, geozones = DetectionsSchemaService.get_run_geozones(
        q=request.GET.get("q") or None,
        batch_created_at_min=_parse_date_or_none(request.GET.get("batchCreatedAtMin")),
        limit=limit,
        offset=offset,
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

    deployed_zae_layers = _deployed_zae_layers(
        [zae for zaes in zae_by_dept.values() for zae in zaes]
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
                    _serialize_batch(batch, deployment_by_batch[batch["id"]])
                    for batch in batches_by_geozone.get(geozone_id, [])
                ],
                "zae_layers": [
                    _serialize_zae(zae, deployed_zae_layers)
                    for zae in zae_by_dept.get(dept_codes.get(geozone_id), [])
                ],
            }
        )

    return _paginated(count, results)


@api_view(["GET"])
@permission_classes([SuperAdminRolePermission])
def batches_endpoint(request):
    """Flat listing of every batch, searchable on batch name. Each row carries the
    geozone of its run so it can be deployed straight from the list (a batch whose run
    has no geozone has geozone_id null and isn't deployable)."""
    limit, offset = _pagination(request)
    count, batches = DetectionsSchemaService.get_batches(
        q=request.GET.get("q") or None, limit=limit, offset=offset
    )

    deployment_by_batch = _deployment_status_by_batch([b["id"] for b in batches])
    names = dict(
        GeoZone.objects.filter(
            id__in={b["geozone_id"] for b in batches if b["geozone_id"]}
        ).values_list("id", "name")
    )

    results = [
        {
            **_serialize_batch(batch, deployment_by_batch[batch["id"]]),
            "uuid": str(batch["id"]),
            "geozone_id": batch["geozone_id"],
            "geozone_name": names.get(batch["geozone_id"]),
        }
        for batch in batches
    ]
    return _paginated(count, results)


@api_view(["GET"])
@permission_classes([SuperAdminRolePermission])
def zae_endpoint(request):
    """Zae layers grouped by department, searchable on layer name. The department's
    GeoZone id (null when the department isn't in the app yet) is what the per-layer
    deploy endpoint is addressed with."""
    limit, offset = _pagination(request)
    q = request.GET.get("q") or None
    count, department_codes = DetectionsSchemaService.get_zae_department_codes(
        q=q, limit=limit, offset=offset
    )

    zaes = DetectionsSchemaService.get_zae_layers(department_codes, q=q)
    deployed_zae_layers = _deployed_zae_layers(zaes)
    zae_by_dept = {}
    for zae in zaes:
        zae_by_dept.setdefault(zae["department_code"], []).append(zae)

    departments = {
        row["insee_code"]: row
        for row in GeoDepartment.objects.filter(insee_code__in=department_codes).values(
            "insee_code", "id", "name"
        )
    }

    results = [
        {
            "uuid": code,
            "department_code": code,
            "department_name": (departments.get(code) or {}).get("name"),
            "geozone_id": (departments.get(code) or {}).get("id"),
            "zae_layers": [
                _serialize_zae(zae, deployed_zae_layers)
                for zae in zae_by_dept.get(code, [])
            ],
        }
        for code in department_codes
    ]
    return _paginated(count, results)


@api_view(["POST"])
@permission_classes([SuperAdminRolePermission])
def run_endpoint(request, geozone_id):
    """Deploy a geozone's detections-schema data: create its per-batch TileSets and
    Cabanisation UserGroup inline, then queue the import commands. Optional body
    `batchIds` / `zaeLayerIds` restrict the deploy to the selected batches / zae layers
    (absent = all); only the specified, in-scope items are deployed. Optional body
    `overrideCustomZones` replaces the custom zones the selected zae layers already have
    instead of failing the import on them."""
    try:
        result = DataDeploymentService.run_deployment(
            geozone_id=geozone_id,
            batch_ids=_parse_id_list(request.data.get("batch_ids")),
            zae_layer_ids=_parse_id_list(request.data.get("zae_layer_ids")),
            override_custom_zones=_parse_bool(
                request.data.get("override_custom_zones")
            ),
        )
    except (ValueError, BadRequest) as error:
        # ValueError = our validation (geozone/category/conflict); BadRequest = a command
        # param rejected by parse_parameters during enqueue. Both are clean 400s.
        return Response({"detail": str(error)}, status=400)
    return Response(result)


@api_view(["POST"])
@permission_classes([SuperAdminRolePermission])
def run_batch_endpoint(request, geozone_id, batch_id):
    """Deploy a single batch (a new millesime) onto an already-deployed geozone:
    create the batch's TileSet and queue its detections import."""
    try:
        result = DataDeploymentService.run_batch_deployment(
            geozone_id=geozone_id, batch_id=batch_id
        )
    except (ValueError, BadRequest) as error:
        return Response({"detail": str(error)}, status=400)
    return Response(result)


@api_view(["POST"])
@permission_classes([SuperAdminRolePermission])
def run_zae_endpoint(request, geozone_id, zae_id):
    """Deploy a single zae layer (zone à enjeux) for an already-deployed geozone:
    import that source row as a GeoCustomZone. Optional body `overrideCustomZones`
    replaces the custom zone it conflicts with — required to redeploy a layer that is
    already deployed, which the import would otherwise skip."""
    try:
        result = DataDeploymentService.run_zae_deployment(
            geozone_id=geozone_id,
            zae_id=zae_id,
            override_custom_zones=_parse_bool(
                request.data.get("override_custom_zones")
            ),
        )
    except (ValueError, BadRequest) as error:
        return Response({"detail": str(error)}, status=400)
    return Response(result)
