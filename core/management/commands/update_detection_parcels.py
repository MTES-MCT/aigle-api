from django.core.management.base import BaseCommand
from core.models.detection_object import DetectionObject
from core.models.parcel import Parcel
from django.contrib.gis.geos import GEOSGeometry
from django.db import transaction

from core.utils.cache import invalidate_count_caches
from core.utils.logs_helpers import log_command_event

BATCH_SIZE_DEFAULT = 1000


def log_event(info: str):
    log_command_event(command_name="update_detection_parcels", info=info)


class Command(BaseCommand):
    help = "Update parcel_id in DetectionObject model with pagination"

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=BATCH_SIZE_DEFAULT,
            help="Number of records to process per batch.",
        )
        parser.add_argument(
            "--department-code",
            type=str,
            default=None,
            help=(
                "Only update detection objects whose commune belongs to the "
                "department with this insee_code (GeoDepartment.insee_code)."
            ),
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        department_code = options["department_code"]
        log_event("Starting updating parcel_id...")

        detection_objects_queryset = (
            DetectionObject.objects.prefetch_related("detections")
            .filter(parcel=None)
            .order_by("id")
        )

        if department_code:
            detection_objects_queryset = detection_objects_queryset.filter(
                commune__department__insee_code=department_code
            )
            log_event(f"Filtering on department with insee_code={department_code}")

        total = detection_objects_queryset.count()
        log_event(f"Detection objects without parcel associated: {total}")

        all_ids = list(detection_objects_queryset.values_list("id", flat=True))

        processed_count = 0
        updated_count = 0

        for i in range(0, len(all_ids), batch_size):
            batch_ids = all_ids[i : i + batch_size]
            detection_objects = DetectionObject.objects.prefetch_related(
                "detections"
            ).filter(id__in=batch_ids)

            updated_detection_objects = []

            for detection_object in detection_objects:
                if not detection_object.detections.exists():
                    continue

                detection = detection_object.detections.first()
                if not detection or not detection.geometry:
                    continue

                try:
                    geom = detection.geometry
                    if not isinstance(geom, GEOSGeometry):
                        geom = GEOSGeometry(geom)

                    centroid = geom.centroid

                    parcel = Parcel.objects.filter(geometry__contains=centroid).first()

                    if not parcel:
                        continue

                    detection_object.parcel_id = parcel.id
                    updated_detection_objects.append(detection_object)

                except Exception as e:
                    log_event(
                        f"Error processing detection object {detection_object.id}: {e}"
                    )
                    continue

            if updated_detection_objects:
                with transaction.atomic():
                    DetectionObject.objects.bulk_update(
                        updated_detection_objects, ["parcel_id"]
                    )
                    # bulk_update bypasses post_save; invalidate counts explicitly.
                    transaction.on_commit(invalidate_count_caches)
                updated_count += len(updated_detection_objects)

            processed_count += len(batch_ids)
            log_event(
                f"Progress: {processed_count}/{total} processed, {updated_count} updated"
            )

            if processed_count >= total:
                break

        log_event(
            f"Finished updating parcel_id. Total updated: {updated_count}/{total}"
        )
