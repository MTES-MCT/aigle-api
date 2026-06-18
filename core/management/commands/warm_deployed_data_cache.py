import time

from django.core.management.base import BaseCommand
from core.management.base import CommandRunTrackerMixin

from core.services.deployed_data import DeployedDataService
from core.utils.logs_helpers import log_command_event


def log_event(info: str):
    log_command_event(command_name="warm_deployed_data_cache", info=info)


class Command(CommandRunTrackerMixin, BaseCommand):
    help = (
        "Recompute and cache the SUPER_ADMIN 'deployed data' overview: both the "
        "department list AND every per-department detail page. Run this after a "
        "detection/parcel import (which invalidates the cache) so every HTTP request "
        "hits a warm cache instead of paying the cold per-department computation. "
        "Computing all department details scans the detection/parcel dataset once per "
        "department, so this takes on the order of a minute; it is meant to run "
        "out-of-band (Celery/cron), not in the request path."
    )

    def handle(self, *args, **options):
        started_at = time.time()
        departments = DeployedDataService.refresh_cache()
        log_event(
            f"Warmed deployed-data cache: {len(departments)} department(s) "
            f"in {time.time() - started_at:.1f}s"
        )
