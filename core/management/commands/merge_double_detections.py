from django.core.management.base import BaseCommand

from core.services.detection_process import DetectionProcessService
from core.utils.logs_helpers import log_command_event


def log_event(info: str):
    log_command_event(command_name="merge_double_detections", info=info)


class Command(BaseCommand):
    help = "Command to merge detections that belong to the same tileset but are attached to the same detection object"

    def add_arguments(self, parser):
        parser.add_argument("--tile-set-id", type=int, required=True)

    def handle(self, *args, **options):
        log_event("started")

        tile_set_id = options["tile_set_id"]

        DetectionProcessService.merge_double_detections(tile_set_id=tile_set_id)

        log_event("finished")
