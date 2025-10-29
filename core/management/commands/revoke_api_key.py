from django.core.management.base import BaseCommand
from rest_framework_api_key.models import APIKey

from core.utils.logs_helpers import log_command_event


def log_event(info: str):
    log_command_event(command_name="revoke_api_key", info=info)


class Command(BaseCommand):
    help = "Revoke an API key for external API access"

    def add_arguments(self, parser):
        parser.add_argument(
            "--name", type=str, required=True, help="Name of the API key to revoke"
        )

    def handle(self, *args, **options):
        name = options["name"]

        try:
            # Find the API key by name
            api_key = APIKey.objects.get(name=name)

            # Delete the API key
            api_key.delete()

            log_event(f"API Key revoked successfully - Name: {name}")

        except APIKey.DoesNotExist:
            # List all available API keys
            api_keys = APIKey.objects.all()
            if api_keys.exists():
                available_keys = ", ".join(
                    [
                        f"{key.name} (expires: {key.expiry_date.strftime('%Y-%m-%d %H:%M:%S') if key.expiry_date else 'Never'})"
                        for key in api_keys
                    ]
                )
                log_event(
                    f"API Key not found: {name}. Available keys: {available_keys}"
                )
            else:
                log_event(f"API Key not found: {name}. No API keys found in database.")
