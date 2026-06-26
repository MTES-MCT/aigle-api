from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from django.db import IntegrityError, transaction

from core.models.geo_commune import GeoCommune
from core.models.geo_department import GeoDepartment
from core.models.geo_epci import GeoEpci
from core.models.geo_zone import GeoZone, GeoZoneType
from core.models.object_type_category import ObjectTypeCategory
from core.models.tile_set import TileSet, TileSetScheme, TileSetStatus, TileSetType
from core.models.user_group import UserGroup, UserGroupType
from core.services.command_async import CommandAsyncService
from core.services.detections_schema import DetectionsSchemaService

S3_TILES_PREFIX = "s3://aigle-tiles/"
TILES_BASE_URL = "https://tiles.aigle.beta.gouv.fr/"

# Per-batch TileSets are the per-year aerial imagery detections are imported onto.
DEPLOYMENT_TILE_SET_TYPE = TileSetType.BACKGROUND
DEPLOYMENT_TILE_SET_MIN_ZOOM = 15
DEPLOYMENT_TILE_SET_MAX_ZOOM = 19
CABANISATION_CATEGORY_NAME = "Cabanisation"
# A batch's src_image_year must be a plausible imagery year to date the TileSet.
MIN_IMAGERY_YEAR = 1900
MAX_IMAGERY_YEAR = 2100


def batch_tiles_url_to_xyz(batch_tiles_url: Optional[str]) -> Optional[str]:
    """s3://aigle-tiles/<path> -> https://tiles.aigle.beta.gouv.fr/<path>/{z}/{x}/{y}.png"""
    if not batch_tiles_url:
        return None
    path = batch_tiles_url.removeprefix(S3_TILES_PREFIX).strip("/")
    return f"{TILES_BASE_URL}{path}/{{z}}/{{x}}/{{y}}.png"


class DataDeploymentService:
    """Deploys a geozone's detections-schema data into the app.

    Two steps run inline (TileSets + UserGroup); the heavy imports are queued on
    the `sequential_commands` Celery queue, which has concurrency 1, so they run
    strictly in enqueue order — custom zones, tiles, parcels, detections (one per
    batch), then sitadel.
    """

    @staticmethod
    def run_deployment(geozone_id: int) -> Dict[str, Any]:
        geo_zone = GeoZone.objects.filter(id=geozone_id).first()
        if geo_zone is None:
            raise ValueError(f"Geozone {geozone_id} not found")

        # department_code scopes the dept-wide import commands; geozone_code (the zone's
        # own unique insee/iso/siren code) disambiguates the globally-unique TileSet /
        # UserGroup names — commune names repeat across departments in France.
        department_code, geozone_code = DataDeploymentService._resolve_codes(geo_zone)
        # DDTM = state service (department-wide); a single commune/epci is a local collectivity.
        user_group_type = (
            UserGroupType.DDTM
            if geo_zone.geo_zone_type == GeoZoneType.DEPARTMENT
            else UserGroupType.COLLECTIVITY
        )

        cabanisation_category = ObjectTypeCategory.objects.filter(
            name=CABANISATION_CATEGORY_NAME
        ).first()
        if cabanisation_category is None:
            raise ValueError(
                f'ObjectTypeCategory "{CABANISATION_CATEGORY_NAME}" not found'
            )

        batches = DetectionsSchemaService.get_batches_by_geozone([geozone_id])

        # Inline writes are atomic; commands are queued only after they commit, so a
        # rollback can't leave detached Celery tasks pointing at missing TileSets.
        try:
            with transaction.atomic():
                batch_tile_sets, skipped_batches = (
                    DataDeploymentService._create_batch_tile_sets(
                        geo_zone, geozone_code, batches
                    )
                )
                user_group = DataDeploymentService._create_user_group(
                    geo_zone, geozone_code, user_group_type, cabanisation_category
                )
        except IntegrityError as error:
            # e.g. a TileSet url already owned by another (differently-named) TileSet,
            # or a concurrent run racing the unique name — surface a clean 400, not a 500.
            raise ValueError(f"Deployment conflict: {error}")

        queued_commands = DataDeploymentService._queue_commands(
            geo_zone=geo_zone,
            department_code=department_code,
            batch_tile_sets=batch_tile_sets,
        )

        return {
            "geozone_name": geo_zone.name,
            "user_group_name": user_group.name,
            "tile_sets_created": [bts["name"] for bts in batch_tile_sets],
            "skipped_batches": skipped_batches,
            "queued_commands": queued_commands,
        }

    @staticmethod
    def _resolve_codes(geo_zone: GeoZone) -> Tuple[str, str]:
        """(department insee_code the dept-scoped commands import from, the geozone's
        OWN unique code for name disambiguation). DEPARTMENT → its insee_code for both;
        COMMUNE → (parent dept insee_code, own iso_code); EPCI → (parent dept insee_code,
        own siren_code)."""
        if geo_zone.geo_zone_type == GeoZoneType.DEPARTMENT:
            insee_code = GeoDepartment.objects.values_list("insee_code", flat=True).get(
                id=geo_zone.id
            )
            return insee_code, insee_code
        if geo_zone.geo_zone_type == GeoZoneType.COMMUNE:
            commune = GeoCommune.objects.values(
                "department__insee_code", "iso_code"
            ).get(id=geo_zone.id)
            return commune["department__insee_code"], commune["iso_code"]
        if geo_zone.geo_zone_type == GeoZoneType.EPCI:
            epci = GeoEpci.objects.values("department__insee_code", "siren_code").get(
                id=geo_zone.id
            )
            return epci["department__insee_code"], epci["siren_code"]
        raise ValueError(
            f"Geozone type {geo_zone.geo_zone_type} is not deployable "
            "(expected DEPARTMENT, COMMUNE or EPCI)"
        )

    @staticmethod
    def _create_batch_tile_sets(
        geo_zone: GeoZone, geozone_code: str, batches: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """One TileSet per batch, named "{geozone} ({code}) {year}" — the code keeps the
        globally-unique name distinct between same-named geozones. Idempotent by name, so
        a re-run (or two same-year batches) reuses the existing TileSet. Batches without a
        tiles url or source year can't be deployed and are reported back as skipped.
        Returns records of {batch_id, tile_set_id, name} for the detections import."""
        batch_tile_sets: List[Dict[str, Any]] = []
        skipped_batches: List[Dict[str, Any]] = []

        for batch in batches:
            year = batch["src_image_year"]
            url = batch_tiles_url_to_xyz(batch["batch_tiles_url"])
            # A bad batch is skipped, not fatal — one of them must not roll back the rest.
            if (
                not url
                or year is None
                or not MIN_IMAGERY_YEAR <= year <= MAX_IMAGERY_YEAR
            ):
                skipped_batches.append({"id": batch["id"], "name": batch["batch_name"]})
                continue

            name = f"{geo_zone.name} ({geozone_code}) {year}"
            # get_or_create (by unique name) makes re-runs idempotent and narrows the
            # concurrent same-name race; a url collision still raises IntegrityError,
            # caught in run_deployment.
            tile_set, _ = TileSet.objects.get_or_create(
                name=name,
                defaults={
                    "url": url,
                    "tile_set_status": TileSetStatus.VISIBLE,
                    "date": date(int(year), 1, 1),
                    "tile_set_scheme": TileSetScheme.xyz,
                    "tile_set_type": DEPLOYMENT_TILE_SET_TYPE,
                    "min_zoom": DEPLOYMENT_TILE_SET_MIN_ZOOM,
                    "max_zoom": DEPLOYMENT_TILE_SET_MAX_ZOOM,
                },
            )
            tile_set.geo_zones.add(geo_zone)
            batch_tile_sets.append(
                {"batch_id": batch["id"], "tile_set_id": tile_set.id, "name": name}
            )

        return batch_tile_sets, skipped_batches

    @staticmethod
    def _create_user_group(
        geo_zone: GeoZone,
        geozone_code: str,
        user_group_type: str,
        cabanisation_category: ObjectTypeCategory,
    ) -> UserGroup:
        """Idempotent "Cabanisation {geozone} ({code})" group, scoped to the geozone and
        the Cabanisation object-type category. The code disambiguates same-named geozones
        so a second one never reuses (and widens the access of) another's group."""
        name = f"Cabanisation {geo_zone.name} ({geozone_code})"
        user_group, _ = UserGroup.objects.get_or_create(
            name=name, defaults={"user_group_type": user_group_type}
        )
        user_group.geo_zones.add(geo_zone)
        user_group.object_type_categories.add(cabanisation_category)
        return user_group

    @staticmethod
    def _queue_commands(
        geo_zone: GeoZone,
        department_code: str,
        batch_tile_sets: List[Dict[str, Any]],
    ) -> List[Dict[str, str]]:
        """Enqueue the import commands in dependency order. The sequential_commands
        queue (concurrency 1) runs them one at a time in this exact order."""
        queued: List[Dict[str, str]] = []

        def enqueue(command_name: str, parameters: Dict[str, Any]) -> None:
            queued.append(
                {
                    "command_name": command_name,
                    "command_run_uuid": CommandAsyncService.run_command_async(
                        command_name=command_name, parameters=parameters
                    ),
                }
            )

        enqueue("import_custom_zones", {"--department-code": department_code})
        enqueue("create_tile", {"--geozone-uuid": str(geo_zone.uuid)})
        enqueue("import_parcels", {"--department-code": department_code})
        for bts in batch_tile_sets:
            enqueue(
                "import_detections",
                {
                    "--tile-set-id": bts["tile_set_id"],
                    "--batch-id": str(bts["batch_id"]),
                },
            )
        # --persist-data is mandatory: without it import_sitadel is a dry run.
        enqueue(
            "import_sitadel",
            {"--department-code": department_code, "--persist-data": True},
        )
        return queued
