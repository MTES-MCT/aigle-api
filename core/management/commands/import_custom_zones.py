import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from django.contrib.gis.geos import GEOSGeometry
from django.core.management.base import BaseCommand, CommandError
from core.management.base import CommandRunTrackerMixin
from django.db import connection, transaction

from core.constants.geo import LAYER_TYPE_CATEGORY_NAME_MAP, SRID
from core.models.geo_commune import GeoCommune
from core.models.geo_epci import GeoEpci
from core.models.geo_custom_zone import (
    GeoCustomZone,
    GeoCustomZoneStatus,
    GeoCustomZoneType,
)
from core.models.geo_custom_zone_category import GeoCustomZoneCategory
from core.models.geo_department import GeoDepartment
from core.models.user_group import UserGroup
from core.services.geo_custom_zone import GeoCustomZoneService
from core.utils.cache import invalidate_deployed_data_cache
from core.utils.logs_helpers import log_command_event
from core.utils.string import normalize

DEFAULT_TABLE_SCHEMA = "detections"
DEFAULT_TABLE_NAME = "zae_layer"

# Schema / table names can't be passed as query parameters, so they are validated
# against a strict allowlist before being interpolated into the SQL (see CLAUDE.md
# "Management Commands and SQL").
IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def log_event(info: str):
    log_command_event(command_name="import_custom_zones", info=info)


class Command(CommandRunTrackerMixin, BaseCommand):
    help = (
        "Import custom zones from the detections schema (default table: zae_layer). "
        "Each source row becomes one GeoCustomZone, attached to the department "
        "matching department_code and to the category matching layer_type. "
        "Re-running is idempotent: rows whose import_id already exists are skipped "
        "(use --override to refresh them, and the zones they conflict with, in place)."
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
            "--department-code",
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
                "and category (skips the duplicate check), creating a second zone next "
                "to it. Already-imported rows are still skipped by import_id. "
                "--override takes precedence: with both, the existing zone is replaced "
                "rather than duplicated."
            ),
        )
        parser.add_argument(
            "--override",
            action="store_true",
            default=False,
            help=(
                "Replace the conflicting custom zone instead of failing the "
                "(department, category) duplicate check. The zone imported from the "
                "same source row — or, failing that, the one already holding the pair — "
                "is updated in place (geometry, name, source ids) and keeps its uuid, "
                "user groups and detection links; those links are then refreshed exactly "
                "as update_custom_zones does. Already-imported rows are re-imported "
                "(refreshed from their source row) instead of being skipped. Caveats: a "
                "zone drawn in the app (no import_id) is never replaced, a name edited "
                "in the app is kept, sub-zone geometries are not re-clipped, and "
                "parcel-to-zone links are not recomputed."
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
        department_codes = options["department_code"]
        ids = options["ids"]
        force = options["force"]
        override = options["override"]
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

        # idempotency: never re-create a row that was already imported. --override turns
        # a re-import into a refresh of the existing zone, so the skip would defeat it.
        if override:
            already_imported = 0
            log_event(
                "--override enabled: already-imported rows are refreshed in place "
                "instead of being skipped"
            )
        else:
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
        elif override:
            # The check exists to stop a second zone appearing on a pair; overriding
            # answers it by replacing the first instead of aborting. Two rows that do
            # end up on one zone are resolved (and reported) row by row in _write_zones,
            # which is the only place that knows which zone each row actually claims.
            log_event(
                "--override enabled: existing zones are replaced instead of failing "
                "the (department, category) duplicate check"
            )
        elif force:
            log_event(
                "--force enabled: skipping the (department, category) duplicate check"
            )
        else:
            self._check_no_duplicate_pairs(resolved)

        created_zone_ids, overridden_zone_ids = self._write_zones(
            resolved, override=override
        )

        log_event(
            f"Custom zones import finished: {len(created_zone_ids)} created, "
            f"{len(overridden_zone_ids)} overridden, {skipped} skipped, "
            f"{already_imported} already imported "
            f"(elapsed: {datetime.now() - start_time})"
        )

        if created_zone_ids:
            log_event(f"Associating detections to {len(created_zone_ids)} new zone(s)")
            GeoCustomZoneService.associate_detections_to_custom_zones(
                custom_zone_ids=created_zone_ids,
                log_event=log_event,
            )

        if overridden_zone_ids:
            # An overridden zone's geometry moved, so links its OLD geometry covered can
            # now be stale — and the association pass above only ever adds. Run the exact
            # refresh update_custom_zones performs (associate + drop outdated links).
            log_event(
                f"Refreshing detections of {len(overridden_zone_ids)} overridden zone(s)"
            )
            GeoCustomZoneService.update_custom_zones_data(
                zone_ids=overridden_zone_ids,
                log_event=log_event,
            )
            # The SUPER_ADMIN "deployed data" overview counts detections per custom zone
            # off the M2M the refresh above just deleted from. It is only ever bumped
            # out of band, so without this the dashboard keeps serving the pre-override
            # (inflated) counts until its TTL expires.
            invalidate_deployed_data_cache()

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
        same import batch — for any (department, category) pair. Bypassed with --force
        (which then creates a second zone) and with --override (which replaces the
        first)."""
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

        if not conflicts:
            return

        details = ", ".join(
            f"{department_by_id[d].name} / {category_by_id[c].name}"
            for d, c in sorted(conflicts)
        )
        raise CommandError(
            "A custom zone already exists (or is duplicated within this import) for "
            f"these department/category pairs: {details}. Use --override to replace the "
            "existing zone, or --force to import anyway."
        )

    def _write_zones(
        self, resolved: List[Dict[str, Any]], override: bool = False
    ) -> Tuple[List[int], List[int]]:
        """Create one GeoCustomZone per resolved row — or, under --override, update the
        zone that row conflicts with. Returns (created ids, overridden ids): the two need
        different detection refreshes, an override having invalidated existing links."""
        created_ids: List[int] = []
        overridden_ids: List[int] = []
        written_zone_ids: Set[int] = set()
        zone_ids_by_department_id: Dict[int, List[int]] = defaultdict(list)
        with transaction.atomic():
            for item in resolved:
                department = item["department"]
                category = item["category"]
                name = item["layer_name"] or self._default_zone_name(item)

                zone = self._find_zone_to_override(item) if override else None
                if zone is not None:
                    # Update in place rather than delete + recreate: the zone's uuid is
                    # what the app, the user groups and the detection-object links all
                    # point at, and those must survive a re-import of its geometry.
                    log_event(
                        f"Overriding custom zone '{zone.name}' (uuid={zone.uuid}) "
                        f"with source row id={item['id']}"
                    )
                    if zone.id in written_zone_ids:
                        # two source rows of this run claim one zone: without --override
                        # that is the fatal duplicate-pair case, so say what was lost
                        log_event(
                            f"Source row id={item['id']} overwrites what an earlier row "
                            f"of this import just wrote to custom zone '{zone.name}' — "
                            "several source rows target the same department/category"
                        )
                    # Refresh the name only while it is still the one the import wrote —
                    # computed BEFORE the category below moves, since that is what an
                    # uncategorized-source name was built from.
                    previous_name = self._name_the_import_last_wrote(zone, department)
                    if previous_name is not None and zone.name == previous_name:
                        zone.name = name
                    else:
                        log_event(
                            f"Keeping the name of custom zone '{zone.name}': it was not "
                            "left as the import set it"
                        )
                    # The source row's layer_type can have been corrected since the first
                    # import; leaving the old category would keep the zone on the pair it
                    # no longer belongs to. None means --ignore-categories, which must
                    # not wipe the category an earlier categorized import set.
                    if category is not None:
                        zone.geo_custom_zone_category = category
                    zone.geometry = item["geometry"]
                    zone.import_id = item["id"]
                    zone.import_layer_name = item["layer_name"]
                    self._warn_on_override_side_effects(zone, department)
                else:
                    if override:
                        # "Created 1, overrode 0" on a pair the operator expected to be
                        # replaced is the confusing outcome; say what was looked for.
                        log_event(
                            f"Row id={item['id']}: nothing to override for "
                            f"{department.name} / "
                            f"{category.name if category else 'no category'} "
                            f"(no zone with import_id={item['id']}, none holding that "
                            "department/category pair) — creating a new zone"
                        )
                    zone = GeoCustomZone(
                        name=name,
                        geometry=item["geometry"],
                        geo_custom_zone_type=GeoCustomZoneType.COMMON,
                        geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE,
                        geo_custom_zone_category=category,
                        import_id=item["id"],
                        import_layer_name=item["layer_name"],
                    )

                # save() (via GeoZone.save) sets geo_zone_type=CUSTOM and name_normalized.
                # An overridden zone was fetched with `geometry` deferred, but assigning
                # it above makes it loaded again, so Django's implicit update_fields
                # (= the loaded fields) still writes the new geometry.
                is_override = zone.pk is not None
                zone.save()
                zone.geo_zones.add(department)
                written_zone_ids.add(zone.id)
                # a zone written twice in one run is reported once, on the side it
                # ended up on — the refresh only needs each id once
                target_ids = overridden_ids if is_override else created_ids
                if zone.id not in target_ids:
                    target_ids.append(zone.id)
                zone_ids_by_department_id[department.id].append(zone.id)

            # a zone created and then overridden by a later row of the same run only
            # needs the override refresh, which subsumes the plain association
            overridden_id_set = set(overridden_ids)
            created_ids = [
                zone_id for zone_id in created_ids if zone_id not in overridden_id_set
            ]

            self._associate_user_groups(zone_ids_by_department_id)

        log_event(
            f"Created {len(created_ids)} custom zone(s), "
            f"overrode {len(overridden_ids)}"
        )
        return created_ids, overridden_ids

    @staticmethod
    def _find_zone_to_override(item: Dict[str, Any]) -> Optional[GeoCustomZone]:
        """The zone an --override import replaces: the one imported from that same source
        row, else the one already holding its (department, category) pair. None when the
        row conflicts with nothing — it is then simply created.

        The pair lookup MUST match the same zones _check_no_duplicate_pairs blocks on,
        whatever created them. Zones predating this command (SQL import, insert_shp, the
        admin) carry no import_id, and they are exactly what the duplicate check reports;
        skipping them here would leave --override unable to resolve the very conflict its
        error message points at, silently adding a second zone to the pair instead.
        An import-born zone is still preferred when both exist, and a zone with no source
        row is called out when replaced. An uncategorized row (--ignore-categories) has no
        usable pair key, so it can only be matched back to its own source row.

        `--force` runs can leave several zones on one pair, so every lookup takes the
        lowest id — an arbitrary but stable pick, rather than a different one per run."""
        by_import_id = (
            GeoCustomZone.objects.filter(deleted=False, import_id=item["id"])
            .order_by("id")
            .first()
        )
        if by_import_id is not None:
            return by_import_id

        category = item["category"]
        if category is None:
            return None

        on_pair = GeoCustomZone.objects.filter(
            deleted=False,
            geo_custom_zone_category_id=category.id,
            geo_zones__id=item["department"].id,
        )
        candidates = list(on_pair.order_by("id").distinct()[:2])
        if not candidates:
            return None
        if len(candidates) > 1:
            log_event(
                f"Row id={item['id']}: several zones hold "
                f"{item['department'].name} / {category.name} — overriding the oldest "
                "one this import can claim"
            )
        # prefer a zone this command created; only fall back to one of another provenance
        zone = (
            on_pair.filter(import_id__isnull=False).order_by("id").first()
            or candidates[0]
        )
        if zone.import_id is None:
            log_event(
                f"Custom zone '{zone.name}' holds {item['department'].name} / "
                f"{category.name} but came from outside this import (no source row): "
                f"--override replaces its geometry with source row id={item['id']}"
            )
        return zone

    @staticmethod
    def _warn_on_override_side_effects(
        zone: GeoCustomZone, department: GeoDepartment
    ) -> None:
        """Report what replacing a zone's geometry leaves behind — neither case is worth
        refusing the override for, but neither should pass unnoticed either."""
        # geo_zones is only ever added to, so a source row that changed department leaves
        # the zone attached to both rather than moving it.
        previous = list(
            GeoDepartment.objects.filter(geo_custom_zones=zone)
            .exclude(id=department.id)
            .values_list("name", flat=True)
        )
        if previous:
            log_event(
                f"Custom zone '{zone.name}' stays attached to {', '.join(previous)} "
                f"on top of {department.name}: its source row changed department"
            )

        # Sub zones carry their own geometry and are not re-clipped: a shrunk parent can
        # leave a child sticking out of it, and the detection refresh won't notice
        # (it matches each sub zone against its own geometry).
        sub_zone_names = list(zone.sub_custom_zones.values_list("name", flat=True))
        if sub_zone_names:
            log_event(
                f"Custom zone '{zone.name}' has sub-zone(s) "
                f"{', '.join(sub_zone_names)}: their geometry is NOT re-clipped to the "
                "new parent geometry and may need to be reviewed"
            )

    def _associate_user_groups(
        self, zone_ids_by_department_id: Dict[int, List[int]]
    ) -> None:
        """Give every user group operating in a zone's department access to the new
        custom zones (UserGroup.geo_custom_zones M2M) — matching the groups already
        scoped, through their geo_zones M2M, to the department itself (DDTM) or to any
        of its EPCIs or communes (collectivities). Idempotent: .add() never duplicates
        a row."""
        for department_id, zone_ids in zone_ids_by_department_id.items():
            commune_ids = list(
                GeoCommune.objects.filter(department_id=department_id).values_list(
                    "id", flat=True
                )
            )
            epci_ids = list(
                GeoEpci.objects.filter(department_id=department_id).values_list(
                    "id", flat=True
                )
            )
            user_groups = list(
                UserGroup.objects.filter(
                    geo_zones__id__in=[department_id, *epci_ids, *commune_ids]
                ).distinct()
            )
            for user_group in user_groups:
                user_group.geo_custom_zones.add(*zone_ids)
            if user_groups:
                log_event(
                    f"Associated {len(zone_ids)} custom zone(s) to "
                    f"{len(user_groups)} user group(s) for department id={department_id}"
                )

    @classmethod
    def _name_the_import_last_wrote(
        cls, zone: GeoCustomZone, department: GeoDepartment
    ) -> Optional[str]:
        """The name the previous import gave `zone`, or None when it can't be known.

        `name` is admin-editable; a name still equal to this one was never touched in the
        app and can be refreshed, while a different one is somebody's rename that an
        import must not undo. `import_layer_name` records the source layer_name verbatim,
        but a row that carried none was named from its category instead — comparing
        against the NULL would wrongly read every such zone as renamed, freezing its name
        even after its category changed.

        Only the category-derived default is reconstructible: an uncategorized zone's
        default folded in the source layer_type, which is not stored, so there is nothing
        to compare against and the name is left alone.
        """
        if zone.import_layer_name:
            return zone.import_layer_name
        if zone.geo_custom_zone_category is None:
            return None
        return cls._default_zone_name(
            {"department": department, "category": zone.geo_custom_zone_category}
        )

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
