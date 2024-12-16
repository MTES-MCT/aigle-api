from django.core.management.base import BaseCommand

from core.models.detection_object import DetectionObject
from core.models.geo_custom_zone import GeoCustomZone


BATCH_SIZE = 10000


class Command(BaseCommand):
    help = "Refresh data after update geometry of a custom zone"

    def add_arguments(self, parser):
        parser.add_argument("--zones-uuids", action="append", required=False)

    def handle(self, *args, **options):
        zones_uuids = options["zones_uuids"]

        custom_zones_queryset = GeoCustomZone.objects

        if zones_uuids:
            custom_zones_queryset = custom_zones_queryset.filter(uuid__in=zones_uuids)

        custom_zones = custom_zones_queryset.filter(geometry__isnull=False).all()

        print(
            f"Starting updating detection data for zones: {", ".join([zone.name for zone in custom_zones])}"
        )

        for zone in custom_zones:
            print(f"Updating detection data for zone: {zone.name}")

            # clean previously inside detections that are now outside

            detection_objects_outside = (
                DetectionObject.objects.filter(geo_custom_zones__uuid=zone.uuid)
                .exclude(detections__geometry__intersects=zone.geometry)
                .prefetch_related("geo_custom_zones")
                .all()
            )

            for detection_object in detection_objects_outside:
                geo_custom_zone_to_remove = detection_object.geo_custom_zones.filter(
                    uuid=zone.uuid
                ).all()
                detection_object.geo_custom_zones.remove(geo_custom_zone_to_remove)

            # update detections that are now inside

            detection_objects_inside = (
                DetectionObject.objects.filter(
                    detections__geometry__intersects=zone.geometry
                )
                .exclude(geo_custom_zones__uuid=zone.uuid)
                .prefetch_related("geo_custom_zones")
                .all()
            )

            for detection_object in detection_objects_inside:
                detection_object.geo_custom_zones.add(zone)
