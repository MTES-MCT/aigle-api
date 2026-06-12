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
            # Find the (still active) API key by name: revoked keys are kept in the
            # database for audit, so the name lookup must skip them — also allows
            # recreating a key under the same name after a revocation.
            api_key = APIKey.objects.get(name=name, revoked=False)

            # Revoke instead of delete: a revoked key fails authentication, and the
            # row is kept as a record of the key having existed.
            api_key.revoked = True
            api_key.save()

            log_event(f"API Key revoked successfully - Name: {name}")

        except APIKey.DoesNotExist:
            # List all active (non-revoked) API keys
            api_keys = APIKey.objects.filter(revoked=False)
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
