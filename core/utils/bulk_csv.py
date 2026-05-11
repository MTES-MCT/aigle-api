"""Shared helpers for CSV bulk import / export endpoints.

All admin bulk CSV endpoints (User, UserGroup, GeoCustomZone, TileSet) share
the same wire format, so the parsing/writing/zone-resolution logic lives here
to avoid drift between viewsets.

CSV format:
- field separator: ";" (Excel-FR friendly)
- inner list separator: "|" (for columns containing lists of names)
- encoding: UTF-8 with BOM (so Excel renders accents correctly)
"""

import csv
import io
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from django.db import transaction
from django.http import HttpResponse
from rest_framework import status
from rest_framework.response import Response

from core.models.geo_commune import GeoCommune
from core.models.geo_department import GeoDepartment
from core.models.geo_region import GeoRegion
from core.models.geo_zone import GeoZone, GeoZoneType
from core.models.user_action_log import UserActionLog, UserActionLogAction


CSV_SEP = ";"
LIST_SEP = "|"
BOM = "﻿"

COL_REGIONS = "régions (code INSEE)"
COL_DEPARTMENTS = "départements (code INSEE)"
COL_COMMUNES = "communes (code ISO)"

BulkError = Dict[str, Any]


def bulk_error(message: str, line: Optional[int] = None) -> BulkError:
    return {"line": line, "message": message}


def parse_list(value: Optional[str]) -> List[str]:
    """Split a list-of-names cell on LIST_SEP, trimming and dropping empties."""
    if not value:
        return []
    return [item.strip() for item in value.split(LIST_SEP) if item and item.strip()]


def join_list(values: Iterable[str]) -> str:
    return LIST_SEP.join(v for v in values if v)


def parse_csv(uploaded_file) -> Tuple[List[Dict[str, str]], List[BulkError]]:
    """Parse an uploaded CSV file.

    Returns (rows, errors) where rows is a list of dicts keyed by normalized
    header (lowercase, stripped). Errors is a list of structured error dicts;
    if non-empty, callers should bail before attempting any per-row validation.
    """
    try:
        raw = uploaded_file.read()
    except Exception as exc:
        return [], [bulk_error(f"Impossible de lire le fichier: {exc}")]

    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = raw.decode("latin-1")
            except UnicodeDecodeError as exc:
                return [], [bulk_error(f"Encodage du fichier non supporté: {exc}")]
    else:
        text = raw.lstrip(BOM)

    reader = csv.DictReader(io.StringIO(text), delimiter=CSV_SEP)
    if not reader.fieldnames:
        return [], [bulk_error("Le fichier CSV est vide ou invalide")]

    normalized_field_map = {fn: (fn or "").strip().lower() for fn in reader.fieldnames}

    rows: List[Dict[str, str]] = []
    for raw_row in reader:
        normalized: Dict[str, str] = {}
        for original, normalized_key in normalized_field_map.items():
            value = raw_row.get(original)
            normalized[normalized_key] = (value or "").strip()
        rows.append(normalized)

    return rows, []


def write_csv(
    response: HttpResponse, headers: Sequence[str], rows: Iterable[Dict[str, Any]]
) -> None:
    """Write a CSV body to ``response``.

    Always emits a BOM so Excel-FR opens UTF-8 correctly. Rows are dicts; values
    that are lists are joined with LIST_SEP automatically.
    """
    buffer = io.StringIO()
    buffer.write(BOM)
    writer = csv.DictWriter(buffer, fieldnames=list(headers), delimiter=CSV_SEP)
    writer.writeheader()
    for row in rows:
        cleaned = {}
        for key in headers:
            value = row.get(key, "")
            if isinstance(value, (list, tuple)):
                value = join_list(str(v) for v in value)
            cleaned[key] = "" if value is None else str(value)
        writer.writerow(cleaned)
    response.write(buffer.getvalue())


def partition_zones_by_type(
    zones: Iterable[GeoZone],
) -> Dict[str, List[str]]:
    """Group GeoZones by type, returning lists of codes (insee/iso).

    Returns a dict keyed by GeoZoneType.{REGION,DEPARTMENT,COMMUNE} containing
    the matching zone codes (insee_code for regions and departments, iso_code
    for communes). Used by export endpoints that emit one column per
    collectivity level.
    """
    ids_by_type: Dict[str, List[int]] = {
        GeoZoneType.REGION: [],
        GeoZoneType.DEPARTMENT: [],
        GeoZoneType.COMMUNE: [],
    }
    for zone in zones:
        if zone.geo_zone_type in ids_by_type:
            ids_by_type[zone.geo_zone_type].append(zone.id)

    region_codes = dict(
        GeoRegion.objects.filter(id__in=ids_by_type[GeoZoneType.REGION]).values_list(
            "id", "insee_code"
        )
    )
    department_codes = dict(
        GeoDepartment.objects.filter(
            id__in=ids_by_type[GeoZoneType.DEPARTMENT]
        ).values_list("id", "insee_code")
    )
    commune_codes = dict(
        GeoCommune.objects.filter(id__in=ids_by_type[GeoZoneType.COMMUNE]).values_list(
            "id", "iso_code"
        )
    )

    return {
        GeoZoneType.REGION: [
            region_codes[zid]
            for zid in ids_by_type[GeoZoneType.REGION]
            if zid in region_codes
        ],
        GeoZoneType.DEPARTMENT: [
            department_codes[zid]
            for zid in ids_by_type[GeoZoneType.DEPARTMENT]
            if zid in department_codes
        ],
        GeoZoneType.COMMUNE: [
            commune_codes[zid]
            for zid in ids_by_type[GeoZoneType.COMMUNE]
            if zid in commune_codes
        ],
    }


def resolve_collectivity_uuids(
    regions: List[str],
    departments: List[str],
    communes: List[str],
    line_index: int,
    errors: List[BulkError],
) -> Tuple[List[str], List[str], List[str], bool]:
    """Resolve collectivity codes to GeoZone uuids.

    Regions and departments are looked up by ``insee_code``, communes by
    ``iso_code``. Any unmatched code is appended to ``errors`` (mutated in
    place). Returns (region_uuids, department_uuids, commune_uuids, has_error).
    """
    has_error = False
    resolved: Dict[str, List[str]] = {"région": [], "département": [], "commune": []}

    for label, model, raw_values, code_field in (
        ("région", GeoRegion, regions, "insee_code"),
        ("département", GeoDepartment, departments, "insee_code"),
        ("commune", GeoCommune, communes, "iso_code"),
    ):
        for raw in raw_values:
            obj = model.objects.filter(**{code_field: raw.strip()}).first()
            if not obj:
                errors.append(
                    bulk_error(
                        f"{label} avec le code '{raw}' introuvable",
                        line=line_index,
                    )
                )
                has_error = True
                continue
            resolved[label].append(str(obj.uuid))

    return (
        resolved["région"],
        resolved["département"],
        resolved["commune"],
        has_error,
    )


def attachment_response(filename: str) -> HttpResponse:
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


ValidateFn = Callable[
    [Any], Tuple[List[Dict[str, Any]], List[BulkError], List[Dict[str, Any]]]
]


def bulk_import_preview_response(validate_fn: ValidateFn, request) -> Response:
    """Return the standard preview body: rows_count + preview rows + errors."""
    preview, errors, _ = validate_fn(request)
    return Response({"rows_count": len(preview), "preview": preview, "errors": errors})


def bulk_import_run(
    validate_fn: ValidateFn,
    request,
    serializer_class,
    log_kind: str,
    extra_response: Optional[Callable[[List[Any]], Dict[str, Any]]] = None,
) -> Response:
    """Validate, then atomically save each payload via ``serializer_class``.

    Logs a ``UserActionLog`` row on success. ``extra_response`` may add fields to
    the 201 body using the saved instances (e.g. generated passwords).
    """
    preview, errors, payloads = validate_fn(request)
    if errors:
        return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)

    saved_instances: List[Any] = []
    with transaction.atomic():
        for payload in payloads:
            serializer = serializer_class(data=payload, context={"request": request})
            serializer.is_valid(raise_exception=True)
            saved_instances.append(serializer.save())

    UserActionLog.objects.create(
        user=request.user,
        route=request.path,
        action=UserActionLogAction.CUSTOM,
        data={"kind": log_kind, "count": len(saved_instances)},
    )

    body: Dict[str, Any] = {"created_count": len(saved_instances)}
    if extra_response:
        body.update(extra_response(saved_instances))
    return Response(body, status=status.HTTP_201_CREATED)
