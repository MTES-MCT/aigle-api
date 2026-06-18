from django.core.management.base import BaseCommand
from django.db import connection, transaction

from core.utils.cache import invalidate_count_caches
from core.utils.logs_helpers import log_command_event


def log_event(info: str):
    log_command_event(command_name="clean_detections", info=info)


# Rows orphaned once their detections are gone (no detection points at them).
ORPHAN_DETECTION_DATA = """
    SELECT dd.id FROM core_detectiondata dd
    LEFT JOIN core_detection d ON dd.id = d.detection_data_id
    WHERE d.detection_data_id IS NULL
"""
ORPHAN_DETECTION_OBJECTS = """
    SELECT obj.id FROM core_detectionobject obj
    LEFT JOIN core_detection d ON obj.id = d.detection_object_id
    WHERE d.detection_object_id IS NULL
"""


class Command(BaseCommand):
    help = "Completely remove detections (and their orphaned data/objects) for a batch id or a tile set id."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--batch-id", type=str, help="Delete every detection with this batch_id"
        )
        group.add_argument(
            "--tile-set-id", type=int, help="Delete every detection in this tile set"
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options.get("batch_id") is not None:
            where, param = "batch_id = %s", options["batch_id"]
            log_event(f"Deleting detections for batch_id: {options['batch_id']}")
        else:
            where, param = "tile_set_id = %s", options["tile_set_id"]
            log_event(f"Deleting detections for tile_set_id: {options['tile_set_id']}")

        with connection.cursor() as cursor:
            # where only ever holds a hardcoded column literal; the value is bound via %s.
            cursor.execute(f"DELETE FROM core_detection WHERE {where}", [param])
            deleted_detections = cursor.rowcount

            # Authorizations FK detection_data (NOT NULL), so they must go before it.
            cursor.execute(
                f"DELETE FROM core_detectionauthorization "
                f"WHERE detection_data_id IN ({ORPHAN_DETECTION_DATA})"
            )
            cursor.execute(
                f"DELETE FROM core_detectiondata WHERE id IN ({ORPHAN_DETECTION_DATA})"
            )
            deleted_data = cursor.rowcount

            # Both M2M junctions FK detection_object, so clear them before the objects.
            cursor.execute(
                f"DELETE FROM core_detectionobject_geo_custom_zones "
                f"WHERE detectionobject_id IN ({ORPHAN_DETECTION_OBJECTS})"
            )
            cursor.execute(
                f"DELETE FROM core_detectionobject_geo_sub_custom_zones "
                f"WHERE detectionobject_id IN ({ORPHAN_DETECTION_OBJECTS})"
            )
            cursor.execute(
                f"DELETE FROM core_detectionobject WHERE id IN ({ORPHAN_DETECTION_OBJECTS})"
            )
            deleted_objects = cursor.rowcount

        invalidate_count_caches()

        log_event(
            f"Deleted {deleted_detections} detections, {deleted_data} orphaned detection data, "
            f"{deleted_objects} orphaned detection objects"
        )
