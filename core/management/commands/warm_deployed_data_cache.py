import time

from django.core.management.base import BaseCommand

from core.services.deployed_data import DeployedDataService
from core.utils.logs_helpers import log_command_event


def log_event(info: str):
    log_command_event(command_name="warm_deployed_data_cache", info=info)


class Command(BaseCommand):
    help = (
        "Recompute and cache the SUPER_ADMIN 'deployed data' overview. The aggregation "
        "scans the whole detection/parcel dataset and takes ~1-2 min; run this after a "
        "detection/parcel import (which invalidates the cache) so HTTP requests always "
        "hit a warm cache instead of paying the cold computation cost."
    )

    def handle(self, *args, **options):
        started_at = time.time()
        departments = DeployedDataService.refresh_cache()
        log_event(
            f"Warmed deployed-data cache: {len(departments)} department(s) "
            f"in {time.time() - started_at:.1f}s"
        )
