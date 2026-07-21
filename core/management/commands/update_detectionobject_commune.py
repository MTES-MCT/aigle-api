import time

from django.core.management.base import BaseCommand
from core.management.base import CommandRunTrackerMixin
from core.models.detection_object import DetectionObject
from django.db import connection

from core.services.deployed_data import DeployedDataService
from core.utils.cache import invalidate_count_caches

from core.utils.logs_helpers import log_command_event, log_command_progress

BATCH_SIZE_DEFAULT = 1000

# Set-based form of "take each object's first detection, find the commune containing
# its centroid". The spatial join stays in PostGIS on purpose: resolving it in Python
# cost one query per object to load the detection and one more to match the commune.
UPDATE_SQL = """
WITH first_detection AS (
    SELECT DISTINCT ON (d.detection_object_id)
        d.detection_object_id AS object_id,
        ST_Centroid(d.geometry) AS centroid
    FROM core_detection d
    WHERE d.detection_object_id = ANY(%s)
    ORDER BY d.detection_object_id, d.id
)
UPDATE core_detectionobject o
SET commune_id = z.id
FROM first_detection fd
JOIN core_geozone z
    ON z.geo_zone_type = 'COMMUNE'
    AND ST_Contains(z.geometry, fd.centroid)
WHERE o.id = fd.object_id
    AND o.commune_id IS DISTINCT FROM z.id
"""


def log_event(info: str):
    log_command_event(command_name="update_detectionobject_commune", info=info)


class Command(CommandRunTrackerMixin, BaseCommand):
    help = "Update commune_id in DetectionObject model with pagination"

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=BATCH_SIZE_DEFAULT,
            help="Number of records to process per batch.",
        )
        parser.add_argument("--tile-set-uuids", action="append", required=False)
        parser.add_argument(
            "--force",
            action="store_true",
            help="Update all detection objects, not only those without a commune.",
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        tile_set_uuids = options["tile_set_uuids"]
        force = options["force"]
        log_event("Starting updating commune_id...")

        detection_objects_queryset = DetectionObject.objects.order_by("id")

        if not force:
            detection_objects_queryset = detection_objects_queryset.filter(commune=None)

        if tile_set_uuids:
            detection_objects_queryset = detection_objects_queryset.filter(
                tile_sets__uuid__in=tile_set_uuids
            ).distinct()

        total = detection_objects_queryset.count()
        log_event(f"Detection objects to update: {total}")

        start_time = time.monotonic()
        processed_count = 0
        updated_count = 0
        last_id = 0

        # Keyset pagination: batches stay stable as rows drop out of the commune=None
        # filter, and no full id list is held in memory.
        while True:
            batch_ids = list(
                detection_objects_queryset.filter(id__gt=last_id).values_list(
                    "id", flat=True
                )[:batch_size]
            )

            if not batch_ids:
                break

            last_id = batch_ids[-1]

            with connection.cursor() as cursor:
                cursor.execute(UPDATE_SQL, [batch_ids])
                updated_count += cursor.rowcount

            processed_count += len(batch_ids)
            log_command_progress(
                "update_detectionobject_commune", processed_count, total, start_time
            )

        if updated_count:
            # Raw SQL bypasses post_save; invalidate counts explicitly, once.
            invalidate_count_caches()

            # The SUPER_ADMIN deployed-data dashboard aggregates detections per commune,
            # which is exactly what this command rewrites. Its cache is version-gated and
            # otherwise only refreshed by warm_deployed_data_cache, so without this the
            # dashboard serves pre-run figures until the TTL. refresh_cache invalidates
            # AND recomputes — never leaving it cold. Once at the end: it's a
            # full-dataset recompute.
            log_event("Refreshing deployed-data cache after commune update")
            DeployedDataService.refresh_cache()

        log_event(
            f"Finished updating commune_id. Total updated: {updated_count}/{total}"
        )
