from django.core.management.base import BaseCommand, CommandError

from core.models.detection_object import DetectionObject
from core.models.object_type import ObjectType
from core.utils.prescription import compute_prescription

BATCH_SIZE = 10000


class Command(BaseCommand):
    help = "Compute prescription statuses for specified object types"

    def add_arguments(self, parser):
        parser.add_argument("--object-type-uuids", action="append", required=True)

    def handle(self, *args, **options):
        object_type_uuids = list(set(options["object_type_uuids"]))
        object_types = ObjectType.objects.filter(uuid__in=object_type_uuids).all()

        if len(object_type_uuids) != len(object_types):
            raise CommandError("Some object types were not found")

        print(f"Starting compute prescription statuses for object types: {
              [ot.name for ot in object_types]}")

        offset = 0
        total = DetectionObject.objects.filter(object_type__in=object_types).count()

        while True:
            detection_objects = (
                DetectionObject.objects.filter(object_type__in=object_types)
                .prefetch_related(
                    "detections", "detections__detection_data", "detections__tile_set"
                )
                .all()[offset : offset + BATCH_SIZE]
            )

            if not detection_objects:
                break

            for detection_object in detection_objects:
                compute_prescription(detection_object)

            offset += len(detection_objects)

            print(f"Computed prescription for detection objects: {
                  offset}/{total}")

        print("Prescription computation done")
