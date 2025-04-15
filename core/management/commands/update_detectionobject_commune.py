from django.core.management.base import BaseCommand
from core.models.detection_object import DetectionObject
from core.models.geo_zone import GeoZone, GeoZoneType
from django.contrib.gis.geos import GEOSGeometry
from django.db import transaction

BATCH_SIZE_DEFAULT = 1000


class Command(BaseCommand):
    help = "Update commune_id in DetectionObject model with pagination"

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=BATCH_SIZE_DEFAULT,
            help="Number of records to process per batch.",
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        self.stdout.write("Starting updating commune_id...")

        detection_objects_queryset = (
            DetectionObject.objects.prefetch_related("detections")
            .filter(commune=None)
            .order_by("id")
        )

        total = detection_objects_queryset.count()
        self.stdout.write(f"Detection objects without commune associated: {total}")

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

                    commune = GeoZone.objects.filter(
                        geo_zone_type=GeoZoneType.COMMUNE, geometry__contains=centroid
                    ).first()

                    if not commune:
                        continue

                    detection_object.commune_id = commune.id
                    updated_detection_objects.append(detection_object)

                except Exception as e:
                    self.stdout.write(
                        f"Error processing detection object {detection_object.id}: {e}"
                    )
                    continue

            if updated_detection_objects:
                with transaction.atomic():
                    DetectionObject.objects.bulk_update(
                        updated_detection_objects, ["commune_id"]
                    )
                updated_count += len(updated_detection_objects)

            processed_count += len(batch_ids)
            self.stdout.write(
                f"Progress: {processed_count}/{total} processed, {updated_count} updated"
            )

            if processed_count >= total:
                break

        self.stdout.write(
            f"Finished updating commune_id. Total updated: {updated_count}/{total}"
        )
