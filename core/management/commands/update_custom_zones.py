from django.core.management.base import BaseCommand

from core.models.geo_custom_zone import GeoCustomZone
from core.services.geo_custom_zone import GeoCustomZoneService
from core.utils.logs_helpers import log_command_event


def log_event(info: str):
    log_command_event(command_name="update_custom_zones", info=info)


class Command(BaseCommand):
    help = "Refresh data after update geometry of a custom zone"

    def add_arguments(self, parser):
        parser.add_argument("--zones-uuids", action="append", required=False)
        parser.add_argument("--batch-uuids", action="append", required=False)
        parser.add_argument("--tile-set-uuids", action="append", required=False)

    def handle(self, *args, **options):
        zones_uuids = options["zones_uuids"]
        batch_uuids = options["batch_uuids"]
        tile_set_uuids = options["tile_set_uuids"]

        custom_zones_queryset = GeoCustomZone.objects
        if zones_uuids:
            custom_zones_queryset = custom_zones_queryset.filter(uuid__in=zones_uuids)

        custom_zone_ids = list(
            custom_zones_queryset.filter(geometry__isnull=False).values_list(
                "id", flat=True
            )
        )

        log_event(
            f"Starting updating detection data for {len(custom_zone_ids)} zone(s)"
        )

        GeoCustomZoneService.associate_detections_to_custom_zones(
            custom_zone_ids=custom_zone_ids,
            batch_ids=batch_uuids,
            tile_set_uuids=tile_set_uuids,
            log_event=log_event,
        )
