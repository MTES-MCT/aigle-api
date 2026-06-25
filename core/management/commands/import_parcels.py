import json
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple, TypedDict
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from core.management.base import CommandRunTrackerMixin
from datetime import datetime
import gzip

from core.management.commands._common.file import (
    download_file,
)
from core.models.geo_commune import GeoCommune
from core.models.geo_department import GeoDepartment
from django.contrib.gis.geos import GEOSGeometry

from core.constants.geo import SRID
from core.models.parcel import Parcel
from core.utils.cache import (
    invalidate_count_caches,
    suppress_count_cache_invalidation,
)
from core.services.deployed_data import DeployedDataService
from core.utils.logs_helpers import log_command_event, log_command_progress


# Etalab cadastre = same DGFiP data as IGN PARCELLAIRE-EXPRESS, already in WGS84
# (SRID 4326), refreshed ~quarterly. "latest" is a server symlink to the newest
# millésime, so we never hardcode a vintage.
BASE_URL = (
    "https://cadastre.data.gouv.fr/data/etalab-cadastre/latest/geojson/departements"
)
BATCH_SIZE = 5000

# Refreshed on upsert; id_parcellaire (conflict target) and created_at stay put.
# updated_at MUST stay here: the stale-prune keys off it (see import_department_parcels).
UPSERT_UPDATE_FIELDS = [
    "prefix",
    "section",
    "num_parcel",
    "contenance",
    "arpente",
    "geometry",
    "commune",
    "refreshed_at",
    "updated_at",
]


class ParcelProperties(TypedDict):
    id: str
    commune: str
    prefixe: str
    section: str
    numero: str
    contenance: int
    arpente: bool
    created: str
    updated: str


class Feature(TypedDict):
    type: "Feature"
    id: str
    geometry: Dict[str, Any]
    properties: ParcelProperties


def get_data_parcels(
    department: str,
) -> Tuple[tempfile.TemporaryDirectory[str], List[Feature]]:
    url = f"{BASE_URL}/{department}/cadastre-{department}-parcelles.json.gz"
    file_name = f"cadastre-{department}-parcelles.json.gz"

    temp_dir, file_path = download_file(url=url, file_name=file_name)

    # ponytail: whole-file load (~2GB peak for the biggest departments, one at a
    # time). Switch to ijson streaming if a department OOMs the worker.
    with gzip.open(file_path, "rb") as file:
        file_content = file.read()

    return temp_dir, json.loads(file_content)["features"]


def log_event(info: str):
    log_command_event(command_name="import_parcels", info=info)


def _build_parcel(
    feature: Feature, commune_by_code: Dict[str, GeoCommune]
) -> Optional[Parcel]:
    properties = feature["properties"]
    commune = commune_by_code.get(properties["commune"])
    if not commune:
        return None

    geometry = GEOSGeometry(json.dumps(feature["geometry"]), srid=SRID)
    refreshed_at = datetime.strptime(properties["updated"], "%Y-%m-%d").date()

    return Parcel(
        id_parcellaire=properties["id"],
        prefix=properties["prefixe"],
        section=properties["section"],
        num_parcel=int(properties["numero"]),
        contenance=properties.get("contenance") or 0,
        arpente=properties.get("arpente", False),
        geometry=geometry,
        commune=commune,
        refreshed_at=refreshed_at,
    )


def import_department_parcels(
    department: str, features: List[Feature], dry_run: bool = False
) -> Tuple[int, int, int]:
    """Upsert the department's parcels by id_parcellaire, then delete the
    department's parcels this run did not refresh (stale: merged/split away).
    Returns (upserted, deleted, skipped). Caller suppresses + then invalidates
    count caches (bulk paths bypass the post_save/post_delete signal). With
    dry_run the work runs inside a rolled-back transaction (nothing persists)."""
    communes = GeoCommune.objects.filter(
        iso_code__in={feature["properties"]["commune"] for feature in features}
    )
    commune_by_code = {commune.iso_code: commune for commune in communes}

    total = len(features)
    start_time = time.monotonic()
    # Marker for the stale-prune: every upsert bumps updated_at (auto_now) to a
    # time strictly after this, so rows left with updated_at < marker are stale.
    run_started_at = timezone.now()

    missing_commune_codes = set()
    batch: List[Parcel] = []
    counters = {"upserted": 0, "parsed": 0}

    def flush(done: int):
        if not batch:
            return
        Parcel.objects.bulk_create(
            batch,
            update_conflicts=True,
            unique_fields=["id_parcellaire"],
            update_fields=UPSERT_UPDATE_FIELDS,
            batch_size=BATCH_SIZE,
        )
        counters["upserted"] += len(batch)
        batch.clear()
        log_command_progress("import_parcels", done, total, start_time)

    def run() -> int:
        for index, feature in enumerate(features, start=1):
            parcel = _build_parcel(feature, commune_by_code)
            if parcel is None:
                missing_commune_codes.add(feature["properties"]["commune"])
                continue
            counters["parsed"] += 1
            batch.append(parcel)
            if len(batch) >= BATCH_SIZE:
                flush(index)
        flush(total)

        # Prune by updated_at, NOT by id_parcellaire__in=fresh_ids: a real
        # department has >65535 parcels, which would blow past Postgres's
        # per-statement parameter limit. Guarded so an empty/corrupt download
        # (parsed == 0) can't wipe the whole department.
        if not counters["parsed"]:
            return 0
        deleted, _ = Parcel.objects.filter(
            commune__department__insee_code=department,
            updated_at__lt=run_started_at,
        ).delete()
        return deleted

    with transaction.atomic():
        deleted = run()
        if dry_run:
            transaction.set_rollback(True)

    upserted = counters["upserted"]
    skipped = total - counters["parsed"]
    prefix = "DRY-RUN " if dry_run else ""
    log_event(
        f"{prefix}Department {department}: upserted {upserted}, "
        f"deleted {deleted} stale, skipped {skipped} (commune not in DB), "
        f"total features {total}"
    )
    if missing_commune_codes:
        log_event(
            f"{prefix}Department {department}: communes not in DB (parcels skipped): "
            f"{', '.join(sorted(missing_commune_codes))}"
        )
    return upserted, deleted, skipped


class Command(CommandRunTrackerMixin, BaseCommand):
    help = "Import parcels to database from the Etalab cadastre (latest millésime)"

    def add_arguments(self, parser):
        parser.add_argument("--departments", action="append", required=False)
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Download and analyse but roll back all writes (nothing persists)",
        )

    def handle(self, *args, **options):
        departments = options["departments"]
        dry_run = options["dry_run"]

        log_event(f"Starting importing parcels... (dry_run={dry_run})")

        if not departments:
            log_event(
                "No departments provided, importing parcels for all departments in database"
            )
            departments = [
                department.insee_code for department in GeoDepartment.objects.all()
            ]

        log_event(f"Departments: {', '.join(departments)}")

        deployed_data_dirty = False
        for department in departments:
            if not GeoDepartment.objects.filter(insee_code=department).exists():
                log_event(f"Department not found for code: {department}")
                continue

            temp_dir, features = get_data_parcels(department=department)
            try:
                with suppress_count_cache_invalidation():
                    upserted, deleted, _ = import_department_parcels(
                        department, features, dry_run=dry_run
                    )
            finally:
                temp_dir.cleanup()

            if dry_run:
                continue

            if upserted or deleted:
                deployed_data_dirty = True

            invalidate_count_caches()
            if deleted:
                # Pruned parcels SET_NULL their detection links; re-link the
                # affected detections to the surviving (e.g. merged) parcels.
                log_event(
                    f"Department {department}: re-linking detections after pruning "
                    f"{deleted} stale parcels"
                )
                call_command("update_detection_parcels", department_code=department)

        # Parcel counts feed the SUPER_ADMIN deployed-data dashboard, whose cache is
        # version-gated and otherwise only refreshed by warm_deployed_data_cache. Refresh
        # once after all departments (invalidate + recompute, never left cold).
        if deployed_data_dirty:
            log_event("Refreshing deployed-data cache after parcels import")
            DeployedDataService.refresh_cache()

        log_event("Finished importing parcels")
