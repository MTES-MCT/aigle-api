from django.core.management.base import BaseCommand

from core.models.detection_object import DetectionObject

from core.models.parcel import Parcel
from django.contrib.gis.db.models.functions import Centroid


from django.core.paginator import Paginator
from django.db import transaction

BATCH_SIZE_DEFAULT = 1000


class Command(BaseCommand):
    help = "Update parcel_id in DetectionObject model with pagination"

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=BATCH_SIZE_DEFAULT,
            help="Number of records to process per batch.",
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        print("Starting updating parcel_id...")

        detection_objects_queryset = (
            DetectionObject.objects.prefetch_related("detections")
            .order_by("id")
            .filter(parcel=None)
        )
        total = detection_objects_queryset.count()
        print(f"Detection objects without parcel associated: {total}")

        paginator = Paginator(detection_objects_queryset, batch_size)

        for page_number in paginator.page_range:
            detection_objects = paginator.page(page_number).object_list

            updated_detection_objects = []

            for detection_object in detection_objects:
                if not detection_object.detections.exists():
                    continue

                centroid = Centroid(detection_object.detections.first().geometry)
                parcel = Parcel.objects.filter(geometry__contains=centroid).first()

                if not parcel:
                    continue

                detection_object.parcel = parcel
                updated_detection_objects.append(detection_object)

            if updated_detection_objects:
                with transaction.atomic():
                    DetectionObject.objects.bulk_update(
                        updated_detection_objects, ["parcel"]
                    )
                print(f"Updated batch for page: {page_number}/{paginator.num_pages}")

        print("Finished updating parcel_id")
