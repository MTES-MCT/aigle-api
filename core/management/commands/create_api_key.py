from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from rest_framework_api_key.models import APIKey

from core.utils.logs_helpers import log_command_event


def log_event(info: str):
    log_command_event(command_name="create_api_key", info=info)


class Command(BaseCommand):
    help = "Create an API key for external API access"

    def add_arguments(self, parser):
        parser.add_argument(
            "--name", type=str, required=True, help="Name to identify this API key"
        )
        parser.add_argument(
            "--expiry-days",
            type=int,
            required=False,
            help="Number of days until expiry (optional)",
        )

    def handle(self, *args, **options):
        name = options["name"]
        expiry_days = options.get("expiry_days")

        # Create API key with optional expiry date
        if expiry_days:
            expiry_date = datetime.now() + timedelta(days=expiry_days)
            api_key, key = APIKey.objects.create_key(name=name, expiry_date=expiry_date)
            expiry_str = expiry_date.strftime("%Y-%m-%d %H:%M:%S")

            log_event(
                f"API Key created successfully - Name: {name}, Expires: {expiry_str}, Key: {key}"
            )
        else:
            api_key, key = APIKey.objects.create_key(name=name)

            log_event(
                f"API Key created successfully - Name: {name}, Expires: Never, Key: {key}"
            )
