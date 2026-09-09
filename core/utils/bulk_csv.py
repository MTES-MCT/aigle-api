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
import logging
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from django.db import transaction
from django.http import HttpResponse
from rest_framework import status
from rest_framework.response import Response

from core.constants.collectivity import CODE_FIELD_BY_LEVEL, model_for_level
from core.models.geo_zone import GeoZone, GeoZoneType
from core.serializers.utils.with_collectivities import FIELD_NAME_BY_LEVEL
from core.models.user_action_log import UserActionLog, UserActionLogAction


logger = logging.getLogger(__name__)

# Un CSV d'import est lu intégralement en mémoire : au-delà de cette taille on refuse
# avant la lecture plutôt que de laisser un envoi arbitraire saturer le worker.
MAX_UPLOAD_SIZE_BYTES = 5 * 1024 * 1024

CSV_SEP = ";"
LIST_SEP = "|"
BOM = "﻿"

COL_REGIONS = "régions (code INSEE)"
COL_DEPARTMENTS = "départements (code INSEE)"
COL_EPCIS = "EPCI (code SIREN)"
COL_COMMUNES = "communes (code ISO)"

# Coarse -> fine, which is the column order of every collectivity-bearing export.
# Import reads columns by name, so a file predating a new level still parses.
COL_BY_LEVEL = {
    GeoZoneType.REGION: COL_REGIONS,
    GeoZoneType.DEPARTMENT: COL_DEPARTMENTS,
    GeoZoneType.EPCI: COL_EPCIS,
    GeoZoneType.COMMUNE: COL_COMMUNES,
}
COLLECTIVITY_CSV_HEADERS = list(COL_BY_LEVEL.values())

# Excel et LibreOffice évaluent une cellule commençant par un de ces caractères comme
# une formule. Un nom de groupe ou de zone est du texte libre : =HYPERLINK(...) s'y
# glisse et s'exécute sur le poste de l'administrateur qui ouvre l'export. Même
# neutralisation que côté frontend (aigle-frontend, utils/download.ts).
CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

BulkError = Dict[str, Any]


def escape_csv_formula(value: str) -> str:
    return f"'{value}" if value.startswith(CSV_FORMULA_PREFIXES) else value


def unescape_csv_formula(value: str) -> str:
    """Inverse exacte d'``escape_csv_formula`` : l'aller-retour export -> import doit
    rendre le nom d'origine. N'enlève l'apostrophe que devant un caractère déclencheur,
    donc un vrai nom commençant par une apostrophe est laissé intact."""
    if value.startswith("'") and value[1:2] in CSV_FORMULA_PREFIXES:
        return value[1:]
    return value


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
    size = getattr(uploaded_file, "size", None)
    if size is not None and size > MAX_UPLOAD_SIZE_BYTES:
        return [], [
            bulk_error(
                f"Fichier trop volumineux (maximum {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)} Mo)"
            )
        ]

    # Le texte de l'exception décrit l'intérieur du serveur (chemins, pilote, encodage) :
    # il part au log, le client reçoit un message stable.
    try:
        raw = uploaded_file.read()
    except Exception:
        logger.exception("Lecture du CSV importé impossible")
        return [], [bulk_error("Impossible de lire le fichier")]

    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = raw.decode("latin-1")
            except UnicodeDecodeError:
                logger.exception("Encodage du CSV importé non supporté")
                return [], [bulk_error("Encodage du fichier non supporté")]
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
            normalized[normalized_key] = unescape_csv_formula((value or "").strip())
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
            cleaned[key] = "" if value is None else escape_csv_formula(str(value))
        writer.writerow(cleaned)
    response.write(buffer.getvalue())


def partition_zones_by_type(
    zones: Iterable[GeoZone],
) -> Dict[str, List[str]]:
    """Group GeoZones by level, returning lists of codes (insee/siren/iso).

    Keyed by GeoZoneType; zones of any other type (custom zones) are dropped.
    Used by export endpoints that emit one column per collectivity level.
    """
    ids_by_level: Dict[str, List[int]] = {level: [] for level in COL_BY_LEVEL}

    for zone in zones:
        if zone.geo_zone_type in ids_by_level:
            ids_by_level[zone.geo_zone_type].append(zone.id)

    codes_by_level: Dict[str, List[str]] = {}
    for level, ids in ids_by_level.items():
        codes = dict(
            model_for_level(level)
            .objects.filter(id__in=ids)
            .values_list("id", CODE_FIELD_BY_LEVEL[level])
        )
        codes_by_level[level] = [codes[zid] for zid in ids if zid in codes]

    return codes_by_level


def parse_collectivity_columns(row: Dict[str, str]) -> Dict[str, List[str]]:
    """Read every collectivity column of an imported row into {level: [codes]}.

    A column absent from the uploaded file yields an empty list, so files written
    before a level existed still import.
    """
    return {
        level: parse_list(row.get(col.lower(), ""))
        for level, col in COL_BY_LEVEL.items()
    }


def collectivity_csv_cells(codes_by_level: Dict[str, List[str]]) -> Dict[str, str]:
    """{column header: joined codes} — the collectivity half of an export row or of
    an import preview row."""
    return {
        col: join_list(codes_by_level.get(level) or [])
        for level, col in COL_BY_LEVEL.items()
    }


def collectivity_uuids_payload(
    uuids_by_level: Dict[str, List[str]],
) -> Dict[str, List[str]]:
    """{level: [uuids]} -> the `<level>s_uuids` keys the input serializers expect."""
    return {
        f"{FIELD_NAME_BY_LEVEL[level]}_uuids": uuids_by_level.get(level) or []
        for level in COL_BY_LEVEL
    }


_LEVEL_LABELS = {
    GeoZoneType.REGION: "région",
    GeoZoneType.DEPARTMENT: "département",
    GeoZoneType.EPCI: "EPCI",
    GeoZoneType.COMMUNE: "commune",
}


def resolve_collectivity_uuids(
    codes_by_level: Dict[str, List[str]],
    line_index: int,
    errors: List[BulkError],
) -> Tuple[Dict[str, List[str]], bool]:
    """Resolve collectivity codes to GeoZone uuids, per level.

    Each level is looked up on its own code column (insee/siren/iso). Any unmatched
    code is appended to ``errors`` (mutated in place). Returns
    ({level: [uuids]}, has_error).
    """
    has_error = False
    resolved: Dict[str, List[str]] = {level: [] for level in COL_BY_LEVEL}

    for level, raw_values in codes_by_level.items():
        model = model_for_level(level)
        code_field = CODE_FIELD_BY_LEVEL[level]

        for raw in raw_values:
            obj = model.objects.filter(**{code_field: raw.strip()}).first()
            if not obj:
                errors.append(
                    bulk_error(
                        f"{_LEVEL_LABELS[level]} avec le code '{raw}' introuvable",
                        line=line_index,
                    )
                )
                has_error = True
                continue
            resolved[level].append(str(obj.uuid))

    return resolved, has_error


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
