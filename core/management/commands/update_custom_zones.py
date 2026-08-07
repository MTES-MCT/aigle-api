from django.core.management.base import BaseCommand
from core.management.base import CommandRunTrackerMixin

from core.services.geo_custom_zone import GeoCustomZoneService
from core.utils.logs_helpers import log_command_event


def log_event(info: str):
    log_command_event(command_name="update_custom_zones", info=info)


class Command(CommandRunTrackerMixin, BaseCommand):
    help = (
        "Refresh data after update geometry of a custom zone: links the detections the "
        "zone now covers and removes the links it does not cover anymore"
    )

    def add_arguments(self, parser):
        parser.add_argument("--zones-uuids", action="append", required=False)
        parser.add_argument("--batch-uuids", action="append", required=False)
        parser.add_argument("--tile-set-uuids", action="append", required=False)

    def handle(self, *args, **options):
        # The refresh itself lives in the service so `import_custom_zones --override`
        # runs this exact code for the zones it replaced.
        GeoCustomZoneService.update_custom_zones_data(
            zones_uuids=options["zones_uuids"],
            batch_ids=options["batch_uuids"],
            tile_set_uuids=options["tile_set_uuids"],
            log_event=log_event,
        )
