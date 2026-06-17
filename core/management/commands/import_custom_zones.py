import re
from datetime import datetime
from typing import Any, Dict, List, Set, Tuple

from django.contrib.gis.geos import GEOSGeometry
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from core.constants.geo import SRID
from core.models.geo_custom_zone import (
    GeoCustomZone,
    GeoCustomZoneStatus,
    GeoCustomZoneType,
)
from core.models.geo_custom_zone_category import GeoCustomZoneCategory
from core.models.geo_department import GeoDepartment
from core.services.geo_custom_zone import GeoCustomZoneService
from core.utils.logs_helpers import log_command_event
from core.utils.string import normalize

DEFAULT_TABLE_SCHEMA = "detections"
DEFAULT_TABLE_NAME = "zae_layer"

# detections.zae_layer.layer_type -> GeoCustomZoneCategory.name
LAYER_TYPE_CATEGORY_NAME_MAP = {
    "zfee": "Zones à fort enjeu environnemental",
    "zrf": "Zones à risque fort",
    "zi": "Zones inondables",
    "zenaf": "Zones naturelles et agricoles",
}

# Schema / table names can't be passed as query parameters, so they are validated
# against a strict allowlist before being interpolated into the SQL (see CLAUDE.md
# "Management Commands and SQL").
IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def log_event(info: str):
    log_command_event(command_name="import_custom_zones", info=info)


class Command(BaseCommand):
    help = (
        "Import custom zones from the detections schema (default table: zae_layer). "
        "Each source row becomes one GeoCustomZone, attached to the department "
        "matching department_code and to the category matching layer_type. "
        "Re-running is idempotent: rows whose import_id already exists are skipped."
    )

    def add_arguments(self, parser):
        parser.add_argument("--table-name", type=str, default=DEFAULT_TABLE_NAME)
        parser.add_argument("--table-schema", type=str, default=DEFAULT_TABLE_SCHEMA)
        parser.add_argument(
            "--source-srid",
            type=int,
            default=SRID,
            help=(
                "SRID assumed for source geometries whose declared SRID is unknown "
                "(0 or absent from spatial_ref_sys). Geometries that declare a known "
                "SRID are reprojected from it. Defaults to %(default)s."
            ),
        )
        parser.add_argument(
            "--department-codes",
            action="append",
            required=False,
            help=(
                "Restrict the import to these department codes (matched against "
                "GeoDepartment.insee_code). Repeat the flag for several departments."
            ),
        )
        parser.add_argument(
            "--ids",
            action="append",
            type=int,
            required=False,
            help=(
                "Restrict the import to these source row ids (matched against "
                "the source table's primary key). Repeat the flag for several ids."
            ),
        )
        parser.add_argument(
            "--force",
            action="store_true",
            default=False,
            help=(
                "Import even if a custom zone already exists for the same department "
                "and category (skips the duplicate check). Already-imported rows are "
                "still skipped by import_id."
            ),
        )
        parser.add_argument(
            "--ignore-categories",
            action="store_true",
            default=False,
            help=(
                "Import every source row as an uncategorized custom zone "
                "(geo_custom_zone_category = NULL). Rows with unknown layer_type "
                "are no longer skipped, the (department, category) duplicate check "
                "is bypassed, and no GeoCustomZoneCategory rows need to exist."
            ),
        )

    def handle(self, *args, **options):
        table_name = options["table_name"]
        table_schema = options["table_schema"]
        source_srid = options["source_srid"]
        department_codes = options["department_codes"]
        ids = options["ids"]
        force = options["force"]
        ignore_categories = options["ignore_categories"]

        if not IDENTIFIER_RE.match(table_name) or not IDENTIFIER_RE.match(table_schema):
            raise CommandError(f"Invalid table reference: {table_schema}.{table_name}")

        start_time = datetime.now()
        log_event(f"Starting custom zones import from {table_schema}.{table_name}")
        if ignore_categories:
            log_event(
                "--ignore-categories enabled: zones will be imported as uncategorized"
            )

        department_map = self._get_department_map()

        rows = self._read_rows(
            table_schema=table_schema,
            table_name=table_name,
            source_srid=source_srid,
            department_codes=department_codes,
            ids=ids,
        )

        # When categories are honored, every layer type actually present must be
        # seeded as a GeoCustomZoneCategory; the --ignore-categories path skips
        # this entirely and stores NULL on the category FK.
        category_map = {} if ignore_categories else self._get_category_map(rows)

        resolved, skipped = self._resolve_rows(
            rows,
            category_map=category_map,
            department_map=department_map,
            ignore_categories=ignore_categories,
        )

        # idempotency: never re-create a row that was already imported
        resolved, already_imported = self._filter_already_imported(resolved)
        if already_imported:
            log_event(
                f"Skipping {already_imported} row(s) already imported "
                "(existing import_id)"
            )

        if not resolved:
            log_event("Nothing to import. Done.")
            return

        # duplicate (department, category) guard — before any write. Meaningless
        # under --ignore-categories (every row's category is NULL), so skipped.
        if ignore_categories:
            log_event(
                "--ignore-categories enabled: skipping the "
                "(department, category) duplicate check"
            )
        elif force:
            log_event(
                "--force enabled: skipping the (department, category) duplicate check"
            )
        else:
            self._check_no_duplicate_pairs(resolved)

        created_zone_ids = self._create_zones(resolved)

        log_event(
            f"Custom zones import finished: {len(created_zone_ids)} created, "
            f"{skipped} skipped, {already_imported} already imported "
            f"(elapsed: {datetime.now() - start_time})"
        )

        if created_zone_ids:
            log_event(f"Associating detections to {len(created_zone_ids)} new zone(s)")
            GeoCustomZoneService.associate_detections_to_custom_zones(
                custom_zone_ids=created_zone_ids,
                log_event=log_event,
            )

    def _get_category_map(
        self, rows: List[Dict[str, Any]]
    ) -> Dict[str, GeoCustomZoneCategory]:
        """Resolve the GeoCustomZoneCategory for every *known* layer type present in
        the source rows, failing fast if any of those categories is missing.

        Scoped to the layer types actually being imported (not all four) so a partial
        import doesn't require every category to be seeded. Unknown layer types (not
        in the mapping) are ignored here and skipped later in _resolve_rows.
        """
        present_layer_types = {
            (row.get("layer_type") or "").strip().lower() for row in rows
        }
        needed_layer_types = {
            layer_type
            for layer_type in present_layer_types
            if layer_type in LAYER_TYPE_CATEGORY_NAME_MAP
        }
        if not needed_layer_types:
            return {}

        # normalized category name -> layer_type
        wanted_by_normalized = {
            normalize(LAYER_TYPE_CATEGORY_NAME_MAP[layer_type]): layer_type
            for layer_type in needed_layer_types
        }
        categories = GeoCustomZoneCategory.objects.filter(
            name_normalized__in=list(wanted_by_normalized.keys()),
            deleted=False,
        )
        found_by_normalized = {
            category.name_normalized: category for category in categories
        }

        missing = sorted(
            LAYER_TYPE_CATEGORY_NAME_MAP[layer_type]
            for normalized, layer_type in wanted_by_normalized.items()
            if normalized not in found_by_normalized
        )
        if missing:
            raise CommandError(
                "Missing GeoCustomZoneCategory in the database for: "
                + ", ".join(missing)
            )

        return {
            layer_type: found_by_normalized[normalized]
            for normalized, layer_type in wanted_by_normalized.items()
        }

    def _get_department_map(self) -> Dict[str, GeoDepartment]:
        # GeoZoneManager already defers the (heavy) geometry field.
        departments = GeoDepartment.objects.filter(deleted=False)
        return {department.insee_code: department for department in departments}

    def _read_rows(
        self,
        table_schema: str,
        table_name: str,
        source_srid: int,
        department_codes: List[str],
        ids: List[int] = None,
    ) -> List[Dict[str, Any]]:
        # ST_MakeValid: zones drive spatial containment downstream, so an invalid
        # source polygon would break those queries — repair on read.
        # SRID handling: a single bad row must not abort the whole import. ST_Transform
        # raises (not NULL) on a SRID absent from spatial_ref_sys (including 0), so we
        # only transform from a SRID we know is registered; anything else (0 or an
        # unregistered code) is coerced to --source-srid first.
        select_sql = """
            SELECT
                id,
                layer_name,
                layer_type,
                layer_year,
                department_code,
                ST_Transform(
                    CASE
                        WHEN ST_SRID(geometry) IN (SELECT srid FROM spatial_ref_sys)
                            THEN ST_MakeValid(geometry)
                        ELSE ST_SetSRID(ST_MakeValid(geometry), %s)
                    END,
                    %s
                ) AS geometry
            FROM {schema}.{table}
            WHERE geometry IS NOT NULL
        """.format(schema=table_schema, table=table_name)
        params: List[Any] = [source_srid, SRID]

        if department_codes:
            select_sql += " AND department_code = ANY(%s)"
            params.append(list(department_codes))

        if ids:
            select_sql += " AND id = ANY(%s)"
            params.append(list(ids))

        select_sql += " ORDER BY id"

        with connection.cursor() as cursor:
            cursor.execute(select_sql, params)
            columns = [col[0] for col in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

        log_event(f"Read {len(rows)} row(s) from {table_schema}.{table_name}")
        return rows

    def _resolve_rows(
        self,
        rows: List[Dict[str, Any]],
        category_map: Dict[str, GeoCustomZoneCategory],
        department_map: Dict[str, GeoDepartment],
        ignore_categories: bool = False,
    ) -> Tuple[List[Dict[str, Any]], int]:
        resolved: List[Dict[str, Any]] = []
        skipped = 0

        for row in rows:
            layer_type = (row.get("layer_type") or "").strip().lower()
            department_code = (row.get("department_code") or "").strip()

            # Under --ignore-categories, unknown layer_type is no longer fatal:
            # the zone is created with a NULL category.
            if ignore_categories:
                category = None
            else:
                category = category_map.get(layer_type)
                if not category:
                    log_event(
                        f"Row id={row['id']}: unknown layer_type "
                        f"'{row.get('layer_type')}', skipping"
                    )
                    skipped += 1
                    continue

            department = department_map.get(department_code)
            if not department:
                log_event(
                    f"Row id={row['id']}: unknown department_code "
                    f"'{row.get('department_code')}', skipping"
                )
                skipped += 1
                continue

            geometry_raw = row.get("geometry")
            if not geometry_raw:
                log_event(f"Row id={row['id']}: empty geometry, skipping")
                skipped += 1
                continue

            geometry = GEOSGeometry(geometry_raw, srid=SRID)
            # ST_MakeValid can collapse a degenerate polygon to an EMPTY geometry,
            # which is non-NULL — guard against creating a zone that matches nothing.
            if geometry.empty:
                log_event(f"Row id={row['id']}: geometry empty after repair, skipping")
                skipped += 1
                continue

            resolved.append(
                {
                    "id": row["id"],
                    "layer_name": row.get("layer_name"),
                    "layer_type": layer_type,
                    "category": category,
                    "department": department,
                    "geometry": geometry,
                }
            )

        return resolved, skipped

    def _filter_already_imported(
        self, resolved: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Drop rows whose import_id already has a (non-deleted) GeoCustomZone, so the
        command can be re-run safely without creating duplicates."""
        import_ids = [item["id"] for item in resolved]
        if not import_ids:
            return resolved, 0

        existing_import_ids = set(
            GeoCustomZone.objects.filter(
                deleted=False, import_id__in=import_ids
            ).values_list("import_id", flat=True)
        )
        kept = [item for item in resolved if item["id"] not in existing_import_ids]
        return kept, len(resolved) - len(kept)

    def _check_no_duplicate_pairs(self, resolved: List[Dict[str, Any]]) -> None:
        """Abort if a GeoCustomZone already exists — in the database OR within this
        same import batch — for any (department, category) pair. Bypassed with --force."""
        department_by_id = {
            item["department"].id: item["department"] for item in resolved
        }
        category_by_id = {item["category"].id: item["category"] for item in resolved}

        # in-batch duplicates: two source rows resolving to the same (department, category)
        seen: Set[Tuple[int, int]] = set()
        conflicts: Set[Tuple[int, int]] = set()
        for item in resolved:
            pair = (item["department"].id, item["category"].id)
            if pair in seen:
                conflicts.add(pair)
            seen.add(pair)

        # pre-existing zones in the database
        for department_id, category_id in seen:
            exists = GeoCustomZone.objects.filter(
                deleted=False,
                geo_custom_zone_category_id=category_id,
                geo_zones__id=department_id,
            ).exists()
            if exists:
                conflicts.add((department_id, category_id))

        if conflicts:
            details = ", ".join(
                f"{department_by_id[d].name} / {category_by_id[c].name}"
                for d, c in sorted(conflicts)
            )
            raise CommandError(
                "A custom zone already exists (or is duplicated within this import) for "
                f"these department/category pairs: {details}. Use --force to import anyway."
            )

    def _create_zones(self, resolved: List[Dict[str, Any]]) -> List[int]:
        created_ids: List[int] = []
        with transaction.atomic():
            for item in resolved:
                department = item["department"]
                category = item["category"]
                name = item["layer_name"] or self._default_zone_name(item)

                zone = GeoCustomZone(
                    name=name,
                    geometry=item["geometry"],
                    geo_custom_zone_type=GeoCustomZoneType.COMMON,
                    geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE,
                    geo_custom_zone_category=category,
                    import_id=item["id"],
                )
                # save() (via GeoZone.save) sets geo_zone_type=CUSTOM and name_normalized.
                zone.save()
                zone.geo_zones.add(department)
                created_ids.append(zone.id)

        log_event(f"Created {len(created_ids)} custom zone(s)")
        return created_ids

    @staticmethod
    def _default_zone_name(item: Dict[str, Any]) -> str:
        """Fallback name when the source row carries no layer_name."""
        department = item["department"]
        category = item["category"]
        if category is not None:
            return f"{category.name} - {department.name}"
        layer_type = item.get("layer_type")
        if layer_type:
            return f"{layer_type} - {department.name}"
        return f"Zone - {department.name}"
