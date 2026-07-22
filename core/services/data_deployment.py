from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from django.db import IntegrityError, transaction
from django.db.models import Q

from core.models.geo_commune import GeoCommune
from core.models.geo_custom_zone import GeoCustomZone, GeoCustomZoneStatus
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
    """s3://aigle-tiles/<path> -> https://tiles.aigle.beta.gouv.fr/<path>/{z}/{x}/{y}.webp"""
    if not batch_tiles_url:
        return None
    path = batch_tiles_url.removeprefix(S3_TILES_PREFIX).strip("/")
    return f"{TILES_BASE_URL}{path}/{{z}}/{{x}}/{{y}}.webp"


def _run_command(command_name: str, parameters: Dict[str, Any]) -> Dict[str, str]:
    """Queue one command on the sequential_commands queue, return its trace record."""
    return {
        "command_name": command_name,
        "command_run_uuid": CommandAsyncService.run_command_async(
            command_name=command_name, parameters=parameters
        ),
    }


def _queue_detection_imports(
    batch_tile_sets: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    """One import_detections per batch, each scoped to its TileSet + batch id."""
    return [
        _run_command(
            "import_detections",
            {"--tile-set-id": bts["tile_set_id"], "--batch-id": str(bts["batch_id"])},
        )
        for bts in batch_tile_sets
    ]


class DataDeploymentService:
    """Deploys a geozone's detections-schema data into the app.

    Two steps run inline (TileSets + UserGroup); the heavy imports are queued on
    the `sequential_commands` Celery queue, which has concurrency 1, so they run
    strictly in enqueue order — custom zones, tiles, parcels, detections (one per
    batch), then sitadel.
    """

    @staticmethod
    def run_deployment(
        geozone_id: int,
        batch_ids: Optional[List[int]] = None,
        zae_layer_ids: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """batch_ids / zae_layer_ids restrict the deploy to the selected batches / zae
        layers (None = all of them). Both are intersected with what actually belongs to
        the geozone, so an out-of-scope id is ignored, never deployed."""
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
        if batch_ids is not None:
            wanted = set(batch_ids)
            batches = [batch for batch in batches if batch["id"] in wanted]

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
                # A DDTM (state service) oversees the whole department, so ensure a
                # DDTM-level group covers the deployed geozone's department — wiring up
                # the department's DDTM even when only a commune/epci is deployed.
                department = GeoDepartment.objects.filter(
                    insee_code=department_code
                ).first()
                if department is not None:
                    DataDeploymentService._ensure_department_ddtm_group(
                        department, department_code, cabanisation_category
                    )
        except IntegrityError as error:
            # e.g. a TileSet url already owned by another (differently-named) TileSet,
            # or a concurrent run racing the unique name — surface a clean 400, not a 500.
            raise ValueError(f"Deployment conflict: {error}")

        queued_commands = DataDeploymentService._queue_commands(
            geo_zone=geo_zone,
            department_code=department_code,
            batch_tile_sets=batch_tile_sets,
            zae_layer_ids=zae_layer_ids,
        )

        return {
            "geozone_name": geo_zone.name,
            "user_group_name": user_group.name,
            "tile_sets_created": [bts["name"] for bts in batch_tile_sets],
            "skipped_batches": skipped_batches,
            "queued_commands": queued_commands,
        }

    @staticmethod
    def run_batch_deployment(geozone_id: int, batch_id: int) -> Dict[str, Any]:
        """Deploy a single batch (a new imagery millesime) onto an already-deployed
        geozone: create the batch's TileSet, (re)create the geozone's tiles, queue its
        detections import, then refresh sitadel for the department (building permits gain
        new millesimes too). create_tile is idempotent, so re-running is safe. The other
        department-wide steps (custom zones, parcels, user group) are year-independent and
        already done by the initial geozone deploy."""
        geo_zone = GeoZone.objects.filter(id=geozone_id).first()
        if geo_zone is None:
            raise ValueError(f"Geozone {geozone_id} not found")

        department_code, geozone_code = DataDeploymentService._resolve_codes(geo_zone)

        batch = next(
            (
                b
                for b in DetectionsSchemaService.get_batches_by_geozone([geozone_id])
                if b["id"] == batch_id
            ),
            None,
        )
        if batch is None:
            raise ValueError(f"Batch {batch_id} not found for geozone {geozone_id}")

        try:
            with transaction.atomic():
                batch_tile_sets, _ = DataDeploymentService._create_batch_tile_sets(
                    geo_zone, geozone_code, [batch]
                )
        except IntegrityError as error:
            raise ValueError(f"Deployment conflict: {error}")

        if not batch_tile_sets:
            raise ValueError(
                f'Batch "{batch.get("batch_name")}" cannot be deployed '
                "(missing tiles url or imagery year)"
            )

        # create_tile first: detections import onto these tiles, so they must exist.
        # Idempotent (INSERT ... ON CONFLICT (x,y,z) DO NOTHING), so re-deploying a batch
        # never duplicates tiles.
        queued_commands = [
            _run_command("create_tile", {"--geozone-uuid": str(geo_zone.uuid)})
        ]
        queued_commands += _queue_detection_imports(batch_tile_sets)
        # --persist-data is mandatory: without it import_sitadel is a dry run.
        queued_commands.append(
            _run_command(
                "import_sitadel",
                {"--department-code": department_code, "--persist-data": True},
            )
        )

        return {
            "geozone_name": geo_zone.name,
            "tile_sets_created": [bts["name"] for bts in batch_tile_sets],
            "queued_commands": queued_commands,
        }

    @staticmethod
    def run_zae_deployment(geozone_id: int, zae_id: int) -> Dict[str, Any]:
        """Deploy a single zae layer (zone à enjeux) for an already-deployed geozone:
        import just that source row as a GeoCustomZone (import_custom_zones --ids). The
        command resolves the department itself from the row's department_code."""
        geo_zone = GeoZone.objects.filter(id=geozone_id).first()
        if geo_zone is None:
            raise ValueError(f"Geozone {geozone_id} not found")

        department_code, _ = DataDeploymentService._resolve_codes(geo_zone)

        zae = next(
            (
                z
                for z in DetectionsSchemaService.get_zae_layers([department_code])
                if z["id"] == zae_id
            ),
            None,
        )
        if zae is None:
            raise ValueError(f"Zae layer {zae_id} not found for geozone {geozone_id}")

        return {
            "geozone_name": geo_zone.name,
            "zae_layer_name": zae["layer_name"],
            "queued_commands": [_run_command("import_custom_zones", {"--ids": zae_id})],
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
        # commune / epci: parent department insee_code + the zone's own unique code
        own = {
            GeoZoneType.COMMUNE: (GeoCommune, "iso_code"),
            GeoZoneType.EPCI: (GeoEpci, "siren_code"),
        }.get(geo_zone.geo_zone_type)
        if own is None:
            raise ValueError(
                f"Geozone type {geo_zone.geo_zone_type} is not deployable "
                "(expected DEPARTMENT, COMMUNE or EPCI)"
            )
        model, own_code_field = own
        row = model.objects.values("department__insee_code", own_code_field).get(
            id=geo_zone.id
        )
        return row["department__insee_code"], row[own_code_field]

    @staticmethod
    def _effective_geo_zones(geo_zone: GeoZone) -> List[GeoZone]:
        """Geo zones to actually scope TileSets / UserGroups to. EPCI isn't a concept in
        the app, so an EPCI expands to its communes; a department / commune maps to itself.
        Assumes the EPCI's communes are already imported (import_geocommune)."""
        if geo_zone.geo_zone_type == GeoZoneType.EPCI:
            return list(GeoCommune.objects.filter(epci_id=geo_zone.id))
        return [geo_zone]

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
        effective_geo_zones = DataDeploymentService._effective_geo_zones(geo_zone)

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
            tile_set.geo_zones.add(*effective_geo_zones)
            batch_tile_sets.append(
                {"batch_id": batch["id"], "tile_set_id": tile_set.id, "name": name}
            )

        return batch_tile_sets, skipped_batches

    @staticmethod
    def _upsert_cabanisation_group(
        name: str,
        user_group_type: str,
        geo_zones: List[GeoZone],
        cabanisation_category: ObjectTypeCategory,
    ) -> UserGroup:
        """get_or_create a group by its (unique) name, linked to the geozones and the
        Cabanisation category. Idempotent."""
        user_group, _ = UserGroup.objects.get_or_create(
            name=name, defaults={"user_group_type": user_group_type}
        )
        user_group.geo_zones.add(*geo_zones)
        user_group.object_type_categories.add(cabanisation_category)
        DataDeploymentService._link_custom_zones(user_group, geo_zones)
        return user_group

    @staticmethod
    def _link_custom_zones(user_group: UserGroup, geo_zones: List[GeoZone]) -> None:
        """Give the group every ACTIVE zone à enjeux attached to its collectivities.
        The whole app is gated on this M2M (GeoCustomZonePermission), so a group without
        it sees an empty map. import_custom_zones does the mirror pass (zone -> existing
        groups) for zones created after the group.

        Both sides label their collectivities at any level of the hierarchy — a group is
        scoped to communes (an EPCI expands to them) while an imported zone lists only
        its department — so the group's zones are widened to the whole
        commune/epci/department/region chain before intersecting the two M2Ms."""
        zone_ids = {geo_zone.id for geo_zone in geo_zones}
        related_ids = GeoCommune.objects.filter(
            Q(id__in=zone_ids) | Q(department_id__in=zone_ids)
        ).values_list("id", "epci_id", "department_id", "department__region_id")
        scope_ids = zone_ids.union(*map(set, related_ids))
        scope_ids.discard(None)  # communes without an epci

        user_group.geo_custom_zones.add(
            *GeoCustomZone.objects.filter(
                geo_zones__id__in=scope_ids,
                geo_custom_zone_status=GeoCustomZoneStatus.ACTIVE,
            )
            .distinct()
            .values_list("id", flat=True)
        )

    @staticmethod
    def _create_user_group(
        geo_zone: GeoZone,
        geozone_code: str,
        user_group_type: str,
        cabanisation_category: ObjectTypeCategory,
    ) -> UserGroup:
        """Idempotent "Cabanisation {geozone} ({code})" group, scoped to the geozone. The
        code disambiguates same-named geozones so a second one never reuses (and widens
        the access of) another's group."""
        name = f"Cabanisation {geo_zone.name} ({geozone_code})"
        return DataDeploymentService._upsert_cabanisation_group(
            name,
            user_group_type,
            DataDeploymentService._effective_geo_zones(geo_zone),
            cabanisation_category,
        )

    @staticmethod
    def _ensure_department_ddtm_group(
        department: GeoDepartment,
        department_code: str,
        cabanisation_category: ObjectTypeCategory,
    ) -> Optional[UserGroup]:
        """Ensure a DDTM-level group is linked to the department. Skipped if one already
        is — so deploying several communes of one department wires up a single shared DDTM
        group, and a department deploy reuses the DDTM group it just created."""
        if UserGroup.objects.filter(
            user_group_type=UserGroupType.DDTM, geo_zones=department
        ).exists():
            return None
        name = f"Cabanisation {department.name} ({department_code})"
        return DataDeploymentService._upsert_cabanisation_group(
            name, UserGroupType.DDTM, [department], cabanisation_category
        )

    @staticmethod
    def _queue_commands(
        geo_zone: GeoZone,
        department_code: str,
        batch_tile_sets: List[Dict[str, Any]],
        zae_layer_ids: Optional[List[int]] = None,
    ) -> List[Dict[str, str]]:
        """Enqueue the import commands in dependency order. The sequential_commands
        queue (concurrency 1) runs them one at a time in this exact order."""
        # Resolve the custom-zones args first (pure reads); _run_command dispatches
        # eagerly, so the enqueue order below must stay the dependency order.
        custom_zones_params = DataDeploymentService._resolve_custom_zones_params(
            department_code, zae_layer_ids
        )
        queued: List[Dict[str, str]] = []
        if custom_zones_params is not None:
            queued.append(_run_command("import_custom_zones", custom_zones_params))
        queued.append(
            _run_command("create_tile", {"--geozone-uuid": str(geo_zone.uuid)})
        )
        queued.append(
            _run_command("import_parcels", {"--department-code": department_code})
        )
        queued += _queue_detection_imports(batch_tile_sets)
        # --persist-data is mandatory: without it import_sitadel is a dry run.
        queued.append(
            _run_command(
                "import_sitadel",
                {"--department-code": department_code, "--persist-data": True},
            )
        )
        return queued

    @staticmethod
    def _resolve_custom_zones_params(
        department_code: str, zae_layer_ids: Optional[List[int]]
    ) -> Optional[Dict[str, Any]]:
        """Args for import_custom_zones, or None to skip it entirely.
        zae_layer_ids None -> every zae layer of the department (--department-code).
        zae_layer_ids list -> only the ids that actually belong to the department
        (--ids), so an out-of-scope id is never imported; an empty selection skips it."""
        if zae_layer_ids is None:
            return {"--department-code": department_code}
        dept_zae_ids = {
            zae["id"]
            for zae in DetectionsSchemaService.get_zae_layers([department_code])
        }
        selected = [zae_id for zae_id in zae_layer_ids if zae_id in dept_zae_ids]
        if not selected:
            return None
        return {"--ids": selected}
